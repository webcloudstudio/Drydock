"""Bounds applied to any child process Drydock executes to observe a build.

Two commands run the code under test: an acceptance check (``drydock/acceptance.py``) and a
governed gate (``drydock/acceptance_contract.py``). Both hand control to code a model wrote, so
both need the same three bounds — a timeout, an address-space ceiling, and a cap on how much
output Drydock is willing to hold. The timeout each already owned; this module owns the other two
so the two paths cannot drift apart again.

They did drift, and the drift is the reason this module exists. A build's acceptance run capped
the child's address space while the release gate did not, so a target that allocated without
bound was stopped by the kernel during the build and then materialised 2.1 GB of output during
scoring, which ``subprocess.run(capture_output=True)`` held in memory until the scorer itself was
killed. A target failing a resource-limit conformance case is an ordinary product defect and must
be reported as one; it must never be able to kill the process grading it.
"""

from __future__ import annotations

import os
import signal
import subprocess
from collections.abc import Callable

__all__ = [
    "CaptureOverflow",
    "child_limits",
    "kill_process_group",
    "run_bounded",
]


class CaptureOverflow(Exception):
    """A child produced more output than Drydock agreed to hold.

    Carries the output captured up to the ceiling so the caller can still report what the child
    was doing when it was stopped. The truncated text is evidence; the bytes past the ceiling are
    not worth the memory.
    """

    def __init__(self, stream: str, limit_bytes: int, stdout: str, stderr: str) -> None:
        super().__init__(f"{stream} exceeded {limit_bytes} bytes")
        self.stream = stream
        self.limit_bytes = limit_bytes
        self.stdout = stdout
        self.stderr = stderr


def child_limits(limit_mb: int) -> Callable[[], None] | None:
    """A ``preexec_fn`` capping the child's address space, or ``None`` when unavailable.

    ``RLIMIT_AS`` is inherited across ``fork``/``exec``, so the bound also covers every process
    the child spawns — the runner, the built program under it, and so on. That is the point: the
    runaway is never the harness, it is the built code the harness invokes.
    """
    if limit_mb <= 0 or os.name != "posix":
        return None
    try:
        import resource
    except ImportError:  # pragma: no cover - non-POSIX
        return None

    ceiling = limit_mb * 1024 * 1024

    def apply() -> None:
        resource.setrlimit(resource.RLIMIT_AS, (ceiling, ceiling))
        # A multi-GB core dump from a bounded runaway helps nobody and costs the disk.
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))

    return apply


def kill_process_group(process: subprocess.Popen) -> None:
    """Kill the child's whole process group, not just the process Drydock started.

    A command that shells out leaves grandchildren. Killing only the direct child orphans them,
    and a runaway grandchild then survives the stop that was meant to end it.
    """
    try:
        os.killpg(os.getpgid(process.pid), signal.SIGKILL)
    except (ProcessLookupError, PermissionError, AttributeError, OSError):
        process.kill()


def _drain(
    pipe,
    chunks: list[bytes],
    state: dict,
    stream: str,
    limit_bytes: int,
) -> None:
    """Read one stream into ``chunks``, recording the first overflow rather than growing.

    Past the ceiling the bytes are dropped, not buffered: the whole purpose is to refuse to
    allocate what the child is trying to make Drydock allocate.
    """
    held = 0
    try:
        while True:
            data = pipe.read(65536)
            if not data:
                break
            if limit_bytes <= 0 or held < limit_bytes:
                keep = data if limit_bytes <= 0 else data[: limit_bytes - held]
                chunks.append(keep)
                held += len(keep)
            if limit_bytes > 0 and held >= limit_bytes and state.get("overflow") is None:
                state["overflow"] = stream
    finally:
        try:
            pipe.close()
        except OSError:  # pragma: no cover - pipe already torn down
            pass


def run_bounded(
    argv: list[str],
    *,
    cwd,
    timeout: int,
    limit_mb: int = 0,
    capture_limit_bytes: int = 0,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run a child under an address-space ceiling and an output ceiling.

    Raises :class:`CaptureOverflow` when either stream passes ``capture_limit_bytes``, and
    ``subprocess.TimeoutExpired`` on timeout, both after killing the child's process group.
    ``0`` for either ceiling lifts it. Output is decoded once at the end, from bounded bytes, so
    the peak cost of a runaway child is the ceiling and not what the child chose to emit.
    """
    import threading

    process = subprocess.Popen(  # noqa: S603 - argv is supplied by a governed contract
        argv,
        cwd=cwd,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=os.name == "posix",
        preexec_fn=child_limits(limit_mb),  # noqa: PLW1509 - the bound is the point
    )
    out_chunks: list[bytes] = []
    err_chunks: list[bytes] = []
    state: dict = {"overflow": None}
    readers = [
        threading.Thread(
            target=_drain,
            args=(process.stdout, out_chunks, state, "stdout", capture_limit_bytes),
            daemon=True,
        ),
        threading.Thread(
            target=_drain,
            args=(process.stderr, err_chunks, state, "stderr", capture_limit_bytes),
            daemon=True,
        ),
    ]
    for reader in readers:
        reader.start()

    def decoded() -> tuple[str, str]:
        return (
            b"".join(out_chunks).decode("utf-8", errors="replace"),
            b"".join(err_chunks).decode("utf-8", errors="replace"),
        )

    # Poll rather than ``wait(timeout)``: an overflow has to stop the child while it is still
    # running, and the reader threads cannot do that themselves without racing the timeout path.
    deadline = None if timeout <= 0 else timeout
    waited = 0.0
    interval = 0.05
    while True:
        if process.poll() is not None:
            break
        if state["overflow"] is not None:
            kill_process_group(process)
            process.wait()
            for reader in readers:
                reader.join(timeout=5)
            stdout, stderr = decoded()
            raise CaptureOverflow(state["overflow"], capture_limit_bytes, stdout, stderr)
        if deadline is not None and waited >= deadline:
            kill_process_group(process)
            process.wait()
            for reader in readers:
                reader.join(timeout=5)
            stdout, stderr = decoded()
            raise subprocess.TimeoutExpired(argv, deadline, output=stdout, stderr=stderr)
        import time as _time

        _time.sleep(interval)
        waited += interval

    for reader in readers:
        reader.join(timeout=5)
    stdout, stderr = decoded()
    if state["overflow"] is not None:
        raise CaptureOverflow(state["overflow"], capture_limit_bytes, stdout, stderr)
    return subprocess.CompletedProcess(argv, process.returncode, stdout, stderr)

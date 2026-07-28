"""Blueprint-owned acceptance assertions for build verification."""

from __future__ import annotations

import os
import re
import signal
import subprocess
import sys
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from drydock.build_plan import BuildPlan, PlanBlock
from drydock.config import get_sandbox_mem_limit_mb
from drydock.proof_integrity import analyze_proof

SECTION_RE = re.compile(r"^## (?P<name>[^\n]+)\n", re.MULTILINE)
PYTHON_FENCE_RE = re.compile(r"```python\s*\n(?P<code>.*?)\n```", re.DOTALL)
HEADING_RE = re.compile(r"^###\s+(?P<title>.+?)\s*$", re.MULTILINE)
TIMEOUT_SECONDS = 60
# A suite-bound check runs a complete conformance suite; a story timeout would kill it.
SUITE_TIMEOUT_SECONDS = 900
# Category prefixes for a check that failed by exhausting a resource rather than by missing
# an expectation. Consumers use these to gate a repair pass on the resource fact.
MEMORY_FAILURE_PREFIX = "exhausted memory"
TIMEOUT_FAILURE_PREFIX = "timed out"
# A check that died inside its own snippet rather than inside the code under test. No
# implementation can turn it green, so a repair pass on it is wasted.
MALFORMED_FAILURE_PREFIX = "malformed check"
_MEMORY_SIGNATURES = ("MemoryError", "Cannot allocate memory", "std::bad_alloc", "Killed")
# Exceptions that, when raised by the snippet's own frame, mean the snippet is defective:
# it reads a name it never bound or does not parse. Neither is a statement about the code
# under test.
_MALFORMED_EXCEPTIONS = frozenset({
    "NameError",
    "UnboundLocalError",
    "SyntaxError",
    "IndentationError",
    "TabError",
})
_TRACEBACK_FILE_RE = re.compile(r'^\s*File "([^"]+)", line ', re.MULTILINE)
_EXCEPTION_LINE_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_.]*(?:Error|Exception))\b:?(.*)$")


def _timeout_output_text(value: bytes | str | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode(errors="replace")
    return value


def _child_limits(limit_mb: int) -> Callable[[], None] | None:
    """A ``preexec_fn`` capping the child's address space, or ``None`` when unavailable.

    ``RLIMIT_AS`` is inherited across ``fork``/``exec``, so the bound also covers every
    process the check spawns — the runner, the built program under it, and so on. That is
    the point: the runaway is never the acceptance snippet itself, it is the built code the
    snippet invokes.
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


def _kill_process_group(process: subprocess.Popen[str]) -> None:
    """Kill the check's whole process group, not just the process Drydock started.

    A check that shells out leaves grandchildren. Killing only the direct child orphans
    them, and a runaway grandchild then survives the timeout that was meant to stop it.
    """
    try:
        os.killpg(os.getpgid(process.pid), signal.SIGKILL)
    except (ProcessLookupError, PermissionError, AttributeError, OSError):
        process.kill()


def _resource_failure(return_code: int, stderr: str, limit_mb: int) -> str | None:
    """Classify a non-zero exit as resource exhaustion, or ``None`` when it is not.

    Distinguishes "the built code cannot run within its budget" from "the built code ran
    and missed an expectation". Only the former should tell a repair pass to fix an
    unbounded loop or allocation rather than adjust behavior.
    """
    if return_code == 0:
        return None
    oom_signalled = return_code == -signal.SIGKILL
    if oom_signalled or any(sig in stderr for sig in _MEMORY_SIGNATURES):
        bound = f"{limit_mb} MB" if limit_mb > 0 else "the available memory"
        return (
            f"{MEMORY_FAILURE_PREFIX}: the built code exceeded {bound} and was stopped by the "
            f"kernel. This is unbounded allocation or a non-terminating loop in the code under "
            f"test, not a missed expectation."
        )
    return None


def _malformed_failure(return_code: int, stderr: str, script_name: str) -> str | None:
    """Classify a non-zero exit as a defective snippet, or ``None`` when it is not.

    Attribution is by traceback frame, not by exception type alone. ``NameError`` raised
    inside the code under test is a genuine red the build must drive green; the same
    exception raised in the check's own frame means the check reads a name nothing binds —
    most often a name a sibling check defined, which is not in scope because every check runs
    as its own script in its own process.
    """
    if return_code == 0:
        return None
    lines = [line for line in stderr.splitlines() if line.strip()]
    if not lines:
        return None
    match = _EXCEPTION_LINE_RE.match(lines[-1].strip())
    if match is None:
        return None
    exception = match.group(1).rsplit(".", 1)[-1]
    detail = match.group(2).strip()

    frames = _TRACEBACK_FILE_RE.findall(stderr)
    if not frames or Path(frames[-1]).name != script_name:
        # The failure surfaced inside the code under test. That is the build's job to fix.
        return None

    # ``ImportError`` is deliberately absent. A missing module is the *expected* red baseline
    # before the code under test is written, and nothing in the traceback distinguishes that
    # from a typo'd import. Classifying it would block builds that should proceed, so it is
    # left to the build.
    if exception in _MALFORMED_EXCEPTIONS:
        return (
            f"{MALFORMED_FAILURE_PREFIX}: the assertion itself raised {exception}"
            f"{f' ({detail})' if detail else ''} in its own frame, before reaching the code "
            f"under test. No implementation can satisfy it. Each check runs as its own "
            f"script in its own process, so a name bound by another check is not in scope. "
            f"Repair the assertion in the Blueprint specification."
        )
    return None


def _scrub_script_path(text: str, script: Path) -> str:
    """Replace the throwaway script's absolute path with its stable check name.

    The path is a per-run temporary directory; leaving it in evidence makes otherwise
    identical failures compare unequal across runs.
    """
    return text.replace(str(script), script.name)


@dataclass(frozen=True)
class ProgrammaticAcceptance:
    check_id: str
    source: str
    intent: str
    code: str
    sea_trials: tuple[str, ...] = ()
    full_suite: bool = False

    @property
    def timeout_seconds(self) -> int:
        """A suite-bound check runs a whole conformance suite, not a story unit test."""
        return SUITE_TIMEOUT_SECONDS if self.full_suite else TIMEOUT_SECONDS


@dataclass(frozen=True)
class AcceptanceRunResult:
    check_id: str
    source: str
    intent: str
    passed: bool
    return_code: int | None
    stdout: str
    stderr: str
    error: str | None = None


@dataclass(frozen=True)
class AcceptanceObservation:
    check_id: str
    source: str
    intent: str
    passed: bool
    return_code: int | None
    stdout: str
    stderr: str
    error: str | None = None
    integrity_ok: bool = True
    integrity_reasons: tuple[str, ...] = ()

    @property
    def status(self) -> str:
        if not self.passed:
            return "baseline-red"
        return "green" if self.integrity_ok else "green-vacuous"

    @property
    def weak(self) -> bool:
        return self.passed


def _slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug or "acceptance"


def _sections(text: str) -> dict[str, str]:
    matches = list(SECTION_RE.finditer(text))
    sections: dict[str, str] = {}
    for index, match in enumerate(matches):
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        sections[match.group("name").strip().lower()] = text[start:end].strip()
    return sections


def _last_heading(text: str) -> str | None:
    headings = list(HEADING_RE.finditer(text))
    if not headings:
        return None
    return headings[-1].group("title").strip()


def _intent(prefix: str, title: str | None) -> str:
    lines = []
    for raw in prefix.splitlines():
        line = raw.strip()
        if not line or line.startswith("###"):
            continue
        if re.match(r"(Sea Trials|Suite):", line, re.I):
            continue
        lines.append(line)
    if lines:
        return " ".join(lines)
    return title or "Programmatic acceptance assertion"


def _full_suite(prefix: str) -> bool:
    """Whether the assertion runs the whole test suite rather than a bounded story check.

    Story acceptance is bounded by default so an ordinary check cannot accidentally invoke the
    whole test suite. A suite-bound check declares ``Suite: full`` (a terminal verification story
    gating on the entire suite) or ``Suite: scoped`` (a feature story gating on the sections it
    owns); both get the suite execution budget.
    """
    return bool(re.search(r"^Suite:\s*(?:full|scoped)\s*$", prefix, re.MULTILINE | re.IGNORECASE))


def _sea_trials(prefix: str) -> tuple[str, ...]:
    match = re.search(r"^Sea Trials:\s*(.+?)\s*$", prefix, re.MULTILINE | re.IGNORECASE)
    if not match:
        return ()
    return tuple(value.lower() for raw in match.group(1).split(",") if (value := raw.strip()))


def parse_programmatic_acceptance(path: Path) -> tuple[ProgrammaticAcceptance, ...]:
    """Return Python acceptance snippets from one Blueprint spec file."""
    text = path.read_text(encoding="utf-8")
    section = _sections(text).get("programmatic acceptance", "")
    if not section or section.strip() == "- None.":
        return ()

    checks: list[ProgrammaticAcceptance] = []
    previous_end = 0
    for index, match in enumerate(PYTHON_FENCE_RE.finditer(section), start=1):
        prefix = section[previous_end : match.start()]
        title = _last_heading(prefix)
        check_id = _slugify(title or f"{path.stem}-{index}")
        code = match.group("code").strip()
        checks.append(
            ProgrammaticAcceptance(
                check_id=check_id,
                source=path.name,
                intent=_intent(prefix, title),
                code=code,
                sea_trials=_sea_trials(prefix),
                full_suite=_full_suite(prefix),
            )
        )
        previous_end = match.end()
    return tuple(checks)


def programmatic_acceptance_for_step(
    block: PlanBlock, blueprint_dir: Path
) -> tuple[ProgrammaticAcceptance, ...]:
    """Load programmatic assertions from the Blueprint files a step implements."""
    checks: list[ProgrammaticAcceptance] = []
    for name in block.fields.get("implements", ()):
        if not isinstance(name, str):
            continue
        path = blueprint_dir / name
        if path.is_file():
            checks.extend(parse_programmatic_acceptance(path))
    return tuple(checks)


def all_programmatic_acceptance(
    plan: BuildPlan, blueprint_dir: Path
) -> tuple[ProgrammaticAcceptance, ...]:
    """Every Blueprint assertion the plan implements, deduped by ``(source, check_id)``.

    This is the projection source for ``SOUNDINGS.md``: one entry per individual Programmatic
    Acceptance assertion across the Blueprint spec files the plan's stories implement.
    """
    checks: list[ProgrammaticAcceptance] = []
    seen: set[tuple[str, str]] = set()
    for block in plan.blocks:
        if block.block_type != "story":
            continue
        for name in block.fields.get("implements", ()):
            if not isinstance(name, str):
                continue
            path = blueprint_dir / name
            if not path.is_file():
                continue
            for check in parse_programmatic_acceptance(path):
                key = (check.source, check.check_id)
                if key in seen:
                    continue
                seen.add(key)
                checks.append(check)
    return tuple(checks)


def run_programmatic_acceptance(
    checks: tuple[ProgrammaticAcceptance, ...],
    *,
    build_dir: Path,
    target_dir: Path,
    blueprint_dir: Path,
) -> tuple[AcceptanceRunResult, ...]:
    """Execute Python acceptance snippets from the build directory."""
    results: list[AcceptanceRunResult] = []
    pythonpath = os.pathsep.join(
        part for part in (str(build_dir), os.environ.get("PYTHONPATH", "")) if part
    )
    env = {
        **os.environ,
        "DRYDOCK_BUILD_DIR": str(build_dir),
        "DRYDOCK_TARGET_DIR": str(target_dir),
        "DRYDOCK_BLUEPRINT_DIR": str(blueprint_dir),
        "PYTHONPATH": pythonpath,
    }
    limit_mb = get_sandbox_mem_limit_mb()
    preexec = _child_limits(limit_mb)
    for check in checks:
        # Run from a real file, never ``python -c``: a ``-c`` traceback reports
        # ``File "<string>", line N`` with no source text, so a failing assertion names
        # neither the assertion nor the expectation it asserted. Written to a file, the
        # traceback carries the offending line and the failure is diagnosable in one pass.
        with tempfile.TemporaryDirectory(prefix="drydock-acceptance-") as tmp:
            script = Path(tmp) / f"{check.check_id or 'acceptance'}.py"
            script.write_text(check.code + "\n", encoding="utf-8")
            # Own session so the timeout can reap the whole tree, and a bounded address
            # space so a runaway is stopped by the kernel long before the timeout.
            process = subprocess.Popen(
                [sys.executable, str(script)],
                cwd=build_dir,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                start_new_session=os.name == "posix",
                preexec_fn=preexec,
            )
            try:
                stdout, stderr = process.communicate(timeout=check.timeout_seconds)
            except subprocess.TimeoutExpired:
                _kill_process_group(process)
                stdout, stderr = process.communicate()
                results.append(
                    AcceptanceRunResult(
                        check_id=check.check_id,
                        source=check.source,
                        intent=check.intent,
                        passed=False,
                        return_code=None,
                        stdout=_timeout_output_text(stdout),
                        stderr=_scrub_script_path(_timeout_output_text(stderr), script),
                        error=(
                            f"{TIMEOUT_FAILURE_PREFIX} after {check.timeout_seconds}s: the built "
                            f"code did not terminate within its budget. This is a "
                            f"non-terminating loop or unbounded work in the code under test, "
                            f"not a missed expectation."
                        ),
                    )
                )
                continue
            return_code = process.returncode
            scrubbed = _scrub_script_path(stderr, script)
            verdict = _resource_failure(return_code, stderr, limit_mb) or _malformed_failure(
                return_code, scrubbed, script.name
            )
        results.append(
            AcceptanceRunResult(
                check_id=check.check_id,
                source=check.source,
                intent=check.intent,
                passed=return_code == 0,
                return_code=return_code,
                stdout=stdout,
                stderr=scrubbed,
                error=verdict,
            )
        )
    return tuple(results)


def observe_programmatic_acceptance(
    checks: tuple[ProgrammaticAcceptance, ...],
    *,
    build_dir: Path,
    target_dir: Path,
    blueprint_dir: Path,
) -> tuple[AcceptanceObservation, ...]:
    """Execute checks and annotate whether a passing proof is integrity-valid or vacuous."""
    if not checks:
        return ()
    runtime = run_programmatic_acceptance(
        checks, build_dir=build_dir, target_dir=target_dir, blueprint_dir=blueprint_dir
    )
    observations: list[AcceptanceObservation] = []
    for check, result in zip(checks, runtime, strict=True):
        integrity = analyze_proof(check.code)
        observations.append(
            AcceptanceObservation(
                check_id=result.check_id,
                source=result.source,
                intent=result.intent,
                passed=result.passed,
                return_code=result.return_code,
                stdout=result.stdout,
                stderr=result.stderr,
                error=result.error,
                integrity_ok=integrity.ok,
                integrity_reasons=integrity.reasons,
            )
        )
    return tuple(observations)

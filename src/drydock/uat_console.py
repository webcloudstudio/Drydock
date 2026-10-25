"""Live console framing for the child commands a UAT run executes.

Child evidence remains verbatim on disk. The terminal suppresses housekeeping and duplicate
status views, condenses plan progress, and highlights failures independently of color.
"""

from __future__ import annotations

import re
import shutil
import sys
import textwrap
import threading
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Protocol, TextIO

if TYPE_CHECKING:
    from drydock.uat import UATResult

from drydock import console
from drydock.execution import format_ms

_MAX_RULE_WIDTH = 96
_MAX_ARGV_WIDTH = 140
_RED = "\x1b[31m"
_GREEN = "\x1b[32m"
_BLUE = "\x1b[34m"
_DIM = "\x1b[2m"
_RESET = "\x1b[0m"


def result_box(heading: str, details: Sequence[str], *, width: int = 88) -> str:
    """An ASCII frame remains conspicuous in terminals and redirected logs alike."""
    width = max(24, min(width, 96))
    lines = [heading, *details]
    wrapped = [
        part
        for line in lines
        for part in textwrap.wrap(line, width=width - 4, break_on_hyphens=False) or [""]
    ]
    return "\n".join([
        "#" * width,
        *(f"# {line:<{width - 4}} #" for line in wrapped),
        "#" * width,
    ])


def render_result(result: UATResult, *, stream: TextIO | None = None) -> str:
    """Final recorded verdict, after checkpointing; failed probes are not run verdicts."""
    from drydock.uat import result_blockers

    details = [
        f"Run: {result.run_id} | Execution: {result.execution_status} | "
        f"Acceptance: {result.acceptance_status}",
        f"Verdict: expected {result.expected_verdict}, observed {result.observed_verdict}",
    ]
    if blockers := result_blockers(result):
        details.append(f"BLOCKED: {result.target} | {blockers.summary}")
    if result.status != "passed":
        failed = next(
            (
                command
                for command in reversed(result.commands)
                if command.returncode and not command.label.endswith(("-status", "-ready"))
            ),
            None,
        )
        if failed:
            details.append(
                f"Last failed command: {format_label(failed.label)} (exit {failed.returncode})"
            )
            details.append(format_argv(failed.argv))
            if failed.stderr_path:
                try:
                    with Path(failed.stderr_path).open(
                        encoding="utf-8", errors="replace"
                    ) as handle:
                        diagnostic = handle.read(4096)
                    details.extend(
                        line.strip() for line in diagnostic.splitlines()[:3] if line.strip()
                    )
                except OSError:
                    pass  # The recorded run error remains authoritative when a log is absent.
    if result.error:
        details.append(f"{'Reported' if result.status == 'passed' else 'Error'}: {result.error}")
    details.extend(result.degraded)
    details.extend(f"MANUAL TEST REQUIRED: {item}" for item in result.attestations)
    box = result_box(f"UAT {result.status.upper()}: {result.target}", details)
    if console.color_enabled(stream if stream is not None else sys.stdout):
        return f"{_GREEN if result.status == 'passed' else _RED}{box}{_RESET}"
    return box


class StepSink(Protocol):
    """What a streaming runner reports as it executes one child command."""

    def step(self, argv: Sequence[str], label: str) -> None: ...

    def chunk(self, source: str, text: str) -> None: ...

    def finish(self, returncode: int, elapsed_ms: int) -> None: ...


def format_argv(argv: Sequence[str]) -> str:
    """Render a child command the way an operator would type it.

    ``<python> -m drydock analyze Toml`` becomes ``drydock analyze Toml``; a fixture's own test
    command is shown verbatim.
    """
    parts = list(argv)
    if len(parts) >= 3 and parts[1] == "-m" and parts[2] == "drydock":
        parts = ["drydock", *parts[3:]]
    # A fixture's own test command may carry newlines. The echo is one line by contract, so a
    # multi-line argument cannot break out of the frame.
    line = " ".join(" ".join(part.split()) for part in parts)
    if len(line) > _MAX_ARGV_WIDTH:
        line = line[: _MAX_ARGV_WIDTH - 1] + console.render("…", console.active_tier())
    return line


def format_label(label: str) -> str:
    """Render a recorded step label as the operator's own vocabulary.

    The stored label carries the step's position as a numeric prefix — ``16-score-acceptance`` —
    which reads as part of the command name rather than as the number ``--from-step`` takes.
    Naming it explicitly is the difference between "step 16" and an opaque prefix.
    """
    number, separator, name = label.partition("-")
    if separator and number.isdigit():
        return f"step {int(number)}: {name}"
    return label


def command_heading(argv: Sequence[str]) -> str:
    """Uppercase command and positional arguments, without invocation options."""
    parts = list(argv)
    if len(parts) >= 3 and parts[1:3] == ["-m", "drydock"]:
        parts = ["drydock", *parts[3:]]
    end = next((i for i, part in enumerate(parts) if i and part.startswith("-")), len(parts))
    return format_argv(parts[:end]).upper()


class StepConsole:
    """Frame and stream the output of each UAT child command onto one stream."""

    def __init__(
        self,
        stream: TextIO | None = None,
        *,
        quiet: bool = False,
        width: int | None = None,
        clock: object = None,
    ) -> None:
        self._stream = stream if stream is not None else sys.stdout
        self._quiet = quiet
        self._width = width
        self._clock = clock or (lambda: datetime.now())  # noqa: DTZ005 - local wall clock
        self._lock = threading.RLock()
        self._tier = console.active_tier()
        self._color = console.color_enabled(self._stream)
        self._kit = ""
        self._label = ""
        self._heading = ""
        self._occurrences: dict[str, int] = {}
        self._at_line_start = True
        self._open_source: str | None = None
        self._last_was_cr = False
        self._pending: dict[str, str] = {}
        self._emitted: dict[str, int] = {}
        self._snapshot = False
        self._hidden = False
        self._blocker_dump = False
        self._plan: dict[str, str] = {}
        self._errors: list[str] = []

    # -- context ----------------------------------------------------------------

    def event(self, text: str) -> None:
        """Record the ``<kit>: <stage>`` breadcrumb the run engine announces.

        Under ``--quiet`` this is the whole console contract, identical to the previous
        behaviour. When streaming, the breadcrumb only supplies the kit name for the header the
        runner is about to print, so a stage is announced exactly once.
        """
        with self._lock:
            kit, _, _stage = text.partition(": ")
            if kit != self._kit:
                self._occurrences.clear()
            self._kit = kit or text
            if self._quiet:
                self._write(f"UAT: {text}\n")

    # -- StepSink ---------------------------------------------------------------

    def step(self, argv: Sequence[str], label: str) -> None:
        with self._lock:
            self._label = label
            self._snapshot = label.endswith("-build-status")
            self._hidden = label.endswith(("-target-status", "-workspace-status"))
            self._pending.clear()
            self._emitted.clear()
            self._plan.clear()
            self._errors.clear()
            self._blocker_dump = False
            self._heading = command_heading(argv)
            if self._quiet or self._hidden:
                return
            heading = self._heading
            count = self._occurrences.get(heading, 0) + 1
            self._occurrences[heading] = count
            self._heading = heading + (f" [{count}]" if count > 1 else "")
            self._close_open_line()
            stamp = self._clock().strftime("%H:%M:%S")
            self._write("\n" + self._paint(self._rule(self._title(), stamp), _BLUE) + "\n")
            self._write(self._paint(f"   {format_argv(argv)}\n", _DIM))

    def chunk(self, source: str, text: str) -> None:
        if self._quiet or not text:
            return
        with self._lock:
            pending = self._pending.get(source, "") + text
            parts = re.split(r"(\r\n|\r|\n)", pending)
            emitted = self._emitted.get(source, 0)
            for index in range(0, len(parts) - 1, 2):
                line = parts[index] + parts[index + 1]
                if emitted:
                    self._chunk(source, line[emitted:])
                    self._remember_error(source, line)
                else:
                    self._line(source, line)
                emitted = 0
            tail = parts[-1]
            # Unknown output streams immediately, including unfinished progress lines. Only
            # recognized presentation records wait for a newline before being compacted.
            candidates = (
                ("Contents of ", "=")
                if source == "stderr"
                else ("Drydock ", "Target - ", "git:", "Claude session: start id=", "Next:")
            )
            stripped = tail.lstrip()
            hold = source == "stdout" and (self._snapshot or self._hidden or "plan" in self._label)
            hold = hold or (source == "stderr" and self._blocker_dump)
            hold = hold or any(
                prefix.startswith(stripped) or stripped.startswith(prefix) for prefix in candidates
            )
            if tail and (emitted or not hold):
                self._chunk(source, tail[emitted:])
                emitted = len(tail)
            self._pending[source] = tail
            self._emitted[source] = emitted

    def _remember_error(self, source: str, text: str) -> None:
        if source == "stderr" and text.strip() and len(self._errors) < 4:
            self._errors.append(text.strip())

    def _line(self, source: str, text: str) -> None:
        line = text.strip()
        if source == "stderr":
            if (self._snapshot or self._hidden) and line.startswith("Contents of "):
                self._blocker_dump = True
            if self._blocker_dump:
                return
            if line and not set(line) <= {"="}:
                self._remember_error(source, text)
                self._chunk(source, text)
            return
        if self._hidden:
            return
        if line.startswith("Next:"):
            return
        if (line.startswith("Drydock ") and "Copyright (c)" in line) or line.startswith((
            "Target - setup project workspace git store",
            "Target - committed project workspace git store",
            "git:",
            "Claude session: start id=",
        )):
            return
        if self._snapshot:
            if (
                line.startswith(("Steps:", "Buildable now:", "BLOCKED:", "STOPPED:"))
                or "[failed]" in line
            ):
                self._chunk(source, text)
            return
        if "plan" in self._label:
            if line and set(line) == {"="}:
                return
            if line.startswith("PLAN PROGRESS"):
                self._plan = {"stage": line.removeprefix("PLAN PROGRESS").strip(" ·")}
                return
            key, separator, value = line.partition(":")
            if (
                separator
                and key
                in {
                    "Topology Created",
                    "Blueprints Created",
                    "Manifest Created",
                    "Blueprints Remaining",
                    "Batch Result",
                }
                and self._plan
            ):
                self._plan[key] = value.strip()
                if key == "Batch Result":
                    self._chunk(
                        source,
                        self._paint(
                            f"Plan: {self._plan['stage']} | "
                            f"Blueprints {self._plan.get('Blueprints Created', '?')} | {value.strip()}\n",
                            _BLUE,
                        ),
                    )
                    self._plan.clear()
                return
        self._chunk(source, text)

    def _chunk(self, source: str, text: str) -> None:
        if self._quiet or not text:
            return
        with self._lock:
            if self._open_source is not None and self._open_source != source:
                # The other stream left a line open; close it so the two never tangle mid-line.
                self._write("\n")
                self._at_line_start = True
                self._last_was_cr = False
            gutter = self._gutter(source)
            out: list[str] = []
            for char in text:
                if self._at_line_start and not (char == "\n" and self._last_was_cr):
                    out.append(gutter)
                    self._at_line_start = False
                out.append(char)
                self._last_was_cr = char == "\r"
                if char in "\n\r":
                    self._at_line_start = True
            self._open_source = None if self._at_line_start else source
            self._write("".join(out))

    def finish(self, returncode: int, elapsed_ms: int) -> None:
        with self._lock:
            for source, pending in self._pending.items():
                if pending:
                    if self._emitted.get(source):
                        self._remember_error(source, pending)
                    else:
                        self._line(source, pending)
            self._pending.clear()
            if self._quiet:
                return
            self._close_open_line()
            if returncode:
                detail = [f"Command exited {returncode} | {format_ms(elapsed_ms)}", *self._errors]
                heading = "NOT READY" if self._label.endswith("-ready") else "STEP ERROR"
                self._write(
                    self._paint(
                        result_box(
                            f"{heading}: {self._title()}",
                            detail,
                            width=self._width
                            or min(shutil.get_terminal_size((88, 24)).columns, 88),
                        ),
                        _RED,
                    )
                    + "\n"
                )
            elif not self._hidden:
                self._write(
                    self._paint(self._rule(self._title(), f"OK   {format_ms(elapsed_ms)}"), _GREEN)
                    + "\n"
                )

    # -- rendering --------------------------------------------------------------

    def _title(self) -> str:
        return self._heading or "STEP"

    def _rule(self, title: str, right: str) -> str:
        dash = console.render("─", self._tier)
        head = f"{dash * 2} {title} "
        tail = f" {right} {dash * 2}"
        width = self._width or min(
            shutil.get_terminal_size((_MAX_RULE_WIDTH, 24)).columns, _MAX_RULE_WIDTH
        )
        fill = max(1, width - console.display_width(head) - console.display_width(tail))
        return f"{head}{dash * fill}{tail}"

    def _gutter(self, source: str) -> str:
        if source == "stderr":
            return self._paint(" ! ", _RED)
        return self._paint(f" {console.render('│', self._tier)} ", _DIM)

    def _paint(self, text: str, code: str) -> str:
        return f"{code}{text}{_RESET}" if self._color else text

    def _close_open_line(self) -> None:
        if not self._at_line_start:
            self._write("\n")
            self._at_line_start = True
            self._open_source = None
            self._last_was_cr = False

    def _write(self, text: str) -> None:
        self._stream.write(text)
        self._stream.flush()

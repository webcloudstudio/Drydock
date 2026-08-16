"""Live console framing for the child commands a UAT run executes.

A UAT run is a long sequence of full Drydock commands. Reporting only the stage name leaves an
operator unable to tell progress from a stall, so every child's output is written through to the
terminal as it arrives, framed by a header and a footer that name the stage and time it.

Fidelity is the constraint: a chunk is written exactly as the child produced it. The gutter is
inserted only at the start of a line, so a progress line that redraws itself with a carriage
return still redraws, and a line without a trailing newline still appears.
"""

from __future__ import annotations

import shutil
import sys
import threading
from collections.abc import Sequence
from datetime import datetime
from typing import Protocol, TextIO

from drydock import console
from drydock.execution import format_ms

_MAX_RULE_WIDTH = 96
_MAX_ARGV_WIDTH = 140
_RED = "\x1b[31m"
_DIM = "\x1b[2m"
_RESET = "\x1b[0m"


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
        self._at_line_start = True
        self._open_source: str | None = None
        self._last_was_cr = False

    # -- context ----------------------------------------------------------------

    def event(self, text: str) -> None:
        """Record the ``<kit>: <stage>`` breadcrumb the run engine announces.

        Under ``--quiet`` this is the whole console contract, identical to the previous
        behaviour. When streaming, the breadcrumb only supplies the kit name for the header the
        runner is about to print, so a stage is announced exactly once.
        """
        with self._lock:
            kit, _, _stage = text.partition(": ")
            self._kit = kit or text
            if self._quiet:
                self._write(f"UAT: {text}\n")

    # -- StepSink ---------------------------------------------------------------

    def step(self, argv: Sequence[str], label: str) -> None:
        with self._lock:
            self._label = label
            if self._quiet:
                return
            self._close_open_line()
            stamp = self._clock().strftime("%H:%M:%S")
            self._write("\n" + self._rule(self._title(), stamp) + "\n")
            self._write(self._paint(f"   {format_argv(argv)}\n", _DIM))

    def chunk(self, source: str, text: str) -> None:
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
            if self._quiet:
                return
            self._close_open_line()
            outcome = f"exit {returncode}   {format_ms(elapsed_ms)}"
            line = self._rule(self._title(), outcome)
            self._write(self._paint(line, _RED) if returncode else line)
            self._write("\n")

    # -- rendering --------------------------------------------------------------

    def _title(self) -> str:
        parts = [part for part in (self._kit, format_label(self._label)) if part]
        return console.render(" · ", self._tier).join(parts) or "step"

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

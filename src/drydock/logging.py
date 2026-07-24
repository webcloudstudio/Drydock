"""Command transcripts and console diagnostics for Drydock."""

from __future__ import annotations

import logging
import os
import re
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TextIO

from drydock.execution import log_basename

_ANSI_ESCAPE_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
_PARENT_TRANSCRIPT_ENV = "DRYDOCK_PARENT_TRANSCRIPT"
_TEST_LOGGING_OPT_IN_ENV = "DRYDOCK_TEST_COMMAND_LOGGING"


def command_logging_enabled() -> bool:
    """Whether this process should record user-visible command activity.

    Pytest drives the CLI repeatedly to configure isolated fixtures. Those calls are
    test implementation detail and must not pollute the developer's workspace logs.
    Logging contract tests can opt in explicitly.
    """
    return not os.environ.get("PYTEST_CURRENT_TEST") or bool(
        os.environ.get(_TEST_LOGGING_OPT_IN_ENV)
    )


class StdoutTee:
    """Copy stdout to a plain-text command transcript without changing terminal behavior."""

    def __init__(self, terminal: TextIO, transcript: TextIO) -> None:
        self._terminal = terminal
        self._transcript = transcript

    def write(self, text: str) -> int:
        written = self._terminal.write(text)
        self._transcript.write(_ANSI_ESCAPE_RE.sub("", text))
        return written

    def flush(self) -> None:
        self._terminal.flush()
        self._transcript.flush()

    def isatty(self) -> bool:
        return self._terminal.isatty()

    @property
    def encoding(self) -> str | None:
        return self._terminal.encoding

    @property
    def errors(self) -> str | None:
        return self._terminal.errors

    def __getattr__(self, name: str) -> object:
        return getattr(self._terminal, name)


@dataclass
class CommandLogging:
    transcript_path: Path
    stdout: StdoutTee
    _transcript: TextIO
    _handlers: tuple[logging.Handler, ...]

    def close(self) -> None:
        root = logging.getLogger("drydock")
        for handler in self._handlers:
            root.removeHandler(handler)
            handler.close()
        self._transcript.close()


def setup_command_logging(
    log_dir: Path,
    command_name: str,
    *,
    stdout: TextIO,
    target: str = "",
    debug: bool = False,
) -> CommandLogging:
    """Create or join a plain stdout command transcript.

    A Drydock command may cause an LLM to invoke more ``drydock`` commands.  Those
    child processes inherit the parent transcript path and append their output to it
    instead of creating a misleading sibling transcript for each implementation step.
    """
    log_dir.mkdir(parents=True, exist_ok=True)
    inherited = os.environ.get(_PARENT_TRANSCRIPT_ENV)
    transcript_path: Path
    if inherited:
        candidate = Path(inherited)
        try:
            candidate.resolve().relative_to(log_dir.resolve())
        except (OSError, ValueError):
            candidate = Path()
        if candidate.is_file():
            transcript_path = candidate
            transcript = transcript_path.open("a", encoding="utf-8", newline="")
        else:
            inherited = None
    if not inherited:
        timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
        base = log_dir / log_basename(timestamp, target, command_name)
        transcript_path = base.with_suffix(".log")
        transcript = transcript_path.open("w", encoding="utf-8", newline="")

    root = logging.getLogger("drydock")
    root.setLevel(logging.DEBUG)

    # A handler prevents Python's last-resort logger from leaking warnings to
    # stderr when diagnostics are disabled.
    null_handler = logging.NullHandler()
    root.addHandler(null_handler)
    handlers: list[logging.Handler] = [null_handler]

    if debug:
        console_handler = logging.StreamHandler(sys.stderr)
        console_handler.setLevel(logging.DEBUG)
        console_handler.setFormatter(logging.Formatter("%(levelname)-7s  %(name)s  %(message)s"))
        console_handler._drydock_debug_console = True  # type: ignore[attr-defined]
        root.addHandler(console_handler)
        handlers.append(console_handler)

    return CommandLogging(
        transcript_path=transcript_path,
        stdout=StdoutTee(stdout, transcript),
        _transcript=transcript,
        _handlers=tuple(handlers),
    )


def create_execution_logger(
    execution_id: str,
    *,
    debug: bool,
) -> logging.Logger:
    """Create an execution logger that writes only to an enabled debug console."""
    logger = logging.getLogger(f"drydock.execution.{execution_id}")
    logger.setLevel(logging.DEBUG)
    logger.propagate = True
    logger.handlers.clear()
    logger.addHandler(logging.NullHandler())

    root = logging.getLogger("drydock")
    root_has_debug_console = any(
        getattr(handler, "_drydock_debug_console", False) for handler in root.handlers
    )
    if debug and not root_has_debug_console:
        console_handler = logging.StreamHandler(sys.stderr)
        console_handler.setLevel(logging.DEBUG)
        console_handler.setFormatter(logging.Formatter("%(levelname)-7s  %(name)s  %(message)s"))
        logger.addHandler(console_handler)
    return logger


def close_execution_logger(logger: logging.Logger) -> None:
    for handler in list(logger.handlers):
        handler.close()
        logger.removeHandler(handler)

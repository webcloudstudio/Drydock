"""Command transcripts, debug logs, and per-execution logging for Drydock."""

from __future__ import annotations

import logging
import re
import sys
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TextIO

_ANSI_ESCAPE_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
_SLUG_RE = re.compile(r"[^A-Za-z0-9._-]+")


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
    debug_path: Path
    stdout: StdoutTee
    _transcript: TextIO
    _handlers: tuple[logging.Handler, ...]

    def close(self) -> None:
        root = logging.getLogger("drydock")
        for handler in self._handlers:
            root.removeHandler(handler)
            handler.close()
        self._transcript.close()


def _command_slug(command_name: str) -> str:
    slug = _SLUG_RE.sub("-", command_name.strip()).strip("-._").lower()
    return slug or "drydock"


def setup_command_logging(
    log_dir: Path,
    command_name: str,
    *,
    stdout: TextIO,
    debug: bool = False,
) -> CommandLogging:
    """Create one plain stdout transcript and one internal debug log for a CLI invocation."""
    log_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    base = log_dir / f"{timestamp}_{_command_slug(command_name)}"
    transcript_path = base.with_suffix(".log")
    debug_path = base.with_suffix(".debug.log")
    transcript = transcript_path.open("w", encoding="utf-8", newline="")

    root = logging.getLogger("drydock")
    root.setLevel(logging.DEBUG)

    formatter = logging.Formatter(
        "%(asctime)sZ  %(levelname)-7s  %(name)s  %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )
    formatter.converter = time.gmtime

    file_handler = logging.FileHandler(debug_path, encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(formatter)
    root.addHandler(file_handler)
    handlers: list[logging.Handler] = [file_handler]

    if debug:
        console_handler = logging.StreamHandler(sys.stderr)
        console_handler.setLevel(logging.DEBUG)
        console_handler.setFormatter(logging.Formatter("%(levelname)-7s  %(name)s  %(message)s"))
        root.addHandler(console_handler)
        handlers.append(console_handler)

    return CommandLogging(
        transcript_path=transcript_path,
        debug_path=debug_path,
        stdout=StdoutTee(stdout, transcript),
        _transcript=transcript,
        _handlers=tuple(handlers),
    )


def create_execution_logger(
    execution_id: str,
    debug_file: Path,
    *,
    debug: bool,
) -> logging.Logger:
    logger = logging.getLogger(f"drydock.execution.{execution_id}")
    logger.setLevel(logging.DEBUG)
    logger.propagate = False

    formatter = logging.Formatter(
        "%(asctime)sZ %(levelname)s %(name)s %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )
    formatter.converter = time.gmtime

    file_handler = logging.FileHandler(debug_file, encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(formatter)

    logger.handlers.clear()
    logger.addHandler(file_handler)

    if debug:
        console_handler = logging.StreamHandler(sys.stderr)
        console_handler.setLevel(logging.DEBUG)
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)
    return logger


def close_execution_logger(logger: logging.Logger) -> None:
    for handler in list(logger.handlers):
        handler.close()
        logger.removeHandler(handler)

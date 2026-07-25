"""Durable execution artifacts and append-only JSONL job records."""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def utc_now() -> datetime:
    return datetime.now(UTC)


def isoformat(value: datetime) -> str:
    return value.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def log_timestamp(value: datetime) -> str:
    """Format one UTC instant as the shared log filename timestamp.

    ``20260725.004228.288Z`` — date, time, and milliseconds separated so the stamp is
    readable at a glance while still sorting lexically in directory listings. Every log
    filename and every ``execution_id`` derives from this one function, so a transcript,
    its evidence files, and its ``llm.jsonl`` record all share the same stamp.
    """
    return f"{value:%Y%m%d.%H%M%S}.{value.microsecond // 1000:03d}Z"


def sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def log_component(value: str) -> str:
    """Normalize one filename component (target, command, provider).

    Lowercases, collapses runs of unsupported characters to ``-``, and returns an
    empty string when nothing remains so callers can omit absent parts.
    """
    return re.sub(r"[^a-z0-9._-]+", "-", value.strip().lower()).strip("-._")


def log_basename(timestamp: str, *components: str) -> str:
    """Build the shared log basename ``<timestamp>[_<component>...]``.

    Empty components are dropped so a run with no target or no provider simply omits
    that part. Every Drydock log file — command transcripts and LLM evidence alike —
    derives its name from this one function.
    """
    parts = [c for c in (log_component(value) for value in components) if c]
    return "_".join([timestamp, *parts])


@dataclass(frozen=True)
class ExecutionArtifacts:
    execution_id: str
    records_file: Path
    prompt_file: Path
    raw_file: Path
    output_file: Path
    stderr_file: Path

    @classmethod
    def create(
        cls,
        working_directory: Path,
        command_name: str,
        llm: str,
        *,
        log_dir: Path | None = None,
        target: str = "",
    ) -> ExecutionArtifacts:
        logs = log_dir if log_dir is not None else working_directory / "logs"
        logs.mkdir(parents=True, exist_ok=True)
        timestamp = log_timestamp(utc_now())
        execution_id = f"{timestamp}-{uuid.uuid4().hex[:8]}"
        # The stamp contains dots, so names are composed explicitly; ``with_suffix`` would
        # treat the millisecond field as the extension and overwrite the rest of the stem.
        stem = log_basename(timestamp, target, command_name, llm)
        return cls(
            execution_id=execution_id,
            records_file=logs / "llm.jsonl",
            prompt_file=logs / f"{stem}.prompt.md",
            raw_file=logs / f"{stem}.raw.jsonl",
            output_file=logs / f"{stem}.output.txt",
            stderr_file=logs / f"{stem}.stderr.log",
        )

    def prune_empty(self) -> None:
        """Discard the stderr transcript when the provider wrote nothing to it.

        A silent stderr is the healthy case, and an empty file is noise that reads as a
        missing artifact. ``paths()`` omits it once removed, so no record points at a
        file that is not there.
        """
        try:
            if self.stderr_file.is_file() and self.stderr_file.stat().st_size == 0:
                self.stderr_file.unlink()
        except OSError:
            pass  # evidence pruning must never fail an execution

    def paths(self) -> dict[str, str]:
        paths = {
            "prompt": str(self.prompt_file),
            "raw": str(self.raw_file),
            "output": str(self.output_file),
            "execution_records": str(self.records_file),
        }
        if self.stderr_file.exists():
            paths["stderr"] = str(self.stderr_file)
        return paths


def append_execution_record(path: Path, record: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(record, sort_keys=True, separators=(",", ":"), default=str)
    with path.open("a", encoding="utf-8", newline="\n") as stream:
        stream.write(encoded + "\n")

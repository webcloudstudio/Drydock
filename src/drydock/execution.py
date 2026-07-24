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
        now = utc_now()
        timestamp = now.strftime("%Y%m%dT%H%M%S%fZ")
        execution_id = f"{timestamp}-{uuid.uuid4().hex[:8]}"
        base = logs / log_basename(timestamp, target, command_name, llm)
        return cls(
            execution_id=execution_id,
            records_file=logs / "llm.jsonl",
            prompt_file=base.with_suffix(".prompt.md"),
            raw_file=base.with_suffix(".raw.jsonl"),
            output_file=base.with_suffix(".output.txt"),
            stderr_file=base.with_suffix(".stderr.log"),
        )

    def paths(self) -> dict[str, str]:
        return {
            "prompt": str(self.prompt_file),
            "raw": str(self.raw_file),
            "output": str(self.output_file),
            "stderr": str(self.stderr_file),
            "execution_records": str(self.records_file),
        }


def append_execution_record(path: Path, record: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(record, sort_keys=True, separators=(",", ":"), default=str)
    with path.open("a", encoding="utf-8", newline="\n") as stream:
        stream.write(encoded + "\n")

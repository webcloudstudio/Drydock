"""Drydock error types."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path


class DrydockError(Exception):
    """Base class for all expected Drydock errors."""


class UsageError(DrydockError):
    """Command arguments do not satisfy the public CLI contract."""


class ConfigurationError(DrydockError):
    """A required configuration value is missing or invalid."""


class SpecificationError(DrydockError):
    """A Blueprint or one of its Typed Specification files is invalid."""


class ValidationError(DrydockError):
    """Validation found one or more failures."""


class LlmError(DrydockError):
    """An LLM CLI execution could not be completed."""


class LlmConfigurationError(LlmError):
    """An LLM provider or execution option is invalid."""


@dataclass(frozen=True)
class ErrorRecord:
    """The current recoverable post-LLM failure for one Target."""

    command: str
    phase: str
    timestamp: str
    classification: str
    detail: str
    recovery: str
    execution_id: str = ""
    evidence: str = ""
    state: str = "Error"


class RecordedError(DrydockError):
    """A post-LLM failure already persisted as a Target error record."""

    def __init__(self, record: ErrorRecord):
        self.record = record
        super().__init__(record.classification)


def errors_path(target_dir: Path) -> Path:
    return target_dir / "ERRORS.md"


def _safe(text: str, limit: int = 800) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def write_error_record(
    target_dir: Path,
    *,
    command: str,
    phase: str,
    classification: str,
    detail: str,
    recovery: str,
    execution_id: str | None = None,
    evidence: Path | str | None = None,
    state: str = "Error",
) -> ErrorRecord:
    """Overwrite the Target's current post-LLM error; execution evidence is history."""
    record = ErrorRecord(
        command=command,
        phase=phase,
        timestamp=datetime.now(UTC).isoformat(timespec="seconds"),
        classification=_safe(classification, 240),
        detail=_safe(detail) or "No additional safe diagnostic was available.",
        recovery=recovery,
        execution_id=execution_id or "",
        evidence=str(evidence or ""),
        state=state,
    )
    lines = [
        "# BIG ERRORS — action required",
        "",
        f"- Command: `{record.command}`",
        f"- Phase: {record.phase}",
        f"- State: {record.state}",
        f"- Timestamp: {record.timestamp}",
        f"- Execution ID: {record.execution_id or '-'}",
        f"- Classification: {record.classification}",
        f"- Evidence / logs: {record.evidence or '-'}",
        "",
        "## Diagnostic",
        "",
        record.detail,
        "",
        "## Recovery",
        "",
        record.recovery,
        "",
    ]
    path = errors_path(target_dir)
    path.write_text("\n".join(lines), encoding="utf-8", newline="\n")
    return record


def clear_error_record(target_dir: Path) -> bool:
    """Remove only the current generated error after preflight has passed."""
    path = errors_path(target_dir)
    if not path.exists():
        return False
    path.unlink()
    return True


def read_error_record(target_dir: Path) -> ErrorRecord | None:
    path = errors_path(target_dir)
    if not path.is_file():
        return None
    text = path.read_text(encoding="utf-8")
    fields = {}
    for line in text.splitlines():
        if line.startswith("- ") and ": " in line:
            key, value = line[2:].split(": ", 1)
            fields[key.lower()] = value.strip().strip("`")
    diagnostic = text.partition("## Diagnostic\n")[2].partition("## Recovery")[0].strip()
    recovery = text.partition("## Recovery\n")[2].strip()
    return ErrorRecord(
        command=fields.get("command", ""),
        phase=fields.get("phase", ""),
        timestamp=fields.get("timestamp", ""),
        classification=fields.get("classification", ""),
        detail=diagnostic,
        recovery=recovery,
        execution_id=fields.get("execution id", ""),
        evidence=fields.get("evidence / logs", ""),
        state=fields.get("state", "Error"),
    )

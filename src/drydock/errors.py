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
    challenge_execution_id: str = ""
    evidence: str = ""
    state: str = "Error"
    diagnosis: str = ""


class RecordedError(DrydockError):
    """A post-LLM failure already persisted as a Target error record."""

    def __init__(self, record: ErrorRecord):
        self.record = record
        super().__init__(record.classification)


def errors_path(target_dir: Path) -> Path:
    return target_dir / "ERRORS.md"


def _safe(text: str, limit: int | None = 800) -> str:
    if limit is None:
        return text.strip()
    text = " ".join(text.split())
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def _safe_detail(text: str, limit: int | None = 800) -> str:
    """Bound a diagnostic without destroying its Markdown line structure."""
    text = text.strip()
    if limit is None or len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def write_error_record(
    target_dir: Path,
    *,
    command: str,
    phase: str,
    classification: str,
    detail: str,
    recovery: str,
    execution_id: str | None = None,
    challenge_execution_id: str | None = None,
    evidence: Path | str | None = None,
    state: str = "Error",
    detail_limit: int | None = 800,
) -> ErrorRecord:
    """Overwrite the Target's current post-LLM error; execution evidence is history."""
    record = ErrorRecord(
        command=command,
        phase=phase,
        timestamp=datetime.now(UTC).isoformat(timespec="seconds"),
        classification=_safe(classification, 240),
        detail=_safe_detail(detail, detail_limit) or "No additional safe diagnostic was available.",
        recovery=recovery,
        execution_id=execution_id or "",
        challenge_execution_id=challenge_execution_id or "",
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
        f"- Challenge Execution ID: {record.challenge_execution_id or '-'}",
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


DIAGNOSIS_HEADING = "## Diagnosis"


def _append_diagnosis_section(path: Path, text: str) -> bool:
    """Append (or replace) a standoff diagnosis section on an existing markdown file."""
    body = text.strip()
    if not body or not path.is_file():
        return False
    existing = path.read_text(encoding="utf-8").rstrip("\n")
    if DIAGNOSIS_HEADING in existing:
        existing = existing.partition(f"\n{DIAGNOSIS_HEADING}\n")[0].rstrip("\n")
    path.write_text(
        f"{existing}\n\n{DIAGNOSIS_HEADING}\n\n{body}\n", encoding="utf-8", newline="\n"
    )
    return True


def append_diagnosis(target_dir: Path, text: str) -> bool:
    """Append a standoff diagnosis section to the Target's current error record."""
    return _append_diagnosis_section(errors_path(target_dir), text)


def append_diagnosis_to_evidence(evidence_path: Path, text: str) -> bool:
    """Append a standoff diagnosis section to a build's evidence file so it is self-contained."""
    return _append_diagnosis_section(evidence_path, text)


def clear_error_record(target_dir: Path) -> bool:
    """Remove only the current generated error after preflight has passed."""
    path = errors_path(target_dir)
    if not path.exists():
        return False
    path.unlink()
    return True


def _until_next_section(text: str) -> str:
    """Take a section body up to the next ``## `` heading so later sections do not bleed in."""
    for index, line in enumerate(text.splitlines()):
        if line.startswith("## "):
            return "\n".join(text.splitlines()[:index]).strip()
    return text.strip()


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
    recovery = _until_next_section(text.partition("## Recovery\n")[2])
    diagnosis = _until_next_section(text.partition(f"{DIAGNOSIS_HEADING}\n")[2])
    return ErrorRecord(
        command=fields.get("command", ""),
        phase=fields.get("phase", ""),
        timestamp=fields.get("timestamp", ""),
        classification=fields.get("classification", ""),
        detail=diagnostic,
        recovery=recovery,
        execution_id=fields.get("execution id", ""),
        challenge_execution_id=fields.get("challenge execution id", ""),
        evidence=fields.get("evidence / logs", ""),
        state=fields.get("state", "Error"),
        diagnosis=diagnosis,
    )

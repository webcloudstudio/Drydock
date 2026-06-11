"""JSONL-only Ship's Log event persistence and audit."""

from __future__ import annotations

import json
import os
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from drydock.errors import DrydockError
from drydock.execution import isoformat, utc_now

SCHEMA_VERSION = 1
EVENT_TYPES = {"decision", "milestone"}
REQUIRED_FIELDS = (
    "schema_version",
    "event_id",
    "recorded_at",
    "event_type",
    "title",
    "summary",
    "rationale",
    "source",
)
OPTIONAL_LIST_FIELDS = ("affected_scope", "alternatives", "evidence", "supersedes", "tags")


class ShipsLogError(DrydockError):
    """A Ship's Log record or operation is invalid."""


@dataclass(frozen=True)
class AuditFinding:
    line: int
    message: str


@dataclass
class AuditResult:
    path: Path
    records: list[dict[str, Any]] = field(default_factory=list)
    findings: list[AuditFinding] = field(default_factory=list)

    def ok(self) -> bool:
        return not self.findings


def ships_log_path(target_directory: Path) -> Path:
    return target_directory / "logs" / "ships_log.jsonl"


def _nonempty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def validate_record(record: dict[str, Any]) -> None:
    missing = [field for field in REQUIRED_FIELDS if field not in record]
    if missing:
        raise ShipsLogError(f"Ship's Log record missing required fields: {', '.join(missing)}")

    if record["schema_version"] != SCHEMA_VERSION:
        raise ShipsLogError(
            f"Unsupported Ship's Log schema_version: {record['schema_version']!r}; "
            f"expected {SCHEMA_VERSION}"
        )
    if not _nonempty_string(record["event_id"]):
        raise ShipsLogError("Ship's Log event_id must be a non-empty string.")
    try:
        datetime.fromisoformat(str(record["recorded_at"]).replace("Z", "+00:00"))
    except ValueError as exc:
        raise ShipsLogError("Ship's Log recorded_at must be an ISO-8601 timestamp.") from exc
    if record["event_type"] not in EVENT_TYPES:
        raise ShipsLogError(
            f"Invalid Ship's Log event_type: {record['event_type']!r}; "
            f"expected one of {', '.join(sorted(EVENT_TYPES))}"
        )
    for field_name in ("title", "summary", "rationale"):
        if not _nonempty_string(record[field_name]):
            raise ShipsLogError(f"Ship's Log {field_name} must be a non-empty string.")
    source = record["source"]
    if not isinstance(source, dict) or not _nonempty_string(source.get("type")):
        raise ShipsLogError("Ship's Log source must be an object with a non-empty type.")
    for field_name in OPTIONAL_LIST_FIELDS:
        if field_name in record and not isinstance(record[field_name], list):
            raise ShipsLogError(f"Ship's Log {field_name} must be a list when provided.")


def create_record(
    *,
    event_type: str,
    title: str,
    summary: str,
    rationale: str,
    source_type: str,
    source_command: str | None = None,
    source_provider: str | None = None,
    affected_scope: list[str] | None = None,
    alternatives: list[dict[str, str]] | None = None,
    evidence: list[str] | None = None,
    supersedes: list[str] | None = None,
    tags: list[str] | None = None,
) -> dict[str, Any]:
    source = {"type": source_type}
    if source_command:
        source["command"] = source_command
    if source_provider:
        source["provider"] = source_provider
    record: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "event_id": str(uuid.uuid4()),
        "recorded_at": isoformat(utc_now()),
        "event_type": event_type,
        "title": title,
        "summary": summary,
        "rationale": rationale,
        "source": source,
    }
    for name, value in (
        ("affected_scope", affected_scope),
        ("alternatives", alternatives),
        ("evidence", evidence),
        ("supersedes", supersedes),
        ("tags", tags),
    ):
        if value:
            record[name] = value
    validate_record(record)
    return record


def append_record(target_directory: Path, record: dict[str, Any]) -> Path:
    validate_record(record)
    path = ships_log_path(target_directory)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        for existing in _valid_records(path):
            if existing["event_id"] == record["event_id"]:
                raise ShipsLogError(f"Duplicate Ship's Log event_id: {record['event_id']}")

    encoded = (
        json.dumps(record, sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n"
    ).encode("utf-8")
    descriptor = os.open(path, os.O_APPEND | os.O_CREAT | os.O_WRONLY, 0o644)
    try:
        written = os.write(descriptor, encoded)
    finally:
        os.close(descriptor)
    if written != len(encoded):
        raise ShipsLogError(f"Incomplete Ship's Log append to {path}.")
    return path


def _valid_records(path: Path) -> list[dict[str, Any]]:
    result = audit_log(path)
    if not result.ok():
        first = result.findings[0]
        raise ShipsLogError(
            f"Cannot append to invalid Ship's Log: line {first.line}: {first.message}"
        )
    return result.records


def audit_log(path: Path) -> AuditResult:
    result = AuditResult(path=path)
    if not path.exists():
        return result

    seen: set[str] = set()
    for line_number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not raw.strip():
            result.findings.append(AuditFinding(line_number, "blank line"))
            continue
        try:
            record = json.loads(raw)
        except json.JSONDecodeError as exc:
            result.findings.append(AuditFinding(line_number, f"invalid JSON: {exc.msg}"))
            continue
        if not isinstance(record, dict):
            result.findings.append(AuditFinding(line_number, "record must be a JSON object"))
            continue
        try:
            validate_record(record)
        except ShipsLogError as exc:
            result.findings.append(AuditFinding(line_number, str(exc)))
            continue
        event_id = record["event_id"]
        if event_id in seen:
            result.findings.append(AuditFinding(line_number, f"duplicate event_id: {event_id}"))
            continue
        seen.add(event_id)
        result.records.append(record)

    for line_number, record in enumerate(result.records, start=1):
        for superseded in record.get("supersedes", []):
            if superseded not in seen:
                result.findings.append(
                    AuditFinding(line_number, f"unknown supersedes event_id: {superseded}")
                )
    return result

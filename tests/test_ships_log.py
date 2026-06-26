"""Tests for the JSONL-only Ship's Log."""

from __future__ import annotations

import json

import pytest

from drydock.ships_log import (
    ShipsLogError,
    append_record,
    audit_log,
    create_record,
    ships_log_path,
)


def _record(**overrides):
    values = {
        "event_type": "decision",
        "title": "Use JSONL",
        "summary": "Store one event per line.",
        "rationale": "Structured records support machine consumers.",
        "source_type": "agent",
    }
    values.update(overrides)
    return create_record(**values)


def test_append_creates_canonical_target_log(tmp_path):
    record = _record(tags=["ships-log"], affected_scope=["persistence"])
    path = append_record(tmp_path, record)

    assert path == tmp_path / "logs" / "ships_log.jsonl"
    assert json.loads(path.read_text()) == record


def test_append_preserves_existing_bytes(tmp_path):
    first = _record(title="First")
    second = _record(title="Second", supersedes=[first["event_id"]])
    path = append_record(tmp_path, first)
    original = path.read_bytes()

    append_record(tmp_path, second)

    assert path.read_bytes().startswith(original)
    assert len(path.read_text().splitlines()) == 2
    assert audit_log(path).ok()


def test_invalid_record_does_not_create_file(tmp_path):
    record = _record()
    record["rationale"] = ""

    with pytest.raises(ShipsLogError, match="rationale"):
        append_record(tmp_path, record)

    assert not ships_log_path(tmp_path).exists()


def test_duplicate_event_id_is_rejected(tmp_path):
    record = _record()
    append_record(tmp_path, record)

    with pytest.raises(ShipsLogError, match="Duplicate"):
        append_record(tmp_path, record)


def test_audit_reports_invalid_json_duplicate_and_unknown_supersedes(tmp_path):
    first = _record()
    second = _record(supersedes=["missing"])
    path = ships_log_path(tmp_path)
    path.parent.mkdir()
    path.write_text(
        "\n".join([
            json.dumps(first),
            "{broken",
            json.dumps(first),
            json.dumps(second),
        ])
        + "\n",
        encoding="utf-8",
    )

    messages = [finding.message for finding in audit_log(path).findings]
    assert any("invalid JSON" in message for message in messages)
    assert any("duplicate event_id" in message for message in messages)
    assert any("unknown supersedes" in message for message in messages)


def test_audit_missing_log_is_valid_and_empty(tmp_path):
    result = audit_log(ships_log_path(tmp_path))
    assert result.ok()
    assert result.records == []

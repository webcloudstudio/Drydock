"""Lifecycle boundaries and grouping for ``drydock score llm``."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from drydock.llm_report import LlmReportError, build_llm_score_report


def _record(
    execution_id: str,
    started_at: str,
    command: str,
    *,
    target: str = "Widget",
    model: str = "gpt-5.6-luna",
    llm: str = "codex",
    status: str = "succeeded",
    returncode: int = 0,
    parameters: dict | None = None,
    input_tokens: int = 100,
    cached_input_tokens: int = 80,
    cache_creation_input_tokens: int = 0,
    output_tokens: int = 5,
) -> dict:
    return {
        "execution_id": execution_id,
        "status": status,
        "started_at": started_at,
        "completed_at": started_at,
        "job": {
            "target": target,
            "command_name": command,
            "llm": llm,
            "model": model,
            "parameters": parameters or {"target": target},
        },
        "result": {
            "returncode": returncode,
            "timed_out": False,
            "error": None,
            "stats": {
                "input_tokens": input_tokens,
                "cached_input_tokens": cached_input_tokens,
                "cache_creation_input_tokens": cache_creation_input_tokens,
                "output_tokens": output_tokens,
            },
        },
        "prompt": {},
        "artifacts": {},
    }


def _write_jsonl(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(record) for record in records) + "\n", encoding="utf-8")


def _write_history(workspace: Path, records: list[dict]) -> None:
    _write_jsonl(workspace / "logs" / "history.jsonl", records)


def test_report_defaults_to_latest_init_and_excludes_incomplete_runs(tmp_path):
    workspace = tmp_path
    target_dir = workspace / "targets" / "Widget"
    workspace_records = [
        _record("before", "2026-09-09T12:00:00.000Z", "analyze"),
        _record("synthesis", "2026-09-10T10:01:00.000Z", "plan"),
        _record(
            "lineage",
            "2026-09-10T10:02:00.000Z",
            "lineage_attribute",
            parameters={"source": "FEATURE-WIDGET.md"},
        ),
        _record("broken", "2026-09-10T10:03:00.000Z", "build", status="failed", returncode=1),
    ]
    _write_jsonl(workspace / "logs" / "llm.jsonl", workspace_records)
    _write_jsonl(
        target_dir / "logs" / "llm.jsonl",
        [
            _record("lineage", "2026-09-10T10:02:00.000Z", "lineage_attribute"),
            _record("diagnosis", "2026-09-10T10:04:00.000Z", "diagnose", model=""),
        ],
    )
    _write_history(
        workspace,
        [
            {
                "target": "Widget",
                "argv": ["init", "Widget"],
                "return_code": 0,
                "stamp": "20260910.100000.000Z",
            }
        ],
    )

    report = build_llm_score_report(workspace, target_dir, "Widget")

    assert report.calls == 3
    assert report.excluded_before_init == 1
    assert report.excluded_incomplete == 1
    assert [(row.verb, row.subclass, row.calls) for row in report.rows] == [
        ("plan", "synthesis", 1),
        ("plan", "lineage", 1),
        ("diagnose", "repair", 1),
    ]
    assert report.total_tokens == 315


def test_all_history_includes_pre_init_and_incomplete_runs(tmp_path):
    workspace = tmp_path
    target_dir = workspace / "targets" / "Widget"
    _write_jsonl(
        workspace / "logs" / "llm.jsonl",
        [
            _record("before", "2026-09-09T12:00:00.000Z", "analyze"),
            _record("broken", "2026-09-10T10:03:00.000Z", "build", status="failed", returncode=1),
        ],
    )

    report = build_llm_score_report(workspace, target_dir, "Widget", all_history=True)

    assert report.calls == 2
    assert report.excluded_before_init == 0
    assert report.excluded_incomplete == 0


def test_default_scope_requires_a_successful_init_record(tmp_path):
    workspace = tmp_path
    target_dir = workspace / "targets" / "Widget"
    _write_jsonl(
        workspace / "logs" / "llm.jsonl",
        [_record("run", "2026-09-10T10:03:00.000Z", "build")],
    )

    with pytest.raises(LlmReportError, match="No successful drydock init"):
        build_llm_score_report(workspace, target_dir, "Widget")


def test_report_counts_claude_cache_writes_as_input(tmp_path):
    workspace = tmp_path
    target_dir = workspace / "targets" / "Widget"
    _write_jsonl(
        workspace / "logs" / "llm.jsonl",
        [
            _record(
                "sonnet",
                "2026-09-10T10:01:00.000Z",
                "plan",
                llm="claude",
                model="sonnet",
                input_tokens=2,
                cached_input_tokens=4_000,
                cache_creation_input_tokens=120_000,
                output_tokens=45_000,
            )
        ],
    )
    _write_history(
        workspace,
        [
            {
                "target": "Widget",
                "argv": ["init", "Widget"],
                "return_code": 0,
                "stamp": "20260910.100000.000Z",
            }
        ],
    )

    report = build_llm_score_report(workspace, target_dir, "Widget")

    assert report.total_input_tokens == 124_002
    assert report.cached_input_tokens == 4_000
    assert report.cache_write_input_tokens == 120_000
    assert report.fresh_input_tokens == 2
    assert report.total_tokens == 169_002
    assert report.rows[0].cache_write_input_tokens == 120_000
    assert report.rows[0].cache_write_reported


def test_report_marks_unreported_cache_writes_without_converting_them_to_zero(tmp_path):
    workspace = tmp_path
    target_dir = workspace / "targets" / "Widget"
    _write_jsonl(
        workspace / "logs" / "llm.jsonl",
        [
            _record(
                "luna",
                "2026-09-10T10:01:00.000Z",
                "plan",
                cache_creation_input_tokens=None,
            )
        ],
    )
    _write_history(
        workspace,
        [
            {
                "target": "Widget",
                "argv": ["init", "Widget"],
                "return_code": 0,
                "stamp": "20260910.100000.000Z",
            }
        ],
    )

    report = build_llm_score_report(workspace, target_dir, "Widget")

    assert report.cache_write_input_tokens is None
    assert not report.rows[0].cache_write_reported

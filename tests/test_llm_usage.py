"""Unit tests for target-scoped aggregation of LLM execution evidence."""

from __future__ import annotations

import json
from pathlib import Path

from drydock.llm_usage import (
    build_report,
    iter_targets,
    read_records,
    record_target,
    scan_activity,
    usage_report,
)


def _record(
    *,
    execution_id: str = "exec-1",
    target: str | None = "Alpha",
    command: str = "build",
    llm: str = "codex",
    model: str = "gpt-5.6-luna",
    started_at: str = "2026-07-24T18:00:00.000Z",
    returncode: int | None = 0,
    status: str = "succeeded",
    input_tokens: int | None = 1000,
    cached_input_tokens: int | None = 900,
    output_tokens: int | None = 50,
    elapsed_ms: int | None = 12_000,
    prompt_estimate: int = 400,
    parameters: dict | None = None,
    artifacts: dict | None = None,
    error: str | None = None,
) -> dict:
    job: dict = {
        "command_name": command,
        "llm": llm,
        "model": model,
        "argv": ["codex", "exec"],
        "working_directory": "/tmp/work",
        "parameters": parameters or {},
    }
    if target is not None:
        job["target"] = target
    return {
        "schema_version": 1,
        "execution_id": execution_id,
        "status": status,
        "started_at": started_at,
        "completed_at": started_at,
        "job": job,
        "prompt": {
            "path": "/tmp/logs/p.prompt.md",
            "bytes": prompt_estimate * 4,
            "total_tokens_estimate": prompt_estimate,
            "parts": [],
        },
        "artifacts": artifacts if artifacts is not None else {},
        "result": {
            "returncode": returncode,
            "stats": {
                "input_tokens": input_tokens,
                "cached_input_tokens": cached_input_tokens,
                "output_tokens": output_tokens,
                "elapsed_ms": elapsed_ms,
            },
            "error": error,
            "timed_out": False,
        },
    }


def test_read_records_skips_unparsable_lines(tmp_path: Path) -> None:
    path = tmp_path / "llm.jsonl"
    path.write_text(
        "\n".join([json.dumps(_record()), "{broken", "", "[1, 2]"]) + "\n",
        encoding="utf-8",
    )

    records, invalid = read_records(path)

    assert len(records) == 1
    assert invalid == 2


def test_read_records_tolerates_a_missing_file(tmp_path: Path) -> None:
    assert read_records(tmp_path / "absent.jsonl") == ([], 0)


def test_record_target_prefers_the_recorded_job_target() -> None:
    assert record_target(_record(target="Alpha")) == "Alpha"


def test_record_target_falls_back_to_the_job_parameter() -> None:
    record = _record(target=None, parameters={"target": "Beta"})

    assert record_target(record) == "Beta"


def test_record_target_recovers_older_records_from_the_artifact_basename() -> None:
    record = _record(
        target=None,
        command="rigging compact",
        llm="codex",
        artifacts={
            "prompt": "/logs/20260724T183803132947Z_commonmark_2_rigging-compact_codex.prompt.md"
        },
    )

    assert record_target(record) == "commonmark_2"


def test_record_target_is_empty_when_nothing_attributes_the_run() -> None:
    assert record_target(_record(target=None, artifacts={})) == ""


def test_build_report_scopes_runs_to_one_target_newest_first() -> None:
    records = [
        _record(execution_id="a", target="Alpha", started_at="2026-07-24T10:00:00.000Z"),
        _record(execution_id="b", target="Beta", started_at="2026-07-24T11:00:00.000Z"),
        _record(execution_id="c", target="Alpha", started_at="2026-07-24T12:00:00.000Z"),
    ]

    report = build_report(records, "Alpha", include_activity=False)

    assert [run.execution_id for run in report.runs] == ["c", "a"]
    assert report.target == "Alpha"
    assert report.run_count == 2


def test_codex_cache_tokens_are_a_subset_of_reported_input() -> None:
    records = [_record(llm="codex", input_tokens=1000, cached_input_tokens=900)]

    run = build_report(records, "Alpha", include_activity=False).runs[0]

    assert run.total_input_tokens == 1000
    assert run.cached_input_tokens == 900
    assert run.fresh_input_tokens == 100


def test_claude_cache_tokens_are_added_to_reported_input() -> None:
    records = [_record(llm="claude", model="opus", input_tokens=4, cached_input_tokens=900)]

    run = build_report(records, "Alpha", include_activity=False).runs[0]

    assert run.total_input_tokens == 904
    assert run.cached_input_tokens == 900
    assert run.fresh_input_tokens == 4


def test_missing_stats_are_treated_as_zero_not_an_error() -> None:
    records = [
        _record(input_tokens=None, cached_input_tokens=None, output_tokens=None, elapsed_ms=None)
    ]

    run = build_report(records, "Alpha", include_activity=False).runs[0]

    assert run.total_input_tokens == 0
    assert run.output_tokens == 0
    assert run.seconds == 0.0
    assert run.cache_hit_rate == 0.0


def test_report_totals_and_groupings() -> None:
    records = [
        _record(execution_id="a", command="build", input_tokens=1000, cached_input_tokens=800),
        _record(execution_id="b", command="build", input_tokens=500, cached_input_tokens=400),
        _record(
            execution_id="c",
            command="analyze",
            llm="claude",
            model="opus",
            input_tokens=100,
            cached_input_tokens=0,
            returncode=1,
            status="failed",
            error="provider rate limit 429",
        ),
    ]

    report = build_report(records, "Alpha", include_activity=False)

    assert report.total_input_tokens == 1600
    assert report.cached_input_tokens == 1200
    assert report.fresh_input_tokens == 400
    assert report.output_tokens == 150
    assert report.total_tokens == 1750
    assert report.prompt_tokens_estimate == 1200
    assert report.seconds == 36.0
    assert report.cache_hit_rate == 0.75
    assert [group.key for group in report.by_command] == ["build", "analyze"]
    assert report.by_command[0].runs == 2
    assert report.by_command[0].total_tokens == 1600
    assert report.by_command[1].failures == 1
    assert [group.key for group in report.by_provider] == [
        "codex · gpt-5.6-luna",
        "claude · opus",
    ]
    assert [run.execution_id for run in report.failures] == ["c"]


def test_build_step_and_attempt_become_the_run_detail() -> None:
    records = [
        _record(parameters={"step": "parser-foundation", "attempt": 0}),
        _record(execution_id="b", parameters={"step": "parser-foundation", "attempt": 1}),
        _record(execution_id="c", command="analyze", parameters={}),
    ]

    runs = {
        run.execution_id: run for run in build_report(records, "Alpha", include_activity=False).runs
    }

    assert runs["exec-1"].detail == "parser-foundation"
    assert runs["b"].detail == "parser-foundation (attempt 2)"
    assert runs["c"].detail == "analyze"


def test_scan_activity_counts_completed_codex_items(tmp_path: Path) -> None:
    raw = tmp_path / "run.raw.jsonl"
    raw.write_text(
        "\n".join([
            json.dumps({"type": "thread.started"}),
            json.dumps({"type": "item.started", "item": {"type": "command_execution"}}),
            json.dumps({"type": "item.completed", "item": {"type": "command_execution"}}),
            json.dumps({"type": "item.completed", "item": {"type": "command_execution"}}),
            json.dumps({"type": "item.completed", "item": {"type": "file_change"}}),
            json.dumps({"type": "item.completed", "item": {"type": "agent_message"}}),
            "{broken",
        ])
        + "\n",
        encoding="utf-8",
    )

    activity = scan_activity(raw, "codex")

    assert activity.scanned is True
    assert activity.tool_calls == 2
    assert activity.file_changes == 1
    assert activity.messages == 1
    assert activity.events == 6


def test_scan_activity_counts_claude_tool_use_blocks_and_rate_limits(tmp_path: Path) -> None:
    raw = tmp_path / "run.raw.jsonl"
    raw.write_text(
        "\n".join([
            json.dumps({
                "type": "assistant",
                "message": {
                    "content": [
                        {"type": "text", "text": "working"},
                        {"type": "tool_use", "name": "Bash"},
                        {"type": "tool_use", "name": "Read"},
                    ]
                },
            }),
            json.dumps({"type": "rate_limit_event", "rate_limit_info": {"utilization": 0.5}}),
            json.dumps({"type": "rate_limit_event", "rate_limit_info": {"utilization": 0.97}}),
        ])
        + "\n",
        encoding="utf-8",
    )

    activity = scan_activity(raw, "claude")

    assert activity.tool_calls == 2
    assert activity.messages == 1
    assert activity.rate_limit_utilization == 0.97


def test_scan_activity_returns_empty_counts_for_a_missing_transcript(tmp_path: Path) -> None:
    activity = scan_activity(tmp_path / "absent.jsonl", "codex")

    assert activity.scanned is False
    assert activity.tool_calls == 0


def test_usage_report_reads_the_workspace_log_and_scans_activity(tmp_path: Path) -> None:
    logs = tmp_path / "logs"
    logs.mkdir()
    raw = logs / "run.raw.jsonl"
    raw.write_text(
        json.dumps({"type": "item.completed", "item": {"type": "command_execution"}}) + "\n",
        encoding="utf-8",
    )
    (logs / "llm.jsonl").write_text(
        json.dumps(_record(artifacts={"raw": str(raw)})) + "\n",
        encoding="utf-8",
    )

    report = usage_report(logs, "Alpha")

    assert report.run_count == 1
    assert report.tool_calls == 1
    assert report.peak_rate_limit_utilization is None


def test_usage_report_is_empty_for_an_unknown_target(tmp_path: Path) -> None:
    logs = tmp_path / "logs"
    logs.mkdir()
    (logs / "llm.jsonl").write_text(json.dumps(_record(target="Alpha")) + "\n", encoding="utf-8")

    report = usage_report(logs, "Beta")

    assert report.runs == ()
    assert report.records_read == 1


def test_iter_targets_lists_each_target_once_in_first_seen_order() -> None:
    records = [_record(target="Alpha"), _record(target="Beta"), _record(target="Alpha")]

    assert list(iter_targets(records)) == ["Alpha", "Beta"]

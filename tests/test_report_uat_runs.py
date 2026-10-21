"""Successful-run comparison for the read-only ``drydock report uat_report``."""

from __future__ import annotations

import json
from pathlib import Path

_MANIFEST = """# MANIFEST: ReadingList
state: approved

## feature 1: Core
id: feature-core
summary: Core work.
state: pending

## story 1: First
id: first
parent: feature-core
summary: First story.
implements: FEATURE-CORE.md
state: implemented

## story 2: Second
id: second
parent: feature-core
summary: Second story.
implements: FEATURE-CORE.md
state: implemented
"""


def _record(
    *,
    llm: str,
    command: str,
    parameters: dict | None = None,
    stats: dict | None = None,
    raw: str = "",
) -> dict:
    return {
        "status": "succeeded",
        "job": {"llm": llm, "command_name": command, "parameters": parameters or {}},
        "result": {"stats": stats or {}},
        "artifacts": {"raw": raw},
    }


def _run(
    uat_root: Path, kit: str, run_id: str, *, status: str, model: str, records: list[dict]
) -> Path:
    run_dir = uat_root / kit / "runs" / run_id
    (run_dir / "evidence").mkdir(parents=True)
    (run_dir / "workspace" / "logs").mkdir(parents=True)
    result = {"run_id": run_id, "status": status, "environment": {"model": model}}
    (run_dir / "result.json").write_text(json.dumps(result), encoding="utf-8")
    (run_dir / "evidence" / "llm.jsonl").write_text(
        "".join(json.dumps(record) + "\n" for record in records), encoding="utf-8"
    )
    return run_dir


def _jsonl(path: Path, events: list[dict]) -> None:
    path.write_text("".join(json.dumps(event) + "\n" for event in events), encoding="utf-8")


def _workspace(tmp_path: Path) -> Path:
    uat_root = tmp_path / "uat"
    claude = _run(
        uat_root,
        "ReadingList",
        "20261014.051827",
        status="passed",
        model="claude-haiku-5-5",
        records=[
            _record(llm="claude", command="analyze"),
            _record(llm="claude", command="plan"),
            _record(llm="claude", command="plan", parameters={"continuation_pass": "1"}),
            _record(llm="claude", command="plan", parameters={"artifact_repair_pass": "1"}),
            _record(llm="claude", command="plan repair"),
            _record(llm="claude", command="lineage_attribute"),
            _record(
                llm="claude",
                command="build",
                parameters={"attempt": "0"},
                stats={
                    "input_tokens": 10,
                    "cached_input_tokens": 1_000,
                    "cache_creation_input_tokens": 200,
                    "output_tokens": 50,
                    "elapsed_ms": 120_000,
                },
                raw="/elsewhere/claude_build.raw.jsonl",
            ),
            _record(llm="claude", command="build", parameters={"attempt": "1"}),
            _record(llm="claude", command="diagnose"),
            _record(llm="claude", command="score release"),
        ],
    )
    targets = claude / "workspace" / "targets" / "ReadingList"
    targets.mkdir(parents=True)
    (targets / "MANIFEST.md").write_text(_MANIFEST, encoding="utf-8")
    _jsonl(
        claude / "workspace" / "logs" / "claude_build.raw.jsonl",
        [
            {
                "type": "assistant",
                "message": {
                    "content": [
                        {"type": "tool_use", "name": "Bash"},
                        {"type": "tool_use", "name": "Edit"},
                        {"type": "tool_use", "name": "Write"},
                        {"type": "tool_use", "name": "Read"},
                        {"type": "text", "text": "done"},
                    ]
                },
            }
        ],
    )
    codex = _run(
        uat_root,
        "Toml",
        "20261021.013141",
        status="passed",
        model="gpt-5.6-luna",
        records=[
            _record(
                llm="codex",
                command="build",
                parameters={"attempt": "0"},
                stats={"input_tokens": 400, "cached_input_tokens": 300, "output_tokens": 7},
                raw="/elsewhere/codex_build.raw.jsonl",
            )
        ],
    )
    _jsonl(
        codex / "workspace" / "logs" / "codex_build.raw.jsonl",
        [
            {"type": "item.completed", "item": {"type": "command_execution"}},
            {"type": "item.completed", "item": {"type": "command_execution"}},
            {"type": "item.completed", "item": {"type": "file_change"}},
            {"type": "item.completed", "item": {"type": "agent_message"}},
            {"type": "turn.completed"},
        ],
    )
    _run(
        uat_root,
        "Toml",
        "20261020.000000",
        status="failed",
        model="gpt-5.6-luna",
        records=[_record(llm="codex", command="build")],
    )
    return uat_root


def test_successful_runs_exclude_failures_and_sort_newest_first(tmp_path):
    from drydock.report_uat_runs import successful_runs

    rows = successful_runs(_workspace(tmp_path))

    assert [(row.project, row.date, row.model) for row in rows] == [
        ("Toml", "2026-10-21", "gpt-5.6-luna"),
        ("ReadingList", "2026-10-14", "claude-haiku-5-5"),
    ]


def test_calls_are_categorized_and_stories_counted(tmp_path):
    from drydock.report_uat_runs import successful_runs

    claude = successful_runs(_workspace(tmp_path))[1]

    assert claude.stories == 2
    assert dict(claude.calls) == {
        "build": 1,
        "repair": 2,
        "plan": 3,
        "plan_repair": 2,
        "other": 2,
    }
    assert claude.total_calls == 10


def test_tokens_split_by_type_per_provider(tmp_path):
    from drydock.report_uat_runs import successful_runs

    codex, claude = successful_runs(_workspace(tmp_path))

    assert (claude.fresh_input_tokens, claude.cache_read_tokens) == (10, 1_000)
    assert (claude.cache_write_tokens, claude.output_tokens, claude.total_tokens) == (
        200,
        50,
        1_260,
    )
    assert (codex.fresh_input_tokens, codex.cache_read_tokens) == (100, 300)
    assert (codex.cache_write_tokens, codex.total_tokens) == (None, 407)
    assert claude.llm_elapsed_ms == 120_000


def test_tool_calls_normalized_across_providers(tmp_path):
    from drydock.report_uat_runs import successful_runs

    codex, claude = successful_runs(_workspace(tmp_path))

    assert (claude.shell_calls, claude.edit_calls, claude.other_tool_calls) == (1, 2, 1)
    assert (codex.shell_calls, codex.edit_calls, codex.other_tool_calls) == (2, 1, 0)


def test_render_uat_report_tables(tmp_path):
    from drydock.report_uat_runs import render_uat_report, successful_runs

    lines = render_uat_report(successful_runs(_workspace(tmp_path)))
    text = "\n".join(lines)

    assert lines[:2] == ["UAT RUN REPORT", "--------------"]
    for title in ("DRYDOCK LLM CALLS", "TOKENS", "TOOL CALLS AND TIME"):
        assert title in lines
    calls_header = lines.index("DRYDOCK LLM CALLS") + 1
    assert lines[calls_header + 2].split() == [
        "ReadingList", "2026-10-14", "claude-haiku-5-5", "2", "1", "2", "3", "2", "2", "10"
    ]  # fmt: skip
    assert "—" in text


def test_render_uat_report_with_no_successful_runs():
    from drydock.report_uat_runs import render_uat_report

    assert render_uat_report([]) == ["UAT RUN REPORT", "--------------", "No successful UAT runs."]


def test_cli_report_uat_report_reads_workspace_kits(tmp_path, monkeypatch):
    from tests.test_cli import run_cli

    _workspace(tmp_path)
    monkeypatch.setenv("DRYDOCK_WORKSPACE", str(tmp_path))

    rc, out, _err = run_cli("report", "uat_report")

    assert rc == 0
    assert "UAT RUN REPORT" in out
    assert "2026-10-20" not in out


def test_cli_report_uat_report_rejects_operands_and_missing_root(tmp_path, monkeypatch):
    from tests.test_cli import run_cli

    monkeypatch.setenv("DRYDOCK_WORKSPACE", str(tmp_path))

    assert run_cli("report", "uat_report", "Toml")[0] == 2
    rc, _out, err = run_cli("report", "uat_report")
    assert rc == 1
    assert "no UAT kits found" in err

"""Successful-run comparison for the read-only ``drydock score uat_report``."""

from __future__ import annotations

import json
from pathlib import Path


def _record(*, llm: str, turns: int | None, raw: str = "") -> dict:
    return {
        "status": "succeeded",
        "job": {"llm": llm, "command_name": "build"},
        "result": {"stats": {"turns": turns}},
        "artifacts": {"raw": raw},
    }


def _run(
    uat_root: Path,
    kit: str,
    run_id: str,
    *,
    status: str,
    model: str,
    records: list[dict],
    usage: tuple[int, int] = (0, 0),
) -> Path:
    run_dir = uat_root / kit / "runs" / run_id
    (run_dir / "evidence").mkdir(parents=True)
    (run_dir / "workspace" / "logs").mkdir(parents=True)
    result = {
        "run_id": run_id,
        "status": status,
        "environment": {"model": model, "provider": "x"},
        "usage": {"input_tokens": usage[0], "output_tokens": usage[1]},
    }
    (run_dir / "result.json").write_text(json.dumps(result), encoding="utf-8")
    (run_dir / "evidence" / "llm.jsonl").write_text(
        "".join(json.dumps(record) + "\n" for record in records), encoding="utf-8"
    )
    return run_dir


def _codex_transcript(path: Path) -> None:
    events = [
        {"type": "turn.started"},
        {"type": "item.completed", "item": {"type": "command_execution"}},
        {"type": "item.completed", "item": {"type": "file_change"}},
        {"type": "item.completed", "item": {"type": "agent_message"}},
        {"type": "turn.completed"},
    ]
    path.write_text("".join(json.dumps(event) + "\n" for event in events), encoding="utf-8")


def _workspace(tmp_path: Path) -> Path:
    uat_root = tmp_path / "uat"
    _run(
        uat_root,
        "ReadingList",
        "20261014.051827",
        status="passed",
        model="claude-haiku-5-5",
        records=[_record(llm="claude", turns=12), _record(llm="claude", turns=3)],
        usage=(1_000_000, 2_500),
    )
    codex = _run(
        uat_root,
        "Toml",
        "20261021.013141",
        status="passed",
        model="gpt-5.6-luna",
        # The recorded path is stale, as after a kit moves; the transcript sits in workspace/logs.
        records=[_record(llm="codex", turns=None, raw="/elsewhere/run_build_codex.raw.jsonl")],
        usage=(40, 2),
    )
    _codex_transcript(codex / "workspace" / "logs" / "run_build_codex.raw.jsonl")
    _run(
        uat_root,
        "Toml",
        "20261020.000000",
        status="failed",
        model="gpt-5.6-luna",
        records=[_record(llm="codex", turns=99)],
        usage=(9, 9),
    )
    return uat_root


def test_successful_runs_exclude_failures_and_sort_newest_first(tmp_path):
    from drydock.score_uat import successful_runs

    rows = successful_runs(_workspace(tmp_path))

    assert [(row.project, row.date, row.model, row.turns, row.total_tokens) for row in rows] == [
        ("Toml", "2026-10-21", "gpt-5.6-luna", 3, 42),
        ("ReadingList", "2026-10-14", "claude-haiku-5-5", 15, 1_002_500),
    ]


def test_render_uat_report_aligns_columns(tmp_path):
    from drydock.score_uat import render_uat_report, successful_runs

    lines = render_uat_report(successful_runs(_workspace(tmp_path)))

    assert lines[:2] == ["UAT RUN REPORT", "--------------"]
    assert lines[2].split() == ["Project", "Date", "Model", "Turns", "Total", "Tokens"]
    assert lines[4].split() == ["ReadingList", "2026-10-14", "claude-haiku-5-5", "15", "1,002,500"]
    assert len({len(line) for line in lines[2:]}) == 1


def test_render_uat_report_with_no_successful_runs():
    from drydock.score_uat import render_uat_report

    assert render_uat_report([]) == ["UAT RUN REPORT", "--------------", "No successful UAT runs."]


def test_cli_score_uat_report_reads_workspace_kits(tmp_path, monkeypatch):
    from tests.test_cli import run_cli

    _workspace(tmp_path)
    monkeypatch.setenv("DRYDOCK_WORKSPACE", str(tmp_path))

    rc, out, _err = run_cli("score", "uat_report")

    assert rc == 0
    assert "UAT RUN REPORT" in out
    assert "20261020" not in out and "2026-10-20" not in out


def test_cli_score_uat_report_rejects_operands_and_missing_root(tmp_path, monkeypatch):
    from tests.test_cli import run_cli

    monkeypatch.setenv("DRYDOCK_WORKSPACE", str(tmp_path))

    assert run_cli("score", "uat_report", "Toml")[0] == 2
    rc, _out, err = run_cli("score", "uat_report")
    assert rc == 1
    assert "no UAT kits found" in err

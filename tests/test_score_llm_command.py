"""CLI contract for the read-only ``drydock score llm`` report."""

from __future__ import annotations

import json


def test_score_llm_renders_lifecycle_usage_without_mutating_target(tmp_path, monkeypatch, capsys):
    from drydock import cli

    target_dir = tmp_path / "targets" / "Widget"
    target_dir.mkdir(parents=True)
    logs = tmp_path / "logs"
    logs.mkdir()
    record = {
        "execution_id": "run-1",
        "status": "succeeded",
        "started_at": "2026-09-10T10:01:00.000Z",
        "completed_at": "2026-09-10T10:01:01.000Z",
        "job": {
            "target": "Widget",
            "command_name": "lineage_attribute",
            "llm": "codex",
            "model": "gpt-5.6-luna",
            "parameters": {"source": "FEATURE-WIDGET.md"},
        },
        "result": {
            "returncode": 0,
            "timed_out": False,
            "error": None,
            "stats": {"input_tokens": 100, "cached_input_tokens": 80, "output_tokens": 5},
        },
        "prompt": {},
        "artifacts": {},
    }
    (logs / "llm.jsonl").write_text(json.dumps(record) + "\n", encoding="utf-8")
    (logs / "history.jsonl").write_text(
        json.dumps({
            "target": "Widget",
            "argv": ["init", "Widget"],
            "return_code": 0,
            "stamp": "20260910.100000.000Z",
        })
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("DRYDOCK_WORKSPACE", str(tmp_path))

    assert cli.cmd_score_llm("Widget") == 0

    output = capsys.readouterr().out
    assert "LLM usage: Widget" in output
    assert "plan" in output
    assert "lineage" in output
    assert "codex / gpt-5.6-luna" in output
    assert "All selected activity" in output
    assert not (target_dir / "PROJECT_STATUS.jsonl").exists()

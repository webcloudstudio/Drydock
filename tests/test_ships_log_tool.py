"""Tests for the repository-local Ship's Log agent utility."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from drydock.ships_log_tool import main


def test_record_writes_drydock_canonical_log(tmp_path, capsys):
    rc = main(
        [
            "record",
            "--event-type",
            "decision",
            "--title",
            "Use a local process",
            "--summary",
            "Keep Ship's Log capture local to Drydock agents.",
            "--rationale",
            "Target projects must not inherit Drydock development governance.",
            "--source-type",
            "agent",
            "--alternative",
            "Shared Rigging::It applies the policy to every target.",
            "--tag",
            "ships-log",
        ],
        root=tmp_path,
    )

    assert rc == 0
    record = json.loads((tmp_path / "logs" / "ships_log.jsonl").read_text(encoding="utf-8"))
    assert record["alternatives"][0]["option"] == "Shared Rigging"
    assert "Appended Ship's Log event" in capsys.readouterr().out


def test_audit_reports_invalid_local_log(tmp_path, capsys):
    path = tmp_path / "logs" / "ships_log.jsonl"
    path.parent.mkdir()
    path.write_text("{broken\n", encoding="utf-8")

    assert main(["audit"], root=tmp_path) == 1
    output = capsys.readouterr().out
    assert "RESULT: FAIL" in output
    assert str(path) in output


def test_utility_rejects_target_argument():
    with pytest.raises(SystemExit) as exc:
        main(["audit", "AnotherProject"])

    assert exc.value.code == 2


def test_repository_launcher_audits_canonical_log():
    root = Path(__file__).parents[1]
    result = subprocess.run(
        [sys.executable, str(root / "bin" / "ships_log.py"), "audit"],
        cwd=root,
        capture_output=True,
        check=False,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert f"Ship's Log: {root / 'logs' / 'ships_log.jsonl'}" in result.stdout
    assert "RESULT: PASS" in result.stdout


def test_capture_contract_is_local_not_shared_rigging():
    root = Path(__file__).parents[1]
    agents = (root / "AGENTS.md").read_text(encoding="utf-8")
    shared_rules = "\n".join(
        (root / path).read_text(encoding="utf-8")
        for path in ("Rigging/BUSINESS_RULES.md", "Rigging/CLAUDE_RULES.md")
    )

    assert "Ship's Log Process" in agents
    assert "final Ship's Log review" in agents
    for classification in ("open-item", "deferred-item", "accepted-risk"):
        assert classification in agents
    assert "drydock log append" not in shared_rules

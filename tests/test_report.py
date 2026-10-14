"""Deterministic report registry and Target artifact contracts."""

from __future__ import annotations

from drydock.project_status import record_status
from drydock.report import REPORT_TYPES, ReportContext, report_help, write_reports
from tests.test_cli import run_cli

_PLAN = """# MANIFEST: Demo
state: approved
updated: 2026-10-05T00:00:00
plan_hash: example

## story 1: Foundation
id: foundation
state: closed/verified

## story 2: Screen
id: screen
depends: foundation
state: pending
"""


def test_help_lists_registered_commands_without_creating_reports(
    tmp_workspace, isolated_config, monkeypatch
):
    monkeypatch.setenv("DRYDOCK_WORKSPACE", str(tmp_workspace))

    rc, out, err = run_cli("report", "help")

    assert rc == 0, err
    assert "ReportName | Command | Description" in out
    for report_type in REPORT_TYPES:
        assert report_type.command in out
    assert not (tmp_workspace / "targets" / "reports").exists()
    assert "drydock report --all <Target>" in report_help()
    assert "drydock report --all" in report_help()


def test_manifest_report_uses_plan_state_without_editing_manifest(tmp_workspace):
    target_dir = tmp_workspace / "targets" / "Demo"
    target_dir.mkdir()
    manifest = target_dir / "MANIFEST.md"
    manifest.write_text(_PLAN, encoding="utf-8")
    ctx = ReportContext("Demo", target_dir, tmp_workspace)

    (report_path,) = write_reports(ctx, ("manifest",))

    body = report_path.read_text(encoding="utf-8")
    assert "foundation: closed/verified" in body
    assert "screen: pending · ready" in body
    assert "Buildable now: screen" in body
    assert manifest.read_text(encoding="utf-8") == _PLAN


def test_all_reports_write_target_report_artifacts(tmp_workspace, isolated_config, monkeypatch):
    monkeypatch.setenv("DRYDOCK_WORKSPACE", str(tmp_workspace))
    target_dir = tmp_workspace / "targets" / "Demo"
    target_dir.mkdir()
    (target_dir / "MANIFEST.md").write_text(_PLAN, encoding="utf-8")
    monkeypatch.chdir(tmp_workspace)

    rc, out, err = run_cli("report", "--all", "Demo")

    assert rc == 0, err
    for report_type in REPORT_TYPES:
        path = target_dir / "reports" / f"{report_type.name}.txt"
        assert path.is_file()
        assert f"Report: targets/Demo/reports/{report_type.name}.txt" in out
    assert not (tmp_workspace / "uat").exists()


def test_all_without_target_covers_every_initialized_target(
    tmp_workspace, isolated_config, monkeypatch
):
    monkeypatch.setenv("DRYDOCK_WORKSPACE", str(tmp_workspace))
    monkeypatch.chdir(tmp_workspace)
    for name in ("Alpha", "Beta"):
        target_dir = tmp_workspace / "targets" / name
        target_dir.mkdir()
        (target_dir / "METADATA.md").write_text(f"# {name}\n", encoding="utf-8")
        (target_dir / "MANIFEST.md").write_text(_PLAN, encoding="utf-8")

    rc, out, err = run_cli("report", "--all")

    assert rc == 0, err
    for name in ("Alpha", "Beta"):
        for report_type in REPORT_TYPES:
            path = tmp_workspace / "targets" / name / "reports" / f"{report_type.name}.txt"
            assert path.is_file()
            assert f"Report: targets/{name}/reports/{report_type.name}.txt" in out


def test_workspace_sweep_continues_after_one_target_fails(
    tmp_workspace, isolated_config, monkeypatch
):
    monkeypatch.setenv("DRYDOCK_WORKSPACE", str(tmp_workspace))
    monkeypatch.chdir(tmp_workspace)
    for name, plan in (("Alpha", "not a manifest\n"), ("Beta", _PLAN)):
        target_dir = tmp_workspace / "targets" / name
        target_dir.mkdir()
        (target_dir / "METADATA.md").write_text(f"# {name}\n", encoding="utf-8")
        (target_dir / "MANIFEST.md").write_text(plan, encoding="utf-8")

    rc, out, err = run_cli("report", "--all")

    assert rc == 1
    assert "error: Alpha:" in err
    assert "Report: targets/Beta/reports/manifest.txt" in out
    assert not (tmp_workspace / "targets" / "Alpha" / "reports").exists()


def test_run_report_uses_recorded_lifecycle_state(tmp_workspace):
    target_dir = tmp_workspace / "targets" / "Demo"
    target_dir.mkdir()
    record_status(target_dir, "INITIALIZED", passed=True, command="drydock init Demo")
    record_status(
        target_dir, "ANALYZED", passed=False, detail="blocked", command="drydock analyze Demo"
    )

    (path,) = write_reports(ReportContext("Demo", target_dir, tmp_workspace), ("run",))

    body = path.read_text(encoding="utf-8")
    assert "Current: ANALYZED · FAIL" in body
    assert "Detail: blocked" in body
    assert "INITIALIZED: PASS" in body


def test_unknown_report_is_usage_error_without_output(tmp_workspace, isolated_config, monkeypatch):
    monkeypatch.setenv("DRYDOCK_WORKSPACE", str(tmp_workspace))
    target_dir = tmp_workspace / "targets" / "Demo"
    target_dir.mkdir()

    rc, _out, err = run_cli("report", "mystery", "Demo")

    assert rc == 2
    assert "Usage: drydock report" in err
    assert not (target_dir / "reports").exists()


def test_target_path_is_rejected_before_access(tmp_workspace, isolated_config, monkeypatch):
    monkeypatch.setenv("DRYDOCK_WORKSPACE", str(tmp_workspace))

    rc, _out, err = run_cli("report", "manifest", "../Other")

    assert rc == 2
    assert "Target must be a name" in err


def test_token_report_lists_each_call_with_prompt_size_model_and_run_time(tmp_workspace):
    import json

    target_dir = tmp_workspace / "targets" / "Demo"
    target_dir.mkdir()

    def record(execution_id, started_at, command, prompt_bytes, tokens, elapsed_ms, status):
        return {
            "execution_id": execution_id,
            "status": status,
            "started_at": started_at,
            "completed_at": started_at,
            "job": {
                "target": "Demo",
                "command_name": command,
                "llm": "claude",
                "model": "claude-haiku-5-5",
                "parameters": {"target": "Demo"},
            },
            "result": {"returncode": 0, "stats": {"elapsed_ms": elapsed_ms}},
            "prompt": {"bytes": prompt_bytes, "total_tokens_estimate": tokens},
        }

    logs = tmp_workspace / "logs"
    logs.mkdir(exist_ok=True)
    (logs / "llm.jsonl").write_text(
        "\n".join(
            json.dumps(item)
            for item in (
                record("b", "2026-10-13T23:57:49.000Z", "plan", 139_092, 53_299, 95_000, "failed"),
                record(
                    "a", "2026-10-13T23:57:30.000Z", "analyze", 58_561, 22_441, 18_400, "succeeded"
                ),
            )
        )
        + "\n",
        encoding="utf-8",
    )

    (report_path,) = write_reports(ReportContext("Demo", target_dir, tmp_workspace), ("token",))

    lines = report_path.read_text(encoding="utf-8").splitlines()
    assert "Calls: 2 · prompt 197,653 bytes · ~75,740 tokens · run time 1m53s" in lines
    rows = [line for line in lines if line.startswith("2026-")]
    assert rows == [
        "2026-10-13 23:57:30 | analyze/decomposition | analyze | claude-haiku-5-5 | 58,561 | 22,441 "
        "| 18.4s | succeeded",
        "2026-10-13 23:57:49 | plan/synthesis | plan | claude-haiku-5-5 | 139,092 | 53,299 "
        "| 1m35s | failed",
    ]

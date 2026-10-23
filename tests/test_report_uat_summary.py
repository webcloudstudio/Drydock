"""Read-only 30-day UAT summary, using temporary receipts only."""

import json
from datetime import UTC, datetime, timedelta

from drydock.report_uat_runs import render_uat_summary

_NOW = datetime(2026, 10, 23, 12, tzinfo=UTC)


def _receipt(root, kit, run_id, *, provider="codex", status="passed", finished=None):
    run = root / kit / "runs" / run_id
    run.mkdir(parents=True)
    environment = {"provider": provider}
    if finished is not None:
        environment["finished_at"] = finished
    (run / "result.json").write_text(
        json.dumps({
            "status": status,
            "run_id": run_id,
            "environment": environment,
        })
    )


def test_summary_matrix_and_read_only(tmp_path):
    root = tmp_path / "receipts"
    _receipt(root, "CommonMark", "20261022.000000", provider="claude")
    _receipt(root, "CommonMark", "20261022.000001")
    _receipt(root, "CommonMark", "20261023.000000", status="failed")
    _receipt(root, "CsvStat", "20261021.000000")
    (root / "DupFind").mkdir()
    (root / "README.md").write_text("not a kit")
    before = {p.relative_to(root): p.read_bytes() for p in root.rglob("*") if p.is_file()}

    lines = render_uat_summary(root, now=_NOW)

    assert lines == [
        "# 30 Day UAT Summary Report",
        "#                       Claude  Codex",
        "# CommonMark            Y       Y",
        "# CsvStat                       Y",
        "# DupFind",
    ]
    assert {p.relative_to(root): p.read_bytes() for p in root.rglob("*") if p.is_file()} == before


def test_summary_window_boundaries_and_invalid_results(tmp_path):
    for name, stamp in (
        ("AtCutoff", _NOW - timedelta(days=30)),
        ("TooOld", _NOW - timedelta(days=30, seconds=1)),
        ("AtNow", _NOW),
        ("Future", _NOW + timedelta(seconds=1)),
    ):
        _receipt(tmp_path, name, stamp.strftime("%Y%m%d.%H%M%S"))
    _receipt(tmp_path, "Failed", "20261022.000000", status="failed")
    _receipt(tmp_path, "Degraded", "20261022.000000", status="degraded")
    _receipt(tmp_path, "UnknownProvider", "20261022.000000", provider="gemini")
    _receipt(tmp_path, "BadDate", "invalid")
    _receipt(tmp_path, "BadJson", "20261022.000000")
    (tmp_path / "BadJson/runs/20261022.000000/result.json").write_text("broken")
    _receipt(tmp_path, "BadShape", "20261022.000000")
    (tmp_path / "BadShape/runs/20261022.000000/result.json").write_text("[]")
    lines = render_uat_summary(tmp_path, now=_NOW)
    marked = {line.split()[1] for line in lines[2:] if line.endswith("Y")}
    assert marked == {"AtCutoff", "AtNow"}


def test_summary_uses_completion_time_for_resumed_runs(tmp_path):
    _receipt(tmp_path, "Resumed", "20260101.000000", finished=_NOW.isoformat())
    _receipt(tmp_path, "BadCompletion", "20261022.000000", finished="invalid")
    lines = render_uat_summary(tmp_path, now=_NOW)
    assert lines[-1].split() == ["#", "Resumed", "Y"]
    assert "Y" not in lines[-2]


def test_empty_summary(tmp_path):
    assert render_uat_summary(tmp_path, now=_NOW) == [
        "# 30 Day UAT Summary Report",
        "#                       Claude  Codex",
    ]


def test_cli_summary(tmp_path, monkeypatch):
    from tests.test_cli import run_cli

    root = tmp_path / "uat"
    _receipt(root, "Toml", datetime.now(UTC).strftime("%Y%m%d.%H%M%S"))
    monkeypatch.setenv("DRYDOCK_WORKSPACE", str(tmp_path))
    rc, out, err = run_cli("report", "uat_summary")
    assert rc == 0
    assert not err
    assert [line for line in out.splitlines() if line.startswith("#")][0] == (
        "# 30 Day UAT Summary Report"
    )
    assert out.splitlines()[-1].split() == ["#", "Toml", "Y"]
    assert not (tmp_path / "reports").exists()
    assert run_cli("report", "uat_summary", "Toml")[0] == 2


def test_cli_missing_root_and_help(tmp_path, monkeypatch):
    from tests.test_cli import run_cli

    monkeypatch.setenv("DRYDOCK_WORKSPACE", str(tmp_path))
    rc, _, err = run_cli("report", "uat_summary")
    assert rc == 1
    assert "no UAT kits found" in err
    rc, out, _ = run_cli("report", "help")
    assert rc == 0
    assert "drydock report uat_summary" in out

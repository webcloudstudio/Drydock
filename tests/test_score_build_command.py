"""Command contract for the observational ``drydock score build`` report."""

from __future__ import annotations

from types import SimpleNamespace


def test_score_build_reports_missing_evidence_without_mutating_or_failing(tmp_path, monkeypatch):
    """A report is useful precisely when its subject is incomplete."""
    from drydock import cli

    target_dir = tmp_path / "targets" / "widget"
    target_dir.mkdir(parents=True)
    monkeypatch.setenv("DRYDOCK_WORKSPACE", str(tmp_path))
    report = SimpleNamespace(
        target="widget",
        evidence_dir=target_dir / "evidence",
        records_path=tmp_path / "logs" / "llm.jsonl",
        acceptance=SimpleNamespace(recorded=False),
        blocks=(),
    )
    monkeypatch.setattr("drydock.build_report.build_score_report", lambda *args, **kwargs: report)

    assert cli.cmd_score_build("widget") == 0
    assert not (target_dir / "PROJECT_STATUS.jsonl").exists()
    assert not (target_dir / "SCORECARD.md").exists()

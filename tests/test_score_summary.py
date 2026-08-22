"""Unit tests for ``drydock score <Target>`` — the score summary."""

from __future__ import annotations

import json

from drydock.project_status import record_status
from drydock.score_summary import render_summary, summarize_scores
from drydock.standard_artifacts import VERIFIED_FAIL, VERIFIED_PASS


def _journal(workspace, *records) -> None:
    """Write a command journal holding *records* as ``(stamp, argv, return_code)`` triples."""
    logs = workspace / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    (logs / "history.jsonl").write_text(
        "".join(
            json.dumps({
                "command": "drydock " + " ".join(argv),
                "argv": list(argv),
                "target": argv[-1],
                "stamp": stamp,
                "return_code": code,
            })
            + "\n"
            for stamp, argv, code in records
        ),
        encoding="utf-8",
    )


def _target(workspace, name: str = "T"):
    target_dir = workspace / "targets" / name
    target_dir.mkdir(parents=True)
    return target_dir


def _row(summary, verb):
    return next(run for run in summary.runs if run.verb == verb)


class TestLastRun:
    def test_reports_the_exit_code_each_score_last_returned(self, tmp_path):
        target_dir = _target(tmp_path)
        _journal(
            tmp_path,
            ("20260820.100000.000Z", ["score", "ac", "T"], 1),
            ("20260820.101000.000Z", ["score", "build", "T"], 0),
        )

        summary = summarize_scores("T", tmp_path, target_dir)

        assert _row(summary, "ac").result == "fail"
        assert _row(summary, "build").result == "pass"

    def test_a_score_never_invoked_is_not_run(self, tmp_path):
        target_dir = _target(tmp_path)
        _journal(tmp_path, ("20260820.100000.000Z", ["score", "ac", "T"], 0))

        assert _row(summarize_scores("T", tmp_path, target_dir), "release").result == "not run"
        assert _row(summarize_scores("T", tmp_path, target_dir), "release").at == ""

    def test_the_latest_invocation_wins(self, tmp_path):
        target_dir = _target(tmp_path)
        _journal(
            tmp_path,
            ("20260820.120000.000Z", ["score", "ac", "T"], 0),
            ("20260820.100000.000Z", ["score", "ac", "T"], 1),
        )

        assert _row(summarize_scores("T", tmp_path, target_dir), "ac").result == "pass"

    def test_another_targets_scores_are_not_reported(self, tmp_path):
        target_dir = _target(tmp_path)
        _journal(tmp_path, ("20260820.100000.000Z", ["score", "ac", "Other"], 0))

        assert _row(summarize_scores("T", tmp_path, target_dir), "ac").result == "not run"

    def test_scores_before_the_latest_init_belong_to_an_earlier_run(self, tmp_path):
        target_dir = _target(tmp_path)
        _journal(
            tmp_path,
            ("20260820.100000.000Z", ["score", "ac", "T"], 0),
            ("20260820.110000.000Z", ["init", "T"], 0),
            ("20260820.120000.000Z", ["score", "build", "T"], 0),
        )

        summary = summarize_scores("T", tmp_path, target_dir)

        assert _row(summary, "ac").result == "not run"
        assert _row(summary, "build").result == "pass"

    def test_a_record_mis_targeted_to_its_sub_verb_is_still_found(self, tmp_path):
        """Score commands were once journaled with the sub-verb in the ``target`` field."""
        target_dir = _target(tmp_path)
        logs = tmp_path / "logs"
        logs.mkdir(parents=True)
        (logs / "history.jsonl").write_text(
            json.dumps({
                "command": "drydock score report T",
                "argv": ["score", "report", "T"],
                "target": "report",
                "stamp": "20260820.100000.000Z",
                "return_code": 0,
            })
            + "\n",
            encoding="utf-8",
        )

        assert _row(summarize_scores("T", tmp_path, target_dir), "report").result == "pass"

    def test_a_bare_score_target_contributes_no_sub_verb_result(self, tmp_path):
        target_dir = _target(tmp_path)
        _journal(tmp_path, ("20260820.100000.000Z", ["score", "T"], 0))

        summary = summarize_scores("T", tmp_path, target_dir)

        assert all(run.result == "not run" for run in summary.runs)


class TestOutputs:
    def test_names_each_scores_artifact_and_whether_it_exists(self, tmp_path):
        target_dir = _target(tmp_path)
        _journal(tmp_path, ("20260820.100000.000Z", ["score", "release", "T"], 0))

        row = _row(summarize_scores("T", tmp_path, target_dir), "release")

        assert row.output == "SCORECARD.md"
        assert row.output_at == ""
        assert row.note == "not written"

    def test_an_existing_artifact_reports_when_it_was_written(self, tmp_path):
        target_dir = _target(tmp_path)
        (target_dir / "SCORECARD.md").write_text("# score\n", encoding="utf-8")
        _journal(tmp_path, ("20260820.100000.000Z", ["score", "release", "T"], 0))

        assert _row(summarize_scores("T", tmp_path, target_dir), "release").output_at

    def test_score_build_writes_no_file(self, tmp_path):
        target_dir = _target(tmp_path)

        row = _row(summarize_scores("T", tmp_path, target_dir), "build")

        assert row.output == ""
        assert row.note == "console report; writes no file"

    def test_the_acceptance_row_tallies_the_recorded_board(self, tmp_path):
        target_dir = _target(tmp_path)
        (target_dir / "SOUNDINGS.md").write_text(
            "| Status | Blueprint | AC Id | Text | Evidence | Verified At |\n"
            "|---|---|---|---|---|---|\n"
            f"| {VERIFIED_PASS} | bp | AC-1 | one | log | 2026-08-20 |\n"
            f"| {VERIFIED_FAIL} | bp | AC-2 | two | log | 2026-08-20 |\n",
            encoding="utf-8",
        )

        note = _row(summarize_scores("T", tmp_path, target_dir), "ac").note

        assert "2 criteria" in note
        assert "1 passed" in note
        assert "1 failed" in note


class TestState:
    def test_reports_the_workflow_state_the_target_is_in(self, tmp_path):
        target_dir = _target(tmp_path)
        record_status(target_dir, "BUILT", passed=True)

        summary = summarize_scores("T", tmp_path, target_dir)

        assert (summary.state, summary.state_result) == ("BUILT", "pass")

    def test_a_target_with_no_recorded_state_reports_none(self, tmp_path):
        summary = summarize_scores("T", tmp_path, _target(tmp_path))

        assert summary.state == ""
        assert "none recorded" in "\n".join(render_summary(summary))


class TestRender:
    def test_renders_one_row_per_score(self, tmp_path):
        target_dir = _target(tmp_path)
        record_status(target_dir, "SCORE BUILD", passed=True)
        _journal(tmp_path, ("20260820.100000.000Z", ["score", "build", "T"], 0))

        page = "\n".join(render_summary(summarize_scores("T", tmp_path, target_dir)))

        assert "Target: T" in page
        assert "State:  SCORE BUILD" in page
        assert "PASS · " in page
        for verb in ("spec", "ac", "build", "release", "report"):
            assert f"\n{verb}" in page

    def test_does_not_render_the_removed_standing_column(self, tmp_path):
        page = "\n".join(render_summary(summarize_scores("T", tmp_path, _target(tmp_path))))

        assert "Standing" not in page
        assert "voided" not in page

    def test_lists_the_scores_that_have_not_been_run(self, tmp_path):
        target_dir = _target(tmp_path)
        _journal(tmp_path, ("20260820.100000.000Z", ["score", "build", "T"], 0))

        page = "\n".join(render_summary(summarize_scores("T", tmp_path, target_dir)))

        assert "Not yet run: drydock score ac" in page
        assert "drydock score build" not in page

    def test_the_optional_spec_score_is_not_reported_as_missing(self, tmp_path):
        target_dir = _target(tmp_path)
        _journal(
            tmp_path,
            *(
                ("20260820.100000.000Z", ["score", verb, "T"], 0)
                for verb in ("ac", "build", "release", "report")
            ),
        )

        page = "\n".join(render_summary(summarize_scores("T", tmp_path, target_dir)))

        assert "Not yet run" not in page

    def test_release_score_is_reported_as_project_complete(self, tmp_path):
        target_dir = _target(tmp_path)
        record_status(target_dir, "SCORE RELEASE", passed=True)

        page = "\n".join(render_summary(summarize_scores("T", tmp_path, target_dir)))

        assert "State:  PROJECT COMPLETE" in page
        assert "SCORE RELEASE" not in page

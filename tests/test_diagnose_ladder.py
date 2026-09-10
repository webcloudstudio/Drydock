"""Deterministic ladder, stop resolution, and false-positive detection for ``drydock diagnose``."""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from drydock.diagnose_ladder import (
    LadderRow,
    build_ladder,
    classify,
    ladder_of,
    local_clock,
    render_ladder,
    stop_point,
    stop_point_of,
    superseded_failures,
)
from drydock.project_status import StatusEntry, read_status


def _entry(label: str, passed: bool, *, detail: str = "", attempts: int = 1) -> StatusEntry:
    return StatusEntry(
        label=label,
        passed=passed,
        at="2026-08-21T18:44:02.113+00:00",
        detail=detail,
        command=f"drydock {label.lower()} T",
        attempts=attempts,
    )


def _write_status(target_dir: Path, rows: list[dict]) -> None:
    target_dir.mkdir(parents=True, exist_ok=True)
    (target_dir / "PROJECT_STATUS.jsonl").write_text(
        "\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8"
    )


# ── the ladder ───────────────────────────────────────────────────────────────────────


def test_ladder_renders_every_milestone_including_the_unreached(tmp_path):
    _write_status(
        tmp_path,
        [{"label": "INITIALIZED", "result": "pass", "at": "2026-08-21T17:07:00.000+00:00"}],
    )
    rows = build_ladder(tmp_path)
    assert [row.milestone for row in rows] == ["INIT", "ANALYZE", "PLAN", "BUILD", "SCORE"]
    assert rows[0].state == "pass"
    assert rows[1].state == "not run"
    # Three-valued and no more: no milestone renders as unknown.
    assert {row.state for row in rows} <= {"pass", "fail", "not run"}


def test_a_milestone_is_spoken_for_by_its_last_recorded_state(tmp_path):
    _write_status(
        tmp_path,
        [
            {"label": "PLAN CREATED", "result": "fail", "at": "", "detail": "malformed"},
            {"label": "PLAN REPAIRED", "result": "pass", "at": ""},
        ],
    )
    plan = next(row for row in build_ladder(tmp_path) if row.milestone == "PLAN")
    assert plan.state == "pass"
    assert plan.label == "PLAN REPAIRED"
    assert [entry.label for entry in plan.answered] == ["PLAN CREATED"]


def test_ladder_note_comes_from_the_caller_not_the_ladder(tmp_path):
    _write_status(tmp_path, [{"label": "ANALYZED", "result": "pass", "at": ""}])
    rows = build_ladder(tmp_path, {"ANALYZE": "12 stories"})
    analyzed = next(row for row in rows if row.milestone == "ANALYZE")
    assert analyzed.note == "12 stories"
    assert "12 stories" in render_ladder(rows)


def test_render_marks_each_state_distinctly():
    rows = (
        LadderRow(milestone="INIT", state="pass", at="2026-08-21T17:07:00.000+00:00"),
        LadderRow(milestone="ANALYZE", state="fail", at="2026-08-21T17:12:00.000+00:00"),
        LadderRow(milestone="BUILD", state="not run"),
    )
    text = render_ladder(rows)
    assert f"[OK]   INIT      {local_clock('2026-08-21T17:07:00.000+00:00')}" in text
    assert "[FAIL] ANALYZE" in text
    assert "[--]   BUILD" in text and "not run" in text


@pytest.mark.skipif(not hasattr(time, "tzset"), reason="needs time.tzset")
def test_ladder_times_are_local_not_utc(monkeypatch):
    monkeypatch.setenv("TZ", "America/New_York")
    time.tzset()
    try:
        assert local_clock("2026-09-10T19:29:00.000+00:00") == "2026-09-10 15:29"
    finally:
        monkeypatch.undo()
        time.tzset()


def test_local_clock_keeps_a_malformed_instant_readable():
    assert local_clock("2026-09-10Tgarbage") == "2026-09-10 garba"
    assert local_clock("") == ""


def test_render_names_retry_exhaustion(tmp_path):
    rows = (LadderRow(milestone="SCORE", state="fail", attempts=7),)
    assert "retried 7 times" in render_ladder(rows)


def test_render_survives_a_malformed_timestamp():
    rows = (LadderRow(milestone="BUILD", state="pass", at="not-a-timestamp"),)
    assert "BUILD" in render_ladder(rows)


def test_ladder_of_a_target_with_no_status_file_is_all_not_run(tmp_path):
    rows = build_ladder(tmp_path)
    assert all(row.state == "not run" for row in rows)


def test_ladder_skips_corrupt_rows_rather_than_failing(tmp_path):
    target = tmp_path / "T"
    target.mkdir()
    (target / "PROJECT_STATUS.jsonl").write_text(
        '{"label": "INITIALIZED", "result": "pass", "at": ""}\nnot json at all\n',
        encoding="utf-8",
    )
    rows = build_ladder(target)
    assert next(row for row in rows if row.milestone == "INIT").state == "pass"


# ── the stop ─────────────────────────────────────────────────────────────────────────


def test_no_failure_is_no_stop():
    assert stop_point_of([_entry("INITIALIZED", True), _entry("BUILT", True)]) is None


def test_stop_is_the_highest_failure_not_the_lowest():
    """A repaired plan is the repair working, not the defect the operator must fix."""
    entries = [
        _entry("PLAN CREATED", False, detail="malformed batch"),
        _entry("PLAN REPAIRED", True),
        _entry("BUILT", False, detail="provider rate limit: 429"),
    ]
    stop = stop_point_of(entries)
    assert stop is not None
    assert stop.milestone == "BUILD"
    assert stop.label == "BUILT"
    assert stop.classification == "provider rate limit"


def test_a_failure_answered_by_a_later_pass_is_superseded():
    entries = [
        _entry("PLAN CREATED", False, detail="malformed batch"),
        _entry("PLAN REPAIRED", True),
    ]
    assert stop_point_of(entries) is None
    assert [entry.label for entry in superseded_failures(entries)] == ["PLAN CREATED"]


def test_a_live_failure_is_not_reported_as_superseded():
    entries = [_entry("BUILT", True), _entry("SCORE AC", False, detail="6 of 45 failed")]
    assert superseded_failures(entries) == ()
    assert stop_point_of(entries).milestone == "SCORE"


def test_stop_carries_the_retry_count():
    stop = stop_point_of([_entry("SCORE AC", False, detail="failed", attempts=7)])
    assert stop.retried is True
    assert stop.attempts == 7


def test_stop_point_reads_a_target_directory(tmp_path):
    _write_status(
        tmp_path,
        [
            {"label": "BUILT", "result": "pass", "at": ""},
            {"label": "SCORE AC", "result": "fail", "at": "", "detail": "context/token limit"},
        ],
    )
    stop = stop_point(tmp_path)
    assert stop.milestone == "SCORE"
    assert stop.classification == "context/token limit"


# ── classification ───────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("detail", "expected"),
    [
        ("provider rate limit: 429 too many requests", "provider rate limit"),
        ("The model reported a context/token limit.", "context/token limit"),
        ("execution timed out after 900s", "execution timed out"),
        ("programmatic acceptance failed for 6 criteria", "programmatic acceptance failed"),
        ("", ""),
        ("the product's own test suite disagreed", ""),
    ],
)
def test_classification_reports_only_what_drydock_recorded(detail, expected):
    assert classify(detail) == expected


def test_rate_limit_is_not_shadowed_by_the_broader_provider_error():
    assert classify("provider error: provider rate limit reached") == "provider rate limit"


def test_headline_without_a_classification_still_names_the_stage():
    stop = stop_point_of([_entry("SCORE AC", False, detail="six criteria disagreed")])
    assert stop.headline == "Drydock failed at SCORE"


def test_headline_with_a_classification_names_the_cause():
    stop = stop_point_of([_entry("BUILT", False, detail="provider rate limit")])
    assert stop.headline == "Drydock failed at BUILD — provider rate limit"


def test_status_round_trip_against_a_written_target(tmp_path):
    _write_status(
        tmp_path,
        [
            {"label": "INITIALIZED", "result": "pass", "at": "", "attempts": 1},
            {"label": "ANALYZED", "result": "fail", "at": "", "detail": "x", "attempts": 2},
        ],
    )
    entries = read_status(tmp_path)
    assert [entry.label for entry in entries] == ["INITIALIZED", "ANALYZED"]
    assert stop_point_of(entries).attempts == 2


# ── milestone supersession ───────────────────────────────────────────────────────────


def test_a_repaired_plan_answers_the_failed_one():
    entries = [_entry("PLAN CREATED", False, detail="malformed"), _entry("PLAN REPAIRED", True)]
    assert stop_point_of(entries) is None
    assert [entry.label for entry in superseded_failures(entries)] == ["PLAN CREATED"]


def test_a_completed_build_answers_a_failed_building_state():
    entries = [_entry("BUILDING", False, detail="stopped"), _entry("BUILT", True)]
    assert stop_point_of(entries) is None


def test_a_passing_build_report_does_not_answer_a_failed_acceptance_gate():
    """SCORE BUILD is observational; it reports on different work than SCORE AC."""
    entries = [
        _entry("BUILT", True),
        _entry("SCORE AC", False, detail="6 of 45"),
        _entry("SCORE BUILD", True),
    ]
    stop = stop_point_of(entries)
    assert stop is not None
    assert stop.label == "SCORE AC"
    assert superseded_failures(entries) == ()


def test_a_passing_release_answers_every_score_beneath_it():
    entries = [
        _entry("BUILT", True),
        _entry("SCORE AC", False, detail="6 of 45"),
        _entry("SCORE RELEASE", True),
    ]
    assert stop_point_of(entries) is None
    assert [entry.label for entry in superseded_failures(entries)] == ["SCORE AC"]


def test_an_unanswered_earlier_failure_stands_even_when_the_project_advanced():
    """A plan that never got repaired is still the frontier, whatever was built on it."""
    entries = [_entry("PLAN CREATED", False, detail="malformed"), _entry("BUILT", True)]
    stop = stop_point_of(entries)
    assert stop is not None
    assert stop.milestone == "PLAN"
    assert superseded_failures(entries) == ()


def test_the_ladder_records_which_states_a_milestone_answered():
    entries = [_entry("PLAN CREATED", False, detail="malformed"), _entry("PLAN REPAIRED", True)]
    plan = next(row for row in ladder_of(entries) if row.milestone == "PLAN")
    assert plan.state == "pass"
    assert [entry.label for entry in plan.answered] == ["PLAN CREATED"]


def test_milestones_group_the_ten_ladder_states_into_five():
    from drydock.project_status import LABEL_LADDER, MILESTONES

    grouped = [label for _, labels in MILESTONES for label in labels]
    assert sorted(grouped) == sorted(LABEL_LADDER)
    assert [name for name, _ in MILESTONES] == ["INIT", "ANALYZE", "PLAN", "BUILD", "SCORE"]

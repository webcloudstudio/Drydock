"""Unit tests for the PROJECT_STATUS.jsonl workflow state machine."""

from __future__ import annotations

import json

from drydock.errors import UsageError
from drydock.project_status import (
    LABEL_LADDER,
    STATUS_FILENAME,
    current_state,
    last_good,
    latest_per_label,
    read_status,
    record_failure,
    record_status,
    void_above,
)


def _rows(target_dir):
    text = (target_dir / STATUS_FILENAME).read_text(encoding="utf-8")
    return [json.loads(line) for line in text.splitlines() if line.strip()]


class TestRecordStatus:
    def test_records_one_row_per_state_in_ladder_order(self, tmp_path):
        record_status(tmp_path, "ANALYZED", passed=True, command="drydock analyze T")
        record_status(tmp_path, "INITIALIZED", passed=True, command="drydock init T")
        record_status(tmp_path, "ANALYZED", passed=True, command="drydock analyze T")

        entries = read_status(tmp_path)

        assert [e.label for e in entries] == ["INITIALIZED", "ANALYZED"]
        assert entries[1].command == "drydock analyze T"

    def test_re_recording_a_state_replaces_it_rather_than_appending(self, tmp_path):
        record_status(tmp_path, "BUILT", passed=False, detail="3 step(s) failed")
        record_status(tmp_path, "BUILT", passed=True)

        (entry,) = read_status(tmp_path)

        assert entry.passed is True
        assert entry.detail == ""
        assert entry.attempts == 2

    def test_recording_a_mutating_state_voids_every_state_above_it(self, tmp_path):
        for label in ("INITIALIZED", "BUILT", "SCORE BUILD", "SCORE RELEASE"):
            record_status(tmp_path, label, passed=True)

        record_status(tmp_path, "BUILT", passed=True)

        assert [e.label for e in read_status(tmp_path)] == ["INITIALIZED", "BUILT"]

    def test_importing_voids_nothing(self, tmp_path):
        # Reading sources into a Target changes nothing a later state was verified against.
        for label in ("INITIALIZED", "IMPORTED", "BUILT", "SCORE RELEASE"):
            record_status(tmp_path, label, passed=True)

        record_status(tmp_path, "IMPORTED", passed=True)

        assert [e.label for e in read_status(tmp_path)] == [
            "INITIALIZED",
            "IMPORTED",
            "BUILT",
            "SCORE RELEASE",
        ]

    def test_re_running_a_verification_voids_no_other_state(self, tmp_path):
        for label in ("BUILT", "SCORE AC", "SCORE BUILD", "SCORE RELEASE"):
            record_status(tmp_path, label, passed=True)

        record_status(tmp_path, "SCORE AC", passed=True)

        # No evidence changed, so the scores taken on top of acceptance still stand.
        assert [e.label for e in read_status(tmp_path)] == [
            "BUILT",
            "SCORE AC",
            "SCORE BUILD",
            "SCORE RELEASE",
        ]
        assert current_state(tmp_path).label == "SCORE RELEASE"

    def test_a_failed_verification_invalidates_only_itself(self, tmp_path):
        for label in ("BUILT", "SCORE AC", "SCORE BUILD", "SCORE RELEASE"):
            record_status(tmp_path, label, passed=True)

        record_status(tmp_path, "SCORE AC", passed=False, detail="2 failed")

        standing = latest_per_label(read_status(tmp_path))
        assert standing["SCORE AC"].passed is False
        assert standing["SCORE BUILD"].passed is True
        assert standing["SCORE RELEASE"].passed is True
        # A terminal release score remains the current state despite an older failed check.
        assert current_state(tmp_path).label == "SCORE RELEASE"
        assert last_good(read_status(tmp_path)).label == "SCORE RELEASE"

    def test_last_good_skips_the_ladder_s_optional_rungs(self, tmp_path):
        # PLAN REPAIRED and BUILDING run only conditionally; their absence is not a failure.
        for label in ("INITIALIZED", "PLAN CREATED", "BUILT"):
            record_status(tmp_path, label, passed=True)

        assert current_state(tmp_path).label == "BUILT"


class TestVoidAbove:
    def test_drops_every_state_above_the_named_one(self, tmp_path):
        for label in ("PLAN CREATED", "PLAN REPAIRED", "BUILT", "SCORE RELEASE"):
            record_status(tmp_path, label, passed=True)

        void_above(tmp_path, "PLAN REPAIRED")

        assert [e.label for e in read_status(tmp_path)] == ["PLAN CREATED", "PLAN REPAIRED"]

    def test_keeps_the_named_state_and_ignores_an_unknown_one(self, tmp_path):
        record_status(tmp_path, "BUILT", passed=True)

        void_above(tmp_path, "NOT A STATE")

        assert [e.label for e in read_status(tmp_path)] == ["BUILT"]

    def test_a_failed_mutating_attempt_also_voids_downstream_states(self, tmp_path):
        record_status(tmp_path, "BUILT", passed=True)
        record_status(tmp_path, "SCORE RELEASE", passed=True)

        record_status(tmp_path, "BUILT", passed=False, detail="boom")

        # A build that got partway and stopped has already rewritten the tree the receipt
        # was published over, so it voids like any other build.
        assert [e.label for e in read_status(tmp_path)] == ["BUILT"]
        assert current_state(tmp_path).passed is False

    def test_voiding_resets_the_attempt_count(self, tmp_path):
        record_status(tmp_path, "SCORE BUILD", passed=True)
        record_status(tmp_path, "SCORE BUILD", passed=True)
        record_status(tmp_path, "BUILT", passed=True)
        record_status(tmp_path, "SCORE BUILD", passed=True)

        assert latest_per_label(read_status(tmp_path))["SCORE BUILD"].attempts == 1

    def test_records_an_iso_utc_instant(self, tmp_path):
        record_status(tmp_path, "INITIALIZED", passed=True)

        (entry,) = read_status(tmp_path)

        assert entry.at.endswith("+00:00")
        assert entry.at[:4].isdigit()

    def test_collapses_multiline_detail_to_one_line(self, tmp_path):
        record_status(tmp_path, "BUILT", passed=False, detail="line one\nline two\n  line three")

        (entry,) = read_status(tmp_path)

        assert entry.detail == "line one line two line three"

    def test_labels_outside_the_ladder_are_not_recorded(self, tmp_path):
        record_status(tmp_path, "MADE UP", passed=True)

        assert read_status(tmp_path) == ()
        assert not (tmp_path / STATUS_FILENAME).exists()

    def test_missing_target_directory_is_not_recorded(self, tmp_path):
        missing = tmp_path / "never-initialized"

        record_status(missing, "INITIALIZED", passed=False, detail="boom")

        assert not missing.exists()
        assert read_status(missing) == ()


class TestFileFormat:
    def test_last_row_names_the_state_the_project_is_in(self, tmp_path):
        record_status(tmp_path, "INITIALIZED", passed=True)
        record_status(tmp_path, "BUILT", passed=False, detail="boom")

        rows = _rows(tmp_path)

        assert [row.get("label") for row in rows[:-1]] == ["INITIALIZED", "BUILT"]
        assert rows[-1] == {
            "state": "BUILT",
            "result": "fail",
            "at": rows[-2]["at"],
            "attempts": 1,
        }

    def test_summary_names_the_blocking_rung_not_the_states_above_it(self, tmp_path):
        for label in ("BUILT", "SCORE AC", "SCORE RELEASE"):
            record_status(tmp_path, label, passed=True)

        record_status(tmp_path, "SCORE AC", passed=False, detail="2 failed")

        # A terminal release score is the current state despite the older failed check.
        assert _rows(tmp_path)[-1]["state"] == "SCORE RELEASE"
        assert _rows(tmp_path)[-1]["result"] == "pass"

    def test_one_json_object_per_line(self, tmp_path):
        record_status(tmp_path, "BUILT", passed=False, detail="a\nb")

        for row in _rows(tmp_path):
            assert isinstance(row, dict)


class TestCurrentState:
    def test_highest_state_on_the_ladder_is_the_project_state(self, tmp_path):
        record_status(tmp_path, "INITIALIZED", passed=True)
        record_status(tmp_path, "BUILT", passed=True)

        assert current_state(tmp_path).label == "BUILT"

    def test_no_recorded_state_is_none(self, tmp_path):
        assert current_state(tmp_path) is None


class TestReadStatus:
    def test_absent_file_reads_as_empty(self, tmp_path):
        assert read_status(tmp_path) == ()

    def test_empty_file_reads_as_empty(self, tmp_path):
        (tmp_path / STATUS_FILENAME).write_text("\n\n", encoding="utf-8")

        assert read_status(tmp_path) == ()

    def test_corrupt_and_unknown_rows_are_skipped(self, tmp_path):
        (tmp_path / STATUS_FILENAME).write_text(
            "not json\n"
            '{"label": "MADE UP", "result": "pass"}\n'
            '{"label": "ANALYZED", "result": "pass", "at": "x"}\n',
            encoding="utf-8",
        )

        (entry,) = read_status(tmp_path)

        assert entry.label == "ANALYZED"
        assert entry.passed is True

    def test_row_without_result_is_treated_as_a_failed_attempt(self, tmp_path):
        (tmp_path / STATUS_FILENAME).write_text('{"label": "BUILDING"}\n', encoding="utf-8")

        (entry,) = read_status(tmp_path)

        assert entry.label == "BUILDING"
        assert entry.passed is False


class TestLatestPerLabel:
    def test_indexes_states_in_ladder_order(self, tmp_path):
        record_status(tmp_path, "SCORE BUILD", passed=True)
        record_status(tmp_path, "INITIALIZED", passed=True)
        record_status(tmp_path, "BUILT", passed=True)

        latest = latest_per_label(read_status(tmp_path))

        assert list(latest) == ["INITIALIZED", "BUILT"]

    def test_unattempted_labels_are_absent(self, tmp_path):
        record_status(tmp_path, "INITIALIZED", passed=True)

        latest = latest_per_label(read_status(tmp_path))

        assert set(latest) == {"INITIALIZED"}
        assert set(LABEL_LADDER) - set(latest)


class TestRecordFailure:
    def test_records_operational_failure(self, tmp_path):
        record_failure(tmp_path, "IMPORTED", RuntimeError("disk gone"), command="drydock import T")

        (entry,) = read_status(tmp_path)

        assert entry.passed is False
        assert entry.detail == "disk gone"

    def test_usage_error_is_not_an_attempt_and_voids_nothing(self, tmp_path):
        record_status(tmp_path, "SCORE RELEASE", passed=True)

        record_failure(tmp_path, "IMPORTED", UsageError("import requires <Source>"))

        assert [e.label for e in read_status(tmp_path)] == ["SCORE RELEASE"]

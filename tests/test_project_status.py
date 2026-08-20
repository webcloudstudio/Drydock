"""Unit tests for workflow-state persistence in PROJECT_STATUS.md."""

from __future__ import annotations

from drydock.errors import UsageError
from drydock.project_status import (
    LABEL_LADDER,
    latest_per_label,
    read_status,
    record_failure,
    record_status,
)


class TestRecordStatus:
    def test_appends_one_record_per_call(self, tmp_path):
        record_status(tmp_path, "INITIALIZED", passed=True, command="drydock init T")
        record_status(tmp_path, "ANALYZED", passed=True, command="drydock analyze T")

        entries = read_status(tmp_path)

        assert [e.label for e in entries] == ["INITIALIZED", "ANALYZED"]
        assert all(e.passed for e in entries)
        assert entries[1].command == "drydock analyze T"

    def test_preserves_earlier_attempts_at_the_same_label(self, tmp_path):
        record_status(tmp_path, "BUILT", passed=False, detail="3 step(s) failed")
        record_status(tmp_path, "BUILT", passed=True)

        entries = read_status(tmp_path)

        assert len(entries) == 2
        assert entries[0].passed is False
        assert entries[0].detail == "3 step(s) failed"
        assert entries[1].passed is True

    def test_records_an_iso_utc_instant(self, tmp_path):
        record_status(tmp_path, "INITIALIZED", passed=True)

        (entry,) = read_status(tmp_path)

        assert entry.at.endswith("+00:00")
        assert entry.at[:4].isdigit()

    def test_collapses_multiline_detail_to_one_line(self, tmp_path):
        record_status(tmp_path, "BUILT", passed=False, detail="line one\nline two\n  line three")

        (entry,) = read_status(tmp_path)

        assert entry.detail == "line one line two line three"

    def test_missing_target_directory_is_not_recorded(self, tmp_path):
        missing = tmp_path / "never-initialized"

        record_status(missing, "INITIALIZED", passed=False, detail="boom")

        assert not missing.exists()
        assert read_status(missing) == ()


class TestReadStatus:
    def test_absent_file_reads_as_empty(self, tmp_path):
        assert read_status(tmp_path) == ()

    def test_empty_file_reads_as_empty(self, tmp_path):
        (tmp_path / "PROJECT_STATUS.md").write_text("\n\n", encoding="utf-8")

        assert read_status(tmp_path) == ()

    def test_record_without_result_is_treated_as_a_failed_attempt(self, tmp_path):
        (tmp_path / "PROJECT_STATUS.md").write_text(
            "## BUILDING\nat: 2026-08-20T00:00:00.000+00:00\n", encoding="utf-8"
        )

        (entry,) = read_status(tmp_path)

        assert entry.label == "BUILDING"
        assert entry.passed is False

    def test_unknown_lines_are_ignored(self, tmp_path):
        (tmp_path / "PROJECT_STATUS.md").write_text(
            "# PROJECT STATUS\n\n## ANALYZED\nresult: pass\nnoise: ignored\n",
            encoding="utf-8",
        )

        (entry,) = read_status(tmp_path)

        assert entry.label == "ANALYZED"
        assert entry.passed is True


class TestLatestPerLabel:
    def test_returns_last_attempt_per_label_in_ladder_order(self, tmp_path):
        record_status(tmp_path, "SCORE BUILD", passed=True)
        record_status(tmp_path, "BUILT", passed=False, detail="first try")
        record_status(tmp_path, "BUILT", passed=True)
        record_status(tmp_path, "INITIALIZED", passed=True)

        latest = latest_per_label(read_status(tmp_path))

        assert list(latest) == ["INITIALIZED", "BUILT", "SCORE BUILD"]
        assert latest["BUILT"].passed is True
        assert latest["BUILT"].detail == ""

    def test_unattempted_labels_are_absent(self, tmp_path):
        record_status(tmp_path, "INITIALIZED", passed=True)

        latest = latest_per_label(read_status(tmp_path))

        assert set(latest) == {"INITIALIZED"}
        assert set(LABEL_LADDER) - set(latest)

    def test_labels_outside_the_ladder_are_not_rendered(self, tmp_path):
        record_status(tmp_path, "MADE UP", passed=True)

        assert read_status(tmp_path)[0].label == "MADE UP"
        assert latest_per_label(read_status(tmp_path)) == {}


class TestRecordFailure:
    def test_records_operational_failure(self, tmp_path):
        record_failure(tmp_path, "IMPORTED", RuntimeError("disk gone"), command="drydock import T")

        (entry,) = read_status(tmp_path)

        assert entry.passed is False
        assert entry.detail == "disk gone"

    def test_usage_error_is_not_an_attempt(self, tmp_path):
        record_failure(tmp_path, "IMPORTED", UsageError("import requires <Source>"))

        assert read_status(tmp_path) == ()

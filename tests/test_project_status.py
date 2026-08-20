"""Unit tests for the PROJECT_STATUS.jsonl workflow state machine."""

from __future__ import annotations

import json

from drydock.errors import UsageError
from drydock.project_status import (
    LABEL_LADDER,
    STATUS_FILENAME,
    current_state,
    latest_per_label,
    read_status,
    record_failure,
    record_status,
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

    def test_recording_a_state_voids_every_state_below_it(self, tmp_path):
        for label in ("INITIALIZED", "BUILT", "SCORE BUILD", "FINALIZED"):
            record_status(tmp_path, label, passed=True)

        record_status(tmp_path, "BUILT", passed=True)

        assert [e.label for e in read_status(tmp_path)] == ["INITIALIZED", "BUILT"]

    def test_a_failed_attempt_also_voids_downstream_states(self, tmp_path):
        record_status(tmp_path, "BUILT", passed=True)
        record_status(tmp_path, "FINALIZED", passed=True)

        record_status(tmp_path, "BUILT", passed=False, detail="boom")

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

    def test_supersedes_the_legacy_markdown_journal(self, tmp_path):
        legacy = tmp_path / "PROJECT_STATUS.md"
        legacy.write_text("## FINALIZED\nresult: pass\n", encoding="utf-8")

        record_status(tmp_path, "INITIALIZED", passed=True)

        assert not legacy.exists()
        assert [e.label for e in read_status(tmp_path)] == ["INITIALIZED"]


class TestLegacyMigration:
    """The append-only markdown journal folds into the machine under the same void rule."""

    def _journal(self, tmp_path, *records: tuple[str, str, str]) -> None:
        lines = []
        for label, result, at in records:
            lines += [f"## {label}", f"result: {result}", f"at: {at}", "detail: ", "command: x", ""]
        (tmp_path / "PROJECT_STATUS.md").write_text("\n".join(lines), encoding="utf-8")

    def test_replaying_the_journal_voids_states_a_later_record_invalidated(self, tmp_path):
        """A rescore after finalizing is what the journal could never express as one state."""
        self._journal(
            tmp_path,
            ("FINALIZED", "pass", "2026-08-20T05:18:19.695+00:00"),
            ("FINALIZED", "pass", "2026-08-20T05:32:46.556+00:00"),
            ("SCORE BUILD", "pass", "2026-08-20T14:04:35.023+00:00"),
            ("LLM ACCEPTANCE CHECKS OK", "pass", "2026-08-20T14:32:11.785+00:00"),
            ("FINALIZED", "pass", "2026-08-20T14:33:04.068+00:00"),
            ("SCORE BUILD", "pass", "2026-08-20T14:34:50.625+00:00"),
            ("SCORE BUILD", "pass", "2026-08-20T14:38:51.886+00:00"),
        )

        entries = read_status(tmp_path)

        assert [e.label for e in entries] == ["LLM ACCEPTANCE CHECKS OK", "SCORE BUILD"]
        assert current_state(tmp_path).label == "SCORE BUILD"
        assert entries[1].attempts == 2  # reset when the acceptance state voided it

    def test_the_journal_is_removed_once_it_is_folded_in(self, tmp_path):
        self._journal(tmp_path, ("BUILT", "pass", "2026-08-20T00:00:00.000+00:00"))

        read_status(tmp_path)

        assert not (tmp_path / "PROJECT_STATUS.md").exists()
        assert (tmp_path / STATUS_FILENAME).is_file()

    def test_a_journal_holding_no_ladder_state_is_discarded(self, tmp_path):
        self._journal(tmp_path, ("MADE UP", "pass", "2026-08-20T00:00:00.000+00:00"))

        assert read_status(tmp_path) == ()
        assert not (tmp_path / "PROJECT_STATUS.md").exists()

    def test_an_existing_snapshot_is_never_overwritten_by_a_journal(self, tmp_path):
        record_status(tmp_path, "BUILT", passed=True)
        self._journal(tmp_path, ("FINALIZED", "pass", "2026-08-20T00:00:00.000+00:00"))

        assert [e.label for e in read_status(tmp_path)] == ["BUILT"]


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
        record_status(tmp_path, "FINALIZED", passed=True)

        record_failure(tmp_path, "IMPORTED", UsageError("import requires <Source>"))

        assert [e.label for e in read_status(tmp_path)] == ["FINALIZED"]

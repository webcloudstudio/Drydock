"""Tests for the Target error record and its appended standoff diagnosis."""

from __future__ import annotations

from drydock.errors import append_diagnosis, errors_path, read_error_record, write_error_record

DIAGNOSIS = "CAUSE: the build agent wrote no files.\nDO: rerun drydock build widgets"


def _write(tmp_path):
    return write_error_record(
        tmp_path,
        command="build",
        phase="LLM execution",
        classification="no build files written",
        detail="The agent finished but produced nothing.",
        recovery="Rerun the block, then inspect evidence/block-1.md.",
        execution_id="exec-1",
    )


def test_record_round_trips_without_a_diagnosis(tmp_path):
    _write(tmp_path)
    record = read_error_record(tmp_path)
    assert record is not None
    assert record.classification == "no build files written"
    assert record.recovery == "Rerun the block, then inspect evidence/block-1.md."
    assert record.diagnosis == ""


def test_diagnostic_preserves_structured_markdown_lines(tmp_path):
    detail = (
        "Failure\n"
        "  Provenance\n"
        "    Block: Catalog [feature-catalog]\n"
        "    Story: Service [service]\n"
        "  Assertion\n"
        "    Code: assert result.repositories\n"
        "  Result\n"
        "    Process exit code: 1\n"
        "    Error: AssertionError"
    )
    write_error_record(
        tmp_path,
        command="build",
        phase="build step",
        classification="programmatic acceptance failed: scanner-evidence",
        detail=detail,
        recovery="Run: drydock build Marina --step service",
    )

    record = read_error_record(tmp_path)
    assert record is not None
    assert record.detail == detail
    assert "## Diagnostic\n\nFailure\n  Provenance" in errors_path(tmp_path).read_text()


def test_appended_diagnosis_round_trips_and_preserves_recovery(tmp_path):
    _write(tmp_path)
    assert append_diagnosis(tmp_path, DIAGNOSIS) is True

    record = read_error_record(tmp_path)
    assert record is not None
    assert record.diagnosis == DIAGNOSIS
    # The regression this refactor risks: recovery must not swallow the appended section.
    assert record.recovery == "Rerun the block, then inspect evidence/block-1.md."
    assert record.detail == "The agent finished but produced nothing."


def test_second_diagnosis_replaces_the_first(tmp_path):
    _write(tmp_path)
    append_diagnosis(tmp_path, DIAGNOSIS)
    append_diagnosis(tmp_path, "CAUSE: something else entirely.")

    text = errors_path(tmp_path).read_text(encoding="utf-8")
    assert text.count("## Diagnosis") == 1
    record = read_error_record(tmp_path)
    assert record is not None
    assert record.diagnosis == "CAUSE: something else entirely."


def test_diagnosis_is_not_written_without_a_record(tmp_path):
    assert append_diagnosis(tmp_path, DIAGNOSIS) is False
    assert not errors_path(tmp_path).exists()


def test_empty_diagnosis_is_ignored(tmp_path):
    _write(tmp_path)
    assert append_diagnosis(tmp_path, "   \n") is False
    assert "## Diagnosis" not in errors_path(tmp_path).read_text(encoding="utf-8")

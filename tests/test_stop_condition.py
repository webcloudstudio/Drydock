"""The Target-level halt semaphore."""

from __future__ import annotations

from pathlib import Path

from drydock.stop_condition import (
    STOP_FILENAME,
    clear_stop,
    read_stop,
    stop_path,
    write_stop,
)


def test_an_unstopped_target_reads_as_none(tmp_path: Path) -> None:
    assert read_stop(tmp_path) is None


def test_a_declared_stop_round_trips_its_stage_and_reason(tmp_path: Path) -> None:
    write_stop(tmp_path, "initial-build-1", "The build exited 1 with work still on the frontier.")

    halt = read_stop(tmp_path)

    assert halt is not None
    assert halt.stage == "initial-build-1"
    assert halt.reason == "The build exited 1 with work still on the frontier."
    assert halt.declared_at.endswith("Z")


def test_the_first_declaration_wins(tmp_path: Path) -> None:
    """A later failure is a consequence of the halt, not a second cause.

    Overwriting would replace the first causal failure with the last incidental one, which is
    the one piece of information a stopped run exists to preserve.
    """
    write_stop(tmp_path, "initial-build-1", "The real cause.")
    write_stop(tmp_path, "score-release", "A downstream consequence.")

    halt = read_stop(tmp_path)

    assert halt is not None
    assert halt.stage == "initial-build-1"
    assert halt.reason == "The real cause."


def test_the_semaphore_is_a_readable_markdown_record(tmp_path: Path) -> None:
    """It is the first file an operator opens in a halted run tree."""
    path = write_stop(tmp_path, "initial-build-1", "The build exited 1.")

    assert path == stop_path(tmp_path) == tmp_path / STOP_FILENAME
    text = path.read_text(encoding="utf-8")
    assert text.startswith("# STOP\n")
    assert "- stage: initial-build-1" in text
    assert "## Reason" in text
    assert "The build exited 1." in text


def test_an_unreadable_semaphore_still_reports_a_halt(tmp_path: Path) -> None:
    """Reporting "not stopped" because the file would not open is the one wrong answer."""
    stop_path(tmp_path).mkdir()

    halt = read_stop(tmp_path)

    assert halt is None or halt.stage == "unknown"


def test_clearing_lets_the_target_run_again(tmp_path: Path) -> None:
    write_stop(tmp_path, "initial-build-1", "The build exited 1.")

    clear_stop(tmp_path)

    assert read_stop(tmp_path) is None
    clear_stop(tmp_path)  # idempotent

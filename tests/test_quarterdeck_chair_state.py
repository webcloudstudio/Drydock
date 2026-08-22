"""The Commander's Chair renders the workflow state machine as its lifecycle strip."""

from __future__ import annotations

import pytest

from drydock.project_status import record_status
from drydock.quarterdeck_state import refresh_commanders_chair


@pytest.fixture()
def target_dir(tmp_path):
    """A Target far enough along that the Chair builds its analyzed phase."""
    target = tmp_path / "widget"
    (target / "QuarterDeck").mkdir(parents=True)
    (target / "ANALYSIS.md").write_text(
        "# Analysis\n\n## Story List\n\n| ID | Story |\n|---|---|\n| ST-1 | Parse input |\n",
        encoding="utf-8",
    )
    return target


def _chair(target_dir) -> str:
    written = refresh_commanders_chair(target_dir)
    assert written is not None, "the Chair template did not render"
    return written.read_text(encoding="utf-8")


def test_the_chair_names_the_state_the_project_is_in(target_dir):
    record_status(target_dir, "INITIALIZED", passed=True, command="drydock init widget")
    record_status(target_dir, "ANALYZED", passed=True, command="drydock analyze widget")

    page = _chair(target_dir)

    assert "STATE: ANALYZED" in page
    assert '<section class="state-panel">' in page


def test_the_chair_reports_a_failed_state_as_failed(target_dir):
    record_status(target_dir, "INITIALIZED", passed=True)
    record_status(target_dir, "BUILT", passed=False, detail="2 block(s) stalled")

    page = _chair(target_dir)

    assert "STATE: BUILT" in page
    assert "FAIL" in page
    assert "2 block(s) stalled" in page


def test_the_ladder_marks_held_states_and_leaves_the_rest_pending(target_dir):
    record_status(target_dir, "INITIALIZED", passed=True)
    record_status(target_dir, "BUILT", passed=True)

    page = _chair(target_dir)

    assert '<li class="state-step state-held">INITIALIZED</li>' in page
    assert '<li class="state-step state-current state-pass">BUILT</li>' in page
    # Voided and never-attempted states are indistinguishable, and both render as pending.
    assert '<li class="state-step">SCORE RELEASE</li>' in page


def test_a_voided_state_is_no_longer_shown_as_reached(target_dir):
    record_status(target_dir, "INITIALIZED", passed=True)
    record_status(target_dir, "BUILT", passed=True)
    record_status(target_dir, "SCORE BUILD", passed=True)
    record_status(target_dir, "SCORE RELEASE", passed=True)

    record_status(target_dir, "BUILT", passed=True, command="drydock build widget")

    page = _chair(target_dir)

    assert "STATE: BUILT" in page
    assert '<li class="state-step">SCORE RELEASE</li>' in page
    assert '<li class="state-step">SCORE BUILD</li>' in page


def test_a_reattempted_state_reports_its_attempt_count(target_dir):
    record_status(target_dir, "BUILT", passed=False, detail="1 step(s) failed")
    record_status(target_dir, "BUILT", passed=True)

    assert "attempt 2" in _chair(target_dir)


def test_a_target_with_no_recorded_state_gets_no_panel(target_dir):
    page = _chair(target_dir)

    assert '<section class="state-panel">' not in page  # the stylesheet still defines the rule
    assert "STATE:" not in page

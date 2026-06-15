"""Tests for target-local standard QuarterDeck artifacts."""

from __future__ import annotations

from drydock.build_plan import parse_build_plan
from drydock.standard_artifacts import Sounding, load_soundings, render_console, sync_plan_soundings


def test_render_console_places_sea_trials_before_soundings(tmp_path):
    config = render_console("Example", plan_path=tmp_path / "BUILD_PLAN.md")

    assert config.index('label: "Sea Trials"') < config.index('label: "Soundings"')
    assert 'label: "Planning Session"' in config
    assert "command_status" not in config


def test_render_console_commanders_view_is_document_type():
    config = render_console("Example")

    assert "type: document" in config
    assert "path_html: captains_chair.html" in config
    assert "commanders_view" in config
    assert "pages/overview.md" not in config


def test_render_console_includes_spike_questionnaire_source(tmp_path):
    config = render_console("Example")

    assert "spike-*.json" in config
    assert "questionnaire" in config


def test_sync_plan_soundings_projects_acceptance_and_preserves_review(tmp_path):
    target = tmp_path / "Target"
    target.mkdir()
    plan_path = target / "BUILD_PLAN.md"
    plan_path.write_text(
        """# BUILD_PLAN: Example
state: draft

## story 1: Work
id: work
state: pending

## ac 1: System starts
id: system-starts
parent: work
state: pending
""",
        encoding="utf-8",
    )
    soundings = target / "SOUNDINGS.md"
    soundings.write_text(
        "# Soundings\n\n"
        "| ID | Acceptance Criterion | State | Evidence |\n"
        "|---|---|---|---|\n"
        "| system-starts | Old wording | DONE | `evidence/start.txt` |\n",
        encoding="utf-8",
    )

    sync_plan_soundings(parse_build_plan(plan_path), target)

    assert load_soundings(soundings) == {
        "system-starts": Sounding(
            "system-starts", "System starts", "NOT STARTED", "`evidence/start.txt`"
        )
    }

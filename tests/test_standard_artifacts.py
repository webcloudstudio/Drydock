"""Tests for target-local standard QuarterDeck artifacts."""

from __future__ import annotations

from drydock.build_plan import parse_build_plan
from drydock.standard_artifacts import Sounding, load_soundings, render_console, sync_plan_soundings


def test_render_console_places_sea_trials_before_soundings(tmp_path):
    config = render_console("Example", plan_path=tmp_path / "MANIFEST.md")

    assert config.index('label: "Sea Trials"') < config.index('label: "Soundings"')
    assert 'label: "Planning Session"' in config
    assert "command_status" not in config


def test_render_console_commanders_view_is_document_type():
    config = render_console("Example")

    assert "type: document" in config
    assert "path_html: captains_chair.html" in config
    assert "commanders_view" in config
    assert "pages/overview.md" not in config


def test_render_console_declares_tabbed_analysis_item():
    import yaml

    config = render_console("Example")
    parsed = yaml.safe_load(config)
    items = {item["id"]: item for item in parsed["items"]}

    assert "analysis" in items
    analysis = items["analysis"]
    assert analysis["section"] == "core"
    assert analysis["type"] == "markdown"
    assert analysis["tabs"] is True
    assert analysis["path"] == "../ANALYSIS.md"
    # Captain's Chair stays first; Analysis follows it.
    assert items["commanders_view"]["order"] < analysis["order"]
    assert analysis["order"] < items["sea_trials"]["order"]


def test_render_console_labels_compass_feedback_files():
    import yaml

    config = render_console("Example")
    parsed = yaml.safe_load(config)
    items = {item["id"]: item for item in parsed["items"]}

    assert items["analysis_feedback"]["label"] == "Analysis Compass"
    assert items["analysis_feedback"]["path"] == "../ANALYSIS_COMPASS.md"
    assert items["manifest_feedback"]["label"] == "Manifest Compass"
    assert items["manifest_feedback"]["path"] == "../MANIFEST_COMPASS.md"


def test_render_console_includes_spike_questionnaire_source(tmp_path):
    config = render_console("Example")

    assert "spike-*.json" in config
    assert "questionnaire" in config
    assert "section: archive" in config
    assert "template: spike" in config


def test_render_console_includes_blockers_section_first():
    config = render_console("Example")
    import yaml

    parsed = yaml.safe_load(config)
    section_ids = [s["id"] for s in parsed["sections"]]
    assert section_ids[0] == "blockers"
    items = {item["id"]: item for item in parsed["items"]}
    assert "blockers_doc" in items
    assert items["blockers_doc"]["section"] == "blockers"
    assert items["blockers_doc"]["type"] == "editable_markdown"


def test_sync_plan_soundings_projects_acceptance_and_preserves_review(tmp_path):
    target = tmp_path / "Target"
    target.mkdir()
    plan_path = target / "MANIFEST.md"
    plan_path.write_text(
        """# MANIFEST: Example
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

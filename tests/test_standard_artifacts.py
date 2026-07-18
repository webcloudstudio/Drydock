"""Tests for target-local standard QuarterDeck artifacts."""

from __future__ import annotations

from drydock.acceptance import ProgrammaticAcceptance
from drydock.build_plan import parse_build_plan
from drydock.standard_artifacts import (
    VERIFIED_UNVERIFIED,
    Sounding,
    load_soundings,
    project_soundings,
    render_console,
    write_plan_soundings,
)


def test_render_console_places_sea_trials_before_soundings(tmp_path):
    config = render_console("Example", plan_path=tmp_path / "MANIFEST.md")

    assert config.index('label: "Sea Trials"') < config.index('label: "Soundings"')
    # The Planning Session is retired; MANIFEST is the single work-graph view.
    assert 'label: "Planning Session"' not in config
    assert 'label: "MANIFEST"' in config
    assert "command_status" not in config


def test_render_console_commanders_chair_is_document_type():
    config = render_console("Example")

    assert "type: document" in config
    assert "path_html: commanders_chair.html" in config
    assert "commanders_chair" in config
    assert 'label: "⛔ BIG ERRORS — action required"' in config
    assert "pages/overview.md" not in config


def test_render_console_declares_tabbed_analysis_item():
    import yaml

    config = render_console("Example")
    parsed = yaml.safe_load(config)
    items = {item["id"]: item for item in parsed["items"]}

    assert "analysis" in items
    analysis = items["analysis"]
    assert analysis["section"] == "analyze"
    assert analysis["type"] == "markdown"
    assert analysis["tabs"] is True
    assert analysis["path"] == "../ANALYSIS.md"
    # Setup owns orientation; Analysis owns review outputs.
    assert items["commanders_chair"]["section"] == "setup"
    assert analysis["order"] < items["sea_trials"]["order"]


def test_render_console_labels_compass_feedback_files():
    import yaml

    config = render_console("Example")
    parsed = yaml.safe_load(config)
    items = {item["id"]: item for item in parsed["items"]}

    assert "help_text" in items["commanders_chair"]
    assert items["compass_edit"]["label"] == "Compass"
    assert items["compass_edit"]["path"] == "../COMPASS.md"
    assert "help_text" in items["compass_edit"]
    assert "prompt_text" in items["compass_edit"]
    assert "help_text" in items["analysis"]
    assert items["analyze_compass"]["label"] == "Analyze Compass"
    assert items["analyze_compass"]["path"] == "../ANALYZE_COMPASS.md"
    assert "help_text" in items["analyze_compass"]
    assert "prompt_text" in items["analyze_compass"]
    assert "help_text" in items["sea_trials"]
    assert "help_text" in items["soundings"]
    assert items["plan_compass"]["label"] == "Plan Compass"
    assert items["plan_compass"]["path"] == "../PLAN_COMPASS.md"
    assert "help_text" in items["plan_compass"]
    assert "prompt_text" in items["plan_compass"]
    assert "build_compass" not in items


def test_render_console_includes_build_compass_only_when_plan_exists(tmp_path):
    import yaml

    config = render_console("Example", plan_path=tmp_path / "MANIFEST.md")
    parsed = yaml.safe_load(config)
    items = {item["id"]: item for item in parsed["items"]}

    assert items["build_compass"]["label"] == "MANIFEST"
    assert items["build_compass"]["section"] == "implement"
    assert items["build_compass"]["path"] == "../MANIFEST.md"


def test_render_console_places_exclude_files_in_analyze(tmp_path):
    import yaml

    config = render_console("Example", plan_path=tmp_path / "MANIFEST.md")
    parsed = yaml.safe_load(config)
    items = {item["id"]: item for item in parsed["items"]}

    assert items["exclude_files"]["label"] == "Exclude Files"
    assert items["exclude_files"]["section"] == "setup"
    assert items["exclude_files"]["path"] == "../EXCLUDE_FILES.md"
    assert "help_text" in items["exclude_files"]
    assert "prompt_text" in items["exclude_files"]


def test_render_console_includes_discovery_questionnaire_source(tmp_path):
    config = render_console("Example")

    assert "discovery-*.json" in config
    assert "questionnaire" in config
    assert "section: analyze" in config
    assert "template: discovery" in config
    assert "order: 99" in config


def test_render_console_groups_artifacts_by_phase():
    config = render_console("Example")
    import yaml

    parsed = yaml.safe_load(config)
    section_ids = [s["id"] for s in parsed["sections"]]
    assert section_ids == ["setup", "analyze", "implement", "refit"]
    items = {item["id"]: item for item in parsed["items"]}
    assert "blockers_doc" in items
    assert items["blockers_doc"]["section"] == "setup"
    assert items["blockers_doc"]["type"] == "editable_markdown"
    assert "help_text" in items["blockers_doc"]
    assert "prompt_text" in items["blockers_doc"]
    assert items["commanders_chair"]["section"] == "setup"
    assert items["sea_trials"]["section"] == "analyze"
    assert items["soundings"]["section"] == "analyze"
    assert items["board"]["section"] == "implement"
    assert items["plan_compass"]["section"] == "implement"
    assert items["refit_status"]["section"] == "refit"
    assert items["refit_status"]["type"] == "refit"


def test_project_soundings_one_row_per_assertion_all_unverified():
    checks = (
        ProgrammaticAcceptance(
            "catalog-200", "FEATURE-Catalog.md", "GET /catalog returns 200", "1"
        ),
        ProgrammaticAcceptance("catalog-writes", "FEATURE-Catalog.md", "POST persists item", "1"),
        ProgrammaticAcceptance("home-loads", "SCREEN-Home.md", "Home renders", "1"),
    )

    rows = project_soundings(checks)

    # One row per Blueprint assertion, tagged with its source file, all UNVERIFIED at plan time.
    assert [r.criterion_id for r in rows] == ["catalog-200", "catalog-writes", "home-loads"]
    assert [r.blueprint for r in rows] == [
        "FEATURE-Catalog.md",
        "FEATURE-Catalog.md",
        "SCREEN-Home.md",
    ]
    assert all(r.verified == VERIFIED_UNVERIFIED for r in rows)
    assert all(r.evidence == "" and r.verified_at == "" for r in rows)


def test_write_plan_soundings_round_trips_with_blueprint_column(tmp_path):
    checks = (
        ProgrammaticAcceptance(
            "catalog-200", "FEATURE-Catalog.md", "GET /catalog returns 200", "1"
        ),
    )

    write_plan_soundings(checks, tmp_path)

    assert load_soundings(tmp_path / "SOUNDINGS.md") == {
        "catalog-200": Sounding(
            criterion_id="catalog-200",
            blueprint="FEATURE-Catalog.md",
            summary="GET /catalog returns 200",
            verified=VERIFIED_UNVERIFIED,
        )
    }


def test_all_programmatic_acceptance_gathers_implemented_specs_deduped(tmp_path):
    from drydock.acceptance import all_programmatic_acceptance

    target = tmp_path / "Target"
    blueprint = target / "blueprint"
    blueprint.mkdir(parents=True)
    (blueprint / "FEATURE-Catalog.md").write_text(
        "# FEATURE: Catalog\n\n## Programmatic Acceptance\n\n"
        "### catalog responds\n\n```python\nassert True\n```\n\n"
        "### catalog writes\n\n```python\nassert True\n```\n",
        encoding="utf-8",
    )
    plan_path = target / "MANIFEST.md"
    plan_path.write_text(
        "# MANIFEST: Example\nstate: draft\n\n"
        "## story 1: Catalog\nid: catalog\nimplements: FEATURE-Catalog.md\nstate: pending\n",
        encoding="utf-8",
    )

    checks = all_programmatic_acceptance(parse_build_plan(plan_path), blueprint)

    assert [(c.source, c.check_id) for c in checks] == [
        ("FEATURE-Catalog.md", "catalog-responds"),
        ("FEATURE-Catalog.md", "catalog-writes"),
    ]

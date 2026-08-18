from __future__ import annotations

from pathlib import Path

from drydock.compass_sources import (
    clear_compass_import_pending,
    collect_compass_sources,
    compass_import_pending,
    is_compass_source,
    mark_compass_imported,
    seed_compass_from_sources,
)


def test_intent_filename_is_compass_source(tmp_path):
    path = tmp_path / "INTENT.md"
    path.write_text("# Anything\n", encoding="utf-8")

    assert is_compass_source(path)


def test_constitution_filename_is_compass_source(tmp_path):
    path = tmp_path / "constitution.md"
    path.write_text("# Anything\n", encoding="utf-8")

    assert is_compass_source(path)


def test_author_intent_marker_is_compass_source(tmp_path):
    path = tmp_path / "brief.md"
    path.write_text("## AUTHOR'S INTENT\n\nBuild the local path first.\n", encoding="utf-8")

    assert is_compass_source(path)


def test_leading_guardrails_heading_is_compass_source(tmp_path):
    path = tmp_path / "constraints.md"
    path.write_text("# Guardrails\n\nNever mutate source repositories.\n", encoding="utf-8")

    assert is_compass_source(path)


def test_guardrails_section_inside_a_specification_is_not_compass_source(tmp_path):
    # Every Typed Specification template carries a ``## Guardrails`` section. Matching it
    # anywhere in the body classified ordinary Blueprint sources as intent material.
    path = tmp_path / "FEATURE-Scanner.md"
    path.write_text(
        "# FEATURE: Scanner\n\n## Behavior\n\nScans.\n\n## Guardrails\n\n- Never mutate.\n",
        encoding="utf-8",
    )

    assert not is_compass_source(path)


def test_author_intent_section_below_a_title_is_not_compass_source(tmp_path):
    path = tmp_path / "SCREEN-Setup.md"
    path.write_text("# SCREEN: Setup\n\n## Author's Intent\n\nKeep it plain.\n", encoding="utf-8")

    assert not is_compass_source(path)


def test_generic_readme_intent_section_is_not_compass_source(tmp_path):
    path = tmp_path / "README.md"
    path.write_text("# Project\n\n## Intent\n\nUseful background.\n", encoding="utf-8")

    assert not is_compass_source(path)


def test_collect_compass_sources_keeps_only_detected_files(tmp_path):
    intent = tmp_path / "INTENT.md"
    intent.write_text("intent\n", encoding="utf-8")
    functionality = tmp_path / "FUNCTIONALITY.md"
    functionality.write_text("features\n", encoding="utf-8")

    assert collect_compass_sources([functionality, intent]) == [intent]


def test_seed_compass_from_single_source_copies_content(tmp_path):
    source = tmp_path / "INTENT.md"
    source.write_text("# Intent\n\nExact text.\n", encoding="utf-8")

    result = seed_compass_from_sources(tmp_path, [source], overwrite_unpopulated=True)

    assert result == tmp_path / "COMPASS.md"
    text = result.read_text(encoding="utf-8")
    assert text.startswith("# Intent\n\nExact text.\n")
    assert text.count("## Build Write Guardrail") == 1
    assert compass_import_pending(tmp_path)


def test_seed_compass_does_not_overwrite_populated_compass(tmp_path):
    compass = tmp_path / "COMPASS.md"
    compass.write_text("# COMPASS\n\n## Compass\nExisting.\n", encoding="utf-8")
    source = tmp_path / "INTENT.md"
    source.write_text("# Intent\n\nReplacement.\n", encoding="utf-8")

    result = seed_compass_from_sources(tmp_path, [source], overwrite_unpopulated=False)

    assert result is None
    assert compass.read_text(encoding="utf-8") == "# COMPASS\n\n## Compass\nExisting.\n"


def test_mark_and_clear_compass_import_pending(tmp_path):
    source = tmp_path / "brief.md"
    source.write_text("# Intent\n", encoding="utf-8")

    mark_compass_imported(tmp_path, source)
    assert compass_import_pending(tmp_path)

    clear_compass_import_pending(tmp_path)
    assert not compass_import_pending(tmp_path)


def test_seed_compass_combines_multiple_sources_with_source_comments(tmp_path):
    intent = tmp_path / "INTENT.md"
    intent.write_text("# Intent\n", encoding="utf-8")
    constitution = tmp_path / "constitution.md"
    constitution.write_text("# Constitution\n", encoding="utf-8")

    result = seed_compass_from_sources(tmp_path, [constitution, intent], overwrite_unpopulated=True)

    text = result.read_text(encoding="utf-8")
    assert "<!-- Source: INTENT.md -->" in text
    assert "<!-- Source: constitution.md -->" in text
    assert "# Intent" in text
    assert "# Constitution" in text


def test_compass_section_stops_at_the_next_same_depth_heading(tmp_path: Path) -> None:
    from drydock.compass_sources import compass_section

    text = (
        "# COMPASS: X\n\n## Constraints\n\n- one\n\n"
        "## Verification Protocol\n\nrules\n\n### Invoking\n\nmore\n\n## Corpus\n\nlater\n"
    )
    section = compass_section(text, "Verification Protocol")
    assert section.startswith("## Verification Protocol")
    assert "### Invoking" in section
    assert "later" not in section
    assert compass_section(text, "Nothing Here") == ""


def test_normative_compass_sections_collects_the_binding_sections(tmp_path: Path) -> None:
    from drydock.compass_sources import normative_compass_sections

    (tmp_path / "COMPASS.md").write_text(
        "# COMPASS: X\n\n## Compass\n\nprose\n\n## Constraints\n\n- stdlib only\n\n"
        "## Guardrails\n\n- no shelling out\n\n## Verification Protocol\n\n"
        'Supply `env={**os.environ, "JQ": ...}`.\n',
        encoding="utf-8",
    )
    collected = normative_compass_sections(tmp_path)
    assert "## Constraints" in collected
    assert "## Guardrails" in collected
    assert "## Verification Protocol" in collected
    assert "os.environ" in collected
    # Narrative sections are not normative and do not travel.
    assert "prose" not in collected


def test_normative_compass_sections_is_empty_without_a_compass(tmp_path: Path) -> None:
    from drydock.compass_sources import normative_compass_sections

    assert normative_compass_sections(tmp_path) == ""

"""Tests for story guidance: the named story list and the provenance that grades it."""

from __future__ import annotations

import json

import pytest

from drydock.errors import SpecificationError
from drydock.story_guidance import (
    FILENAME,
    PROVENANCE_COMMANDER,
    PROVENANCE_PLAN,
    StoryGuidance,
    StoryGuidanceEntry,
    guidance_from_config,
    load_guidance,
    render_section,
    replace_section,
    write_guidance,
)


def _target(tmp_path, payload: dict | None = None):
    target = tmp_path / "target"
    target.mkdir()
    if payload is not None:
        (target / FILENAME).write_text(json.dumps(payload), encoding="utf-8")
    return target


# ── loading ───────────────────────────────────────────────────────────────────


def test_an_absent_file_is_an_empty_set_not_an_error(tmp_path):
    guidance = load_guidance(_target(tmp_path))

    assert not guidance.declared
    assert guidance.ids == ()
    assert guidance.gates == {}


def test_entries_load_with_their_gates_and_provenance(tmp_path):
    target = _target(
        tmp_path,
        {
            "stories": [
                {
                    "id": "parser-strings",
                    "provenance": "commander",
                    "gate": ["sh", "stage.sh", "valid/string/**"],
                    "note": "string lexing",
                },
                {"id": "parser-keys", "provenance": "plan"},
            ]
        },
    )

    guidance = load_guidance(target)

    assert guidance.ids == ("parser-strings", "parser-keys")
    assert guidance.commander_ids == ("parser-strings",)
    assert guidance.gates == {"parser-strings": ("sh", "stage.sh", "valid/string/**")}


def test_only_commander_gates_are_governed(tmp_path):
    """A gate Drydock derived is a criterion the model effectively wrote; it confers nothing."""
    target = _target(
        tmp_path,
        {
            "stories": [
                {"id": "a", "provenance": "commander", "gate": ["sh", "a.sh"]},
                {"id": "b", "provenance": "plan", "gate": ["sh", "b.sh"]},
            ]
        },
    )

    guidance = load_guidance(target)

    assert set(guidance.gates) == {"a", "b"}
    assert set(guidance.governed_gates) == {"a"}


def test_a_retired_stages_key_is_recovered_as_commander_guidance(tmp_path):
    """A Target planned before the split keeps its gates without being re-planned."""
    target = _target(tmp_path)
    (target / "ACCEPTANCE.json").write_text(
        json.dumps({"full": ["sh", "full.sh"], "stages": {"parser": ["sh", "s.sh"]}}),
        encoding="utf-8",
    )

    guidance = load_guidance(target)

    assert guidance.commander_ids == ("parser",)
    assert guidance.governed_gates == {"parser": ("sh", "s.sh")}


def test_the_new_file_wins_over_the_retired_key(tmp_path):
    target = _target(tmp_path, {"stories": [{"id": "new", "provenance": "commander"}]})
    (target / "ACCEPTANCE.json").write_text(
        json.dumps({"stages": {"old": ["sh", "s.sh"]}}), encoding="utf-8"
    )

    assert load_guidance(target).ids == ("new",)


@pytest.mark.parametrize(
    "payload",
    [
        {"stories": [{"id": ""}]},
        {"stories": [{"id": "a", "gate": "sh s.sh"}]},
        {"stories": [{"id": "a", "gate": []}]},
        {"stories": [{"id": "a", "provenance": "commander"}, {"id": "a"}]},
        {"stories": [{"id": "a", "provenance": "invented"}]},
        {"stories": "not-a-list"},
    ],
)
def test_a_malformed_declaration_is_rejected(tmp_path, payload):
    with pytest.raises(SpecificationError):
        load_guidance(_target(tmp_path, payload))


def test_unreadable_json_is_rejected(tmp_path):
    target = _target(tmp_path)
    (target / FILENAME).write_text("{not json", encoding="utf-8")

    with pytest.raises(SpecificationError):
        load_guidance(target)


# ── writing and fixtures ──────────────────────────────────────────────────────


def test_guidance_round_trips(tmp_path):
    target = _target(tmp_path)
    guidance = StoryGuidance(
        entries=(
            StoryGuidanceEntry("a", PROVENANCE_COMMANDER, ("sh", "a.sh"), "note"),
            StoryGuidanceEntry("b", PROVENANCE_PLAN),
        )
    )

    write_guidance(target, guidance)
    loaded = load_guidance(target)

    assert loaded.entries == guidance.entries


def test_a_fixture_declaration_is_commander_provenance():
    """A kit input precedes every Drydock command, so nothing in it is model-authored."""
    guidance = guidance_from_config(
        {"full": ["sh", "f.sh"], "story_guidance": {"parser": ["sh", "s.sh"]}},
        where="uat/Demo/uat.json",
    )

    assert guidance.commander_ids == ("parser",)
    assert guidance.governed_gates == {"parser": ("sh", "s.sh")}


def test_a_fixture_may_still_declare_the_retired_stages_key():
    guidance = guidance_from_config(
        {"stages": {"parser": ["sh", "s.sh"]}}, where="uat/Toml/uat.json"
    )

    assert guidance.commander_ids == ("parser",)


def test_no_fixture_declaration_is_empty():
    assert not guidance_from_config(None, where="uat/Demo/uat.json").declared
    assert not guidance_from_config({"full": ["sh", "f.sh"]}, where="uat/Demo/uat.json").declared


# ── merging ───────────────────────────────────────────────────────────────────


def test_commander_entries_survive_a_derived_entry_of_the_same_name():
    commander = StoryGuidance(entries=(StoryGuidanceEntry("a", PROVENANCE_COMMANDER, ("sh",)),))
    derived = StoryGuidance(
        entries=(
            StoryGuidanceEntry("a", PROVENANCE_PLAN, ("sh", "wrong.sh")),
            StoryGuidanceEntry("b", PROVENANCE_PLAN),
        )
    )

    merged = commander.merged_with(derived)

    assert merged.ids == ("a", "b")
    assert merged.entry_for("a").provenance == PROVENANCE_COMMANDER
    assert merged.gates["a"] == ("sh",)


def test_entry_lookup_prefers_the_first_selector_given():
    guidance = StoryGuidance(
        entries=(
            StoryGuidanceEntry("LEXICAL-001", PROVENANCE_COMMANDER, ("sh", "stable.sh")),
            StoryGuidanceEntry("lexical-strings", PROVENANCE_COMMANDER, ("sh", "generated.sh")),
        )
    )

    assert guidance.entry_for("LEXICAL-001", "lexical-strings").gate == ("sh", "stable.sh")
    assert guidance.entry_for("absent") is None


# ── rendering into ANALYSIS.md ────────────────────────────────────────────────


def test_an_empty_set_renders_as_none():
    assert "None." in render_section(StoryGuidance())


def test_the_section_shows_the_command_and_names_the_authoritative_file():
    guidance = StoryGuidance(
        entries=(StoryGuidanceEntry("a", PROVENANCE_COMMANDER, ("sh", "a.sh"), "why"),)
    )

    section = render_section(guidance)

    assert "## Story Guidance" in section
    assert FILENAME in section
    assert "`sh a.sh`" in section
    assert "commander" in section
    assert "why" in section


def test_the_section_is_placed_after_the_story_list():
    text = "# Analysis\n\n## Story List\n\nrows\n\n## Relationship Model\n\nmore\n"
    guidance = StoryGuidance(entries=(StoryGuidanceEntry("a", PROVENANCE_PLAN),))

    result = replace_section(text, guidance)

    assert result.index("## Story List") < result.index("## Story Guidance")
    assert result.index("## Story Guidance") < result.index("## Relationship Model")


def test_an_existing_section_is_replaced_not_duplicated():
    text = "# Analysis\n\n## Story Guidance\n\nstale\n\n## Next\n\nkept\n"
    guidance = StoryGuidance(entries=(StoryGuidanceEntry("fresh", PROVENANCE_PLAN),))

    result = replace_section(text, guidance)

    assert result.count("## Story Guidance") == 1
    assert "stale" not in result
    assert "fresh" in result
    assert "kept" in result


def test_a_document_without_a_story_list_gets_the_section_appended():
    result = replace_section("# Analysis\n\nbody\n", StoryGuidance())

    assert result.startswith("# Analysis")
    assert "## Story Guidance" in result

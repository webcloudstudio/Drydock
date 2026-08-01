"""Topology declaration parsing and its projection into ``MANIFEST.md``."""

from __future__ import annotations

import pytest

from drydock.errors import SpecificationError
from drydock.manifest import DrydockManifest
from drydock.plan_graph import PlannedStory, compute_plan
from drydock.plan_topology import (
    computed_field_updates,
    parse_topology,
    parse_topology_strict,
    render_manifest,
    render_story_block,
    stories_from_manifest,
)

DECLARATION = """
## story foundation
summary:    Stand up the application factory.
type:       foundational
kind:       capability
phase:      1
implements: ARCHITECTURE.md
stack:      common.md, fastapi.md
provides:   GET /health
acceptance: yes
depends:

## story catalog
summary:    Serve the catalog.
type:       service
kind:       capability
phase:      2
implements: FEATURE-CATALOG.md
stack:      fastapi.md
consumes:   GET /health
depends:    foundation
"""


def test_declaration_parses_into_stories():
    stories, defects = parse_topology(DECLARATION)
    assert defects == ()
    assert [s.story_id for s in stories] == ["foundation", "catalog"]
    foundation, catalog = stories
    assert foundation.story_type == "foundational"
    assert foundation.phase == 1
    assert foundation.stack == ("common.md", "fastapi.md")
    assert foundation.provides == ("GET /health",)
    assert foundation.acceptance_contract is True
    assert catalog.depends == ("foundation",)
    assert catalog.acceptance_contract is False


def test_declaration_order_carries_no_schedule_meaning():
    """Parsing reads the declaration only; nothing is sorted, grouped, or repositioned."""
    stories, _ = parse_topology(DECLARATION)
    assert all(story.block == 0 and story.stack_mode == "" for story in stories)


def test_unknown_type_is_a_defect_and_falls_back_to_service():
    stories, defects = parse_topology("## story a\ntype: architecture\nimplements: A.md\n")
    assert [d.story_id for d in defects] == ["a"]
    assert stories[0].story_type == "service"


def test_unknown_kind_is_a_defect():
    _, defects = parse_topology("## story a\nkind: chore\nimplements: A.md\n")
    assert "chore" in defects[0].message


def test_non_integer_phase_is_a_defect():
    stories, defects = parse_topology("## story a\nphase: early\nimplements: A.md\n")
    assert "not an integer" in defects[0].message
    assert stories[0].phase == 1


def test_empty_declaration_is_a_defect():
    _, defects = parse_topology("no stories here")
    assert defects[0].story_id == ""


def test_strict_parse_raises_on_defect():
    with pytest.raises(SpecificationError, match="malformed"):
        parse_topology_strict("## story a\ntype: nonsense\n")


def test_strict_parse_returns_stories_when_clean():
    assert len(parse_topology_strict(DECLARATION)) == 2


# ── Serialization ───────────────────────────────────────────────────────────────────


def test_rendered_story_block_carries_the_computed_schedule_fields():
    computed = compute_plan(parse_topology_strict(DECLARATION))
    block = render_story_block(computed.stories[0], 1)
    assert "type:         foundational" in block
    assert "phase:        1" in block
    assert "block:        1" in block
    assert "stack_mode:   builder" in block
    assert "acceptance:   yes" in block
    assert "state:        pending" in block


def test_rendered_manifest_parses_as_a_manifest():
    computed = compute_plan(parse_topology_strict(DECLARATION))
    text = render_manifest("Demo", computed.stories, computed.blocks)
    manifest = DrydockManifest.parse(text, source="MANIFEST.md")
    assert manifest.project == "Demo"
    assert [node.block_id for node in manifest.blocks] == ["foundation", "catalog"]


def test_manifest_round_trip_recovers_the_planning_model():
    computed = compute_plan(parse_topology_strict(DECLARATION))
    text = render_manifest("Demo", computed.stories, computed.blocks)
    manifest = DrydockManifest.parse(text, source="MANIFEST.md")
    recovered = stories_from_manifest(manifest.blocks)
    assert [s.story_id for s in recovered] == ["foundation", "catalog"]
    assert recovered[0].story_type == "foundational"
    assert recovered[0].phase == 1
    assert recovered[1].depends == ("foundation",)


def test_legacy_taxonomy_manifest_projects_to_nothing():
    """A Manifest written before the restructure carries no ``type:`` and is left alone."""
    text = (
        "# MANIFEST: Legacy\n\n"
        "## story 1: Foundation\n"
        "id:           foundation\n"
        "summary:      Legacy story.\n"
        "implements:   ARCHITECTURE.md\n"
        "instructions: Build it.\n"
        "state:        pending\n"
    )
    manifest = DrydockManifest.parse(text, source="MANIFEST.md")
    assert stories_from_manifest(manifest.blocks) == ()


def test_computed_field_updates_only_carry_computed_facts():
    stories = (PlannedStory(story_id="a", stack_mode="consumer", block=3),)
    assert computed_field_updates(stories) == {
        "a": {"stack_mode": "consumer", "block": "3", "size": None, "budget": None}
    }


def test_an_over_target_story_carries_the_marker():
    stories = (PlannedStory(story_id="a", block=1, size_tokens=90_000, over_target=True),)
    updates = computed_field_updates(stories)["a"]
    assert updates["size"] == "90000"
    assert updates["budget"] == "over-target"


def test_rendered_block_carries_the_over_target_marker():
    rendered = render_story_block(
        PlannedStory(story_id="a", block=1, size_tokens=90_000, over_target=True), 1
    )
    assert "size:         90000" in rendered
    assert "budget:       over-target" in rendered


# ── instructions block scalar ───────────────────────────────────────────────────────

INSTRUCTIONS_DECLARATION = """
## story architecture
summary: Application architecture
type: foundational
phase: 1
implements: ARCHITECTURE.md
instructions: |
  Establish the parser module boundaries
  described by ARCHITECTURE.md.

  Do not add side effects.
acceptance: yes

## story parser
summary: Parser core
type: service
phase: 1
implements: FEATURE-Parser.md
depends: architecture
instructions: |
  Implement the block foundation.
"""


def test_instructions_block_scalar_is_parsed_across_lines():
    """The build engine requires `instructions:`, and it does not fit one line."""
    stories, defects = parse_topology(INSTRUCTIONS_DECLARATION)

    assert defects == ()
    by_id = {story.story_id: story for story in stories}
    assert by_id["architecture"].fields["instructions"] == (
        "Establish the parser module boundaries\n"
        "described by ARCHITECTURE.md.\n"
        "\n"
        "Do not add side effects."
    )
    assert by_id["parser"].fields["instructions"] == "Implement the block foundation."


def test_a_block_scalar_body_never_swallows_the_next_story():
    """The body ends at the first column-zero line, so the following heading still parses."""
    stories, _ = parse_topology(INSTRUCTIONS_DECLARATION)

    assert [story.story_id for story in stories] == ["architecture", "parser"]
    assert {story.story_id for story in stories if story.fields.get("implements")} == {
        "architecture",
        "parser",
    }


def test_a_field_after_a_block_scalar_is_still_read():
    """`acceptance: yes` follows the architecture body at column zero and must survive it."""
    stories, _ = parse_topology(INSTRUCTIONS_DECLARATION)
    by_id = {story.story_id: story for story in stories}

    assert by_id["architecture"].acceptance_contract is True
    assert by_id["parser"].acceptance_contract is False


def test_instructions_round_trip_through_the_manifest_parser():
    """Declaration to computed Manifest to parsed plan, with the prose intact."""
    stories, _ = parse_topology(INSTRUCTIONS_DECLARATION)
    computation = compute_plan(stories, target_tokens=50_000, size_fn=lambda story: 100)
    text = render_manifest("Example", computation.stories, computation.blocks)

    parsed = {block.block_id: block for block in DrydockManifest.parse(text).blocks}
    assert parsed["architecture"].fields["instructions"] == (
        "Establish the parser module boundaries\n"
        "described by ARCHITECTURE.md.\n"
        "\n"
        "Do not add side effects."
    )
    assert parsed["parser"].depends == ("architecture",)


def test_rendered_instructions_use_the_indented_block_scalar_form():
    """`build_plan` scans column-zero fields only, so the body must stay indented."""
    story = PlannedStory(story_id="a", block=1, fields={"instructions": "One.\nTwo."})
    rendered = render_story_block(story, 1)

    assert "instructions: |\n  One.\n  Two." in rendered

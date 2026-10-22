"""Stage 2 blocked-Blueprint reports: parsing and the deterministic claim check."""

from pathlib import Path

from drydock.plan_blocked import (
    BlockedBlueprint,
    check_blocked,
    context_inputs,
    parse_blocked,
)
from drydock.prompt_assembly import PromptAssembly, PromptPart

_BODY = """Blueprint: FEATURE-Test-Runner.md
Error type: missing-input
Cited input: `sources/INSTRUCTIONS.md` "Tests"
Details:
- The test runner selectors are not stated.
Required action:
- State the selectors.

Blueprint: FEATURE-Grader-Gate.md
Error type: conflict
Cited input: sources/run.sh and COMPASS.md
Details: run.sh exits 2 where COMPASS.md requires 1.
"""


def _check(entry: BlockedBlueprint, **overrides) -> BlockedBlueprint:
    options = {
        "present": {"sources/INSTRUCTIONS.md", "INSTRUCTIONS.md", "TOPOLOGY.md"},
        "accepted": {"FEATURE-Login.md"},
        "tranche": {"FEATURE-Test-Runner.md", "FEATURE-Grader-Gate.md"},
    }
    options.update(overrides)
    return check_blocked((entry,), **options)[0]


def test_parse_reads_one_entry_per_blueprint_line():
    first, second = parse_blocked(_BODY)

    assert first.blueprint == "FEATURE-Test-Runner.md"
    assert first.error_type == "missing-input"
    assert first.cited == '`sources/INSTRUCTIONS.md` "Tests"'
    assert first.details == "- The test runner selectors are not stated."
    assert first.required_action == "- State the selectors."
    assert second.error_type == "conflict"
    assert second.details == "run.sh exits 2 where COMPASS.md requires 1."


def test_a_missing_input_that_is_present_is_refuted():
    entry = _check(parse_blocked(_BODY)[0])

    assert not entry.stands
    assert "`sources/INSTRUCTIONS.md` is in this context" in entry.refutation


def test_a_missing_accepted_blueprint_is_refuted_by_design():
    entry = _check(BlockedBlueprint("FEATURE-Test-Runner.md", "missing-input", "FEATURE-Login.md"))

    assert "accepted Blueprint" in entry.refutation
    assert "`Provides`" in entry.refutation


def test_a_genuinely_absent_input_stands():
    entry = _check(BlockedBlueprint("FEATURE-Test-Runner.md", "missing-input", "sources/GRADER.md"))

    assert entry.stands


def test_a_conflict_with_a_citation_stands():
    assert _check(parse_blocked(_BODY)[1]).stands


def test_malformed_entries_are_refuted():
    outside = _check(BlockedBlueprint("FEATURE-Other.md", "conflict", "COMPASS.md"))
    untyped = _check(BlockedBlueprint("FEATURE-Test-Runner.md", "no tools", "COMPASS.md"))
    uncited = _check(BlockedBlueprint("FEATURE-Test-Runner.md", "conflict", "the sources"))

    assert "not in the Current batch" in outside.refutation
    assert "not an error type" in untyped.refutation
    assert "cites no input file" in uncited.refutation


def test_context_inputs_names_parts_by_label_path_and_frozen_stage():
    assembly = PromptAssembly(
        parts=(
            PromptPart("COMPASS.md", "x", kind="file", path=Path("/t/COMPASS.md")),
            PromptPart(
                "sources/run.sh", "x", kind="file", path=Path("/t/blueprint/sources/run.sh")
            ),
            PromptPart("Frozen Stage 1 output", "x", kind="frozen-stage"),
            PromptPart("Planning job", "x", kind="job"),
        )
    )

    names = context_inputs(assembly)

    assert {"COMPASS.md", "sources/run.sh", "run.sh", "TOPOLOGY.md", "DECISIONS.json"} <= names
    assert "Planning job" not in names


def test_rendered_and_declaration_carry_the_finding():
    entry = _check(parse_blocked(_BODY)[0])

    rendered = "\n".join(entry.rendered())
    assert rendered.startswith("- FEATURE-Test-Runner.md · missing-input · cited")
    assert "Drydock check: refuted —" in rendered
    declaration = parse_blocked(_BODY)[1].declaration()
    assert "Reason:" in declaration and "Required action:" in declaration

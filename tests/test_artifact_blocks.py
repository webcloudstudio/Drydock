from __future__ import annotations

import pytest

from drydock import artifact_blocks
from drydock.artifact_blocks import (
    pair_artifact_delimiters,
    parse_artifact_blocks,
    parse_artifact_report,
)
from drydock.errors import DrydockError

# The response that killed Toml run 20260813.211658: four well-formed artifacts and one whose
# closing marker lost its `.md`, because the artifact's own heading restated its filename stem.
_COMPASS_RUN = (
    "=== ANALYSIS.md ===\n# Blueprint Analysis: TOML 1.0.0 Parser\n=== END ANALYSIS.md ===\n"
    "=== SEA_TRIALS.md ===\n# Sea Trials: TOML 1.0.0 Parser\n=== END SEA_TRIALS.md ===\n"
    "=== COMPASS.md ===\n# COMPASS: TOML 1.0.0 Parser\n\n## Compass\nA parser.\n"
    "=== END COMPASS ===\n"
    "=== discovery-identity.json ===\n{}\n=== END discovery-identity.json ===\n"
)


def test_parse_artifact_blocks_recovers_missing_first_delimiter():
    text = "alpha\n=== END A.md ===\n=== B.md ===\nbeta\n=== END B.md ===\n"

    blocks = parse_artifact_blocks(text, label="Test")

    assert blocks == {"A.md": "alpha", "B.md": "beta"}


def test_parse_artifact_blocks_recovers_missing_final_end_delimiter():
    text = "=== A.md ===\nalpha\n=== END A.md ===\n=== B.md ===\nbeta\n"

    blocks = parse_artifact_blocks(text, label="Test")

    assert blocks == {"A.md": "alpha", "B.md": "beta"}


def test_parse_artifact_blocks_recovers_missing_end_delimiter_between_blocks():
    text = "=== A.md ===\nalpha\n=== B.md ===\nbeta\n=== END B.md ===\n"

    blocks = parse_artifact_blocks(text, label="Test")

    assert blocks == {"A.md": "alpha", "B.md": "beta"}


def test_parse_artifact_blocks_recovers_write_transcript():
    text = """\
<function_calls>
<invoke name="Write">
<parameter name="path">/tmp/docs/DOC-OVERVIEW.md</parameter>
<parameter name="content"># Overview</parameter>
</invoke>
<invoke name="Write">
<parameter name="file_path">/tmp/docs/DOC-FEATURES.md</parameter>
<parameter name="content"># Features</parameter>
</invoke>
</function_calls>"""

    blocks = parse_artifact_blocks(
        text,
        label="Test",
        allowed_names=("DOC-OVERVIEW.md", "DOC-FEATURES.md"),
    )

    assert blocks == {"DOC-OVERVIEW.md": "# Overview", "DOC-FEATURES.md": "# Features"}


def test_parse_artifact_blocks_still_rejects_preamble():
    with pytest.raises(DrydockError, match="Text appeared outside"):
        parse_artifact_blocks(
            "Here is the plan.\n=== A.md ===\nalpha\n=== END A.md ===\n",
            label="Test",
        )


def test_parse_artifact_blocks_ignores_transition_text_between_blocks():
    text = (
        "=== A.md ===\nalpha\n=== END A.md ===\n"
        "Continuing with the remaining files next.\n"
        "=== B.md ===\nbeta\n=== END B.md ===\n"
    )

    blocks = parse_artifact_blocks(text, label="Test")

    assert blocks == {"A.md": "alpha", "B.md": "beta"}


def test_parse_artifact_blocks_ignores_transition_text_after_write_calls():
    text = """\
<function_calls>
<invoke name="Write">
<parameter name="path">/tmp/docs/DOC-OVERVIEW.md</parameter>
<parameter name="content"># Overview</parameter>
</invoke>
</function_calls>
Continuing with the remaining files next.
<function_calls>
<invoke name="Write">
<parameter name="file_path">/tmp/docs/DOC-FEATURES.md</parameter>
<parameter name="content"># Features</parameter>
</invoke>
</function_calls>"""

    blocks = parse_artifact_blocks(
        text,
        label="Test",
        allowed_names=("DOC-OVERVIEW.md", "DOC-FEATURES.md"),
    )

    assert blocks == {"DOC-OVERVIEW.md": "# Overview", "DOC-FEATURES.md": "# Features"}


# ── §30.2 — a mismatched close is a close, not a new block ────────────────────────


def test_mismatched_close_closes_the_open_block_by_position():
    blocks = parse_artifact_blocks(
        _COMPASS_RUN,
        label="Analyze",
        allowed_names={"ANALYSIS.md", "SEA_TRIALS.md", "COMPASS.md"},
        allowed_prefixes=("discovery-",),
    )

    assert set(blocks) == {
        "ANALYSIS.md",
        "SEA_TRIALS.md",
        "COMPASS.md",
        "discovery-identity.json",
    }
    assert blocks["COMPASS.md"].startswith("# COMPASS: TOML 1.0.0 Parser")


def test_mismatched_close_is_reported_naming_both_markers():
    result = parse_artifact_report(
        _COMPASS_RUN,
        label="Analyze",
        allowed_names={"ANALYSIS.md", "SEA_TRIALS.md", "COMPASS.md"},
        allowed_prefixes=("discovery-",),
    )

    assert result.rejected == ()
    assert [defect.name for defect in result.repaired] == ["COMPASS.md"]
    reason = result.repaired[0].reason
    assert "=== END COMPASS ===" in reason
    assert "=== END COMPASS.md ===" in reason


def test_mismatched_close_does_not_invent_a_block_named_after_the_marker():
    result = parse_artifact_report(
        _COMPASS_RUN,
        label="Analyze",
        allowed_names={"ANALYSIS.md", "SEA_TRIALS.md", "COMPASS.md"},
        allowed_prefixes=("discovery-",),
    )

    assert "COMPASS" not in result.blocks
    assert all(defect.name != "COMPASS" for defect in result.defects)


def test_transposed_end_delimiter_still_opens_the_next_block():
    # `=== END B.md ===` with real content after it is the boundary the model transposed, not a
    # misnamed close. Position is what separates the two cases.
    text = "=== A.md ===\nalpha\n=== END B.md ===\nbeta\n"

    blocks = parse_artifact_blocks(text, label="Test")

    assert blocks == {"A.md": "alpha", "B.md": "beta"}


# ── §30.3 — a parse defect costs the artifact it judged, not the response ─────────


def test_disallowed_block_is_rejected_individually():
    text = (
        "=== ANALYSIS.md ===\n# Analysis\n=== END ANALYSIS.md ===\n"
        "=== NOTES.txt ===\njunk\n=== END NOTES.txt ===\n"
    )

    result = parse_artifact_report(text, label="Analyze", allowed_names={"ANALYSIS.md"})

    assert result.blocks == {"ANALYSIS.md": "# Analysis"}
    assert [defect.name for defect in result.rejected] == ["NOTES.txt"]


def test_conflicting_duplicate_costs_only_that_name():
    text = (
        "=== A.md ===\nalpha\n=== END A.md ===\n"
        "=== B.md ===\nbeta\n=== END B.md ===\n"
        "=== A.md ===\ndifferent\n=== END A.md ===\n"
    )

    result = parse_artifact_report(text, label="Test")

    assert result.blocks == {"B.md": "beta"}
    assert [defect.name for defect in result.rejected] == ["A.md"]


def test_identical_duplicate_is_tolerated():
    text = "=== A.md ===\nalpha\n=== END A.md ===\n=== A.md ===\nalpha\n=== END A.md ===\n"

    result = parse_artifact_report(text, label="Test")

    assert result.blocks == {"A.md": "alpha"}
    assert result.rejected == ()


def test_defects_are_reported_through_the_callback():
    text = (
        "=== ANALYSIS.md ===\n# Analysis\n=== END ANALYSIS.md ===\n"
        "=== NOTES.txt ===\njunk\n=== END NOTES.txt ===\n"
    )
    seen = []

    parse_artifact_blocks(
        text,
        label="Analyze",
        allowed_names={"ANALYSIS.md"},
        on_defect=seen.append,
    )

    assert [defect.name for defect in seen] == ["NOTES.txt"]


# ── §30.4 — the invariant close token ─────────────────────────────────────────────


def test_invariant_boundary_form_parses():
    text = (
        "=== BEGIN ARTIFACT ANALYSIS.md ===\n# Analysis\n=== END ARTIFACT ===\n"
        "=== BEGIN ARTIFACT COMPASS.md ===\n# COMPASS: TOML\n\n## Compass\nx\n"
        "=== END ARTIFACT ===\n"
    )

    blocks = parse_artifact_blocks(
        text, label="Analyze", allowed_names={"ANALYSIS.md", "COMPASS.md"}
    )

    assert set(blocks) == {"ANALYSIS.md", "COMPASS.md"}
    assert blocks["COMPASS.md"].startswith("# COMPASS: TOML")


def test_invariant_close_does_not_become_a_block_named_artifact():
    text = "=== BEGIN ARTIFACT A.md ===\nalpha\n=== END ARTIFACT ===\n"

    result = parse_artifact_report(text, label="Test")

    assert result.blocks == {"A.md": "alpha"}
    assert result.defects == ()


def test_named_close_still_valid_alongside_the_invariant_form():
    text = (
        "=== BEGIN ARTIFACT A.md ===\nalpha\n=== END ARTIFACT ===\n"
        "=== B.md ===\nbeta\n=== END B.md ===\n"
    )

    blocks = parse_artifact_blocks(text, label="Test")

    assert blocks == {"A.md": "alpha", "B.md": "beta"}


def test_invariant_close_terminates_a_named_open():
    text = "=== A.md ===\nalpha\n=== END ARTIFACT ===\n=== B.md ===\nbeta\n=== END ARTIFACT ===\n"

    result = parse_artifact_report(text, label="Test")

    assert result.blocks == {"A.md": "alpha", "B.md": "beta"}
    assert result.defects == ()


def test_ac_containers_are_not_artifact_boundaries():
    text = (
        "=== BEGIN ARTIFACT STORY-Login.md ===\n"
        "=== AC login-1 ===\nassert True\n=== END AC login-1 ===\n"
        "=== END ARTIFACT ===\n"
    )

    blocks = parse_artifact_blocks(text, label="Test")

    assert set(blocks) == {"STORY-Login.md"}
    assert "=== AC login-1 ===" in blocks["STORY-Login.md"]


# ── Delimiter pairing ────────────────────────────────────────────────────────────
#
# Pairing answers a structural question of the raw response — did everything that opened also
# close? — that several callers ask outside the parser. It is exercised here because a pairing
# rule that disagrees with the parser is what killed Toml run 20260813.231738: the prompts moved
# to the invariant boundary, the parser followed, and four name-counting checks did not.


def test_pairing_reads_the_invariant_close():
    text = (
        "=== BEGIN ARTIFACT TOPOLOGY.md ===\n# TOPOLOGY: Demo\n=== END ARTIFACT ===\n"
        "=== BEGIN ARTIFACT DECISIONS.json ===\n[]\n=== END ARTIFACT ===\n"
    )

    pairing = pair_artifact_delimiters(text)

    assert pairing.closed == ("TOPOLOGY.md", "DECISIONS.json")
    assert pairing.unclosed == ()
    assert pairing.orphan_closes == ()


def test_pairing_reads_the_named_close():
    text = "=== A.md ===\nalpha\n=== END A.md ===\n=== B.md ===\nbeta\n=== END B.md ===\n"

    pairing = pair_artifact_delimiters(text)

    assert pairing.closed == ("A.md", "B.md")
    assert pairing.unclosed == ()


def test_pairing_reads_both_grammars_in_one_response():
    text = (
        "=== BEGIN ARTIFACT A.md ===\nalpha\n=== END ARTIFACT ===\n"
        "=== B.md ===\nbeta\n=== END B.md ===\n"
    )

    assert pair_artifact_delimiters(text).closed == ("A.md", "B.md")


def test_pairing_names_an_artifact_that_opens_and_never_closes():
    text = "=== A.md ===\nalpha\n=== END A.md ===\n=== BEGIN ARTIFACT B.md ===\nbeta\n"

    pairing = pair_artifact_delimiters(text)

    assert pairing.closed == ("A.md",)
    assert pairing.unclosed == ("B.md",)
    assert pairing.opened == ("A.md", "B.md")


def test_pairing_reports_a_named_close_with_nothing_open_as_an_orphan():
    text = "=== END A.md ===\n"

    assert pair_artifact_delimiters(text).orphan_closes == ("A.md",)


def test_an_invariant_close_can_never_be_an_orphan_by_name():
    """It carries no name, so a dropped opener surfaces as a missing artifact instead."""
    assert pair_artifact_delimiters("=== END ARTIFACT ===\n").orphan_closes == ()


def test_pairing_agrees_with_the_parser_on_a_misnamed_close():
    """§30.2 — accepted by position, so pairing must count it closed, not damaged."""
    pairing = pair_artifact_delimiters(_COMPASS_RUN)

    assert "COMPASS.md" in pairing.closed
    assert pairing.unclosed == ()
    assert set(pairing.closed) == set(parse_artifact_report(_COMPASS_RUN, label="Test").blocks)


def test_pairing_ignores_ac_containers():
    text = (
        "=== BEGIN ARTIFACT STORY-Login.md ===\n"
        "=== AC login-1 ===\nassert True\n=== END AC login-1 ===\n"
        "=== END ARTIFACT ===\n"
    )

    assert pair_artifact_delimiters(text).closed == ("STORY-Login.md",)


def test_the_emission_contract_is_rendered_from_the_grammar_constants():
    """One authority. A prompt that hand-types a delimiter cannot follow a grammar change."""
    lines = artifact_blocks.emission_contract_lines(("TOPOLOGY.md", "ARCHITECTURE.md"))
    text = "\n".join(lines)

    assert artifact_blocks.ARTIFACT_OPEN_TEMPLATE.format(name="<FILENAME>") in text
    assert artifact_blocks.ARTIFACT_CLOSE_TOKEN in text
    assert "TOPOLOGY.md, ARCHITECTURE.md" in text


def test_a_wrapped_artifact_parses_back_to_its_body():
    """The form a prompt shows and the form the parser reads are the same object."""
    wrapped = artifact_blocks.wrap_artifact("TOPOLOGY.md", "## story one\n")

    parsed = artifact_blocks.parse_artifact_blocks(
        wrapped, label="plan", allowed_names=("TOPOLOGY.md",)
    )

    assert parsed["TOPOLOGY.md"] == "## story one"

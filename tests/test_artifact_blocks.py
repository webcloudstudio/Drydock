from __future__ import annotations

import pytest

from drydock import artifact_blocks
from drydock.artifact_blocks import (
    StrayText,
    carries_no_artifact,
    no_artifact_retry_assembly,
    pair_artifact_delimiters,
    parse_artifact_blocks,
    parse_artifact_report,
    retry_reply_without_artifacts,
)
from drydock.errors import DrydockError
from drydock.prompt_assembly import PromptAssembly

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


def test_parse_artifact_blocks_discards_and_reports_preamble():
    stray: list[StrayText] = []

    blocks = parse_artifact_blocks(
        "I'll produce the analysis from the injected sources.\n"
        "=== BEGIN ARTIFACT A.md ===\nalpha\n=== END ARTIFACT ===\n",
        label="Test",
        on_stray=stray.append,
    )

    assert blocks == {"A.md": "alpha"}
    assert stray == [
        StrayText(
            where="before the first artifact block",
            text="I'll produce the analysis from the injected sources.",
        )
    ]
    assert str(stray[0]) == (
        "stray text before the first artifact block discarded: "
        '"I\'ll produce the analysis from the injected sources."'
    )


def test_parse_artifact_report_discards_stray_text_between_and_after_blocks():
    result = parse_artifact_report(
        "=== A.md ===\nalpha\n=== END A.md ===\nNow the second file.\n"
        "=== B.md ===\nbeta\n=== END B.md ===\nHope this helps.\n",
        label="Test",
    )

    assert result.blocks == {"A.md": "alpha", "B.md": "beta"}
    assert [(item.where, item.text) for item in result.stray] == [
        ("between artifact blocks", "Now the second file."),
        ("after the last artifact block", "Hope this helps."),
    ]


@pytest.mark.parametrize(
    "outside",
    [
        "# Analysis",
        "- one more thing",
        "```",
        '{"key": 1}',
        "| a | b |",
        "<function_calls>",
        "one\ntwo\nthree\nfour",
    ],
)
def test_outside_text_shaped_like_content_still_fails(outside):
    with pytest.raises(DrydockError, match="Text appeared outside"):
        parse_artifact_blocks(
            f"{outside}\n=== BEGIN ARTIFACT A.md ===\nalpha\n=== END ARTIFACT ===\n",
            label="Test",
        )


def test_prose_beside_an_orphan_close_is_not_stray():
    with pytest.raises(DrydockError, match="Text appeared outside"):
        parse_artifact_blocks(
            "=== BEGIN ARTIFACT A.md ===\nalpha\n=== END ARTIFACT ===\n"
            "The body of B.\n=== END ARTIFACT ===\n"
            "=== BEGIN ARTIFACT C.md ===\ngamma\n=== END ARTIFACT ===\n",
            label="Test",
        )


def test_outside_text_error_names_leading_content_and_quotes_it():
    with pytest.raises(DrydockError) as raised:
        parse_artifact_blocks(
            "# Analysis\n\n=== BEGIN ARTIFACT A.md ===\nalpha\n=== END ARTIFACT ===\n",
            label="Test",
        )

    assert "Stray text before the first artifact block: '# Analysis'" in str(raised.value)


def test_outside_text_error_names_trailing_text():
    with pytest.raises(DrydockError) as raised:
        parse_artifact_blocks(
            "=== A.md ===\nalpha\n=== END A.md ===\n- one more thing\n",
            label="Test",
        )

    assert "Stray text after the last artifact block: '- one more thing'" in str(raised.value)


def test_outside_text_error_truncates_a_long_line():
    with pytest.raises(DrydockError) as raised:
        parse_artifact_blocks(
            "x" * 600 + "\n=== A.md ===\nalpha\n=== END A.md ===\n",
            label="Test",
        )

    assert "'" + "x" * 117 + "...'" in str(raised.value)


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


def test_later_duplicate_updates_only_that_name():
    text = (
        "=== A.md ===\nalpha\n=== END A.md ===\n"
        "=== B.md ===\nbeta\n=== END B.md ===\n"
        "=== A.md ===\ndifferent\n=== END A.md ===\n"
    )

    result = parse_artifact_report(text, label="Test")

    assert result.blocks == {"A.md": "different", "B.md": "beta"}
    assert result.defects == ()


def test_three_drafts_use_the_last_without_changing_other_files():
    text = "\n".join(
        f"=== BEGIN ARTIFACT {name} ===\n{body}\n=== END ARTIFACT ==="
        for name, body in [
            ("A.md", "first"),
            ("B.md", "other"),
            ("A.md", "second"),
            ("A.md", "last"),
        ]
    )
    result = parse_artifact_report(text, label="Test")
    assert result.blocks == {"A.md": "last", "B.md": "other"}
    assert result.defects == ()


def test_an_unclosed_final_update_does_not_restore_the_old_draft():
    text = (
        "=== BEGIN ARTIFACT A.md ===\nfirst\n=== END ARTIFACT ===\n"
        "=== BEGIN ARTIFACT B.md ===\nother\n=== END ARTIFACT ===\n"
        "=== BEGIN ARTIFACT A.md ===\nunfinished"
    )
    result = parse_artifact_report(text, label="Test")
    assert result.blocks == {"B.md": "other"}
    assert [(d.name, d.reason) for d in result.rejected] == [
        ("A.md", "final update is unclosed; block discarded")
    ]


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


# LayersTesting 20261021.180733: analyze answered with a question and no artifact, and the run ended.
_REFUSAL = (
    "I can't produce this analysis in the form requested.\n\n"
    "If you want the artifact blocks themselves, tell me which form you want."
)


class _Run:
    def __init__(self, text: str, ok: bool = True):
        self.text = text
        self.ok = ok


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (_REFUSAL, True),
        ("", False),
        ("=== BEGIN ARTIFACT A.md ===\nbody\n=== END ARTIFACT ===\n", False),
        ("Preamble.\n=== A.md ===\nbody\n=== END A.md ===\n", False),
        ("Narration.\n=== END ARTIFACT ===\n", False),
        (
            '<invoke name="Write"><parameter name="path">A.md</parameter>'
            '<parameter name="content">body</parameter></invoke>',
            False,
        ),
    ],
)
def test_carries_no_artifact(text, expected):
    assert carries_no_artifact(text) is expected


def test_retry_assembly_keeps_the_prompt_and_appends_the_reason():
    original = PromptAssembly.single_prompt("ORIGINAL PROMPT\n")

    retry = no_artifact_retry_assembly(original, reply=_REFUSAL, unattended=True)

    assert retry.parts[0] == original.parts[0]
    appended = retry.parts[-1].text
    assert "Your previous reply contained no artifact blocks" in appended
    assert "No Commander is available" in appended
    assert "I can't produce this analysis" in appended


def test_retry_runs_once_more_with_the_reason_and_reports_it():
    original = PromptAssembly.single_prompt("ORIGINAL PROMPT\n")
    sent: list[str] = []
    progress: list[str] = []

    def rerun(assembly):
        sent.append(assembly.rendered_text)
        return _Run("=== A.md ===\nbody\n=== END A.md ===\n")

    result = retry_reply_without_artifacts(
        _Run(_REFUSAL), original, rerun, tag="analyze", on_text=progress.append
    )

    assert result.text.startswith("=== A.md ===")
    assert len(sent) == 1
    assert sent[0].startswith("ORIGINAL PROMPT\n")
    assert "Your previous reply contained no artifact blocks" in sent[0]
    assert progress == [
        "[analyze] response without artifacts, retrying once with the reason: "
        "\"I can't produce this analysis in the form requested. "
        'If you want the artifact blocks themselves, tell me which form you want."\n'
    ]


@pytest.mark.parametrize(
    "first",
    [
        _Run("=== A.md ===\nbody\n=== END A.md ===\n"),
        _Run(_REFUSAL, ok=False),
        _Run(""),
    ],
)
def test_retry_leaves_a_reply_with_artifacts_or_a_failed_run_alone(first):
    def rerun(assembly):
        raise AssertionError("no retry expected")

    original = PromptAssembly.single_prompt("P")
    assert retry_reply_without_artifacts(first, original, rerun, tag="t") is first


def test_content_then_a_surplus_close_marks_the_last_artifact_premature():
    text = (
        "=== BEGIN ARTIFACT A.md ===\nhead\n=== END ARTIFACT ===\ntail\n=== END ARTIFACT ===\n"
        "=== BEGIN ARTIFACT B.md ===\nbody\n=== END ARTIFACT ===\n"
    )

    pairing = pair_artifact_delimiters(text)

    assert pairing.premature_closes == ("A.md",)
    assert pairing.closed == ("A.md", "B.md")

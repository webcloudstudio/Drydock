"""The deterministic ruler behind plan continuation.

Every test here runs without an LLM, a filesystem, or a process: that is the point of the score.
"""

from __future__ import annotations

from drydock.plan_graph import PlannedStory
from drydock.plan_score import artifact_defect, score_plan
from drydock.plan_topology import merge_declaration

_BODY = "# FEATURE: Example\n\nContent.\n"


def _declared(*pairs: tuple[str, str]) -> tuple[PlannedStory, ...]:
    return tuple(
        PlannedStory(story_id=story_id, implements=filename) for story_id, filename in pairs
    )


# ── the score ───────────────────────────────────────────────────────────────────────


def test_score_counts_accepted_against_the_declaration():
    declared = _declared(("s1", "FEATURE-A.md"), ("s2", "FEATURE-B.md"))

    score = score_plan(declared, {"FEATURE-A.md": _BODY})

    assert score.expected == 2
    assert score.accepted == ("FEATURE-A.md",)
    assert [item.filename for item in score.missing] == ["FEATURE-B.md"]
    assert not score.is_complete


def test_a_complete_response_is_complete():
    declared = _declared(("s1", "FEATURE-A.md"), ("s2", "FEATURE-B.md"))

    score = score_plan(declared, {"FEATURE-A.md": _BODY, "FEATURE-B.md": _BODY})

    assert score.is_complete
    assert score.missing == ()


def test_a_damaged_artifact_is_invalid_rather_than_accepted():
    """A cut artifact must stay replaceable; accepting it would freeze the damage."""
    declared = _declared(("s1", "FEATURE-A.md"))

    score = score_plan(declared, {"FEATURE-A.md": _BODY}, damaged={"FEATURE-A.md"})

    assert score.accepted == ()
    assert [item.reason for item in score.invalid] == ["unpaired artifact delimiters"]
    assert not score.is_complete


def test_an_empty_artifact_is_invalid():
    declared = _declared(("s1", "FEATURE-A.md"))

    score = score_plan(declared, {"FEATURE-A.md": "   \n"})

    assert score.accepted == ()
    assert [item.reason for item in score.invalid] == ["artifact body is empty"]


def test_reserved_and_undeclared_blocks_never_enter_the_count():
    declared = _declared(("s1", "FEATURE-A.md"))

    score = score_plan(
        declared,
        {"TOPOLOGY.md": "x", "MANIFEST.md": "x", "README.md": "x", "FEATURE-A.md": _BODY},
    )

    assert score.accepted == ("FEATURE-A.md",)
    assert score.undeclared == ("README.md",)
    assert score.is_complete


def test_a_missing_typed_heading_does_not_block_acceptance_by_default():
    """Repairable by ``conform_specs``; gating on it would burn a pass re-authoring good work."""
    declared = _declared(("s1", "FEATURE-A.md"))

    assert artifact_defect("FEATURE-A.md", "no heading here") is None
    assert score_plan(declared, {"FEATURE-A.md": "no heading here"}).is_complete
    assert (
        artifact_defect("FEATURE-A.md", "no heading here", require_typed_heading=True)
        == "no typed '# Kind: Name' heading"
    )


def test_progress_is_measured_on_accepted_not_on_remaining():
    """A split moves the denominator; the stop rule must not move with it."""
    before = score_plan(_declared(("s1", "A.md"), ("s2", "B.md")), {"A.md": _BODY})
    # s2 split into two children: expected grows, accepted does not.
    split_only = score_plan(
        _declared(("s1", "A.md"), ("s2a", "B1.md"), ("s2b", "B2.md")), {"A.md": _BODY}
    )
    authored = score_plan(
        _declared(("s1", "A.md"), ("s2a", "B1.md"), ("s2b", "B2.md")),
        {"A.md": _BODY, "B1.md": _BODY},
    )

    assert not split_only.improved_on(before)
    assert authored.improved_on(before)


def test_rank_puts_an_unparsed_topology_behind_everything():
    no_ruler = score_plan((), {}, topology_parsed=False)
    with_ruler = score_plan(_declared(("s1", "A.md")), {}, topology_parsed=True)

    assert no_ruler.rank < with_ruler.rank


def test_render_leads_with_numbers_and_names_what_is_missing():
    declared = _declared(("s1", "FEATURE-A.md"), ("s2", "FEATURE-B.md"))

    rendered = score_plan(declared, {"FEATURE-A.md": _BODY}).render()

    assert "specs:     1 / 2  accepted" in rendered
    assert "s2 -> FEATURE-B.md" in rendered
    assert "manifest:  0" in rendered


# ── the amendment merge ─────────────────────────────────────────────────────────────


def test_no_amendment_leaves_the_declaration_untouched():
    current = _declared(("s1", "A.md"))

    merged, defects = merge_declaration(current, (), accepted={"A.md"})

    assert merged == current
    assert defects == ()


def test_a_pending_story_may_be_split():
    current = _declared(("s1", "A.md"), ("s2", "B.md"))
    amendment = _declared(("s1", "A.md"), ("s2a", "B1.md"), ("s2b", "B2.md"))

    merged, defects = merge_declaration(current, amendment, accepted={"A.md"})

    assert defects == ()
    assert [story.story_id for story in merged] == ["s1", "s2a", "s2b"]


def test_modifying_an_accepted_story_is_rejected_and_changes_nothing():
    current = _declared(("s1", "A.md"), ("s2", "B.md"))
    amendment = (
        PlannedStory(story_id="s1", implements="A-renamed.md"),
        PlannedStory(story_id="s2", implements="B.md"),
    )

    merged, defects = merge_declaration(current, amendment, accepted={"A.md"})

    assert merged == current
    assert len(defects) == 1
    assert "frozen" in defects[0].rendered()


def test_dropping_an_accepted_story_is_rejected():
    current = _declared(("s1", "A.md"), ("s2", "B.md"))
    amendment = _declared(("s2", "B.md"))

    merged, defects = merge_declaration(current, amendment, accepted={"A.md"})

    assert merged == current
    assert "dropped" in defects[0].rendered()


def test_a_pending_story_may_be_dropped_or_renamed_freely():
    current = _declared(("s1", "A.md"), ("s2", "B.md"))
    amendment = _declared(("s1", "A.md"))

    merged, defects = merge_declaration(current, amendment, accepted={"A.md"})

    assert defects == ()
    assert [story.story_id for story in merged] == ["s1"]

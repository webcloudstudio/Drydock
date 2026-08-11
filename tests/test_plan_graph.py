"""Deterministic planning core — verification, ordering, stack modes, and block grouping."""

from __future__ import annotations

import pytest

from drydock.plan_graph import (
    DEFAULT_BLOCK_TARGET_TOKENS,
    PlannedStory,
    assign_stack_modes,
    compute_plan,
    find_cycle,
    group_blocks,
    measure_stories,
    order_stories,
    verify_graph,
    verify_two_topologies,
)


def story(story_id: str, **kwargs) -> PlannedStory:
    kwargs.setdefault("implements", f"{story_id.upper()}.md")
    return PlannedStory(story_id=story_id, **kwargs)


def codes(defects) -> set[str]:
    return {defect.code for defect in defects}


# ── Verification ────────────────────────────────────────────────────────────────────


def test_clean_graph_has_no_defects():
    stories = [
        story("foundation", story_type="foundational"),
        story("catalog", depends=("foundation",)),
    ]
    assert verify_graph(stories) == ()


def test_unknown_edge_is_fatal():
    defects = verify_graph([story("catalog", depends=("missing",))])
    assert "unknown-edge" in codes(defects)
    assert all(defect.fatal for defect in defects if defect.code == "unknown-edge")


def test_self_edge_is_reported():
    defects = verify_graph([story("catalog", depends=("catalog",))])
    assert "self-edge" in codes(defects)


def test_cycle_is_detected_and_named():
    stories = [
        story("a", depends=("c",)),
        story("b", depends=("a",)),
        story("c", depends=("b",)),
    ]
    assert "cycle" in codes(verify_graph(stories))
    cycle = find_cycle(stories)
    assert set(cycle) == {"a", "b", "c"}


def test_acyclic_graph_reports_no_cycle():
    assert find_cycle([story("a"), story("b", depends=("a",))]) == ()


def test_story_must_implement_exactly_one_specification():
    defects = verify_graph([PlannedStory(story_id="orphan")])
    assert "no-specification" in codes(defects)


def test_specification_has_exactly_one_owning_story():
    stories = [
        story("first", implements="FEATURE-CATALOG.md"),
        story("second", implements="FEATURE-CATALOG.md"),
    ]
    defects = verify_graph(stories)
    assert "shared-specification" in codes(defects)


def test_duplicate_story_id_is_reported():
    defects = verify_graph([story("catalog"), story("catalog", implements="OTHER.md")])
    assert "duplicate-id" in codes(defects)


def test_empty_runnable_frontier_is_reported():
    stories = [story("a", depends=("b",)), story("b", depends=("a",))]
    assert "empty-frontier" in codes(verify_graph(stories))


def test_feature_without_members_is_reported():
    defects = verify_graph([story("assembly", story_type="feature")])
    assert "feature-without-members" in codes(defects)


def test_unknown_type_and_kind_are_reported():
    defects = verify_graph([story("a", story_type="architecture", delivery_kind="chore")])
    assert {"unknown-type", "unknown-kind"} <= codes(defects)


# ── Two-topology check ──────────────────────────────────────────────────────────────


def test_phase_inversion_is_detected():
    """A story in phase 2 cannot depend on a story in phase 3."""
    stories = [
        story("late", phase=3),
        story("early", phase=2, depends=("late",)),
    ]
    defects = verify_two_topologies(stories)
    assert [defect.code for defect in defects] == ["phase-inversion"]
    assert "phase 2" in defects[0].message and "phase 3" in defects[0].message


def test_agreeing_topologies_produce_no_defect():
    stories = [story("early", phase=1), story("late", phase=2, depends=("early",))]
    assert verify_two_topologies(stories) == ()


def test_same_phase_dependency_is_legal():
    stories = [story("a", phase=2), story("b", phase=2, depends=("a",))]
    assert verify_two_topologies(stories) == ()


# ── Ordering ────────────────────────────────────────────────────────────────────────


def test_order_respects_edges_over_declaration_order():
    stories = [story("consumer", depends=("provider",)), story("provider")]
    assert [s.story_id for s in order_stories(stories)] == ["provider", "consumer"]


def test_order_is_keyed_by_phase_then_declaration():
    stories = [story("b", phase=2), story("a", phase=1), story("c", phase=1)]
    assert [s.story_id for s in order_stories(stories)] == ["a", "c", "b"]


def test_order_is_deterministic_across_runs():
    stories = [
        story("ui", phase=2, depends=("api",)),
        story("api", phase=1, depends=("foundation",)),
        story("foundation", phase=1),
        story("report", phase=2, depends=("api",)),
    ]
    first = [s.story_id for s in order_stories(stories)]
    assert first == [s.story_id for s in order_stories(stories)]
    assert first == ["foundation", "api", "ui", "report"]


def test_unorderable_graph_raises():
    with pytest.raises(ValueError, match="not orderable"):
        order_stories([story("a", depends=("b",)), story("b", depends=("a",))])


# ── Builder and consumer mode ───────────────────────────────────────────────────────


def test_first_user_of_a_stack_is_its_builder():
    ordered = (
        story("foundation", story_type="foundational", stack=("fastapi.md",)),
        story("catalog", stack=("fastapi.md",)),
    )
    assigned, defects = assign_stack_modes(ordered)
    assert [s.stack_mode for s in assigned] == ["builder", "consumer"]
    assert defects == ()


def test_story_without_a_stack_defaults_to_builder():
    assigned, _ = assign_stack_modes((story("solo"),))
    assert assigned[0].stack_mode == "builder"


def test_a_non_foundational_first_user_is_a_non_fatal_defect_signal():
    """Disagreement means a missing edge or a missing foundational story, not a tie to break."""
    ordered = (story("catalog", story_type="service", stack=("fastapi.md",)),)
    assigned, defects = assign_stack_modes(ordered)
    assert assigned[0].stack_mode == "builder"
    assert [defect.code for defect in defects] == ["unfounded-stack"]
    assert defects[0].fatal is False


def test_stack_mode_is_build_order_global_not_per_phase():
    ordered = (
        story("foundation", story_type="foundational", phase=1, stack=("common.md",)),
        story("later", phase=5, stack=("common.md",)),
    )
    assigned, _ = assign_stack_modes(ordered)
    assert [s.stack_mode for s in assigned] == ["builder", "consumer"]


# ── Blocks ──────────────────────────────────────────────────────────────────────────


def test_block_never_mixes_topology_types():
    ordered = (
        story("foundation", story_type="foundational"),
        story("catalog", story_type="service"),
    )
    _, blocks = group_blocks(ordered)
    assert len(blocks) == 2
    assert [b.story_type for b in blocks] == ["foundational", "service"]


def test_block_never_crosses_a_phase_boundary():
    ordered = (story("a", phase=1), story("b", phase=2))
    _, blocks = group_blocks(ordered)
    assert [b.phase for b in blocks] == [1, 2]


def test_block_combines_unequal_stacks_as_a_union():
    ordered = (story("api", stack=("fastapi.md",)), story("ui", stack=("bootstrap5.md",)))
    _, blocks = group_blocks(ordered)
    assert len(blocks) == 1
    assert blocks[0].stack == ("fastapi.md", "bootstrap5.md")


def test_same_key_stories_amortize_one_block():
    ordered = tuple(story(f"s{i}", stack=("fastapi.md",)) for i in range(4))
    stamped, blocks = group_blocks(ordered)
    assert len(blocks) == 1
    assert blocks[0].story_ids == ("s0", "s1", "s2", "s3")
    assert {s.block for s in stamped} == {1}


def test_block_ends_when_the_next_divisible_story_would_pass_the_target():
    ordered = tuple(story(f"s{i}", size_tokens=400) for i in range(3))
    _, blocks = group_blocks(ordered, target_tokens=1000)
    assert [b.story_ids for b in blocks] == [("s0", "s1"), ("s2",)]
    assert [b.over_target for b in blocks] == [False, False]


def test_optimizer_prefers_shared_context_and_unlocks_dependents_inside_block():
    ordered = (
        story("seed", stack=("common.md",)),
        story("unrelated", stack=("other.md",)),
        story("dependent", stack=("common.md", "api.md"), depends=("seed",)),
    )

    def cost(stories):
        files = {name for item in stories for name in item.stack}
        return len(stories) * 10 + len(files) * 100

    _, blocks = group_blocks(ordered, target_tokens=1000, block_size_fn=cost)

    assert blocks[0].story_ids == ("seed", "dependent", "unrelated")
    assert blocks[0].size_tokens == 330


# The CommonMark regression: two cheap, context-sharing stories merged into one block that
# owed 8 acceptance criteria against a flat repair budget of 3. It reached 6 and stopped, third
# of five, starving every block behind it. Token cost never saw it coming — the merge was cheap.


def test_two_heavily_specified_stories_do_not_share_a_block():
    ordered = (
        story("leaf-blocks", acceptance_count=4),
        story("containers-lists", acceptance_count=4),
    )

    _, blocks = group_blocks(ordered)

    assert [b.story_ids for b in blocks] == [("leaf-blocks",), ("containers-lists",)]


def test_blocks_within_the_acceptance_ceiling_pack_exactly_as_before():
    """The 08-10 shape, where no block exceeded five criteria, must be untouched."""
    ordered = tuple(story(f"s{i}", acceptance_count=1) for i in range(5))

    _, blocks = group_blocks(ordered)

    assert [b.story_ids for b in blocks] == [("s0", "s1", "s2", "s3", "s4")]


def test_a_story_over_the_ceiling_alone_still_builds_as_its_own_block():
    """Irreducible, exactly as an over-``limit_tokens`` seed is. A marker, never a refusal."""
    ordered = (story("huge", acceptance_count=9), story("small", acceptance_count=1))

    _, blocks = group_blocks(ordered)

    assert [b.story_ids for b in blocks] == [("huge",), ("small",)]


def test_the_acceptance_ceiling_can_be_disabled():
    ordered = (story("a", acceptance_count=8), story("b", acceptance_count=8))

    _, blocks = group_blocks(ordered, acceptance_limit=0)

    assert [b.story_ids for b in blocks] == [("a", "b")]


def test_optimizer_never_mixes_screen_and_non_screen_work():
    ordered = (story("api"), story("screen", implements="SCREEN-HOME.md"))
    _, blocks = group_blocks(ordered)
    assert [block.story_ids for block in blocks] == [("api",), ("screen",)]


def test_irreducible_story_above_absolute_limit_is_rejected():
    result = compute_plan(
        [story("huge")],
        target_tokens=50_000,
        limit_tokens=120_000,
        size_fn=lambda _: 120_001,
    )
    assert "block-limit" in codes(result.fatal)


def test_irreducible_stories_each_form_a_valid_over_target_block():
    """Splitting around a story that is over target on its own achieves nothing.

    A language definition that is 50,000 tokens of normative text is one indivisible input:
    isolating every story implementing against it would destroy the amortization blocks exist
    for. They pack, and the block is marked.
    """
    ordered = tuple(story(f"s{i}", size_tokens=2000) for i in range(3))
    _, blocks = group_blocks(ordered, target_tokens=1000)
    assert [block.story_ids for block in blocks] == [("s0",), ("s1",), ("s2",)]
    assert all(block.over_target for block in blocks)


def test_a_single_oversize_story_still_gets_its_own_block():
    ordered = (story("huge", size_tokens=50_000),)
    _, blocks = group_blocks(ordered, target_tokens=1000)
    assert len(blocks) == 1
    assert blocks[0].over_target is True


def test_zero_target_disables_size_grouping_and_marking():
    ordered = tuple(story(f"s{i}", size_tokens=10**6) for i in range(3))
    _, blocks = group_blocks(ordered, target_tokens=0, limit_tokens=0)
    assert len(blocks) == 1
    assert blocks[0].over_target is False


def test_over_target_is_a_warning_never_a_refusal():
    """The target is a warning and a target, not a guardrail."""
    stories = [
        story("foundation", story_type="foundational"),
        story("catalog", depends=("foundation",)),
    ]
    result = compute_plan(stories, target_tokens=100, size_fn=lambda _: 5000)
    assert result.fatal == ()
    assert len(result.blocks) == 2
    assert all(s.over_target for s in result.stories)
    assert {d.code for d in result.warnings} == {"over-target-story", "over-target-block"}


def test_measured_sizes_are_stamped_onto_the_stories():
    ordered = (story("a", story_type="foundational"),)
    measured, defects = measure_stories(ordered, lambda _: 30, target_tokens=100)
    assert measured[0].size_tokens == 30
    assert measured[0].over_target is False
    assert defects == ()


def test_a_negative_measurement_floors_at_zero():
    measured, _ = measure_stories((story("a"),), lambda _: -5)
    assert measured[0].size_tokens == 0


def test_unmeasured_plans_carry_no_size_markers():
    result = compute_plan([story("a", story_type="foundational")])
    assert result.stories[0].size_tokens == 0
    assert result.stories[0].over_target is False
    assert result.warnings == ()


# ── Pipeline ────────────────────────────────────────────────────────────────────────


def test_compute_plan_orders_assigns_and_blocks():
    stories = [
        story("ui", phase=2, stack=("bootstrap5.md",), depends=("foundation",)),
        story("foundation", story_type="foundational", phase=1, stack=("fastapi.md",)),
    ]
    result = compute_plan(stories)
    assert result.fatal == ()
    assert [s.story_id for s in result.stories] == ["foundation", "ui"]
    assert [s.stack_mode for s in result.stories] == ["builder", "builder"]
    assert [s.block for s in result.stories] == [1, 2]


def test_compute_plan_short_circuits_on_a_fatal_defect():
    result = compute_plan([story("a", depends=("ghost",))])
    assert result.blocks == ()
    assert "unknown-edge" in codes(result.fatal)


def test_compute_plan_surfaces_non_fatal_stack_warnings():
    result = compute_plan([story("catalog", stack=("fastapi.md",))])
    assert result.fatal == ()
    assert "unfounded-stack" in codes(result.warnings)


def test_default_block_target_is_a_single_build_pass():
    assert DEFAULT_BLOCK_TARGET_TOKENS > 0


def test_story_count_is_not_capped():
    """A correct 300-story project is plausible; scale is answered with a stronger model."""
    stories = [story("root", story_type="foundational")] + [
        story(f"s{i}", depends=("root",)) for i in range(300)
    ]
    result = compute_plan(stories)
    assert result.fatal == ()
    assert len(result.stories) == 301

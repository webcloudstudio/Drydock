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


@pytest.mark.parametrize(
    "state",
    ["closed/verified", "closed/implemented", "implemented", "closed/failed", "blocked/questions"],
)
def test_regrouping_preserves_started_blocks_and_chains_pending_work(state):
    declared = [
        story("original", block=7, state=state),
        story("r1", block=8, depends=("original",)),
        story("r2", block=9, depends=("r1",)),
        story("r3", block=10, depends=("r2",)),
    ]
    result = compute_plan(
        declared,
        preserve_existing=True,
        min_savings=1,
        target_tokens=250,
        block_size_fn=lambda members: 100 + 50 * len(members),
    )
    assert not result.fatal
    assert [block.story_ids for block in result.blocks] == [
        ("original",),
        ("r1",),
        ("r2",),
        ("r3",),
    ]
    assert [s.block for s in result.stories] == [7, 8, 9, 10]


def test_regrouping_does_not_cross_started_work():
    declared = [
        story("original", block=1, state="closed/verified"),
        story("r1", block=2, depends=("original",)),
        story("r2", block=3, depends=("r1",)),
        story("r3", block=4, depends=("r2",)),
    ]
    result = compute_plan(
        declared,
        preserve_existing=True,
        min_savings=1,
        block_size_fn=lambda members: 100 + 50 * len(members),
    )
    assert not result.fatal
    assert [block.story_ids for block in result.blocks] == [
        ("original",),
        ("r1",),
        ("r2",),
        ("r3",),
    ]

    # A fixed block between two pending stories is still an ordering barrier.
    declared[2] = story("r2", block=3, state="implemented", depends=("r1",))
    result = compute_plan(
        declared,
        preserve_existing=True,
        min_savings=1,
        block_size_fn=lambda members: 100 + 50 * len(members),
    )
    assert not result.fatal
    assert [block.story_ids for block in result.blocks] == [
        ("original",),
        ("r1",),
        ("r2",),
        ("r3",),
    ]


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


def test_story_listing_two_specifications_is_reported():
    defects = verify_graph([story("orders", implements="SCREEN-ORDERS.md, FEATURE-PRICING.md")])
    assert "multi-specification" in codes(defects)


def test_a_specification_inside_two_lists_has_two_owners():
    stories = [
        story("orders", implements="SCREEN-ORDERS.md, FEATURE-PRICING.md"),
        story("cart", implements="SCREEN-CART.md FEATURE-PRICING.md"),
    ]
    messages = [defect.message for defect in verify_graph(stories)]
    assert any(m.startswith("FEATURE-PRICING.md is implemented by 2 stories") for m in messages)


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
        story("foundation", story_type="foundational", phase=1, stack=("fastapi.md",)),
        story("later", phase=5, stack=("fastapi.md",)),
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
    _, blocks = group_blocks(ordered, min_savings=0)
    assert len(blocks) == 1
    assert blocks[0].stack == ("fastapi.md", "bootstrap5.md")


def test_same_key_stories_amortize_one_block():
    ordered = tuple(story(f"s{i}", stack=("fastapi.md",)) for i in range(4))
    stamped, blocks = group_blocks(ordered, min_savings=0)
    assert len(blocks) == 1
    assert blocks[0].story_ids == ("s0", "s1", "s2", "s3")
    assert {s.block for s in stamped} == {1}


def test_block_ends_when_the_next_divisible_story_would_pass_the_target():
    ordered = tuple(story(f"s{i}", size_tokens=400) for i in range(3))
    _, blocks = group_blocks(ordered, target_tokens=1000, min_savings=0)
    assert [b.story_ids for b in blocks] == [("s0", "s1"), ("s2",)]
    assert [b.over_target for b in blocks] == [False, False]


def test_optimizer_preserves_dependency_gates_despite_shared_context():
    ordered = (
        story("seed", stack=("common.md",)),
        story("unrelated", stack=("other.md",)),
        story("dependent", stack=("common.md", "api.md"), depends=("seed",)),
    )

    def cost(stories):
        files = {name for item in stories for name in item.stack}
        return len(stories) * 10 + len(files) * 100

    _, blocks = group_blocks(ordered, target_tokens=1000, min_savings=0, block_size_fn=cost)

    assert [block.story_ids for block in blocks] == [("seed", "unrelated"), ("dependent",)]
    assert blocks[0].size_tokens == 220


# A merge is worth taking only when the shared context it saves is worth having. Ranking merges
# by savings alone made any overlap above zero worth taking, so two stories sharing nothing but a
# compacted language file merged for a few hundred tokens — a saving nobody can spend.


def test_a_merge_saving_less_than_the_floor_is_declined():
    ordered = (
        story("language", stack=("python.md",)),
        story("persistence", stack=("python.md", "postgres.md")),
    )

    def cost(stories):
        # python.md is cheap and shared; postgres.md is the real cost and is not.
        weights = {"python.md": 200, "postgres.md": 20_000}
        return sum(weights[name] for name in {n for item in stories for n in item.stack})

    _, blocks = group_blocks(ordered, min_savings=1_000, block_size_fn=cost)

    assert [block.story_ids for block in blocks] == [("language",), ("persistence",)]


def test_a_merge_saving_more_than_the_floor_is_taken():
    ordered = (
        story("screen-list", stack=("bootstrap5.md", "list.md")),
        story("screen-detail", stack=("bootstrap5.md", "detail.md")),
    )

    def cost(stories):
        weights = {"bootstrap5.md": 20_000, "list.md": 200, "detail.md": 200}
        return sum(weights[name] for name in {n for item in stories for n in item.stack})

    _, blocks = group_blocks(ordered, min_savings=1_000, block_size_fn=cost)

    assert [block.story_ids for block in blocks] == [("screen-list", "screen-detail")]


def test_a_zero_floor_merges_on_any_saving_at_all():
    """The prior behavior, still reachable: ``0`` takes every merge above zero savings."""
    ordered = (
        story("language", stack=("python.md",)),
        story("persistence", stack=("python.md", "postgres.md")),
    )

    def cost(stories):
        weights = {"python.md": 200, "postgres.md": 20_000}
        return sum(weights[name] for name in {n for item in stories for n in item.stack})

    _, blocks = group_blocks(ordered, min_savings=0, block_size_fn=cost)

    assert [block.story_ids for block in blocks] == [("language", "persistence")]


def test_the_floor_never_splits_a_block_the_budgets_already_bound():
    """The floor declines merges; it never forces one, and never overrides a hard boundary."""
    ordered = (
        story("foundation", story_type="foundational", stack=("python.md",)),
        story("service", story_type="service", stack=("python.md",)),
    )

    def cost(stories):
        return 100 * len({name for item in stories for name in item.stack})

    _, blocks = group_blocks(ordered, min_savings=0, block_size_fn=cost)

    assert [block.story_type for block in blocks] == ["foundational", "service"]


def test_only_token_cost_splits_a_block():
    """ReadingList 20261023.144538: stories owing 3-8 criteria each built one per block."""
    ordered = tuple(story(f"s{i}", stack=("flask.md",)) for i in range(8))

    def cost(stories):
        return 5_000 + 1_000 * len(stories)

    _, blocks = group_blocks(ordered, target_tokens=10_000, block_size_fn=cost)

    assert [b.story_ids for b in blocks] == [
        ("s0", "s1", "s2", "s3", "s4"),
        ("s5", "s6", "s7"),
    ]


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
    _, blocks = group_blocks(ordered, target_tokens=0, limit_tokens=0, min_savings=0)
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


def test_language_initialization_cannot_merge_with_persistence():
    from drydock.plan_graph import PlannedStory, group_blocks

    language = PlannedStory(
        "language", story_type="foundational", fields={"initializes_language": "yes"}
    )
    database = PlannedStory("database", story_type="foundational", depends=("language",))
    result = group_blocks((language, database), min_savings=0, block_size_fn=lambda stories: 100)
    # The first return value contains the stamped stories.
    stamped, _ = result
    assert stamped[0].block != stamped[1].block


def test_guidance_has_no_runtime_foundation_but_tiered_stacks_still_do():
    assigned, defects = assign_stack_modes(
        (story("release", stack=("common.md",)),), guidance_stacks=frozenset({"common.md"})
    )
    assert assigned[0].stack_mode == "consumer"
    assert not defects
    _, defects = assign_stack_modes((story("ui", stack=("bootstrap5.md",)),))
    assert [d.code for d in defects] == ["unfounded-stack"]


@pytest.mark.parametrize("language", ["python.md", "go.md"])
def test_delivery_chain_keeps_scoped_gates_before_full_suite(language):
    ordered = (
        story("foundation", story_type="foundational", stack=(language,)),
        story("data", depends=("foundation",), stack=(language,)),
        story("api", depends=("data",), stack=(language,)),
        story("release", depends=("data", "api"), stack=(language,)),
    )
    _, blocks = group_blocks(
        ordered, block_size_fn=lambda members: 10000 + len(members), min_savings=1
    )
    assert [block.story_ids for block in blocks] == [
        ("foundation",),
        ("data",),
        ("api",),
        ("release",),
    ]


def test_started_multi_story_block_is_preserved_as_a_resume_unit():
    ordered = (
        story("a", block=4, state="closed/failed"),
        story("b", block=4, depends=("a",)),
        story("c", depends=("b",)),
    )
    _, blocks = group_blocks(ordered, preserve_existing=True, min_savings=0)
    assert [block.story_ids for block in blocks] == [("a", "b"), ("c",)]

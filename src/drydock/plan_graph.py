"""Deterministic planning core — the thirteen non-model jobs of ``drydock plan``.

`plan` performs seventeen distinct jobs; only four require a model. This module owns the
deterministic remainder so they never occupy the planning prompt's context window:

| Job | Owner |
|---|---|
| Relationships — ``depends``, ``provides``, ``consumes`` | Model (declared) |
| Actual topology — the story dependency graph | Model (declared) |
| High-level topology — phases | Model (declared) |
| Programmatic Acceptance | Model (authored) |
| Verification of all the above | This module |
| Block grouping | This module |
| Ordering and Manifest serialization | This module |

The division of labour is **authorship versus verification**, not semantics versus arithmetic.
The model decides everything requiring judgment and states what each story requires and provides;
this module proves the result is internally consistent and refuses it otherwise. A contradiction
becomes a deterministic defect with a precise message instead of a shape failure.

The model never sorts, never checks its own consistency, and never reasons about a position in an
order it has not computed.
"""

from __future__ import annotations

import heapq
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace

#: The Manifest is a list of stories; ``type`` is the only variation.
#:
#: ``foundational`` — foundation and scaffolding; runs early because work depends on it.
#: ``service``      — everything that does work; reorderable, carries no structural debt.
#: ``feature``      — an assembly story: acceptance plus assembly and intent, no implementation
#:                    instructions; runs after its members.
#:
#: Foundation status derives from the dependency graph, not from a filename prefix: the rule is
#: *build the foundation that is needed*, not *build all foundation first*. There is no fourth
#: type — a "foundational service" is foundational to whatever depends on it, which the edges
#: already state more precisely than a label could.
STORY_TYPES = ("foundational", "service", "feature")

#: Delivery kind, emitted by Analyze in the Story Realization Map.
DELIVERY_KINDS = ("capability", "integration", "migration", "test harness")

#: A story's relationship to a stack file, not a position in build order. A builder story
#: receives the full stack file; a consumer story receives the interface (compact) view.
STACK_MODES = ("builder", "consumer")

_DEFAULT_TYPE = "service"
_DEFAULT_KIND = "capability"


@dataclass(frozen=True)
class GraphDefect:
    """One deterministic, precisely located inconsistency in a declared plan."""

    code: str
    story_id: str
    message: str
    fatal: bool = True

    def rendered(self) -> str:
        where = f"{self.story_id}: " if self.story_id else ""
        return f"{where}{self.message}"


@dataclass(frozen=True)
class PlannedStory:
    """One Manifest node. Every attribute is orthogonal and deterministic.

    | Attribute | Values |
    |---|---|
    | Type | ``foundational``, ``service``, ``feature`` |
    | Delivery kind | ``capability``, ``integration``, ``migration``, ``test harness`` |
    | Acceptance contract | Flag; the story has real acceptance to honor |
    | Stack | Stack files, each attached in ``builder`` or ``consumer`` mode |

    Type is separate from stack: a ``service`` may be a backend provider or a screen, so the
    no-cross-stack guardrail — which operates on stack — is unaffected.
    """

    story_id: str
    name: str = ""
    story_type: str = _DEFAULT_TYPE
    phase: int = 1
    delivery_kind: str = _DEFAULT_KIND
    acceptance_contract: bool = False
    implements: str = ""
    depends: tuple[str, ...] = ()
    provides: tuple[str, ...] = ()
    consumes: tuple[str, ...] = ()
    stack: tuple[str, ...] = ()
    #: Estimated build-pass cost in tokens; 0 when unmeasured.
    size_tokens: int = 0
    #: Assigned by :func:`assign_stack_modes`; never authored by the model.
    stack_mode: str = ""
    #: Assigned by :func:`group_blocks`; ephemeral, Manifest-only, regenerated every run.
    block: int = 0
    fields: Mapping[str, str] = field(default_factory=dict)

    @property
    def is_feature(self) -> bool:
        return self.story_type == "feature"

    @property
    def stack_signature(self) -> tuple[str, ...]:
        return tuple(sorted(self.stack))


# ── Verification ────────────────────────────────────────────────────────────────────


def _index(stories: Sequence[PlannedStory]) -> dict[str, PlannedStory]:
    return {story.story_id: story for story in stories}


def find_cycle(stories: Sequence[PlannedStory]) -> tuple[str, ...]:
    """Return one dependency cycle as an ordered id tuple, or ``()`` when acyclic."""
    known = _index(stories)
    WHITE, GRAY, BLACK = 0, 1, 2
    color = dict.fromkeys(known, WHITE)
    stack: list[str] = []

    def visit(node: str) -> tuple[str, ...]:
        color[node] = GRAY
        stack.append(node)
        for nxt in known[node].depends:
            if nxt not in color:
                continue
            if color[nxt] == GRAY:
                return tuple(stack[stack.index(nxt) :]) + (nxt,)
            if color[nxt] == WHITE:
                found = visit(nxt)
                if found:
                    return found
        color[node] = BLACK
        stack.pop()
        return ()

    for node in known:
        if color[node] == WHITE:
            found = visit(node)
            if found:
                return found
    return ()


def verify_graph(stories: Sequence[PlannedStory]) -> tuple[GraphDefect, ...]:
    """Prove a declared plan is internally consistent.

    Checks, in order: unique ids, resolvable edges, no self-edge, acyclicity, exactly one
    governed specification per story and one owning story per specification, a non-empty
    runnable frontier, feature assembly membership, and the two-topology agreement between
    the declared phases and the declared dependency graph.
    """
    defects: list[GraphDefect] = []
    known = _index(stories)

    seen: set[str] = set()
    for story in stories:
        if not story.story_id:
            defects.append(GraphDefect("missing-id", "", "story declares no id"))
        elif story.story_id in seen:
            defects.append(
                GraphDefect("duplicate-id", story.story_id, "duplicate story id in the plan")
            )
        seen.add(story.story_id)
        if story.story_type not in STORY_TYPES:
            defects.append(
                GraphDefect(
                    "unknown-type",
                    story.story_id,
                    f"unknown story type {story.story_type!r}; "
                    f"expected one of {', '.join(STORY_TYPES)}",
                )
            )
        if story.delivery_kind and story.delivery_kind not in DELIVERY_KINDS:
            defects.append(
                GraphDefect(
                    "unknown-kind",
                    story.story_id,
                    f"unknown delivery kind {story.delivery_kind!r}; "
                    f"expected one of {', '.join(DELIVERY_KINDS)}",
                )
            )

    for story in stories:
        for dep in story.depends:
            if dep == story.story_id:
                defects.append(GraphDefect("self-edge", story.story_id, "story depends on itself"))
            elif dep not in known:
                defects.append(
                    GraphDefect("unknown-edge", story.story_id, f"depends on unknown id {dep!r}")
                )

    cycle = find_cycle(stories)
    if cycle:
        defects.append(GraphDefect("cycle", "", "dependency cycle: " + " -> ".join(cycle)))

    owners: dict[str, list[str]] = {}
    for story in stories:
        if not story.implements:
            defects.append(
                GraphDefect(
                    "no-specification",
                    story.story_id,
                    "story implements no governed specification; "
                    "exactly one specification per story",
                )
            )
            continue
        owners.setdefault(story.implements, []).append(story.story_id)
    for spec, claimants in sorted(owners.items()):
        if len(claimants) > 1:
            defects.append(
                GraphDefect(
                    "shared-specification",
                    "",
                    f"{spec} is implemented by {len(claimants)} stories "
                    f"({', '.join(claimants)}); exactly one owning story per specification",
                )
            )

    if stories and not any(not story.depends for story in stories):
        defects.append(
            GraphDefect(
                "empty-frontier",
                "",
                "no story has an empty depends: — the initial runnable frontier is empty "
                "and the build cannot start",
            )
        )

    for story in stories:
        if story.is_feature and not story.depends:
            defects.append(
                GraphDefect(
                    "feature-without-members",
                    story.story_id,
                    "a feature is an assembly story: it depends on its member stories and "
                    "runs after them",
                )
            )

    defects.extend(verify_two_topologies(stories))
    return tuple(defects)


def verify_two_topologies(stories: Sequence[PlannedStory]) -> tuple[GraphDefect, ...]:
    """Require the high-level topology (phases) and the actual topology (edges) to agree.

    A story in phase 2 cannot depend on a story in phase 3. This is a real, silent, common
    failure, free to detect here and impossible for a model to reliably self-audit across a
    hundred stories. It is available only because both topologies are authored explicitly.
    """
    known = _index(stories)
    defects: list[GraphDefect] = []
    for story in stories:
        for dep in story.depends:
            upstream = known.get(dep)
            if upstream is None:
                continue
            if upstream.phase > story.phase:
                defects.append(
                    GraphDefect(
                        "phase-inversion",
                        story.story_id,
                        f"is phase {story.phase} but depends on {dep!r} in phase "
                        f"{upstream.phase}; the high-level topology (phases) and the actual "
                        "topology (edges) must agree",
                    )
                )
    return tuple(defects)


# ── Ordering ────────────────────────────────────────────────────────────────────────


def order_stories(stories: Sequence[PlannedStory]) -> tuple[PlannedStory, ...]:
    """Return the stories in deterministic build order.

    A stable topological sort keyed by ``(phase, declaration index)``: the declared high-level
    topology sequences the work, the declared edges constrain it, and the authored order breaks
    every remaining tie. Ordering is computed here, never authored — the model has not computed
    the order and must not reason about a position within it.

    Requires an acyclic graph with resolvable edges; call :func:`verify_graph` first.
    """
    position = {story.story_id: index for index, story in enumerate(stories)}
    known = _index(stories)
    indegree = {
        story.story_id: sum(1 for dep in story.depends if dep in known) for story in stories
    }
    dependents: dict[str, list[str]] = {story.story_id: [] for story in stories}
    for story in stories:
        for dep in story.depends:
            if dep in known:
                dependents[dep].append(story.story_id)

    ready: list[tuple[int, int, str]] = [
        (known[sid].phase, position[sid], sid) for sid, degree in indegree.items() if degree == 0
    ]
    heapq.heapify(ready)
    ordered: list[PlannedStory] = []
    while ready:
        _, _, story_id = heapq.heappop(ready)
        ordered.append(known[story_id])
        for nxt in dependents[story_id]:
            indegree[nxt] -= 1
            if indegree[nxt] == 0:
                heapq.heappush(ready, (known[nxt].phase, position[nxt], nxt))
    if len(ordered) != len(stories):
        remaining = sorted(set(known) - {story.story_id for story in ordered})
        raise ValueError(f"plan graph is not orderable; unresolved: {', '.join(remaining)}")
    return tuple(ordered)


# ── Builder and consumer mode ───────────────────────────────────────────────────────


def assign_stack_modes(
    ordered: Sequence[PlannedStory],
) -> tuple[tuple[PlannedStory, ...], tuple[GraphDefect, ...]]:
    """Assign each story's stack mode from first use in the computed order.

    The model authors the foundational story that stands a stack up — recognizing that
    something must establish the web server, and making it a node, is judgment. Python assigns
    the flag: by definition the first story using a stack is its builder and later ones are
    consumers. Ordering is build-order-global, as compact substitution already is — not
    per-block, not phase-based.

    Disagreement is a defect signal, not a tie to break. A story requiring a stack to be stood
    up carries that edge, so topology puts the founding story first and the first user *is* the
    builder. The two answers diverge only when an edge or a foundational story is missing; if
    the first user of a stack is not a ``foundational`` story, that is reported. The cost of
    being wrong is asymmetric — consumer-when-it-should-be-builder starves the build agent,
    while builder-when-it-should-be-consumer merely costs tokens — so ambiguity defaults to
    builder.
    """
    seen: set[str] = set()
    defects: list[GraphDefect] = []
    assigned: list[PlannedStory] = []
    for story in ordered:
        builds = [name for name in story.stack if name not in seen]
        for name in builds:
            seen.add(name)
            if story.story_type != "foundational":
                defects.append(
                    GraphDefect(
                        "unfounded-stack",
                        story.story_id,
                        f"is the first user of stack file {name!r} but is a "
                        f"{story.story_type} story; the story that stands a stack up is "
                        "foundational, or an edge to the founding story is missing",
                        fatal=False,
                    )
                )
        mode = "builder" if (builds or not story.stack) else "consumer"
        assigned.append(replace(story, stack_mode=mode))
    return tuple(assigned), tuple(defects)


# ── Blocks ──────────────────────────────────────────────────────────────────────────

#: A build pass ceiling: what one build agent can implement and verify in a single pass — its
#: specification plus stack files in, a working diff and passing assertions out. Measurable in
#: tokens before anything runs. A one-week sprint is an artifact of human capacity and carries
#: no meaning here.
DEFAULT_BLOCK_BUDGET_TOKENS = 60_000


@dataclass(frozen=True)
class Block:
    """A set of stories optimized for context.

    Blocks are an optimization output, not a taxonomy: ephemeral, Manifest-only, regenerated
    every run, and computed here. UI stories group together whether or not they belong to the
    same Agile feature. Context economy comes from blocks, not from feature grouping.

    - **Hard:** one topology type per block; never cross a phase boundary; never violate the edges
    - **Objective:** amortize stack-file cost across the most stories that still fit one build pass

    The mechanism behind the no-cross-stack guardrail is stack creep from Rigging: mixing
    topology types in one block forces every stack file each type needs into the block, so it
    pays for context neither half uses and the build agent reads instructions for work it is not
    doing.
    """

    number: int
    story_type: str
    phase: int
    stack: tuple[str, ...]
    story_ids: tuple[str, ...]
    size_tokens: int = 0


def _partition_key(story: PlannedStory) -> tuple[int, str, tuple[str, ...]]:
    return (story.phase, story.story_type, story.stack_signature)


def group_blocks(
    ordered: Sequence[PlannedStory],
    *,
    budget_tokens: int = DEFAULT_BLOCK_BUDGET_TOKENS,
) -> tuple[tuple[PlannedStory, ...], tuple[Block, ...]]:
    """Bin-pack the computed order into blocks and stamp each story's block number.

    Every input is known at plan time — types, stacks, phases, edges, story size. Because the
    input is already in topological order, contiguous grouping cannot violate an edge, so the
    packer only enforces the partition key (phase, topology type, stack set) and the build-pass
    budget.
    """
    blocks: list[Block] = []
    stamped: list[PlannedStory] = []
    current: list[PlannedStory] = []
    current_key: tuple[int, str, tuple[str, ...]] | None = None
    current_size = 0

    def flush() -> None:
        nonlocal current, current_key, current_size
        if not current:
            return
        number = len(blocks) + 1
        blocks.append(
            Block(
                number=number,
                story_type=current[0].story_type,
                phase=current[0].phase,
                stack=current[0].stack_signature,
                story_ids=tuple(story.story_id for story in current),
                size_tokens=current_size,
            )
        )
        stamped.extend(replace(story, block=number) for story in current)
        current = []
        current_key = None
        current_size = 0

    for story in ordered:
        key = _partition_key(story)
        oversize = (
            bool(budget_tokens) and current and current_size + story.size_tokens > budget_tokens
        )
        if current_key is not None and (key != current_key or oversize):
            flush()
        current.append(story)
        current_key = key
        current_size += story.size_tokens
    flush()
    return tuple(stamped), tuple(blocks)


# ── Pipeline ────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class PlanComputation:
    """The complete deterministic result of Zone C over one declared plan."""

    stories: tuple[PlannedStory, ...]
    blocks: tuple[Block, ...]
    defects: tuple[GraphDefect, ...]

    @property
    def fatal(self) -> tuple[GraphDefect, ...]:
        return tuple(defect for defect in self.defects if defect.fatal)

    @property
    def warnings(self) -> tuple[GraphDefect, ...]:
        return tuple(defect for defect in self.defects if not defect.fatal)


def compute_plan(
    stories: Iterable[PlannedStory],
    *,
    budget_tokens: int = DEFAULT_BLOCK_BUDGET_TOKENS,
) -> PlanComputation:
    """Verify, order, assign stack modes, and block a declared plan.

    Verification runs first and short-circuits: an inconsistent graph is not orderable, and a
    precise defect is more useful than a derived artifact built on a contradiction.
    """
    declared = tuple(stories)
    defects = verify_graph(declared)
    if any(defect.fatal for defect in defects):
        return PlanComputation(stories=declared, blocks=(), defects=defects)
    ordered = order_stories(declared)
    ordered, mode_defects = assign_stack_modes(ordered)
    stamped, blocks = group_blocks(ordered, budget_tokens=budget_tokens)
    return PlanComputation(stories=stamped, blocks=blocks, defects=defects + mode_defects)

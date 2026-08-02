"""How complete a planning response is, expressed as a number rather than a sentence.

A ``plan create`` response fails when the model's output budget runs out mid-emission. Recovering
from that needs one thing the pipeline did not have: a **ruler**. ``TOPOLOGY.md`` is emitted first
precisely so it survives a truncated tail (see :data:`plan_shape.OutputContract.leading`), which
means the count of what should exist outlives the bodies that do not.

This module turns that declaration plus the artifacts actually returned into a single deterministic
value. No LLM, no filesystem, no repair — the score only measures.

The score has exactly three consumers, and all three render the same object:

| Consumer | Rendering |
|---|---|
| Console progress | one line per continuation pass |
| The continuation prompt block | the score's *inverse* — what is still missing |
| The stall or failure message | ``PlanScore.render()`` in place of hand-written prose |

Progress is measured on **accepted**, never on remaining. A ratio against the declared count breaks
the moment a pending story splits and the denominator moves; a strictly increasing accepted count
is immune to that and needs no special case for splits.

Acceptance freezes an artifact irreversibly, so what admits one is deliberately narrow: it must be
declared, non-empty, and carry delimiter evidence that it was not cut. Content quality is not
judged here, and a repairable defect does not block — see :func:`artifact_defect`.
"""

from __future__ import annotations

from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass

from drydock.plan_graph import PlannedStory
from drydock.plan_shape import has_typed_heading

#: Blocks that are never a story artifact and never participate in the accepted count.
RESERVED_ARTIFACTS = frozenset({
    "TOPOLOGY.md",
    "MANIFEST.md",
    "DECISIONS.json",
    "PLAN_CREATE_ERROR.txt",
    "PLAN_CREATE_BLOCKED.txt",
})

#: Markdown artifacts exempt from the typed ``# Kind: Name`` heading requirement.
UNTYPED_ARTIFACTS = frozenset({"README.md", "METADATA.md"})

#: Label column width, so every rendered line's values align under one another.
_COLUMN = 11


@dataclass(frozen=True)
class ArtifactDefect:
    """One returned artifact that cannot be accepted, and why."""

    story_id: str
    filename: str
    reason: str

    def rendered(self) -> str:
        story = f"{self.story_id} -> " if self.story_id else ""
        return f"{story}{self.filename} ({self.reason})"


@dataclass(frozen=True)
class DeclaredArtifact:
    """One story artifact the declaration says must exist."""

    story_id: str
    filename: str

    def rendered(self) -> str:
        return f"{self.story_id} -> {self.filename}"


@dataclass(frozen=True)
class PlanScore:
    """How far a planning run got, as a comparable value.

    ``rank`` is the ordering used by the continuation loop. It is lexicographic on purpose: a run
    that has not parsed a topology is behind every run that has, regardless of how many loose
    artifacts it returned, because without the declaration there is no ruler to measure against.
    """

    topology_parsed: bool
    declared: tuple[DeclaredArtifact, ...]
    accepted: tuple[str, ...]
    invalid: tuple[ArtifactDefect, ...]
    undeclared: tuple[str, ...]
    manifest_serialized: bool

    @property
    def rank(self) -> tuple[int, int, int]:
        return (int(self.topology_parsed), len(self.accepted), int(self.manifest_serialized))

    @property
    def expected(self) -> int:
        return len(self.declared)

    @property
    def missing(self) -> tuple[DeclaredArtifact, ...]:
        done = frozenset(self.accepted)
        return tuple(item for item in self.declared if item.filename not in done)

    @property
    def is_complete(self) -> bool:
        """Whether every declared story has an accepted artifact."""
        return self.topology_parsed and bool(self.declared) and not self.missing

    def improved_on(self, previous: PlanScore | None) -> bool:
        """Whether this pass made progress. Splitting alone is not progress, by construction."""
        if previous is None:
            return True
        return len(self.accepted) > len(previous.accepted)

    def render(self) -> str:
        """The one rendering every consumer uses. Numbers first, detail after."""
        topology_note = (
            f"({self.expected} stories declared)"
            if self.topology_parsed
            else "(no declaration parsed)"
        )
        lines = [
            f"{'topology:':<{_COLUMN}}{int(self.topology_parsed)}  {topology_note}",
            f"{'specs:':<{_COLUMN}}{len(self.accepted)} / {self.expected}  accepted",
            f"{'manifest:':<{_COLUMN}}{int(self.manifest_serialized)}"
            + ("" if self.manifest_serialized else "  (not serialized)"),
        ]
        lines.extend(_labelled("missing", [item.rendered() for item in self.missing]))
        lines.extend(_labelled("invalid", [item.rendered() for item in self.invalid]))
        lines.extend(_labelled("undeclared", list(self.undeclared)))
        return "\n".join(lines)

    def progress_line(self) -> str:
        """The single-line console form, one per continuation pass."""
        return (
            f"topology {int(self.topology_parsed)} · "
            f"specs {len(self.accepted)}/{self.expected} · "
            f"manifest {int(self.manifest_serialized)}"
        )

    def progress_block(self, *, stage: str, result: str) -> str:
        """Render the user-facing score after one planning stage or LLM batch."""
        width = 72
        return "\n".join((
            "=" * width,
            f"PLAN PROGRESS  ·  {stage}",
            "=" * width,
            f"Topology Created:  {self.topology_parsed}",
            f"Blueprints Created: {len(self.accepted)} / {self.expected}",
            f"Manifest Created:  {self.manifest_serialized}",
            f"Blueprints Remaining: {len(self.missing)}",
            f"Batch Result:       {result}",
            "=" * width,
            "",
        ))


def _labelled(label: str, items: Sequence[str]) -> list[str]:
    """One label, one item per line, values aligned in the shared column."""
    if not items:
        return []
    head = f"{label}:".ljust(_COLUMN)
    return [head + items[0]] + [" " * _COLUMN + item for item in items[1:]]


def artifact_defect(name: str, body: str, *, require_typed_heading: bool = False) -> str | None:
    """Why ``name`` cannot be accepted, or ``None`` when its shape is sound.

    Structural only. This never judges whether the content is *good*, only whether it is whole
    enough to freeze — because an accepted artifact is never revisited.

    The typed-heading check is **off by default, deliberately.** A missing ``# Kind: Name`` heading
    is a real defect but a repairable one, which is why ``plan_shape.PLAN_SHAPE_ADVISORY`` reports
    it rather than refusing the plan; ``conform_specs`` is the existing pass that fixes it. It is
    also a poor truncation detector — the heading is the first line of a specification, so a cut
    tail never removes it. Gating acceptance on it would spend a continuation pass re-authoring
    complete work. Truncation is detected by delimiter evidence instead, which is what actually
    proves a cut.
    """
    if not body.strip():
        return "artifact body is empty"
    if (
        require_typed_heading
        and name.lower().endswith(".md")
        and name not in UNTYPED_ARTIFACTS
        and not has_typed_heading(body)
    ):
        return "no typed '# Kind: Name' heading"
    return None


def score_plan(
    declared: Sequence[PlannedStory],
    blocks: Mapping[str, str],
    *,
    topology_parsed: bool = True,
    damaged: Collection[str] = (),
    manifest_serialized: bool = False,
    require_typed_headings: bool = False,
) -> PlanScore:
    """Measure returned artifacts against the declaration.

    ``damaged`` names artifacts whose delimiters the caller already found unpaired. They are
    reported as invalid rather than accepted, and stay eligible for replacement by a later pass.
    """
    declarations = tuple(
        DeclaredArtifact(story.story_id, story.implements.strip())
        for story in declared
        if story.implements.strip()
    )
    owner = {item.filename: item.story_id for item in declarations}
    damaged_names = frozenset(damaged)

    accepted: list[str] = []
    invalid: list[ArtifactDefect] = []
    undeclared: list[str] = []

    for name, body in blocks.items():
        if name in RESERVED_ARTIFACTS:
            continue
        if name not in owner:
            undeclared.append(name)
            continue
        story_id = owner[name]
        if name in damaged_names:
            invalid.append(ArtifactDefect(story_id, name, "unpaired artifact delimiters"))
            continue
        reason = artifact_defect(name, body, require_typed_heading=require_typed_headings)
        if reason is not None:
            invalid.append(ArtifactDefect(story_id, name, reason))
            continue
        accepted.append(name)

    return PlanScore(
        topology_parsed=topology_parsed,
        declared=declarations,
        accepted=tuple(accepted),
        invalid=tuple(invalid),
        undeclared=tuple(undeclared),
        manifest_serialized=manifest_serialized,
    )

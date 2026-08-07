"""Blast radius of a source-driven change, computed from the story graph.

Two questions have to be answered before a refit writes anything, and the graph already holds the
evidence for both. Neither uses an LLM.

**Does this change invalidate downstream work?** Only if it alters a foundational story's
*contract* — what consumers use — rather than how the service is built. Renaming a config value,
adding an index, or raising a timeout stays inside the builder. Changing the shape of what the
service provides can invalidate everything that consumes it, and that cannot be repaired by a
ticket because the blast radius is the whole consumer set. The classification is a judgement the
router makes and is not stable between runs, so this reports and never blocks: the Commander
decides whether to rebuild downstream now or defer it. The deterministic half — *who* consumes a
given provision — comes from the graph and is reliable.

**Does this change break the build outright?** Deleting a provision that another live story still
consumes does. That is not a judgement call and not something a ticket can fix: the specification
has to stop using the deleted service first. This blocks, before any file is written.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass

#: Blueprints whose stories define the shape every other story builds against.
FOUNDATIONAL_STORY_TYPES = frozenset({"foundational"})


@dataclass(frozen=True)
class StoryFacts:
    """The graph facts one story contributes, independent of Manifest node plumbing."""

    story_id: str
    implements: str = ""
    story_type: str = ""
    provides: tuple[str, ...] = ()
    consumes: tuple[str, ...] = ()


@dataclass(frozen=True)
class Impact:
    foundational: tuple[str, ...] = ()
    contract_changed: tuple[str, ...] = ()
    downstream: tuple[tuple[str, str], ...] = ()
    broken: tuple[tuple[str, str], ...] = ()

    def blocks(self) -> bool:
        return bool(self.broken)

    def notable(self) -> bool:
        return bool(self.downstream or self.broken)


def _normalize(value: str) -> str:
    """Provisions are free text, so compare them insensitively to case, spacing and punctuation.

    A renamed provision still reads as a deletion plus an addition. Over-reporting is the safe
    direction here: a spurious downstream notice costs a glance, a missed one costs a broken build.
    """
    return re.sub(r"[^a-z0-9]+", " ", value.casefold()).strip()


def _values(field: object) -> tuple[str, ...]:
    if isinstance(field, tuple):
        return tuple(item.strip() for item in field if str(item).strip())
    text = str(field or "").strip()
    if not text:
        return ()
    return tuple(item.strip() for item in text.split(",") if item.strip())


def facts_from_manifest(blocks: Iterable[object]) -> tuple[StoryFacts, ...]:
    """Read the graph facts this module needs out of Manifest story nodes."""
    facts: list[StoryFacts] = []
    for node in blocks:
        if getattr(node, "block_type", "") != "story":
            continue
        fields: Mapping[str, object] = getattr(node, "fields", {}) or {}
        implements = _values(fields.get("implements"))
        facts.append(
            StoryFacts(
                story_id=getattr(node, "block_id", ""),
                implements=implements[0] if implements else "",
                story_type=str(fields.get("type", "") or "").strip().casefold(),
                provides=_values(fields.get("provides")),
                consumes=_values(fields.get("consumes")),
            )
        )
    return tuple(facts)


def consumers_of(
    provision: str, facts: Sequence[StoryFacts], *, exclude: Sequence[str] = ()
) -> tuple[str, ...]:
    """Every story consuming ``provision``, excluding the named stories."""
    wanted = _normalize(provision)
    excluded = set(exclude)
    return tuple(
        fact.story_id
        for fact in facts
        if fact.story_id not in excluded
        and any(_normalize(item) == wanted for item in fact.consumes)
    )


def analyse(
    routed: Sequence[StoryFacts],
    existing: Sequence[StoryFacts],
    *,
    contract_changed: Sequence[str] = (),
    deleted_provisions: Sequence[str] = (),
) -> Impact:
    """Compute the blast radius of a routed change set.

    ``routed`` are the stories this refit proposes; ``existing`` is the current graph.
    ``contract_changed`` names routed stories the router judged to alter a consumer contract.
    ``deleted_provisions`` names provisions the delta removes outright.
    """
    routed_ids = [fact.story_id for fact in routed]
    by_id = {fact.story_id: fact for fact in routed}

    # A routed story is foundational either by its own declared type or by amending a Blueprint
    # whose existing stories are foundational.
    foundational_blueprints = {
        fact.implements for fact in existing if fact.story_type in FOUNDATIONAL_STORY_TYPES
    }
    foundational = tuple(
        fact.story_id
        for fact in routed
        if fact.story_type in FOUNDATIONAL_STORY_TYPES or fact.implements in foundational_blueprints
    )

    changed = tuple(story_id for story_id in contract_changed if story_id in by_id)
    downstream: list[tuple[str, str]] = []
    for story_id in changed:
        for provision in by_id[story_id].provides or _provides_of_blueprint(
            by_id[story_id].implements, existing
        ):
            for consumer in consumers_of(provision, existing, exclude=routed_ids):
                downstream.append((consumer, provision))

    broken: list[tuple[str, str]] = []
    for provision in deleted_provisions:
        for consumer in consumers_of(provision, existing, exclude=routed_ids):
            broken.append((provision, consumer))

    return Impact(
        foundational=foundational,
        contract_changed=changed,
        downstream=tuple(dict.fromkeys(downstream)),
        broken=tuple(dict.fromkeys(broken)),
    )


def _provides_of_blueprint(blueprint: str, existing: Sequence[StoryFacts]) -> tuple[str, ...]:
    """What the existing stories for a Blueprint provide.

    A routed story that amends a contract usually restates the provision rather than redeclaring
    it, so fall back to what the parent already provides.
    """
    provisions: list[str] = []
    for fact in existing:
        if fact.implements == blueprint:
            provisions.extend(fact.provides)
    return tuple(dict.fromkeys(provisions))


def render_notice(impact: Impact) -> str:
    """Operator-facing summary. Empty when there is nothing worth saying."""
    lines: list[str] = []
    if impact.downstream:
        lines.append("Contract change — the following stories consume what changed:")
        lines.extend(
            f"  {consumer}  (consumes: {provision})" for consumer, provision in impact.downstream
        )
        lines.append("  Rebuild them or defer; the build is not gated on this.")
    if impact.broken:
        lines.append("Deletion breaks live consumers:")
        lines.extend(
            f"  {consumer}  (consumes deleted: {provision})"
            for provision, consumer in impact.broken
        )
    return "\n".join(lines)


def blocking_message(impact: Impact) -> str:
    consumers = ", ".join(sorted({consumer for _, consumer in impact.broken}))
    provisions = ", ".join(sorted({provision for provision, _ in impact.broken}))
    return (
        f"Deleting {provisions} would break {consumers}. "
        "Update the specification to stop using it, re-import, and refit again."
    )

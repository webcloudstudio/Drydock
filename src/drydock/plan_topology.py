"""The model's topology declaration, and its deterministic projection into ``MANIFEST.md``.

Zone B authors judgment: what each story is, what it requires, what it provides, which phase it
belongs to, and its programmatic acceptance. It emits that as a **declaration** — transient, part
of the response — and never as a sorted, grouped, position-bearing plan. Zone C parses the
declaration here, hands it to :mod:`drydock.plan_graph` for verification, ordering, stack-mode
assignment, and blocking, then serializes the computed result.

The discriminator for where a fact lives: **does the fact describe the artifact or the schedule?**

| Fact | Home | Why |
|---|---|---|
| ``Provides``, ``Consumes``, ``Depends On`` | Blueprint header | Describe the file — what it offers and requires |
| Story ``type`` | Manifest | Computed, machine-focused |
| ``Phase`` | Manifest | Describes when the file is built, not the file |
| Programmatic Acceptance | Manifest | Machine-focused; nobody should hand-edit it |
| User Acceptance, ``## Questions`` | Blueprint | Human intent |

``Phase`` never touches disk in the Blueprint. Programmatic Acceptance is executable assertions
carrying pass/fail state and is regenerated wholly by every plan run; User Acceptance is
human-readable intent and stays in the Blueprint specification. Splitting by audience gives each
one home and removes the duplication of the same fact in both files.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass

from drydock.errors import SpecificationError
from drydock.plan_graph import (
    DELIVERY_KINDS,
    STORY_TYPES,
    Block,
    PlannedStory,
)

#: The block name the model wraps its topology declaration in.
TOPOLOGY_BLOCK = "TOPOLOGY.md"

_STORY_HEADER_RE = re.compile(r"^##\s+story\s+(?P<id>[^\s:][^:]*?)\s*$", re.IGNORECASE)
_FIELD_RE = re.compile(r"^(?P<field>[A-Za-z][A-Za-z0-9_-]*):\s*(?P<value>.*)$")
_TRUE = frozenset({"yes", "true", "1", "y"})

_LIST_FIELDS = frozenset({"depends", "provides", "consumes", "stack"})
#: Interface points are comma-separated only: a route such as ``GET /health`` contains a space.
_COMMA_ONLY_FIELDS = frozenset({"provides", "consumes"})
#: Fields carried verbatim into the Manifest story block without deterministic interpretation.
_PASSTHROUGH_FIELDS = (
    "summary",
    "implements",
    "covers",
    "accepts",
    "context",
    "rules",
    "instructions",
)

#: Fields the declaration may write as a ``field: |`` block scalar. ``instructions`` is prose the
#: build engine requires, and it does not fit one line.
_BLOCK_SCALAR_FIELDS = frozenset({"instructions"})


@dataclass(frozen=True)
class TopologyDefect:
    """One malformed declaration, located by story id and field."""

    story_id: str
    message: str

    def rendered(self) -> str:
        where = f"story {self.story_id}: " if self.story_id else ""
        return f"{where}{self.message}"


def _split_list(value: str) -> tuple[str, ...]:
    if "," in value:
        return tuple(part.strip() for part in value.split(",") if part.strip())
    return tuple(part for part in value.split() if part)


def _split_interfaces(value: str) -> tuple[str, ...]:
    """Split an interface list on commas only — ``GET /health`` is one entry, not two."""
    return tuple(part.strip() for part in value.split(",") if part.strip())


def _consume_block_scalar(lines: Sequence[str], start: int) -> tuple[str, int]:
    """Consume an indented ``field: |`` body, returning its dedented text and the next index.

    The body runs until the first non-blank line at column zero, so a following field line or
    ``## story`` heading ends it. Common indentation is stripped: the declaration's indentation
    is presentation, and the Manifest renderer applies its own.
    """
    body: list[str] = []
    index = start
    while index < len(lines):
        raw = lines[index]
        if raw.strip() and not raw[:1].isspace():
            break
        body.append(raw)
        index += 1
    while body and not body[-1].strip():
        body.pop()
    indents = [len(line) - len(line.lstrip()) for line in body if line.strip()]
    pad = min(indents) if indents else 0
    return "\n".join(line[pad:].rstrip() for line in body), index


def _parse_phase(raw: str) -> int | None:
    try:
        return int(raw.strip())
    except (TypeError, ValueError):
        return None


def parse_topology(text: str) -> tuple[tuple[PlannedStory, ...], tuple[TopologyDefect, ...]]:
    """Parse a topology declaration into declared stories.

    Each story is one ``## story <id>`` heading followed by ``field: value`` lines. Only the
    declaration is read here: nothing is sorted, grouped, or repositioned, and a story's place in
    the text carries no meaning beyond breaking ties in :func:`plan_graph.order_stories`.
    """
    stories: list[PlannedStory] = []
    defects: list[TopologyDefect] = []
    current_id: str | None = None
    values: dict[str, str] = {}

    def flush() -> None:
        nonlocal current_id, values
        if current_id is None:
            return
        story_type = (values.get("type", "") or "service").strip().lower()
        if story_type not in STORY_TYPES:
            defects.append(
                TopologyDefect(
                    current_id,
                    f"type {story_type!r} is not one of {', '.join(STORY_TYPES)}",
                )
            )
            story_type = "service"
        kind = (values.get("kind", "") or "capability").strip().lower()
        if kind not in DELIVERY_KINDS:
            defects.append(
                TopologyDefect(
                    current_id,
                    f"kind {kind!r} is not one of {', '.join(DELIVERY_KINDS)}",
                )
            )
            kind = "capability"
        phase = _parse_phase(values.get("phase", "1"))
        if phase is None:
            defects.append(
                TopologyDefect(current_id, f"phase {values.get('phase', '')!r} is not an integer")
            )
            phase = 1
        stories.append(
            PlannedStory(
                story_id=current_id,
                name=values.get("summary", "").strip() or current_id,
                story_type=story_type,
                phase=phase,
                delivery_kind=kind,
                acceptance_contract=values.get("acceptance", "").strip().lower() in _TRUE,
                implements=values.get("implements", "").strip(),
                depends=_split_list(values.get("depends", "")),
                provides=_split_interfaces(values.get("provides", "")),
                consumes=_split_interfaces(values.get("consumes", "")),
                stack=_split_list(values.get("stack", "")),
                fields={
                    key: values[key] for key in _PASSTHROUGH_FIELDS if values.get(key, "").strip()
                },
            )
        )
        current_id = None
        values = {}

    lines = text.splitlines()
    index = 0
    while index < len(lines):
        stripped = lines[index].strip()
        header = _STORY_HEADER_RE.match(stripped)
        if header:
            flush()
            current_id = header.group("id").strip()
            index += 1
            continue
        if current_id is None:
            index += 1
            continue
        match = _FIELD_RE.match(stripped)
        if match:
            field_name = match.group("field").strip().lower()
            value = match.group("value").strip()
            if value == "|" and field_name in _BLOCK_SCALAR_FIELDS:
                body, index = _consume_block_scalar(lines, index + 1)
                if field_name not in values:
                    values[field_name] = body
                continue
            if field_name in _LIST_FIELDS or field_name not in values:
                values[field_name] = value
        index += 1
    flush()

    if not stories:
        defects.append(TopologyDefect("", "the topology declaration contains no stories"))
    return tuple(stories), tuple(defects)


def parse_topology_strict(text: str) -> tuple[PlannedStory, ...]:
    """Parse a declaration, raising :class:`SpecificationError` on any defect."""
    stories, defects = parse_topology(text)
    if defects:
        raise SpecificationError(
            "Plan topology declaration is malformed:\n  "
            + "\n  ".join(defect.rendered() for defect in defects)
        )
    return stories


# ── Manifest serialization ──────────────────────────────────────────────────────────


def _node_list(node: object, name: str) -> tuple[str, ...]:
    value = getattr(node, "fields", {}).get(name, ())
    if isinstance(value, tuple):
        return tuple(str(item) for item in value if str(item).strip())
    text = str(value).strip()
    if not text:
        return ()
    return _split_interfaces(text) if name in _COMMA_ONLY_FIELDS else _split_list(text)


def stories_from_manifest(blocks: Sequence[object]) -> tuple[PlannedStory, ...]:
    """Project Manifest story nodes back into the deterministic planning model.

    Only nodes carrying a ``type:`` participate: the field is what marks a block as belonging to
    the story taxonomy rather than the legacy ``feature``/``story``/``spike``/``ac`` taxonomy, so
    a Manifest written before the restructure projects to an empty set and is left alone.
    """
    stories: list[PlannedStory] = []
    for node in blocks:
        story_type = str(getattr(node, "story_type", "") or "").strip().lower()
        if story_type not in STORY_TYPES:
            continue
        stories.append(
            PlannedStory(
                story_id=str(getattr(node, "block_id", "")),
                name=str(getattr(node, "name", "")),
                story_type=story_type,
                phase=int(getattr(node, "phase", 0) or 1),
                delivery_kind=str(getattr(node, "delivery_kind", "") or "capability"),
                acceptance_contract=bool(getattr(node, "has_acceptance_contract", False)),
                implements=", ".join(_node_list(node, "implements")),
                depends=tuple(str(dep) for dep in getattr(node, "depends", ())),
                provides=_node_list(node, "provides"),
                consumes=_node_list(node, "consumes"),
                stack=_node_list(node, "stack"),
            )
        )
    return tuple(stories)


#: Marker written into an over-target story's Manifest block. Over-target work is planned and
#: built; the marker is how the Commander sees the cost before spending it.
OVER_TARGET_MARKER = "over-target"


def computed_field_updates(
    stories: Sequence[PlannedStory],
) -> dict[str, dict[str, str | None]]:
    """Return the per-story Manifest updates carrying Zone C's computed schedule fields.

    ``size`` is the measured single-build-pass cost in tokens and ``budget`` carries
    ``over-target`` when that cost exceeds the target. Both are markers: nothing downstream
    refuses a story for either value.
    """
    return {
        story.story_id: {
            "stack_mode": story.stack_mode or None,
            "block": str(story.block),
            "size": str(story.size_tokens) if story.size_tokens else None,
            "budget": OVER_TARGET_MARKER if story.over_target else None,
        }
        for story in stories
    }


def _render_list(values: Sequence[str]) -> str:
    return ", ".join(values)


def render_story_block(story: PlannedStory, number: int) -> str:
    """Render one computed story as a Manifest block.

    ``type``, ``phase``, ``block``, and ``stack_mode`` are computed properties of the schedule and
    appear only here. ``depends`` is the declared edge set, re-emitted in the computed order.
    """
    lines = [
        f"## story {number}: {story.name or story.story_id}",
        f"id:           {story.story_id}",
    ]
    if story.fields.get("summary"):
        lines.append(f"summary:      {story.fields['summary']}")
    lines.append(f"type:         {story.story_type}")
    lines.append(f"kind:         {story.delivery_kind}")
    lines.append(f"phase:        {story.phase}")
    lines.append(f"block:        {story.block}")
    if story.implements:
        lines.append(f"implements:   {story.implements}")
    for key in ("covers", "accepts", "context", "rules"):
        if story.fields.get(key):
            lines.append(f"{key + ':':<14}{story.fields[key]}")
    if story.fields.get("instructions"):
        # Block scalar, two-space body: the form ``build_plan`` reads, and the reason its field
        # scan inspects column-zero lines only.
        lines.append("instructions: |")
        lines.extend(
            f"  {body_line}" if body_line.strip() else ""
            for body_line in str(story.fields["instructions"]).splitlines()
        )
    if story.stack:
        lines.append(f"stack:        {_render_list(story.stack)}")
    if story.stack_mode:
        lines.append(f"stack_mode:   {story.stack_mode}")
    if story.size_tokens:
        lines.append(f"size:         {story.size_tokens}")
    if story.over_target:
        lines.append(f"budget:       {OVER_TARGET_MARKER}")
    if story.provides:
        lines.append(f"provides:     {_render_list(story.provides)}")
    if story.consumes:
        lines.append(f"consumes:     {_render_list(story.consumes)}")
    if story.depends:
        lines.append(f"depends:      {_render_list(story.depends)}")
    lines.append(f"acceptance:   {'yes' if story.acceptance_contract else 'no'}")
    lines.append("state:        pending")
    return "\n".join(lines)


def render_manifest(
    project: str,
    stories: Sequence[PlannedStory],
    blocks: Sequence[Block],
    *,
    updated: str = "",
) -> str:
    """Serialize the computed plan. Ordering and serialization are Python's job, never the model's."""
    header = [f"# MANIFEST: {project}"]
    if updated:
        header.append(f"updated:     {updated}")
    header.append(f"blocks:      {len(blocks)}")
    body = [render_story_block(story, index) for index, story in enumerate(stories, start=1)]
    return "\n".join(header) + "\n\n" + "\n\n".join(body) + "\n"

"""Route an imported source delta into Manifest stories.

One LLM call decomposes the whole delta, symmetric with planning: plan decomposes the entire
source into stories, refit decomposes what changed. Everything else here is deterministic — the
module decides filenames, numbering, ordering, phases, and what is allowed to reach disk. The
model supplies judgement about *what the change means*, and nothing else.

The validation gates all run before any file is written, because a partial refit leaves the graph
describing work that was never authorized. In particular a requirement that seats on no existing
Blueprint fails the whole command: refit only ever appends to the graph, and creating a Blueprint
changes the graph's shape, its dependency order, and what the build considers frozen. That is a
replan.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from drydock import change_ticket
from drydock.change_ticket import SCOPES, scope_for_delta
from drydock.errors import SpecificationError
from drydock.lineage_attribution import parse_tag_blocks
from drydock.manifest import DrydockManifest

PROMPT_NAME = "refit_sources_route"

_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")
_EXCLUDED_BLUEPRINTS = frozenset({"COMPASS.md", "MANIFEST.md"})


@dataclass(frozen=True)
class RoutedStory:
    id: str
    implements: str
    scope: str
    summary: str
    requirement: str = ""
    depends: tuple[str, ...] = ()
    sections: tuple[str, ...] = ()
    contract_changed: bool = False


@dataclass(frozen=True)
class RoutedRequirement:
    name: str
    text: str


@dataclass(frozen=True)
class Unseatable:
    requirement: str
    reason: str


@dataclass(frozen=True)
class RouteProposal:
    requirements: tuple[RoutedRequirement, ...] = ()
    stories: tuple[RoutedStory, ...] = ()
    unseatable: tuple[Unseatable, ...] = ()
    deleted_provisions: tuple[str, ...] = ()


def blueprint_names(blueprint_dir: Path) -> tuple[str, ...]:
    """Blueprints a story may implement: authored specs only, never compacts or governance."""
    if not blueprint_dir.is_dir():
        return ()
    return tuple(
        sorted(
            path.name
            for path in blueprint_dir.glob("*.md")
            if path.name not in _EXCLUDED_BLUEPRINTS and not path.name.endswith("_compact.md")
        )
    )


def render_graph(manifest: DrydockManifest) -> str:
    lines: list[str] = []
    for node in manifest.blocks:
        if node.block_type != "story":
            continue
        attrs = [f'id="{node.block_id}"']
        for key in ("implements", "provides", "consumes", "depends"):
            value = node.fields.get(key, "")
            if isinstance(value, tuple):
                value = ", ".join(value)
            if str(value).strip():
                attrs.append(f'{key}="{value}"')
        lines.append(f"  <story {' '.join(attrs)}/>")
    return "\n".join(lines)


def render_blueprints(blueprint_dir: Path, names: Sequence[str]) -> str:
    """Inject the compact form when one exists; it is what the compaction step exists to provide.

    The authored file's section headings are injected alongside it either way. An amending story
    must name the headings it supersedes in the authored Blueprint's exact wording, and the
    compact form is a prose digest that carries no headings at all — so a model given only the
    compact can do nothing but invent plausible ones, which
    :func:`drydock.change_ticket.validate_amended_sections` then rejects, failing the whole refit.
    Naming the closed set removes the guess.
    """
    blocks: list[str] = []
    for name in names:
        authored = blueprint_dir / name
        compact = blueprint_dir / f"{Path(name).stem}_compact.md"
        source = compact if compact.is_file() else authored
        try:
            text = source.read_text(encoding="utf-8", errors="replace").strip()
        except OSError:
            continue
        sections = ()
        try:
            sections = change_ticket.parent_sections(authored.read_text(encoding="utf-8"))
        except OSError:
            pass
        attrs = f' sections="{", ".join(sections)}"' if sections else ""
        blocks.append(f'  <blueprint name="{name}"{attrs}>\n{text}\n  </blueprint>')
    return "\n".join(blocks)


def assemble_route_prompt(
    body: str,
    *,
    diffs: Sequence[tuple[str, str, str | None, str]],
    manifest: DrydockManifest,
    blueprint_dir: Path,
    names: Sequence[str],
) -> str:
    """Build the routing job deterministically.

    ``diffs`` is ``(source path, head commit, base commit, diff text)`` per changed source.
    """
    diff_blocks = "\n\n".join(
        f'<diff source="{source}" base="{base or "(none)"}" head="{head}">\n{text.strip()}\n</diff>'
        for source, head, base, text in diffs
    )
    return (
        f"{body}\n\n"
        "# Routing job\n\n"
        f"{diff_blocks}\n\n"
        f"<graph>\n{render_graph(manifest)}\n</graph>\n\n"
        f"<blueprints>\n{render_blueprints(blueprint_dir, names)}\n</blueprints>\n"
    )


def _split(value: str) -> tuple[str, ...]:
    return tuple(item.strip() for item in value.split(",") if item.strip())


def parse_route_output(text: str) -> RouteProposal:
    requirements: list[RoutedRequirement] = []
    stories: list[RoutedStory] = []
    unseatable: list[Unseatable] = []
    deleted: list[str] = []
    blocks = parse_tag_blocks(
        text, names=frozenset({"requirement", "story", "unseatable", "deleted"})
    )
    for block in blocks:
        if block.name == "requirement":
            name = block.attrs.get("name", "").strip()
            if name:
                requirements.append(RoutedRequirement(name, block.text))
        elif block.name == "story":
            story_id = block.attrs.get("id", "").strip()
            implements = block.attrs.get("implements", "").strip()
            if not story_id or not implements:
                continue
            stories.append(
                RoutedStory(
                    id=story_id,
                    implements=implements,
                    scope=block.attrs.get("scope", "").strip().casefold() or "amending",
                    summary=block.text,
                    requirement=block.attrs.get("requirement", "").strip(),
                    depends=_split(block.attrs.get("depends", "")),
                    sections=_split(block.attrs.get("sections", "")),
                    contract_changed=block.attrs.get("contract", "").strip().casefold()
                    == "changed",
                )
            )
        elif block.name == "unseatable":
            requirement = block.attrs.get("requirement", "").strip()
            unseatable.append(Unseatable(requirement, block.text))
        elif block.name == "deleted":
            provision = block.attrs.get("provides", "").strip()
            if provision:
                deleted.append(provision)
    return RouteProposal(
        tuple(requirements), tuple(stories), tuple(unseatable), tuple(dict.fromkeys(deleted))
    )


def _resolve_collisions(
    stories: Sequence[RoutedStory], existing_ids: Sequence[str]
) -> tuple[RoutedStory, ...]:
    """Suffix colliding ids and rewrite every sibling reference to the new name.

    Replacing an existing story would silently discard verified work, so a collision renames the
    incoming story instead.
    """
    taken = set(existing_ids)
    renames: dict[str, str] = {}
    resolved_ids: list[str] = []
    for story in stories:
        candidate = story.id
        suffix = 2
        while candidate in taken:
            candidate = f"{story.id}-{suffix}"
            suffix += 1
        if candidate != story.id:
            renames[story.id] = candidate
        taken.add(candidate)
        resolved_ids.append(candidate)
    if not renames:
        return tuple(stories)
    return tuple(
        RoutedStory(
            id=new_id,
            implements=story.implements,
            scope=story.scope,
            summary=story.summary,
            requirement=story.requirement,
            depends=tuple(renames.get(item, item) for item in story.depends),
            sections=story.sections,
            contract_changed=story.contract_changed,
        )
        for story, new_id in zip(stories, resolved_ids, strict=True)
    )


def _detect_cycle(stories: Sequence[RoutedStory]) -> tuple[str, ...]:
    """Cycle detection across the newly routed stories only; existing edges are already acyclic."""
    edges = {
        story.id: [dep for dep in story.depends if dep in {s.id for s in stories}]
        for story in stories
    }
    state: dict[str, int] = {}
    path: list[str] = []

    def visit(node: str) -> tuple[str, ...]:
        state[node] = 1
        path.append(node)
        for dependency in edges.get(node, ()):
            if state.get(dependency) == 1:
                return tuple(path[path.index(dependency) :] + [dependency])
            if state.get(dependency, 0) == 0:
                found = visit(dependency)
                if found:
                    return found
        path.pop()
        state[node] = 2
        return ()

    for story in stories:
        if state.get(story.id, 0) == 0:
            cycle = visit(story.id)
            if cycle:
                return cycle
    return ()


def validate_route(
    proposal: RouteProposal,
    *,
    manifest: DrydockManifest,
    blueprint_dir: Path,
    deltas: Mapping[str, str] | None = None,
) -> tuple[RoutedStory, ...]:
    """Reject anything that must not reach disk. Raises before the first write."""
    if proposal.unseatable:
        details = "; ".join(
            f"{item.requirement or 'requirement'}: {item.reason}" for item in proposal.unseatable
        )
        raise SpecificationError(
            f"Replan required — no Blueprint owns this change: {details}\n"
            "  drydock refit never creates a Blueprint. Run: drydock plan <Target>"
        )
    if not proposal.stories:
        raise SpecificationError("Source routing produced no stories")

    allowed = set(blueprint_names(blueprint_dir))
    for story in proposal.stories:
        if story.implements not in allowed:
            raise SpecificationError(
                f"Routing named a Blueprint that does not exist: {story.implements}\n"
                "  drydock refit never creates a Blueprint. Run: drydock plan <Target>"
            )
        if not _ID_RE.match(story.id):
            raise SpecificationError(f"Routed story id is not a valid slug: {story.id}")
        if story.scope not in SCOPES:
            raise SpecificationError(f"Routed story {story.id} has unknown scope: {story.scope}")

    existing_ids = [node.block_id for node in manifest.blocks]
    stories = _resolve_collisions(proposal.stories, existing_ids)

    known = set(existing_ids) | {story.id for story in stories}
    for story in stories:
        unknown = [dep for dep in story.depends if dep not in known]
        if unknown:
            raise SpecificationError(
                f"Routed story {story.id} depends on unknown story id(s): {', '.join(unknown)}"
            )
    cycle = _detect_cycle(stories)
    if cycle:
        raise SpecificationError(f"Routed stories form a dependency cycle: {' -> '.join(cycle)}")

    # A requirement the router named but seated nowhere would silently vanish from the delta.
    routed_requirements = {story.requirement for story in stories if story.requirement}
    missing = [
        requirement.name
        for requirement in proposal.requirements
        if requirement.name not in routed_requirements
    ]
    if missing:
        raise SpecificationError(
            f"Routing left requirement(s) unrouted and unseatable: {', '.join(missing)}"
        )

    if deltas:
        for story in stories:
            expected = scope_for_delta(deltas.get(story.requirement))
            if expected == "amending" and story.scope == "additive" and story.sections:
                raise SpecificationError(
                    f"Routed story {story.id} claims additive scope but names amended sections"
                )
    return stories


def assign_schedule(
    stories: Sequence[RoutedStory], manifest: DrydockManifest
) -> dict[str, dict[str, str]]:
    """Place new stories after what they depend on. Regenerated wholly by the next plan run."""
    phases = {
        node.block_id: int(str(node.fields.get("phase", "") or 0) or 0)
        for node in manifest.blocks
        if node.block_type == "story"
    }
    blocks = [
        int(str(node.fields.get("block", "") or 0) or 0)
        for node in manifest.blocks
        if node.block_type == "story"
    ]
    next_block = max(blocks, default=0) + 1
    schedule: dict[str, dict[str, str]] = {}
    for story in stories:
        parent_phases = [phases.get(dep, 0) for dep in story.depends]
        parent_phases.extend(
            phases.get(node.block_id, 0)
            for node in manifest.blocks
            if node.block_type == "story" and node.fields.get("implements") == story.implements
        )
        phase = max([*parent_phases, 1])
        phases[story.id] = phase
        schedule[story.id] = {"phase": str(phase), "block": str(next_block)}
    return schedule


def route_requirements(
    diffs: Sequence[tuple[str, str, str | None, str]],
    manifest: DrydockManifest,
    blueprint_dir: Path,
    *,
    runner: Callable[..., object] | None = None,
    log_dir: Path | None = None,
    model: str | None = None,
    llm_provider: str | None = None,
    target: str | None = None,
) -> RouteProposal:
    """One call for the whole delta."""
    from drydock.llm import run_prompt
    from drydock.prompts import load_prompt

    prompt = load_prompt(PROMPT_NAME)
    run = runner if runner is not None else run_prompt
    assembled = assemble_route_prompt(
        prompt.body,
        diffs=diffs,
        manifest=manifest,
        blueprint_dir=blueprint_dir,
        names=blueprint_names(blueprint_dir),
    )
    result = run(
        assembled,
        blueprint_dir,
        llm=llm_provider,
        model=model or prompt.model,
        command_name=PROMPT_NAME,
        parameters={"sources": [source for source, _, _, _ in diffs]},
        log_dir=log_dir,
        target=target,
    )
    if not getattr(result, "ok", False) or not str(getattr(result, "text", "")).strip():
        raise SpecificationError("Source routing failed: LLM execution produced no output")
    return parse_route_output(str(result.text))

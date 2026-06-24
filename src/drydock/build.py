"""Build-step assembly — the single deterministic prompt/cost subroutine.

A build *step* is one executable MANIFEST.md block (a ``story`` or ``spike``).
``assemble_step`` resolves everything that block stacks into its build prompt —
the per-step ``COMPASS.md``, the ``implements:`` spec files, the resolved
``context:`` support files, the ``stack:`` guidance, the ``rules:`` governance,
and the block's ``instructions:`` — and reports the byte and story-point cost of
the whole stack.

One assembler, two callers. ``drydock build`` renders the resolved parts into a
single prompt and executes it; the QuarterDeck compass sums the same parts to
show each step's true token cost. Cost and build can never diverge because they
read the same assembly.

Story points are the token estimate (``ceil(bytes / 4)``), derived on demand and
never written back. A step whose total exceeds ``PROMPT_WARN_KB`` is flagged
``over_warn``: it stacks more context than is reliably built in one prompt.

Compact substitution: stack files have ``*_compact.md`` derivatives that contain
only the caller-facing surface (types, config, contracts). The first story to use
a stack file receives the full version; subsequent stories receive the compact
sibling when one exists. ``assemble_steps`` tracks the first-use set and passes
``compact_stack`` to each ``assemble_step`` call. ``build_run`` uses the applied
registry from the manifest instead of a forward-scan set.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from pathlib import Path

from drydock.build_plan import BuildPlan, PlanBlock
from drydock.prompt_assembly import (
    PromptAssembly,
    contextual_markdown_parts,
    lines_part,
    part,
    section_heading_part,
    system_preamble_part,
)
from drydock.prompt_headers import prompt_header_for_file


def story_points_for(byte_count: int) -> int:
    """Story points = estimated token cost = ``ceil(byte_count / 4)``.

    The token estimate and the story-point count are one number: a token is
    ~4 bytes, so there is a single derived unit, not two.
    """
    return math.ceil(byte_count / 4)


# Maximum total context size for one build step before it is flagged. The
# stacking strategy groups similar work to stay under this ceiling.
PROMPT_WARN_KB = 50

# Manifest block types that are executable build steps. Features group; ac blocks
# fold under their parent and are verified, not built.
STEP_TYPES = ("story", "spike")

# Per-role search roots are supplied by ``StepRoots``; each role resolves its
# named files against an ordered list of directories, first hit wins.
_ROLE_ORDER = ("compass", "implements", "context", "stack", "rules")


@dataclass(frozen=True)
class StepRoots:
    """Directories against which a step's named files are resolved."""

    target_dir: Path
    blueprint_dir: Path
    stack_dir: Path
    rigging_dir: Path

    def roots_for(self, role: str) -> tuple[Path, ...]:
        if role == "implements":
            return (self.blueprint_dir,)
        if role == "context":
            return (self.blueprint_dir, self.target_dir)
        if role == "stack":
            return (self.stack_dir,)
        if role == "rules":
            return (self.rigging_dir, self.target_dir)
        if role == "compass":
            return (self.target_dir,)
        return ()


@dataclass(frozen=True)
class StepFile:
    """One resolved (or missing) file stacked into a step, with its cost."""

    name: str
    role: str
    byte_count: int
    story_points: int
    missing: bool
    source: Path | None = None
    compact_substituted: bool = False


@dataclass(frozen=True)
class StepAssembly:
    """The resolved stack and cost for one executable build step."""

    block_id: str
    block_type: str
    name: str
    parent: str | None
    files: tuple[StepFile, ...]
    instructions: str
    instructions_story_points: int
    total_byte_count: int
    total_story_points: int
    over_warn: bool
    warn_kb: int

    def missing_files(self) -> tuple[StepFile, ...]:
        return tuple(f for f in self.files if f.missing)


def _measure(name: str, role: str, roots: tuple[Path, ...]) -> StepFile:
    """Resolve one named file against ordered roots; first existing wins."""
    for root in roots:
        candidate = root / name
        try:
            byte_count = len(candidate.read_bytes())
        except OSError:
            continue
        return StepFile(
            name=name,
            role=role,
            byte_count=byte_count,
            story_points=story_points_for(byte_count),
            missing=False,
            source=candidate,
        )
    return StepFile(name=name, role=role, byte_count=0, story_points=0, missing=True)


def _compact_sibling(name: str) -> str:
    """Return the ``*_compact.md`` sibling name for a stack file."""
    if name.endswith(".md"):
        return name[:-3] + "_compact.md"
    return name


def _measure_compact(canonical: str, role: str, roots: tuple[Path, ...]) -> StepFile:
    """Resolve a file, preferring the ``*_compact.md`` sibling when it exists on disk.

    Falls through to the full file when no compact sibling is found.
    """
    compact = _compact_sibling(canonical)
    if compact != canonical:
        for root in roots:
            candidate = root / compact
            try:
                byte_count = len(candidate.read_bytes())
            except OSError:
                continue
            return StepFile(
                name=compact,
                role=role,
                byte_count=byte_count,
                story_points=story_points_for(byte_count),
                missing=False,
                source=candidate,
                compact_substituted=True,
            )
    return _measure(canonical, role, roots)


def _role_names(block: PlanBlock, role: str) -> tuple[str, ...]:
    """Return the file names a block declares for one role."""
    if role == "compass":
        return ("COMPASS.md",)
    value = block.fields.get(role, ())
    if isinstance(value, tuple):
        return value
    return ()


def assemble_step(
    block: PlanBlock,
    roots: StepRoots,
    *,
    warn_kb: int = PROMPT_WARN_KB,
    compact_stack: frozenset[str] | None = None,
) -> StepAssembly:
    """Resolve and cost the full prompt stack for one executable build block.

    Reads files only; writes nothing. Files named by a block but not found are
    reported ``missing`` and contribute zero cost.

    ``compact_stack`` is the set of canonical file names (as written in the
    manifest, any role) that should use their ``*_compact.md`` sibling for this
    step. When ``None``, no compact substitution is applied. The caller —
    either ``assemble_steps`` (forward-scan) or ``build_run`` (applied registry)
    — supplies the set.
    """
    files: list[StepFile] = []
    for role in _ROLE_ORDER:
        names: list[str] = []
        for name in _role_names(block, role):
            if name not in names:
                names.append(name)
        for name in names:
            if compact_stack is not None and name in compact_stack:
                files.append(_measure_compact(name, role, roots.roots_for(role)))
            else:
                files.append(_measure(name, role, roots.roots_for(role)))

    instructions = str(block.fields.get("instructions", ""))
    instr_bytes = len(instructions.encode("utf-8"))
    instr_points = story_points_for(instr_bytes) if instr_bytes else 0

    total_bytes = sum(f.byte_count for f in files) + instr_bytes
    total_points = sum(f.story_points for f in files) + instr_points

    return StepAssembly(
        block_id=block.block_id,
        block_type=block.block_type,
        name=block.name,
        parent=block.parent,
        files=tuple(files),
        instructions=instructions,
        instructions_story_points=instr_points,
        total_byte_count=total_bytes,
        total_story_points=total_points,
        over_warn=total_bytes > warn_kb * 1024,
        warn_kb=warn_kb,
    )


def assemble_steps(
    plan: BuildPlan,
    roots: StepRoots,
    *,
    warn_kb: int = PROMPT_WARN_KB,
) -> tuple[StepAssembly, ...]:
    """Assemble every executable step in the plan, in manifest order.

    Performs a forward scan for compact substitution across all roles: the first
    step that names any file receives the full version; every subsequent step
    receives the compact sibling (``*_compact.md``) when one exists on disk.
    Steps show the resolved name so the QuarterDeck displays honest token costs
    before the build runs.
    """
    files_seen: set[str] = set()
    result: list[StepAssembly] = []
    for block in plan.blocks:
        if block.block_type not in STEP_TYPES:
            continue
        step = assemble_step(
            block, roots, warn_kb=warn_kb, compact_stack=frozenset(files_seen)
        )
        for role in _ROLE_ORDER:
            for name in _role_names(block, role):
                files_seen.add(name)
        result.append(step)
    return tuple(result)


def _fence_for(text: str) -> str:
    """Pick a backtick fence longer than any run of backticks in the content."""
    longest = max((len(m) for m in re.findall(r"`+", text)), default=0)
    return "`" * max(3, longest + 1)


def render_build_prompt(
    body: str,
    assembly: StepAssembly,
    *,
    target: str,
    build_dir: Path,
    today: str,
) -> str:
    return render_build_prompt_assembly(
        body,
        assembly,
        target=target,
        build_dir=build_dir,
        today=today,
    ).rendered_text


def render_build_prompt_assembly(
    body: str,
    assembly: StepAssembly,
    *,
    target: str,
    build_dir: Path,
    today: str,
) -> PromptAssembly:
    """Compose the full executable build prompt for one step.

    The same assembly the compass costs is rendered into the agent prompt: the
    prompt-contract body, a build-job block, every resolved file fenced under its
    role, and the step's instructions. Missing files are listed, not fenced.
    """
    parts = [
        system_preamble_part(),
        section_heading_part("# Input Context"),
        lines_part(
            "Build job",
            [
                "## Build job",
                f"- TARGET: {target}",
                f"- BUILD_DIRECTORY: {build_dir}",
                f"- STEP: {assembly.name} ({assembly.block_id}) [{assembly.block_type}]",
                f"- DATE: {today}",
                "",
            ],
            kind="job",
        ),
    ]
    missing = assembly.missing_files()
    if missing:
        parts.append(
            lines_part(
                "Missing context files",
                [
                    "Missing context files (named by the plan but not found):",
                    *[f"- {f.role}: {f.name}" for f in missing],
                    "",
                ],
                kind="section",
            )
        )
    for step_file in assembly.files:
        if step_file.missing or step_file.source is None:
            continue
        try:
            content = step_file.source.read_text(encoding="utf-8")
        except OSError:
            continue
        header = prompt_header_for_file(step_file.name)
        if header is not None:
            parts.extend(
                contextual_markdown_parts(
                    step_file.name,
                    content.rstrip(),
                    filename=step_file.name,
                    role=step_file.role,
                    path=step_file.source,
                )
            )
            continue
        parts.append(
            part(
                step_file.name,
                (
                    f'<pblock filename="{step_file.name}" role="{step_file.role}"'
                    + (f' path="{step_file.source}"' if step_file.source else "")
                    + f">\n{_fence_for(content)}\n{content.rstrip()}\n{_fence_for(content)}\n</pblock>\n\n"
                ),
                kind="file",
                role=step_file.role,
                path=step_file.source,
            )
        )
    if assembly.instructions.strip():
        parts.append(
            lines_part(
                "Build instructions",
                ["### Build instructions for this step", assembly.instructions.strip(), ""],
                kind="instructions",
            )
        )
    parts.append(section_heading_part("# Agent Task"))
    parts.append(part("Prompt body", body.rstrip() + "\n\n", kind="prompt-body"))
    return PromptAssembly(parts=tuple(parts))


@dataclass(frozen=True)
class StepGroup:
    """A feature grouping of steps with a story-point rollup, for the compass."""

    feature_id: str | None
    name: str
    steps: tuple[StepAssembly, ...]
    total_story_points: int = field(default=0)


def group_steps(plan: BuildPlan, steps: tuple[StepAssembly, ...]) -> tuple[StepGroup, ...]:
    """Group assembled steps under their parent feature, in manifest order.

    Steps with no feature parent fall into a trailing ``Ungrouped`` group. Group
    order follows first appearance of each feature's steps in manifest order.
    """
    by_id = plan.by_id()
    order: list[str | None] = []
    members: dict[str | None, list[StepAssembly]] = {}
    for step in steps:
        parent = step.parent
        key = parent if parent and parent in by_id else None
        if key not in members:
            members[key] = []
            order.append(key)
        members[key].append(step)

    groups: list[StepGroup] = []
    for key in order:
        steps_in = tuple(members[key])
        if key is None:
            name = "Ungrouped"
        else:
            name = by_id[key].name
        groups.append(
            StepGroup(
                feature_id=key,
                name=name,
                steps=steps_in,
                total_story_points=sum(s.total_story_points for s in steps_in),
            )
        )
    return groups

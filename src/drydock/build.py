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
never written back. A step whose story-point total exceeds the configured
``PROMPT_WARN_TOKENS`` ceiling is flagged ``over_warn``: it stacks more context than
is reliably built in one prompt. The ceiling and every displayed cost are the same
unit — tokens.

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
import stat
from collections.abc import Iterable
from dataclasses import dataclass, field, replace
from hashlib import sha256
from pathlib import Path

from drydock.build_plan import BuildPlan, PlanBlock
from drydock.compass_sources import is_compass_file
from drydock.config import get_prompt_error_tokens, get_prompt_warn_tokens
from drydock.errors import ConfigurationError
from drydock.prompt_assembly import (
    PromptAssembly,
    contextual_markdown_parts,
    lines_part,
    part,
    section_heading_part,
    system_preamble_part,
)
from drydock.prompt_headers import prompt_header_for_file
from drydock.source_roles import StagedAsset


def story_points_for(byte_count: int) -> int:
    """Story points = estimated token cost = ``ceil(byte_count / 4)``.

    The token estimate and the story-point count are one number: a token is
    ~4 bytes, so there is a single derived unit, not two.
    """
    return math.ceil(byte_count / 4)


# Default maximum assembled prompt cost, in tokens (story points), for one build step
# before it is flagged; the effective ceiling comes from the ``PROMPT_WARN_TOKENS``
# configuration key. The stacking strategy groups similar work to stay under this
# ceiling. Tokens, not bytes: it is the unit every cost is displayed in.
PROMPT_WARN_TOKENS = 50_000


def resolve_warn_tokens() -> int:
    """Return the configured warn ceiling, falling back to the built-in default.

    Assembly is a read-only costing pass; an unusable ``PROMPT_WARN_TOKENS`` setting
    downgrades to the default rather than failing the build.
    """
    try:
        return get_prompt_warn_tokens()
    except ConfigurationError:
        return PROMPT_WARN_TOKENS


# The red light to ``PROMPT_WARN_TOKENS``' yellow. Warn is advisory and a legitimate
# specification trips it routinely, so it is deliberately not a stop sign; this is the
# threshold worth raising with the Commander.
PROMPT_ERROR_TOKENS = 120_000


def resolve_error_tokens() -> int:
    """Return the configured error ceiling, falling back to the built-in default."""
    try:
        return get_prompt_error_tokens()
    except ConfigurationError:
        return PROMPT_ERROR_TOKENS


# Manifest block types that are executable build steps. Features group; ac blocks
# fold under their parent and are verified, not built.
STEP_TYPES = ("story", "spike")

# Per-role search roots are supplied by ``StepRoots``; each role resolves its
# named files against an ordered list of directories, first hit wins.
_ROLE_ORDER = ("compass", "implements", "context", "stack", "rules")
_PROMPT_RENDER_ROLE_ORDER = ("compass", "rules", "stack", "context", "implements")
_ROLE_HEADINGS = {
    "compass": "## COMPASS - Target Orientation",
    "rules": "## RULES - Governance",
    "stack": "## STACK - Technology HOW",
    "context": "## CONTEXT - Read-Only Support",
    "implements": "## IMPLEMENTS - Authoritative Step Specifications",
}
_AUTO_CONTEXT_MANAGED = frozenset({
    "ARCHITECTURE.md",
    "DATABASE.md",
    "ARCHITECTURE_compact.md",
    "DATABASE_compact.md",
})


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
    prompt_role: str | None = None


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
    warn_tokens: int
    overhead_story_points: int = 0

    def missing_files(self) -> tuple[StepFile, ...]:
        return tuple(f for f in self.files if f.missing)

    @property
    def own_story_points(self) -> int:
        """The step's own cost: its ``implements`` specs plus its instructions.

        ``own = total - overhead``, where overhead is the shared/injected context
        (COMPASS, context, stack, rules) stacked into every step in the group.
        """
        return self.total_story_points - self.overhead_story_points


def _file_size(candidate: Path) -> int | None:
    """Byte length of a regular file via one stat call; None when unusable.

    stat instead of read: the assembler only needs lengths, and the compass
    re-measures every named file per refresh — content reads made that slow
    on network-mounted filesystems.
    """
    try:
        st = candidate.stat()
    except OSError:
        return None
    if not stat.S_ISREG(st.st_mode):
        return None
    return st.st_size


def _measure(name: str, role: str, roots: tuple[Path, ...]) -> StepFile:
    """Resolve one named file against ordered roots; first existing wins."""
    for root in roots:
        candidate = root / name
        byte_count = _file_size(candidate)
        if byte_count is None:
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


_COMPACT_PROVENANCE_SHA_RE = re.compile(r"^<!-- Compacted from .+ sha256=([0-9a-f]{64}) ")


def compact_path_for(source: Path) -> Path:
    """Return the persisted compact-derivative path for a Blueprint source."""
    return source.with_name(f"{source.stem}_compact.md")


def has_fresh_compact(source: Path) -> bool:
    """True when ``source`` has a compact sibling made from its current content."""
    compact = compact_path_for(source)
    if not source.is_file() or not compact.is_file():
        return False
    try:
        first_line = compact.read_text(encoding="utf-8").splitlines()[0]
        match = _COMPACT_PROVENANCE_SHA_RE.match(first_line)
        if match is None:
            return False
        return match.group(1) == sha256(source.read_bytes()).hexdigest()
    except OSError:
        return False


def _canonical_spec_name(name: str) -> str:
    """Map a compact-derivative name back to its source name; identity otherwise."""
    for suffix in ("_compact.skip.md", "_compact.md"):
        if name.endswith(suffix):
            return name[: -len(suffix)] + ".md"
    return name


def _implements(block: PlanBlock) -> tuple[str, ...]:
    value = block.fields.get("implements", ())
    if isinstance(value, tuple):
        return value
    return ()


def _context_names(block: PlanBlock) -> tuple[str, ...]:
    value = block.fields.get("context", ())
    if isinstance(value, tuple):
        return value
    return ()


def is_feature_step(block: PlanBlock) -> bool:
    """True when the step implements one or more FEATURE-* specs."""
    return any(name.startswith("FEATURE-") for name in _implements(block))


def is_screen_step(block: PlanBlock) -> bool:
    """True when the step implements one or more SCREEN-* specs and no feature specs."""
    implements = _implements(block)
    return (
        bool(implements)
        and not is_feature_step(block)
        and all(name.startswith("SCREEN-") for name in implements)
    )


# Layer bands for build-order validation. Manifest order constrains only the
# coarse layer a step sits in — Foundation before Data/Persistence before the
# implementation band — never a strict per-dependency order, which the engine
# derives at run time from ``depends:``. Feature/service and screen work can live
# in the same band, but they are separate work kinds for grouping.
BAND_FOUNDATION = 0
BAND_DATA = 1
BAND_FEATURES = 2
BAND_NAMES = {
    BAND_FOUNDATION: "Foundation",
    BAND_DATA: "Data/Persistence",
    BAND_FEATURES: "Features/Screens",
}


def band_for(block_type: str, implements: Iterable[str]) -> int:
    """Return the layer band for a step given its type and implemented specs.

    Spikes and steps that implement ``ARCHITECTURE.md`` are Foundation; steps that
    implement ``DATABASE.md`` are Data/Persistence; everything else — features,
    screens, and infrastructure that builds on them — is the Features/Screens band.
    The single source of truth for banding, shared by the compass and the editor.
    """
    if block_type == "spike":
        return BAND_FOUNDATION
    names = tuple(implements)
    if "ARCHITECTURE.md" in names:
        return BAND_FOUNDATION
    if "DATABASE.md" in names:
        return BAND_DATA
    return BAND_FEATURES


def band_of(block: PlanBlock) -> int:
    """Return the layer band a step belongs to, derived from what it implements.

    Acceptance (``ac``) blocks are out of the ordered stream and are never banded.
    """
    return band_for(block.block_type, _implements(block))


def work_kind_for(block_type: str, implements: Iterable[str]) -> str:
    """Return the stack-local work kind used for build grouping.

    Bands answer "can this appear before that"; work kinds answer "should this
    run in the same prompt." Screen work uses a different stack from the
    feature/service/foundation implementation path, so it does not share a build
    prompt with non-screen work.
    """
    names = tuple(implements)
    if names and all(name.startswith("SCREEN-") for name in names):
        return "screen"
    return "feature"


def work_kind_of(block: PlanBlock) -> str:
    """Return the stack-local work kind for a parsed manifest block."""
    return work_kind_for(block.block_type, _implements(block))


def auto_context_files(block: PlanBlock, blueprint_dir: Path) -> tuple[str, ...]:
    """Return deterministic compact context injected for feature steps."""
    if not is_feature_step(block):
        return ()
    names: list[str] = []
    if (blueprint_dir / "ARCHITECTURE.md").is_file():
        names.append("ARCHITECTURE_compact.md")
    if (blueprint_dir / "DATABASE.md").is_file():
        names.append("DATABASE_compact.md")
    return tuple(names)


def normalize_context_names(block: PlanBlock, blueprint_dir: Path) -> tuple[str, ...]:
    """Return authored context with managed architecture/database entries normalized.

    Compass files are dropped from ``context``: COMPASS.md is injected whole by the
    ``compass`` role for every step, so naming it as context only duplicates it.
    """
    current = tuple(name for name in _context_names(block) if not is_compass_file(name))
    if not (is_feature_step(block) or is_screen_step(block)):
        return current
    names: list[str] = [name for name in current if name not in _AUTO_CONTEXT_MANAGED]
    for name in auto_context_files(block, blueprint_dir):
        if name not in names:
            names.append(name)
    return tuple(names)


def required_auto_compact_sources(block: PlanBlock, blueprint_dir: Path) -> tuple[Path, ...]:
    """Return source spec files whose compact derivatives should be fresh for this step.

    ARCHITECTURE/DATABASE remain the required pair. Every other Blueprint file named
    in ``context:`` is an optional compaction source: the assembler prefers its
    ``*_compact.md`` sibling and falls through to the full file, so a missing or
    no-surface derivative never blocks. Context entries whose source is also in
    this block's ``implements:`` are excluded — the step already carries the full file.
    """
    required: list[Path] = []
    implements = _implements(block)
    implements_canonical = {_canonical_spec_name(name) for name in implements}
    effective_context = normalize_context_names(block, blueprint_dir)
    context_canonical = [_canonical_spec_name(name) for name in effective_context]
    for name in ("ARCHITECTURE.md", "DATABASE.md"):
        if name in implements or name in context_canonical:
            path = blueprint_dir / name
            if path.is_file():
                required.append(path)
    for canonical in context_canonical:
        if canonical in ("ARCHITECTURE.md", "DATABASE.md") or canonical in implements_canonical:
            continue
        path = blueprint_dir / canonical
        if path.is_file() and path not in required:
            required.append(path)
    return tuple(required)


def required_plan_auto_compact_sources(
    blocks: Iterable[PlanBlock],
    blueprint_dir: Path,
) -> tuple[Path, ...]:
    """Return unique ARCHITECTURE/DATABASE source files required anywhere in the plan."""
    seen: set[Path] = set()
    required: list[Path] = []
    for block in blocks:
        for path in required_auto_compact_sources(block, blueprint_dir):
            if path not in seen:
                seen.add(path)
                required.append(path)
    return tuple(required)


def reusable_build_compact_sources(
    plan: BuildPlan,
    current_steps: tuple[PlanBlock, ...],
    blueprint_dir: Path,
) -> tuple[Path, ...]:
    """Return current Blueprint inputs that a later Manifest block consumes as context.

    A build agent may create these compacts in its existing response when no derivative exists.
    An existing derivative is never regenerated, even when its source has changed. The current
    build unit never counts as a later consumer, including sibling stories grouped under a
    feature.
    """
    if not current_steps:
        return ()
    current_ids = {block.block_id for block in current_steps}
    indexes = [index for index, block in enumerate(plan.blocks) if block.block_id in current_ids]
    if not indexes:
        return ()
    current_sources: list[Path] = []
    for block in current_steps:
        names = [*_implements(block), *normalize_context_names(block, blueprint_dir)]
        for name in names:
            canonical = _canonical_spec_name(name)
            source = blueprint_dir / canonical
            if source.is_file() and source not in current_sources:
                current_sources.append(source)
    later_context = {
        _canonical_spec_name(name)
        for block in plan.blocks[max(indexes) + 1 :]
        if block.block_type in STEP_TYPES
        for name in normalize_context_names(block, blueprint_dir)
    }
    return tuple(
        source
        for source in current_sources
        if source.name in later_context
        and not compact_path_for(source).is_file()
        and not source.with_name(f"{source.stem}_compact.skip.md").is_file()
    )


def _measure_compact(
    canonical: str,
    role: str,
    roots: tuple[Path, ...],
) -> StepFile:
    """Resolve a file, preferring the ``*_compact.md`` sibling when it exists on disk.

    Falls through to the full file when no compact sibling is found. An existing compact is
    used regardless of its provenance header; compaction is an explicit, separate operation.
    Compass files are never substituted: they are never compacted.
    """
    if is_compass_file(canonical):
        return _measure(canonical, role, roots)
    compact = _compact_sibling(canonical)
    if compact != canonical:
        for root in roots:
            candidate = root / compact
            byte_count = _file_size(candidate)
            if byte_count is None:
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


def _context_roles(block: PlanBlock) -> dict[str, str]:
    """Map each context file to its authored role label.

    Keys are normalized the way ``source_roles.parse_source_roles`` normalizes them, because a
    plan may name an asset either bare (``spec.txt``) or by its import path
    (``sources/spec.txt``) while ``context:`` always carries the bare name.
    """
    raw = block.fields.get("context_roles", "")
    if not isinstance(raw, str):
        return {}
    roles: dict[str, str] = {}
    for line in raw.splitlines():
        if ":" not in line:
            continue
        name, value = line.split(":", 1)
        key = name.strip().strip("`").removeprefix("sources/")
        if key and value.strip():
            roles[key] = value.strip()
    return roles


def _role_names(
    block: PlanBlock, role: str, *, blueprint_dir: Path | None = None
) -> tuple[str, ...]:
    """Return the file names a block declares for one role."""
    if role == "compass":
        return ("COMPASS.md",)
    if role == "context" and blueprint_dir is not None:
        return normalize_context_names(block, blueprint_dir)
    value = block.fields.get(role, ())
    if isinstance(value, tuple):
        return value
    return ()


def assemble_step(
    block: PlanBlock,
    roots: StepRoots,
    *,
    warn_tokens: int | None = None,
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

    The ``context`` role always prefers each file's ``*_compact.md`` sibling and
    falls through to the full file, independent of ``compact_stack``. A context
    entry whose source file is also in this block's ``implements:`` is dropped —
    the step already carries the authoritative full file.
    """
    if warn_tokens is None:
        warn_tokens = resolve_warn_tokens()
    files: list[StepFile] = []
    implements_canonical = {
        _canonical_spec_name(name)
        for name in _role_names(block, "implements", blueprint_dir=roots.blueprint_dir)
    }
    for role in _ROLE_ORDER:
        names: list[str] = []
        if role == "context":
            for name in _role_names(block, role, blueprint_dir=roots.blueprint_dir):
                canonical = _canonical_spec_name(name)
                if canonical in implements_canonical or canonical in names:
                    continue
                names.append(canonical)
        else:
            for name in _role_names(block, role, blueprint_dir=roots.blueprint_dir):
                if name not in names:
                    names.append(name)
        for name in names:
            if role == "context":
                measured = _measure_compact(
                    name,
                    role,
                    roots.roots_for(role),
                )
                files.append(
                    replace(measured, prompt_role=_context_roles(block).get(name, "context"))
                )
            elif compact_stack is not None and name in compact_stack:
                files.append(_measure_compact(name, role, roots.roots_for(role)))
            else:
                files.append(_measure(name, role, roots.roots_for(role)))

    instructions = str(block.fields.get("instructions", ""))
    instr_bytes = len(instructions.encode("utf-8"))
    instr_points = story_points_for(instr_bytes) if instr_bytes else 0

    total_bytes = sum(f.byte_count for f in files) + instr_bytes
    total_points = sum(f.story_points for f in files) + instr_points
    # Overhead is the shared/injected context (everything except the step's own
    # ``implements`` specs and its instruction text): COMPASS, context, stack, rules.
    overhead_points = sum(f.story_points for f in files if f.role != "implements")

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
        over_warn=total_points > warn_tokens,
        warn_tokens=warn_tokens,
        overhead_story_points=overhead_points,
    )


def assemble_steps(
    plan: BuildPlan,
    roots: StepRoots,
    *,
    warn_tokens: int | None = None,
) -> tuple[StepAssembly, ...]:
    """Assemble every executable step in the plan, in manifest order.

    Performs a forward scan for compact substitution across all roles: the first
    step that names any file receives the full version; every subsequent step
    receives the compact sibling (``*_compact.md``) when one exists on disk.
    Steps show the resolved name so the QuarterDeck displays honest token costs
    before the build runs.
    """
    if warn_tokens is None:
        warn_tokens = resolve_warn_tokens()
    files_seen: set[str] = set()
    result: list[StepAssembly] = []
    for block in plan.blocks:
        if block.block_type not in STEP_TYPES:
            continue
        step = assemble_step(
            block, roots, warn_tokens=warn_tokens, compact_stack=frozenset(files_seen)
        )
        for role in _ROLE_ORDER:
            for name in _role_names(block, role, blueprint_dir=roots.blueprint_dir):
                files_seen.add(name)
        result.append(step)
    return tuple(result)


def _fence_for(text: str) -> str:
    """Pick a backtick fence longer than any run of backticks in the content."""
    longest = max((len(m) for m in re.findall(r"`+", text)), default=0)
    return "`" * max(3, longest + 1)


def _staged_files_part(staged_assets: tuple[StagedAsset, ...]):
    """Name the files that exist on disk in the build directory, or nothing when none do.

    The agent otherwise has no account of its own working directory and infers one from the
    imported prose, which describes the author's intent rather than what Drydock staged.
    Markdown is deliberately never staged — it arrives fenced in this prompt — so an agent
    left to guess reports its own context files as missing inputs and halts.
    """
    if not staged_assets:
        return None
    return lines_part(
        "Files on disk",
        [
            "## Files on disk in the build directory",
            *[f"- {asset.relative_path}" for asset in staged_assets],
            "",
            "These are the only imported files present on disk. Every other file named in "
            "this prompt is supplied as prompt context and is not on disk; read it here and "
            "do not report it as a missing input.",
            "",
        ],
        kind="section",
    )


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
    reusable_compacts: tuple[Path, ...] = (),
    staged_assets: tuple[StagedAsset, ...] = (),
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
                f"- WORKING_DIRECTORY: {build_dir}",
                f"- STEP: {assembly.name} ({assembly.block_id}) [{assembly.block_type}]",
                f"- DATE: {today}",
                "- BUILD_SCOPE: exactly one MANIFEST.md step",
                "",
            ],
            kind="job",
        ),
    ]
    staged_part = _staged_files_part(staged_assets)
    if staged_part is not None:
        parts.append(staged_part)
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
    for role in _PROMPT_RENDER_ROLE_ORDER:
        role_files = tuple(
            step_file
            for step_file in assembly.files
            if step_file.role == role and not step_file.missing and step_file.source is not None
        )
        if not role_files:
            continue
        parts.append(section_heading_part(_ROLE_HEADINGS[role]))
        if role == "implements":
            parts.append(
                lines_part(
                    "Implementation recency anchor",
                    [
                        "The files in this section are the load-bearing specifications for this step.",
                        "Build these files exactly. Treat earlier sections as constraints and context.",
                        "",
                    ],
                    kind="section",
                )
            )
        for step_file in role_files:
            source = step_file.source
            assert source is not None
            try:
                content = source.read_text(encoding="utf-8")
            except OSError:
                continue
            header = prompt_header_for_file(step_file.name)
            prompt_role = step_file.prompt_role or step_file.role
            if header is not None:
                parts.extend(
                    contextual_markdown_parts(
                        step_file.name,
                        content.rstrip(),
                        filename=step_file.name,
                        role=prompt_role,
                        path=source,
                    )
                )
                continue
            parts.append(
                part(
                    step_file.name,
                    (
                        f'<pblock filename="{step_file.name}" role="{prompt_role}"'
                        + f' path="{source}"'
                        + f">\n{_fence_for(content)}\n{content.rstrip()}\n{_fence_for(content)}\n</pblock>\n\n"
                    ),
                    kind="file",
                    role=step_file.role,
                    path=source,
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
    _append_reusable_compact_request(parts, reusable_compacts)
    parts.append(section_heading_part("# Agent Task"))
    parts.append(part("Prompt body", body.rstrip() + "\n\n", kind="prompt-body"))
    return PromptAssembly(parts=tuple(parts))


def _append_reusable_compact_request(parts: list, sources: tuple[Path, ...]) -> None:
    """Add optional same-response compact work for sources consumed by later blocks."""
    if not sources:
        return
    lines = [
        "## Reusable compacts",
        "",
        "The Blueprint sources below are consumed as context by later Manifest blocks.",
        "In this same response, extract their consumer-facing contract surface. Preserve",
        "interfaces, schemas, constraints, configuration, and cross-file obligations; drop",
        "implementation narrative and repetition. Do not write these files yourself.",
        "",
        "Before the required RESULT block, emit one optional payload per source exactly as:",
        '<reusable-compact filename="SOURCE.md">',
        "compact content",
        "</reusable-compact>",
        "",
        "Emit no payload when a source has no useful technical surface. These payloads are",
        "advisory and do not change the required build result or file-change report.",
        "",
        "Sources eligible for reusable compaction:",
        *[f"- {source.name}" for source in sources],
        "",
    ]
    parts.append(lines_part("Reusable compact request", lines, kind="section"))


@dataclass(frozen=True)
class StepGroup:
    """A feature grouping of steps with a story-point rollup, for the compass."""

    feature_id: str | None
    name: str
    steps: tuple[StepAssembly, ...]
    total_story_points: int = field(default=0)
    summed_story_points: int = field(default=0)
    story_point_savings: int = field(default=0)

    def missing_files(self) -> tuple[StepFile, ...]:
        missing: list[StepFile] = []
        seen: set[tuple[str, str]] = set()
        for step in self.steps:
            for step_file in step.missing_files():
                key = _group_file_key(step_file)
                if key in seen:
                    continue
                seen.add(key)
                missing.append(step_file)
        return tuple(missing)


def make_step_group(
    *,
    feature_id: str | None,
    name: str,
    steps: tuple[StepAssembly, ...],
) -> StepGroup:
    """Create a StepGroup with the same combined-cost semantics as QuarterDeck."""
    summed_story_points = sum(s.total_story_points for s in steps)
    combined_story_points = _combined_story_points(steps)
    return StepGroup(
        feature_id=feature_id,
        name=name,
        steps=steps,
        total_story_points=combined_story_points,
        summed_story_points=summed_story_points,
        story_point_savings=max(0, summed_story_points - combined_story_points),
    )


def _group_file_key(step_file: StepFile) -> tuple[str, str]:
    """Return the identity used to count a file once in a grouped build."""
    name = step_file.name
    if step_file.compact_substituted and name.endswith("_compact.md"):
        name = name.removesuffix("_compact.md") + ".md"
    if step_file.source is not None:
        source = step_file.source
        if step_file.compact_substituted and source.name.endswith("_compact.md"):
            source = source.with_name(source.name.removesuffix("_compact.md") + ".md")
        return ("path", str(source))
    return ("name", name)


def _combined_story_points(steps: tuple[StepAssembly, ...]) -> int:
    """Cost a group with each duplicate file applied once and all instructions kept."""
    seen: set[tuple[str, str]] = set()
    total = 0
    for step in steps:
        total += step.instructions_story_points
        for step_file in step.files:
            if step_file.missing:
                continue
            key = _group_file_key(step_file)
            if key in seen:
                continue
            seen.add(key)
            total += step_file.story_points
    return total


def group_duplicate_flags(steps: tuple[StepAssembly, ...]) -> tuple[tuple[bool, ...], ...]:
    """Per step, per file: True when an earlier file in this group already covers it.

    Mirrors ``_combined_story_points`` first-seen semantics exactly: identity is
    ``_group_file_key`` (compact derivatives collapse to their source), the seen set
    spans the whole group walk in step order, and missing files are never duplicates.
    A flagged file contributes nothing to the grouped build prompt.
    """
    seen: set[tuple[str, str]] = set()
    flags: list[tuple[bool, ...]] = []
    for step in steps:
        step_flags: list[bool] = []
        for step_file in step.files:
            if step_file.missing:
                step_flags.append(False)
                continue
            key = _group_file_key(step_file)
            step_flags.append(key in seen)
            seen.add(key)
        flags.append(tuple(step_flags))
    return tuple(flags)


def step_incremental_story_points(step: StepAssembly, flags: tuple[bool, ...]) -> int:
    """The step's grouped cost: instructions plus every non-duplicate file."""
    return step.instructions_story_points + sum(
        step_file.story_points
        for step_file, duplicate in zip(step.files, flags, strict=True)
        if not duplicate
    )


def _unique_group_files(steps: tuple[StepAssembly, ...], role: str) -> tuple[StepFile, ...]:
    seen: set[tuple[str, str]] = set()
    files: list[StepFile] = []
    for step in steps:
        for step_file in step.files:
            if step_file.role != role:
                continue
            key = _group_file_key(step_file)
            if key in seen:
                continue
            seen.add(key)
            files.append(step_file)
    return tuple(files)


def _group_render_files(steps: tuple[StepAssembly, ...], role: str) -> tuple[StepFile, ...]:
    """Group files for one role, suppressing compact duplicates of any full source."""
    full_sources = {
        _group_file_key(item)
        for step in steps
        for item in step.files
        if not item.missing and not item.compact_substituted
    }
    return tuple(
        item
        for item in _unique_group_files(steps, role)
        if not (item.compact_substituted and _group_file_key(item) in full_sources)
    )


def render_build_group_prompt_assembly(
    body: str,
    group: StepGroup,
    *,
    target: str,
    build_dir: Path,
    today: str,
    reusable_compacts: tuple[Path, ...] = (),
    regression_steps: tuple[StepAssembly, ...] = (),
    staged_assets: tuple[StagedAsset, ...] = (),
) -> PromptAssembly:
    """Compose the executable build prompt for one feature/group block."""
    block_label = group.feature_id or "ungrouped"
    run_steps = ", ".join(f"{step.name} ({step.block_id})" for step in group.steps)
    parts = [
        system_preamble_part(),
        section_heading_part("# Input Context"),
        lines_part(
            "Build block job",
            [
                "## Build block job",
                f"- TARGET: {target}",
                f"- BUILD_DIRECTORY: {build_dir}",
                f"- WORKING_DIRECTORY: {build_dir}",
                f"- BUILD_BLOCK: {group.name} ({block_label})",
                f"- STORIES: {run_steps}",
                f"- DATE: {today}",
                "- BUILD_SCOPE: exactly one MANIFEST.md build block",
                "",
            ],
            kind="job",
        ),
        lines_part(
            "Stories in this block",
            [
                "## Stories in this block",
                *[f"- {step.name} ({step.block_id}) [{step.block_type}]" for step in group.steps],
                "",
            ],
            kind="section",
        ),
    ]
    staged_part = _staged_files_part(staged_assets)
    if staged_part is not None:
        parts.append(staged_part)
    missing = group.missing_files()
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
    for role in _PROMPT_RENDER_ROLE_ORDER:
        role_files = tuple(
            step_file
            for step_file in _group_render_files(group.steps, role)
            if not step_file.missing and step_file.source is not None
        )
        if not role_files:
            continue
        parts.append(section_heading_part(_ROLE_HEADINGS[role]))
        if role == "implements":
            parts.append(
                lines_part(
                    "Implementation recency anchor",
                    [
                        "The files in this section are the load-bearing specifications for this build block.",
                        "Build these files exactly. Treat earlier sections as constraints and context.",
                        "",
                    ],
                    kind="section",
                )
            )
        for step_file in role_files:
            source = step_file.source
            assert source is not None
            try:
                content = source.read_text(encoding="utf-8")
            except OSError:
                continue
            header = prompt_header_for_file(step_file.name)
            prompt_role = step_file.prompt_role or step_file.role
            if header is not None:
                parts.extend(
                    contextual_markdown_parts(
                        step_file.name,
                        content.rstrip(),
                        filename=step_file.name,
                        role=prompt_role,
                        path=source,
                    )
                )
                continue
            parts.append(
                part(
                    step_file.name,
                    (
                        f'<pblock filename="{step_file.name}" role="{prompt_role}"'
                        + f' path="{source}"'
                        + f">\n{_fence_for(content)}\n{content.rstrip()}\n{_fence_for(content)}\n</pblock>\n\n"
                    ),
                    kind="file",
                    role=step_file.role,
                    path=source,
                )
            )
    if regression_steps:
        parts.append(section_heading_part("## REGRESSION GATES - Verified Sibling Specifications"))
        parts.append(
            lines_part(
                "Verified sibling regression guidance",
                [
                    "These sibling stories are already verified and are not implementation scope.",
                    "Their Programmatic Acceptance criteria run after this build as regression gates.",
                    "Preserve their specified behavior while repairing the active stories.",
                    "",
                ],
                kind="section",
            )
        )
        regression_files = tuple(
            step_file
            for step_file in _group_render_files(regression_steps, "implements")
            if not step_file.missing and step_file.source is not None
        )
        for step_file in regression_files:
            source = step_file.source
            assert source is not None
            try:
                content = source.read_text(encoding="utf-8")
            except OSError:
                continue
            parts.append(
                part(
                    step_file.name,
                    (
                        f'<pblock filename="{step_file.name}" role="regression"'
                        + f' path="{source}"'
                        + f">\n{_fence_for(content)}\n{content.rstrip()}\n{_fence_for(content)}\n"
                        "</pblock>\n\n"
                    ),
                    kind="file",
                    role="regression",
                    path=source,
                )
            )
    instruction_lines = ["### Build instructions for this block"]
    for step in group.steps:
        if not step.instructions.strip():
            continue
        instruction_lines.extend([
            "",
            f"#### {step.name} ({step.block_id})",
            step.instructions.strip(),
        ])
    if len(instruction_lines) > 1:
        instruction_lines.append("")
        parts.append(lines_part("Build instructions", instruction_lines, kind="instructions"))
    _append_reusable_compact_request(parts, reusable_compacts)
    parts.append(section_heading_part("# Agent Task"))
    parts.append(part("Prompt body", body.rstrip() + "\n\n", kind="prompt-body"))
    return PromptAssembly(parts=tuple(parts))


def group_steps(plan: BuildPlan, steps: tuple[StepAssembly, ...]) -> tuple[StepGroup, ...]:
    """Group steps by feature and work kind, in manifest order.

    Steps with no feature parent fall into a trailing ``Ungrouped`` group. Group
    order follows first appearance in manifest order. Screen and feature/service
    work never share a prompt even when they have the same feature parent.
    """
    by_id = plan.by_id()
    if plan.uses_computed_blocks:
        assembly_by_id = {step.block_id: step for step in steps}
        groups: list[StepGroup] = []
        for number, block_steps in plan.computed_groups():
            members = tuple(
                assembly_by_id[block.block_id]
                for block in block_steps
                if block.block_id in assembly_by_id
            )
            if not members:
                continue
            groups.append(
                make_step_group(
                    feature_id=f"block-{number}",
                    name=f"Block {number} · {block_steps[0].story_type.title()}",
                    steps=members,
                )
            )
        return tuple(groups)

    order: list[tuple[str | None, str]] = []
    members: dict[tuple[str | None, str], list[StepAssembly]] = {}
    for step in steps:
        parent = step.parent
        feature_id = parent if parent and parent in by_id else None
        block = by_id.get(step.block_id)
        kind = work_kind_of(block) if block is not None else "feature"
        key = (feature_id, kind)
        if key not in members:
            members[key] = []
            order.append(key)
        members[key].append(step)

    groups: list[StepGroup] = []
    for key in order:
        feature_id, kind = key
        steps_in = tuple(members[key])
        if feature_id is None:
            name = "Ungrouped"
        else:
            name = by_id[feature_id].name
            kinds = {
                work_kind_of(by_id[step.block_id])
                for step in steps
                if step.parent == feature_id and step.block_id in by_id
            }
            if len(kinds) > 1:
                name += f" - {kind.title()}"
        groups.append(make_step_group(feature_id=feature_id, name=name, steps=steps_in))
    return tuple(groups)

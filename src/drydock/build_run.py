"""``drydock build`` — execute the Manifest's buildable frontier.

Build walks the MANIFEST.md work graph and, for each story or spike whose
``depends:`` are all ``closed/verified``, assembles one prompt (the same stack the
compass costs) and runs a tool-enabled agent that writes the application into the
build working directory. After each step it writes reviewable evidence and
transitions the block's state through the decision writer: a step with child
acceptance checks goes to ``implemented`` (a review gate); a step with none closes
automatically. A step advances only when the agent returns a structured success
report and the build directory shows real file changes.

The module owns evidence and state writes. The agent writes application files and
returns a summary. The build performs no git operations of its own; version control
is the user's responsibility. Tests inject a fake runner so no credits or network
are used.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime
from hashlib import sha256
from pathlib import Path

from drydock.acceptance import (
    MALFORMED_FAILURE_PREFIX,
    MEMORY_FAILURE_PREFIX,
    TIMEOUT_FAILURE_PREFIX,
    AcceptanceObservation,
    AcceptanceRequirement,
    AcceptanceRunResult,
    ProgrammaticAcceptance,
    assertion_summary,
    failure_detail,
    is_terminal_check_failure,
    observe_programmatic_acceptance,
    programmatic_acceptance_for_step,
    record_prepassed_acceptance,
    run_programmatic_acceptance,
)
from drydock.acceptance_contract import (
    GateResult,
    load_contract,
    run_gate,
)
from drydock.acceptance_env import read_staged_assets, repair_staged_asset_env
from drydock.acceptance_requirements import (
    authorization_for,
    discover_missing_requirement,
    record_requirement_decision,
    requirement_available,
)
from drydock.build import (
    StepAssembly,
    StepGroup,
    StepRoots,
    assemble_step,
    make_step_group,
    render_build_group_prompt_assembly,
    render_build_prompt_assembly,
    reusable_build_compact_sources,
    work_kind_of,
)
from drydock.build_decisions import (
    record_acceptance_env_decisions,
    record_build_decisions,
    record_skipped_acceptance_decisions,
)
from drydock.build_environment import EnvMaterialization, materialize_env_file
from drydock.build_plan import (
    FINISHED_STATES,
    AppliedSpecRecord,
    BuildPlan,
    PlanBlock,
    build_relevant_sha256,
    foundational_source,
    parse_build_plan,
    set_applied_registry,
    set_applied_specs,
    stale_applied_specs,
)
from drydock.config import (
    DEFAULT_REPAIR_ATTEMPTS,
    blueprint_dir_for,
    build_dir_for,
    get_sandbox_mem_limit_mb,
    max_consecutive_stalls,
)
from drydock.decisions import load_decisions, render_commander_guidance
from drydock.dependency_gate import (
    DependencyGateResult,
    RegistryClient,
    canonicalize_package_name,
    check_python_dependency_manifests,
)
from drydock.errors import SpecificationError, clear_error_record, write_error_record
from drydock.llm import format_token_summary, render_rate_limit_error_block, run_prompt
from drydock.manifest_edit import batch_set_block_fields, reset_all_states
from drydock.metadata import set_build_state, set_sub_state, stamp_last
from drydock.override import (
    ACCEPTANCE_AUTHORIZATION,
    WaivedGate,
    dedupe_waivers,
    stamp_override,
)
from drydock.paths import get_repo_root, get_rigging_root, get_stack_dir
from drydock.prompt_assembly import PromptAssembly, part, section_heading_part
from drydock.prompts import load_prompt
from drydock.source_roles import (
    SourceRole,
    StagedAsset,
    parse_source_roles,
    stage_build_assets,
    verify_staged_assets,
)
from drydock.target_environment import provision_uv_environment

BUILD_FAILURE_HINT = (
    "rerun drydock build to continue this step (repairs in place); "
    "add --reset to discard its work and rebuild from scratch"
)

UNGATED_FINDING_PREFIX = "UNVERIFIED: acceptance bypassed by --ungate"
#: A story whose criteria could not be graded because they cannot pass by construction. It is
#: deliberately not the ``--ungate`` prefix: that marker records an operator decision to release
#: Recorded on a block that finished with no governed command able to judge it. The work is
#: done; nothing with standing examined it. Printed rather than silently reading as verified.
UNGOVERNED_FINDING = (
    "ADVISORY: implemented, not verified — no governed acceptance command covers this story. "
    "Declare one in ACCEPTANCE.json to gate it."
)

#: Recorded on a block whose every criterion settled UNVERIFIED. The product may be correct and
#: the criteria broken, so it is not a failure; nothing measured it, so it is not verification.
UNEXAMINED_FINDING = (
    "ADVISORY: implemented, not verified — every criterion this story declared settled "
    "UNVERIFIED, so nothing was measured against the built code. Repair the criteria in "
    "the Blueprint and rebuild to obtain a verdict."
)


def _ungoverned_finding(gate: GateResult | None) -> str | None:
    """Advisory for a block no governed command verified, or ``None`` when one passed."""
    return None if gate is not None and gate.passed else UNGOVERNED_FINDING


def _story_ids(block: PlanBlock) -> tuple[str, ...]:
    """Return the analyzed story ids a block delivers, for matching a governed stage gate."""
    covers = block.fields.get("covers", ())
    values = covers if isinstance(covers, tuple) else (covers,)
    return tuple(str(value) for value in values if value)


PROMPT_NAME = "build"
RunnerFn = Callable[..., object]
TextCallback = Callable[[str], None]


def _emit(on_text: TextCallback | None, message: str = "") -> None:
    if on_text is not None:
        on_text(message)


def _wall_time() -> str:
    return datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")


def _clock() -> str:
    """Short wall-clock stamp for events inside a build block (the full date lives in the header)."""
    return datetime.now().astimezone().strftime("%H:%M:%S %Z")


_RULE_WIDTH = 72


def _block_header(name: str, block_id: str) -> str:
    """One separator line naming the block: ``──── Name [block-id] ─────…``."""
    label = f"──── {name} [{block_id}] "
    fill = max(0, _RULE_WIDTH - len(label))
    return label + "─" * fill


def _elapsed_text(seconds: float) -> str:
    seconds = max(0.0, seconds)
    if seconds < 1:
        return f"{seconds:.1f} seconds"
    total = int(seconds)
    hours, rem = divmod(total, 3600)
    minutes, secs = divmod(rem, 60)
    parts: list[str] = []
    if hours:
        parts.append(f"{hours} hour{'s' if hours != 1 else ''}")
    if minutes:
        parts.append(f"{minutes} minute{'s' if minutes != 1 else ''}")
    if secs or not parts:
        parts.append(f"{secs} second{'s' if secs != 1 else ''}")
    return " ".join(parts)


@dataclass(frozen=True)
class FileFingerprint:
    size: int
    digest: str


def _git_head(path: Path) -> str | None:
    """Return HEAD commit of the git repo containing path, or None if not in git."""
    try:
        result = subprocess.run(
            ["git", "-C", str(path), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        pass
    return None


def _git_file_commit(path: Path) -> str:
    """Return the latest commit that touched ``path``, or ``-`` when unavailable."""
    try:
        root_result = subprocess.run(
            ["git", "-C", str(path.parent), "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
        )
        if root_result.returncode != 0:
            return "-"
        root = Path(root_result.stdout.strip())
        rel = path.relative_to(root)
        log_result = subprocess.run(
            ["git", "-C", str(root), "log", "-n", "1", "--format=%H", "--", str(rel)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
        )
        if log_result.returncode == 0 and log_result.stdout.strip():
            return log_result.stdout.strip()
    except (OSError, ValueError, subprocess.TimeoutExpired):
        pass
    return "-"


def _is_dirty(path: Path) -> bool:
    """True if the git repo containing path has uncommitted changes in that directory."""
    try:
        result = subprocess.run(
            ["git", "-C", str(path), "status", "--porcelain", "--", "."],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
        )
        return result.returncode == 0 and bool(result.stdout.strip())
    except (OSError, subprocess.TimeoutExpired):
        return False


@dataclass(frozen=True)
class BuildStepResult:
    block_id: str
    name: str
    block_type: str
    status: str  # built | implemented | failed | dry-run
    state: str  # resulting manifest block state
    story_points: int
    # The build unit may be a feature/block containing one or more stories. Keep the
    # container provenance on each emitted story result so terminal diagnostics can name
    # both identities without parsing the evidence prose.
    container_block_id: str | None = None
    container_name: str | None = None
    execution_id: str | None = None
    evidence_path: Path | None = None
    error: str | None = None
    failure_detail: str = ""
    written_files: tuple[str, ...] = ()
    pre_acceptance: tuple[AcceptanceObservation, ...] = ()
    acceptance: tuple[AcceptanceRunResult, ...] = ()
    owned_pre_acceptance: tuple[AcceptanceObservation, ...] = ()
    owned_acceptance: tuple[AcceptanceRunResult, ...] = ()
    agent_summary: str = ""
    agent_blockers: str = ""
    prompt: str | None = None
    # Why the repair loop stopped short of its budget, and what it spent. Without these the
    # failure report shows a run that ended at call 2 of 4 and no reason for the shortfall.
    stop_reason: str = ""
    calls_used: int = 0
    calls_budget: int = 0


@dataclass(frozen=True)
class BuildResult:
    target: str
    build_dir: Path
    steps: list[BuildStepResult]
    readme_path: Path | None = None
    dry_run: bool = False
    env_result: EnvMaterialization | None = None
    waivers: tuple[WaivedGate, ...] = ()
    # Work the Manifest still owes that this run could not advance: blocked, or pending behind an
    # unverified dependency. A build that ends with such work has stalled, not succeeded.
    stalled_blocks: tuple[str, ...] = ()

    def built(self) -> list[BuildStepResult]:
        return [s for s in self.steps if s.status in ("built", "implemented")]

    def failed(self) -> list[BuildStepResult]:
        return [s for s in self.steps if s.status == "failed"]

    def stalled(self) -> bool:
        """True when the run finished with work outstanding that it could not advance.

        A build that parks every remaining story on a question, or that finds nothing buildable
        while the Manifest is unfinished, used to exit 0 — indistinguishable from a completed
        Target. That silence is the failure mode this reports.
        """
        return bool(self.stalled_blocks) and not self.built()

    def exit_code(self) -> int:
        if self.dry_run:
            return 0
        return 1 if self.failed() or self.stalled() else 0


@dataclass(frozen=True)
class BuildUnit:
    block_id: str
    name: str
    block_type: str
    steps: tuple[PlanBlock, ...]
    already_verified: tuple[PlanBlock, ...] = ()

    @property
    def is_group(self) -> bool:
        return self.block_type in {"feature", "block"}

    @property
    def has_manifest_container(self) -> bool:
        return self.block_type == "feature"

    @property
    def resume(self) -> bool:
        """True when a selected step is being continued in place from a prior failure.

        A ``closed/failed`` step keeps its partial work in the build directory; the
        build resumes it — re-running acceptance live and seeding the first pass with
        the failure — rather than restarting from a clean prompt.
        """
        return any(step.state == "closed/failed" for step in self.steps)


def _rel(path: Path, base: Path) -> str:
    try:
        return str(path.relative_to(base))
    except ValueError:
        return str(path)


def _has_child_acs(blocks: tuple[PlanBlock, ...], block_id: str) -> bool:
    return any(b.block_type == "ac" and b.parent == block_id for b in blocks)


def _child_ac_ids(blocks: tuple[PlanBlock, ...], block_id: str) -> tuple[str, ...]:
    return tuple(b.block_id for b in blocks if b.block_type == "ac" and b.parent == block_id)


def _ungate_acceptance_plan(plan: BuildPlan) -> tuple[BuildPlan, int]:
    """Return a plan with acceptance-only failures explicitly marked unverified.

    ``--ungate`` is deliberately narrower than resetting failed work: it releases only stories
    whose persisted finding says programmatic acceptance failed, and it never releases provider,
    dependency, environment, or agent execution failures.
    """
    blocks = list(plan.blocks)
    changed = 0
    marker = UNGATED_FINDING_PREFIX

    for story in tuple(blocks):
        if story.block_type not in {"story", "spike"} or story.state != "closed/failed":
            continue
        finding = str(story.fields.get("finding", ""))
        if not finding.lower().startswith("programmatic acceptance failed"):
            continue
        for index, block in enumerate(blocks):
            if block.block_id == story.block_id:
                fields = dict(block.fields)
                fields["finding"] = marker
                blocks[index] = replace(block, state="closed/verified", fields=fields)
                changed += 1

    return replace(plan, blocks=tuple(blocks)), changed


def _ungate_acceptance_failures(manifest_path: Path) -> int:
    """Persist the explicit ``--ungate`` transition and return changed node count."""
    plan, changed = _ungate_acceptance_plan(parse_build_plan(manifest_path))
    if not changed:
        return 0
    original = parse_build_plan(manifest_path).by_id()
    updates: dict[str, dict[str, str | None]] = {}
    for block in plan.blocks:
        before = original.get(block.block_id)
        if before is None or before.state == block.state and before.fields == block.fields:
            continue
        updates[block.block_id] = {"state": block.state, "finding": block.fields.get("finding")}
    batch_set_block_fields(manifest_path, updates)
    return changed


# A step is a selection candidate when it is unbuilt (``pending``) or when it failed a
# prior pass (``closed/failed``). A failed step is resumed in place: continue is the
# default, and the reset path (``--reset``, optionally with ``--step``/``--story``) flips a
# block back to ``pending`` before selection, so a reset block is selected as a fresh build.
SELECTABLE_STATES = frozenset({"pending", "closed/failed"})


def _is_buildable(block: PlanBlock, by_id: dict[str, PlanBlock]) -> bool:
    def verified(block_id: str) -> bool:
        dependency = by_id.get(block_id)
        return dependency is not None and dependency.state in FINISHED_STATES

    return block.state in SELECTABLE_STATES and all(verified(dep) for dep in block.depends)


def _block_label(block: PlanBlock) -> str:
    return f"{block.name} [{block.block_id}]"


def _dependency_labels(dependencies: tuple[str, ...], by_id: dict[str, PlanBlock]) -> str:
    labels: list[str] = []
    for dep in dependencies:
        block = by_id.get(dep)
        labels.append(_block_label(block) if block is not None else dep)
    return ", ".join(labels)


def _blocked_options(
    dependencies: tuple[str, ...], by_id: dict[str, PlanBlock], target: str
) -> str:
    known_dependencies = [dep for dep in dict.fromkeys(dependencies) if dep in by_id]
    if not known_dependencies:
        return (
            "\nOptions:"
            f"\n  - Review in QuarterDeck: drydock run quarterdeck {target}"
            f"\n  - Inspect build state: drydock build status {target}"
        )
    first = known_dependencies[0]
    return (
        "\nOptions:"
        f"\n  - Review and normalize in QuarterDeck: drydock run quarterdeck {target}"
        f"\n  - Story Retry: drydock build {target} --step {first}"
        f"\n  - Inspect build state: drydock build status {target}"
    )


def _blocked_dependency_details(dependencies: tuple[str, ...], by_id: dict[str, PlanBlock]) -> str:
    lines: list[str] = []
    fatal_blocks: list[str] = []
    for dep in dict.fromkeys(dependencies):
        block = by_id.get(dep)
        if block is None:
            lines.append(f"  - {dep}: missing from MANIFEST.md")
            continue
        detail = f"  - {_block_label(block)}: state={block.state}"
        finding = block.fields.get("finding", "").strip()
        if finding:
            detail += f"; finding={finding}"
            if "rate limit" in finding.lower() or "session limit" in finding.lower():
                fatal_blocks.append(render_rate_limit_error_block(error=finding))
        lines.append(detail)
    if not lines:
        return ""
    block_text = "\nBlocking dependency status:\n" + "\n".join(lines)
    if fatal_blocks:
        block_text += "\n\n" + "\n\n".join(fatal_blocks)
    return block_text


def _verified_dependency(block_id: str, by_id: dict[str, PlanBlock]) -> bool:
    dependency = by_id.get(block_id)
    return dependency is not None and dependency.state in FINISHED_STATES


def _external_unverified_dependencies(
    feature: PlanBlock,
    pending: tuple[PlanBlock, ...],
    executable: tuple[PlanBlock, ...],
    by_id: dict[str, PlanBlock],
) -> tuple[str, ...]:
    """Return dependencies outside this block that are not yet verified.

    Dependencies between children of the same block are internal sequencing for
    the build agent. They do not split the block or make it unbuildable.
    """
    internal_ids = {child.block_id for child in executable}
    dependency_ids: list[str] = []
    dependency_ids.extend(dep for dep in feature.depends if dep not in internal_ids)
    for child in pending:
        dependency_ids.extend(dep for dep in child.depends if dep not in internal_ids)
    return tuple(
        dict.fromkeys(dep for dep in dependency_ids if not _verified_dependency(dep, by_id))
    )


def _first_pending_work_run(pending: tuple[PlanBlock, ...]) -> tuple[PlanBlock, ...]:
    """Return the first contiguous run of pending steps with the same work kind."""
    if not pending:
        return ()
    first_kind = work_kind_of(pending[0])
    run: list[PlanBlock] = []
    for child in pending:
        if work_kind_of(child) != first_kind:
            break
        run.append(child)
    return tuple(run)


def _feature_build_unit(plan: BuildPlan, feature: PlanBlock) -> BuildUnit | None:
    by_id = plan.by_id()
    executable = tuple(
        child for child in plan.children(feature.block_id) if child.block_type in {"story", "spike"}
    )
    if not executable:
        return None
    already_verified = tuple(child for child in executable if child.state in FINISHED_STATES)
    pending = tuple(child for child in executable if child.state in SELECTABLE_STATES)
    if not pending:
        return None
    pending = _first_pending_work_run(pending)
    if _external_unverified_dependencies(feature, pending, pending, by_id):
        return None
    return BuildUnit(
        block_id=feature.block_id,
        name=feature.name,
        block_type="feature",
        steps=pending,
        already_verified=already_verified,
    )


def _computed_block_label(number: int, steps: tuple[PlanBlock, ...]) -> str:
    story_type = steps[0].story_type.title() if steps else "Stories"
    return f"Block {number} · {story_type}"


def _computed_block_parts(
    plan: BuildPlan, number: int
) -> tuple[tuple[PlanBlock, ...], tuple[PlanBlock, ...], tuple[str, ...]]:
    by_id = plan.by_id()
    executable = next((steps for group, steps in plan.computed_groups() if group == number), ())
    pending = tuple(block for block in executable if block.state in SELECTABLE_STATES)
    verified = tuple(block for block in executable if block.state in FINISHED_STATES)
    available = {block.block_id for block in (*pending, *verified)}
    blockers = tuple(
        dict.fromkeys(
            dep
            for block in pending
            for dep in block.depends
            if dep not in available and not _verified_dependency(dep, by_id)
        )
    )
    return pending, verified, blockers


def _computed_build_unit(plan: BuildPlan, number: int) -> BuildUnit | None:
    pending, verified, blockers = _computed_block_parts(plan, number)
    if not pending or blockers:
        return None
    all_steps = next(steps for group, steps in plan.computed_groups() if group == number)
    return BuildUnit(
        block_id=f"block-{number}",
        name=_computed_block_label(number, all_steps),
        block_type="block",
        steps=pending,
        already_verified=verified,
    )


def _blocked_computed_block_message(plan: BuildPlan, number: int, target: str) -> str:
    pending, _, blockers = _computed_block_parts(plan, number)
    by_id = plan.by_id()
    label = f"Block {number}"
    if blockers:
        return (
            f"Build block {label} is blocked by unverified external dependencies: "
            + _dependency_labels(blockers, by_id)
            + _blocked_dependency_details(blockers, by_id)
            + _blocked_options(blockers, by_id, target)
        )
    states = ", ".join(f"{block.block_id}={block.state}" for block in pending) or "no pending work"
    return f"Build block {label} is not buildable; {states}"


def _blocked_block_message(plan: BuildPlan, feature: PlanBlock, target: str) -> str:
    by_id = plan.by_id()
    executable = tuple(
        child for child in plan.children(feature.block_id) if child.block_type in {"story", "spike"}
    )
    pending = tuple(child for child in executable if child.state in SELECTABLE_STATES)
    pending = _first_pending_work_run(pending)
    blockers = _external_unverified_dependencies(feature, pending, pending, by_id)
    if blockers:
        return (
            f"Build block {_block_label(feature)} is blocked by unverified external dependencies: "
            + _dependency_labels(blockers, by_id)
            + _blocked_dependency_details(blockers, by_id)
            + _blocked_options(blockers, by_id, target)
        )
    return (
        f"{_block_label(feature)} is not buildable; state={feature.state!r}, "
        "dependencies must be closed/verified"
    )


def _containing_feature(block: PlanBlock, by_id: dict[str, PlanBlock]) -> PlanBlock | None:
    if not block.parent:
        return None
    parent = by_id.get(block.parent)
    if parent is None or parent.block_type != "feature":
        return None
    return parent


def _resolve_step_selector(plan: BuildPlan, selector: str) -> str:
    """Resolve a ``--step`` token to a canonical block id.

    Accepts the block id exactly, the block id case-insensitively, or the block
    display name case-insensitively, matched against feature/story/spike blocks.
    On no match, raises with the valid selectors so the operator can retry.
    """
    by_id = plan.by_id()
    if selector in by_id:
        return selector
    lowered = selector.strip().lower()
    if plan.uses_computed_blocks:
        computed_ids = {f"block-{number}" for number, _ in plan.computed_groups()}
        if lowered in computed_ids:
            return lowered
        computed_names = {
            _computed_block_label(number, steps).lower(): f"block-{number}"
            for number, steps in plan.computed_groups()
        }
        if lowered in computed_names:
            return computed_names[lowered]
    selectable = [b for b in plan.blocks if b.block_type in {"feature", "story", "spike"}]
    for block in selectable:
        if block.block_id.lower() == lowered:
            return block.block_id
    name_matches = [b for b in selectable if b.name.strip().lower() == lowered]
    if len(name_matches) == 1:
        return name_matches[0].block_id
    if len(name_matches) > 1:
        ids = ", ".join(b.block_id for b in name_matches)
        raise SpecificationError(
            f"--step {selector!r} matches multiple blocks by name; use an id: {ids}"
        )
    valid = ", ".join(b.block_id for b in selectable) or "(none)"
    raise SpecificationError(
        f"Build step {selector!r} not found in MANIFEST.md.\n  Valid --step ids: {valid}"
    )


def _select_build_unit(
    plan: BuildPlan, step_id: str | None, target: str, story_id: str | None = None
) -> BuildUnit | None:
    by_id = plan.by_id()
    if story_id is not None:
        # Single-story selection: build exactly this story/spike, even when it sits inside a
        # feature. This deliberately bypasses feature-group promotion so the operator can
        # rebuild one story alone; buildability (verified dependencies) is still enforced.
        block = by_id.get(story_id)
        if block is None:
            raise SpecificationError(f"Build step {story_id!r} not found in MANIFEST.md")
        if block.block_type not in {"story", "spike"} or not _is_buildable(block, by_id):
            raise SpecificationError(
                f"{_block_label(block)} is not buildable; state={block.state!r}, "
                "dependencies must be closed/verified"
            )
        return BuildUnit(
            block_id=block.block_id,
            name=block.name,
            block_type=block.block_type,
            steps=(block,),
        )
    if step_id is not None:
        if plan.uses_computed_blocks:
            if step_id.startswith("block-") and step_id.removeprefix("block-").isdigit():
                number = int(step_id.removeprefix("block-"))
            else:
                selected = by_id.get(step_id)
                if selected is None or selected.computed_block is None:
                    raise SpecificationError(f"Build step {step_id!r} not found in MANIFEST.md")
                number = selected.computed_block
            unit = _computed_build_unit(plan, number)
            if unit is None:
                raise SpecificationError(_blocked_computed_block_message(plan, number, target))
            return unit
        block = by_id.get(step_id)
        if block is None:
            raise SpecificationError(f"Build step {step_id!r} not found in MANIFEST.md")
        if block.block_type == "feature":
            unit = _feature_build_unit(plan, block)
            if unit is None:
                raise SpecificationError(_blocked_block_message(plan, block, target))
            return unit
        parent = _containing_feature(block, by_id)
        if parent is not None:
            unit = _feature_build_unit(plan, parent)
            if unit is None:
                raise SpecificationError(_blocked_block_message(plan, parent, target))
            return unit
        if block.block_type not in {"story", "spike"} or not _is_buildable(block, by_id):
            raise SpecificationError(
                f"{_block_label(block)} is not buildable; state={block.state!r}, "
                "dependencies must be closed/verified"
            )
        return BuildUnit(
            block_id=block.block_id,
            name=block.name,
            block_type=block.block_type,
            steps=(block,),
        )

    if plan.uses_computed_blocks:
        for number, executable in plan.computed_groups():
            if not any(block.state in SELECTABLE_STATES for block in executable):
                continue
            unit = _computed_build_unit(plan, number)
            if unit is None:
                raise SpecificationError(_blocked_computed_block_message(plan, number, target))
            return unit
        return None

    for block in plan.blocks:
        if block.block_type == "feature":
            unit = _feature_build_unit(plan, block)
            if unit is not None:
                return unit
            if any(
                child.block_type in {"story", "spike"} and child.state in SELECTABLE_STATES
                for child in plan.children(block.block_id)
            ):
                raise SpecificationError(_blocked_block_message(plan, block, target))
        if (
            block.block_type in {"story", "spike"}
            and _containing_feature(block, by_id) is None
            and block.state in SELECTABLE_STATES
        ):
            if not _is_buildable(block, by_id):
                raise SpecificationError(
                    f"Build block {_block_label(block)} is blocked by unverified external dependencies: "
                    + _dependency_labels(block.depends, by_id)
                    + _blocked_dependency_details(block.depends, by_id)
                    + _blocked_options(block.depends, by_id, target)
                )
            return BuildUnit(
                block_id=block.block_id,
                name=block.name,
                block_type=block.block_type,
                steps=(block,),
            )
    return None


# Transient or generated paths that are not build output. They are excluded from the
# change-detection snapshot so bytecode caches, tool caches, and version-control metadata
# never register as "files changed" or pollute the build's file delta.
_SNAPSHOT_IGNORE_DIRS = frozenset({
    ".git",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".hypothesis",
    ".tox",
    ".venv",
    "node_modules",
})
_SNAPSHOT_IGNORE_SUFFIXES = (".pyc", ".pyo")


def _is_ignored_snapshot_path(rel: Path) -> bool:
    """True for transient/generated paths that are not tracked build output."""
    if any(part in _SNAPSHOT_IGNORE_DIRS for part in rel.parts):
        return True
    return rel.suffix in _SNAPSHOT_IGNORE_SUFFIXES


def _snapshot_files(root: Path) -> dict[str, FileFingerprint]:
    """Return a stable fingerprint map for regular files under ``root``.

    Transient and generated paths (``__pycache__``, ``*.pyc``, tool caches, ``.git``) are
    excluded so they never register as build output.
    """
    snapshots: dict[str, FileFingerprint] = {}
    if not root.is_dir():
        return snapshots
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(root)
        if _is_ignored_snapshot_path(rel):
            continue
        data = path.read_bytes()
        snapshots[str(rel)] = FileFingerprint(size=len(data), digest=sha256(data).hexdigest())
    return snapshots


def _written_files(
    before: dict[str, FileFingerprint],
    after: dict[str, FileFingerprint],
) -> tuple[str, ...]:
    """Return created/modified files under the build directory."""
    changed: list[str] = []
    for rel, fp in after.items():
        if before.get(rel) != fp:
            changed.append(rel)
    return tuple(changed)


def _source_roles(target_dir: Path) -> dict[str, SourceRole]:
    """Read the Analysis source-role table. No analysis means no declared assets to stage."""
    analysis = target_dir / "ANALYSIS.md"
    if not analysis.is_file():
        return {}
    return parse_source_roles(analysis.read_text(encoding="utf-8"))


def _file_sha256(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _blueprint_spec_files(
    assembly: StepAssembly, blueprint_dir: Path
) -> tuple[tuple[str, Path], ...]:
    """Return Blueprint files from implements/context for applied-spec tracking."""
    files: list[tuple[str, Path]] = []
    seen: set[str] = set()
    for step_file in assembly.files:
        if step_file.missing or step_file.source is None:
            continue
        if step_file.role not in {"implements", "context"}:
            continue
        try:
            rel = str(step_file.source.relative_to(blueprint_dir))
        except ValueError:
            continue
        if rel not in seen:
            files.append((rel, step_file.source))
            seen.add(rel)
    return tuple(files)


def _stale_applied_specs(plan_path: Path, blueprint_dir: Path) -> tuple[str, ...]:
    plan = parse_build_plan(plan_path)
    details: list[str] = []
    for spec in stale_applied_specs(plan, blueprint_dir):
        if spec.reason == "missing":
            details.append(
                f"{spec.rel_path}: missing (applied_by={spec.record.applied_by}, "
                f"recorded_commit={spec.record.commit})"
            )
            continue
        current_commit = _git_file_commit(blueprint_dir / spec.rel_path)
        details.append(
            f"{spec.rel_path}: recorded_commit={spec.record.commit}, "
            f"current_commit={current_commit}, "
            f"recorded_sha256={spec.record.sha256[:12]}, "
            f"current_sha256={spec.current_sha256[:12]}"
        )
    return tuple(details)


def _ensure_applied_specs_current(plan_path: Path, blueprint_dir: Path) -> tuple[str, ...]:
    """Report changed applied specs without blocking; reject specs that disappeared.

    A Blueprint edit is an authoring event, not a request for Drydock to rewrite its
    compact derivative or silently run ``refit``.  The build therefore continues against
    the current full source and leaves any existing compact derivative untouched.  A
    missing applied source remains fatal because the build no longer has the declared input.
    """
    plan = parse_build_plan(plan_path)
    stale = stale_applied_specs(plan, blueprint_dir)
    if not stale:
        return ()
    missing = [spec for spec in stale if spec.reason == "missing"]
    if missing:
        lines = ["Build blocked: previously applied Blueprint specifications are missing."]
        lines.extend(
            f"  - {spec.rel_path}: missing (applied_by={spec.record.applied_by}, "
            f"recorded_commit={spec.record.commit})"
            for spec in missing
        )
        raise SpecificationError("\n".join(lines))

    foundational = sorted({
        name for spec in stale if (name := foundational_source(spec.rel_path)) is not None
    })
    lines = ["WARNING: Previously applied Blueprint specifications changed; build continues."]
    for name in foundational:
        lines.append(
            f"WARNING: {name} changed. Existing compact derivatives are not regenerated; "
            "existing compact derivatives are used."
        )
    if any(foundational_source(spec.rel_path) is None for spec in stale):
        lines.append(
            "WARNING: non-foundational Blueprint specifications changed. Existing compact "
            "derivatives are not regenerated; existing compact derivatives are used."
        )
    lines.extend(f"  - {detail}" for detail in _stale_applied_specs(plan_path, blueprint_dir))
    return tuple(lines)


_RESULT_RE = re.compile(r"RESULT:\s*(SUCCESS|FAILURE|FAIL|ERROR)", re.IGNORECASE)


def _reported_result(summary: str) -> str | None:
    """Return the agent's self-reported RESULT token, or ``None`` if absent.

    The report contract asks the agent to end with ``RESULT: SUCCESS|FAILURE``. Streaming can
    concatenate output without line breaks, so the token is matched anywhere in the text, not
    only at the start of a line. A missing token is not treated as failure — the observed file
    delta and programmatic acceptance are the authority for whether a step succeeded.
    """
    match = _RESULT_RE.search(summary)
    if not match:
        return None
    return "FAILURE" if match.group(1).upper() in {"FAILURE", "FAIL", "ERROR"} else "SUCCESS"


# Signatures that classify a build failure so a rerun is informed rather than opaque.
# The execution-environment signatures name the specific codex sandbox breakage
# (missing ``codex-linux-sandbox`` helper invoked via ``bwrap``) so it self-identifies
# if it ever recurs, instead of collapsing to "no build files written".
_SANDBOX_SIGNATURES = (
    "codex-linux-sandbox",
    "bwrap: execvp",
    "execvp codex",
    "landlock",
    "seccomp",
    "sandbox denied",
    "failed to spawn sandbox",
)
_TOKEN_SIGNATURES = (
    "context length",
    "maximum context",
    "context window",
    "token limit",
    "prompt is too long",
    "too many tokens",
    "exceeds the maximum",
    "context_length_exceeded",
)

_FAILURE_SUMMARY_RE = re.compile(r"^\s*FAILURE_SUMMARY:\s*(.+)$", re.IGNORECASE | re.MULTILINE)
_FAILURE_DETAIL_RE = re.compile(
    r"^\s*FAILURE_DETAIL:\s*(.+)", re.IGNORECASE | re.MULTILINE | re.DOTALL
)
_REUSABLE_COMPACT_RE = re.compile(
    r'<reusable-compact\s+filename="(?P<filename>[^"]+)">\s*'
    r"(?P<body>.*?)\s*</reusable-compact>",
    re.IGNORECASE | re.DOTALL,
)
_BUILD_REPORT_SECTION_RE = re.compile(
    r"^\s*(?P<name>SUMMARY|BLOCKERS):\s*\n?(?P<body>.*?)"
    r"(?=^\s*(?:RESULT|FILES CHANGED|SUMMARY|BLOCKERS|FAILURE_SUMMARY|FAILURE_DETAIL):|\Z)",
    re.IGNORECASE | re.MULTILINE | re.DOTALL,
)

# Category prefix for a build agent's own declared failure. Such a self-report is advisory:
# when the agent still wrote files, the deterministic acceptance gate is the authority.
_AGENT_REPORTED_PREFIX = "agent-reported failure"
# Category for a step whose observed file delta is empty. Like the self-report above it is
# advisory whenever the block carries acceptance criteria: an empty delta is a statement about
# the agent's work, not about the environment, and a step that rewrites a correct file with
# identical bytes produces one.
_NO_FILES_WRITTEN = "no build files written"


def _parse_agent_failure(summary: str) -> tuple[str, str]:
    """Extract the agent's structured ``FAILURE_SUMMARY`` / ``FAILURE_DETAIL`` report."""
    summary_match = _FAILURE_SUMMARY_RE.search(summary)
    detail_match = _FAILURE_DETAIL_RE.search(summary)
    agent_summary = summary_match.group(1).strip() if summary_match else ""
    agent_detail = detail_match.group(1).strip() if detail_match else ""
    return agent_summary, agent_detail


def _parse_build_report(summary: str) -> tuple[str, str]:
    """Return the build agent's human summary and blockers for terminal reporting."""
    sections = {
        match.group("name").upper(): " ".join(match.group("body").strip().split())
        for match in _BUILD_REPORT_SECTION_RE.finditer(summary)
    }
    return sections.get("SUMMARY", ""), sections.get("BLOCKERS", "")


def _persist_reusable_compacts(
    summary: str,
    sources: tuple[Path, ...],
    *,
    blueprint_dir: Path,
    today: str,
) -> tuple[str, ...]:
    """Persist valid same-response compacts requested for later build blocks.

    Compact payloads are advisory: malformed, unexpected, duplicate, and no-surface
    payloads are ignored so they can never alter the build outcome.
    """
    allowed = {source.name: source for source in sources}
    written: list[str] = []
    seen: set[str] = set()
    for match in _REUSABLE_COMPACT_RE.finditer(summary):
        filename = match.group("filename").strip()
        body = match.group("body").strip()
        source = allowed.get(filename)
        if source is None or filename in seen or not body or body.startswith("COMPACT_ERROR:"):
            continue
        seen.add(filename)
        compact = source.with_name(f"{source.stem}_compact.md")
        if compact.is_file():
            continue
        digest = sha256(source.read_bytes()).hexdigest()
        provenance = (
            f"<!-- Compacted from {source.relative_to(blueprint_dir).as_posix()} sha256={digest} "
            f"on {today} by drydock build agent -->"
        )
        compact.write_text(f"{provenance}\n\n{body}\n", encoding="utf-8", newline="\n")
        written.append(compact.name)
    return tuple(written)


def _result_provider_error(result: object) -> str | None:
    """Return the provider-level error persisted on the execution record, if any."""
    record = getattr(result, "record", None)
    if isinstance(record, Mapping):
        res = record.get("result")
        if isinstance(res, Mapping) and res.get("error"):
            return str(res["error"]).strip()
    return None


def _classify_failure(
    summary: str,
    *,
    ok: bool,
    wrote_files: tuple[str, ...],
    stderr: str = "",
    provider_error: str | None = None,
) -> tuple[str, str] | None:
    """Classify a build step's failure, or return ``None`` when it succeeded.

    Returns ``(category, detail)``: a concise category for the manifest ``finding:`` and a
    fuller detail for the evidence ``## Failure`` section. Signature matching runs before the
    coarse pass/fail authority so a run that exits cleanly but could not execute any command
    (e.g. a missing OS sandbox helper) names the real cause instead of "no build files written".
    """
    text = summary or ""
    haystack = "\n".join(part for part in (text, stderr, provider_error or "") if part).lower()

    if provider_error:
        low = provider_error.lower()
        if "rate limit" in low:
            return "provider rate limit", provider_error
        if "timed out" in low:
            return "execution timed out", provider_error
        if "provider error" in low or "api" in low:
            return "provider error", provider_error

    if any(sig in haystack for sig in _SANDBOX_SIGNATURES):
        detail = (
            "The build agent could not execute commands in this environment: the codex OS "
            "sandbox helper (codex-linux-sandbox) is unavailable. Set codex_sandbox to "
            "'danger-full-access' (runs in the invoking shell) or install the helper, then rerun."
        )
        return "execution environment unavailable", detail

    if any(sig in haystack for sig in _TOKEN_SIGNATURES):
        detail = (
            "The model reported a context or token limit. Reduce the step's stacked context "
            "(split the block or compact its sources), then rerun."
        )
        return "context/token limit", detail

    if not ok:
        detail = stderr.strip() or provider_error or "The provider process exited non-zero."
        return "LLM execution failed", detail

    if not text.strip():
        return "empty output", "The build agent returned no output."

    if _reported_result(text) == "FAILURE":
        agent_summary, agent_detail = _parse_agent_failure(text)
        interruption = "keyboardinterrupt" in haystack or "interrupted" in haystack
        if interruption:
            detail = (
                "A target verification command was interrupted inside the build-agent session. "
                "Drydock did not configure an LLM execution timeout for this build. "
                + (agent_detail or agent_summary or "Inspect execution evidence for the command.")
            )
            return "target verification interrupted by build agent", detail
        category = (
            f"{_AGENT_REPORTED_PREFIX}: {agent_summary}"
            if agent_summary
            else _AGENT_REPORTED_PREFIX
        )
        detail = agent_detail or agent_summary or text.strip()
        return category, detail

    if not wrote_files:
        return _NO_FILES_WRITTEN, "The build agent completed but changed no files."

    return None


def _resource_verdict(result: AcceptanceRunResult) -> bool:
    """True when a check failed by exhausting memory or time, not by missing an expectation."""
    error = result.error or ""
    return error.startswith((MEMORY_FAILURE_PREFIX, TIMEOUT_FAILURE_PREFIX))


def _malformed_verdict(result: AcceptanceRunResult | AcceptanceObservation) -> bool:
    """True when a check failed inside its own snippet rather than in the code under test."""
    return (result.error or "").startswith(MALFORMED_FAILURE_PREFIX)


def _assertion_summary(result: AcceptanceRunResult) -> str:
    """The concrete reason a programmatic check failed, in one line."""
    return assertion_summary(
        result.stderr,
        result.error,
        override=str(result.error) if _resource_verdict(result) else None,
    )


def _render_ac_failure_chain(
    unit: BuildUnit,
    failed: tuple[AcceptanceRunResult, ...],
    story_by_check: dict[str, PlanBlock],
) -> str:
    """Render a Block → Story → AC failure chain naming the story that missed its own DoD.

    The build unit is one step, but every acceptance check maps back to the story whose spec
    declared it, so the report attributes each failure to the story that owns it and states the
    concrete assertion that failed.
    """
    by_story: dict[str, list[AcceptanceRunResult]] = {}
    order: list[str] = []
    for result in failed:
        story = story_by_check.get(result.check_id)
        key = story.block_id if story is not None else "?"
        if key not in by_story:
            by_story[key] = []
            order.append(key)
        by_story[key].append(result)

    lines = [f'Block "{unit.name}" [{unit.block_id}] failed its acceptance criteria.']
    for key in order:
        story = next(
            (s for r in by_story[key] if (s := story_by_check.get(r.check_id)) is not None), None
        )
        label = f'"{story.name}" [{story.block_id}]' if story is not None else "(unattributed)"
        lines.append(f"  Story {label} does not meet its own acceptance criteria:")
        for result in by_story[key]:
            intent = result.intent.strip() or result.check_id
            lines.append(f"    - AC {result.check_id} — {intent}")
            # The assertion alone does not say why it failed. The check prints what it captured
            # before asserting, so the runner's own account of the run is already in stdout —
            # carry its tail into the report rather than making the reader open the evidence file.
            lines.extend(
                failure_detail(
                    stderr=result.stderr,
                    stdout=result.stdout,
                    return_code=result.return_code,
                    error=result.error,
                    override=str(result.error) if _resource_verdict(result) else None,
                    indent="        ",
                )
            )
    return "\n".join(lines)


def _build_outcome(
    summary: str,
    *,
    ok: bool,
    wrote_files: tuple[str, ...],
    stderr: str = "",
    provider_error: str | None = None,
) -> tuple[str, str, str | None, str]:
    """Map provider result + observed file delta + optional self-report to an outcome.

    Returns ``(state, status, error, detail)``. ``error`` is the classified category carried
    onto the manifest ``finding:``; ``detail`` is the fuller explanation written to the evidence
    ``## Failure`` section. A missing or unparsable report does not fail the step: the filesystem
    delta already records what changed, and programmatic acceptance is the real gate.
    """
    classified = _classify_failure(
        summary, ok=ok, wrote_files=wrote_files, stderr=stderr, provider_error=provider_error
    )
    if classified is None:
        return "", "", None, ""
    category, detail = classified
    return "closed/failed", "failed", category, detail


def _dependency_gate_failure(result: DependencyGateResult) -> tuple[str, str]:
    summary = f"dependency legitimacy gate failed: {len(result.issues)} issue(s)"
    lines = [
        "Changed Python dependency manifests introduced unverified package names.",
        "Blocked packages:",
    ]
    for issue in result.issues:
        detail = (
            f"- {issue.package_name} [{issue.verdict}] in {issue.source_file}; "
            f"registry={issue.registry_url}"
        )
        if issue.first_published_at is not None and issue.age_days is not None:
            detail += (
                f"; first_published={issue.first_published_at.date().isoformat()}; "
                f"age_days={issue.age_days}"
            )
        detail += f"; detail={issue.detail}"
        lines.append(detail)
    return summary, "\n".join(lines)


def _clip(text: str, limit: int = 240) -> str:
    """Collapse whitespace to a single line and truncate to ``limit`` characters."""
    collapsed = " ".join(text.split())
    return collapsed if len(collapsed) <= limit else collapsed[: limit - 1].rstrip() + "…"


@dataclass(frozen=True)
class AttemptRecord:
    """One build pass over a block: attempt 0 is the initial build, 1.. are repairs."""

    index: int
    execution_id: str | None
    model: str | None
    passed_checks: int
    total_checks: int
    passed_check_ids: tuple[str, ...]
    passed_cases: int | None
    total_cases: int | None
    case_tallies: tuple[tuple[str, int, int], ...]
    status: str
    stop_reason: str | None = None


#: Calls a block may spend and still be considered correctly sized: the initial build plus three
#: repairs. Beyond this the block went green, but only after the model rediscovered the work
#: several times, which is a Manifest problem rather than a build problem.
_SIZING_ADVISORY_CALLS = 4

_REPAIR_FEEDBACK_CAP = 4000
_CASE_TALLY_RE = re.compile(
    r"(?m)(?P<passed>\d+)\s+passed,\s+"
    r"(?P<failed>\d+)\s+failed"
    r"(?:,\s+(?P<errored>\d+)\s+errored)?"
)


#: Names a block failed by its governed stage gate rather than by a model-authored criterion.
GOVERNED_FAILURE_PREFIX = "governed acceptance failed"
#: A block that broke a criterion an earlier block had already proven. Repairable by
#: construction: working code for it existed in this same tree one block ago.
REGRESSION_FAILURE_PREFIX = "acceptance regression"


def _is_repairable(error: str | None) -> bool:
    """True when a failed block can be driven green by another informed LLM pass.

    A governed gate failure, a programmatic-acceptance miss, or a surviving agent-reported
    failure is repairable: the build directory holds the partial work and the failing gate or
    checks name what remains. A red governed gate is the most repairable signal there is — it
    is the authoritative statement of what the product still gets wrong — so it must buy passes
    rather than end the block with the budget unspent. Every other classification (token/context limit, sandbox unavailable,
    provider error, dependency gate, staged-asset tamper, no files written) is terminal
    and never loops — re-running it only wastes a pass. ``no files written`` reaches here
    only for a block with no acceptance criteria; with criteria it is downgraded to advisory
    before this point and the acceptance verdict is what gets classified.
    """
    if not error:
        return False
    return error.startswith((
        "programmatic acceptance failed",
        REGRESSION_FAILURE_PREFIX,
        GOVERNED_FAILURE_PREFIX,
        _AGENT_REPORTED_PREFIX,
    ))


# The objective escape hatch. An agent that has run a criterion and concluded the criterion
# itself cannot pass emits this line; Drydock stops the repair loop on it without interpreting
# prose. Prose inference (``_DEFECT_CLAIM_TERMS`` below) remains as a fallback for agents that
# describe the defect without using the token, but the token is the contract.
_AC_BROKEN_RE = re.compile(r"^\s*AC[_ -]?BROKEN:\s*(?P<ids>.*)$", re.IGNORECASE | re.MULTILINE)


def _ac_broken_claim(
    summary: str,
    failed_checks: tuple[AcceptanceRunResult, ...],
) -> tuple[str, ...]:
    """Return failing check ids the agent declared broken via the ``AC_BROKEN:`` token.

    The token carries a comma-separated id list. Ids that are not currently failing are
    ignored: an agent cannot condemn a criterion that passed. A token with no recognizable id
    claims every failing check, because an agent that emits it has already concluded no repair
    pass can succeed — and the claim only ever reaches the existing terminal outcome sooner.
    """
    if not failed_checks:
        return ()
    matches = tuple(_AC_BROKEN_RE.finditer(summary))
    if not matches:
        return ()
    failing = {check.check_id for check in failed_checks}
    claimed: list[str] = []
    for match in matches:
        for raw in match.group("ids").replace(";", ",").split(","):
            candidate = raw.strip().strip("`\"'[]")
            if candidate in failing and candidate not in claimed:
                claimed.append(candidate)
    if claimed:
        return tuple(check.check_id for check in failed_checks if check.check_id in claimed)
    return tuple(check.check_id for check in failed_checks)


# Vocabulary that distinguishes "this criterion is itself broken" from an agent merely
# mentioning the check it failed. Naming a check is not a claim about it; these words are.
_DEFECT_CLAIM_TERMS = (
    "malformed",
    "defective",
    "mis-authored",
    "misauthored",
    "mis-written",
    "incorrectly written",
    "broken",
    "invalid",
    "cannot pass",
    "can never pass",
    "cannot be satisfied",
    "can never be true",
    "always fails",
    "always fail",
    "incorrectly reject",
    "unsatisfiable",
)


def _normalize_words(text: str) -> list[str]:
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).split()


def _names_check(words: list[str], check_id: str) -> bool:
    """True when ``words`` contains the check id, or a distinctive tail of it.

    Agents name a criterion the way a reader would — ``scoped-number`` for
    ``verification-scoped-number`` — so an exact-id match alone would almost never fire. Any
    contiguous run of two or more trailing id tokens counts, which keeps the match specific
    without demanding the full identifier.
    """
    tokens = _normalize_words(check_id)
    if not tokens:
        return False
    for start in range(len(tokens) - 1):
        tail = tokens[start:]
        span = len(tail)
        if any(words[i : i + span] == tail for i in range(len(words) - span + 1)):
            return True
    return False


def _defective_acceptance_claim(
    agent_report: tuple[str, ...] | None,
    failed_checks: tuple[AcceptanceRunResult, ...],
) -> tuple[str, ...]:
    """Return the failing check ids the agent reported as defective criteria.

    A repair pass cannot rewrite a criterion: staged acceptance assets are restored before
    grading, so a genuinely broken assertion consumes the whole budget and fails identically
    every time. When the agent both names a failing check and claims it is broken, stop
    immediately and point the operator at the Blueprint.

    The self-report stays advisory. This path never marks a block verified and never hides an
    acceptance failure — it only reaches the same terminal outcome sooner and with the right
    diagnosis. An agent that lies here buys itself an earlier failure, not a pass.
    """
    if agent_report is None or not failed_checks:
        return ()
    words = _normalize_words(" ".join(agent_report))
    if not words:
        return ()
    claim = " ".join(words)
    if not any(term.replace("-", " ") in claim for term in _DEFECT_CLAIM_TERMS):
        return ()
    return tuple(check.check_id for check in failed_checks if _names_check(words, check.check_id))


def _output_tail(result: AcceptanceRunResult, max_lines: int = 6) -> list[str]:
    """Return the most informative tail of a failed check's captured output.

    A conformance suite prints its ``N passed, M failed`` tally to stdout; a bare
    assertion carries its traceback on stderr. Prefer whichever stream has content.
    """
    source = result.stdout if result.stdout.strip() else result.stderr
    lines = [line.rstrip() for line in source.splitlines() if line.strip()]
    return lines[-max_lines:]


def _case_tally(result: AcceptanceRunResult) -> tuple[int, int] | None:
    """Return the last ``passed/total`` subcase tally printed by an acceptance check."""
    matches = tuple(_CASE_TALLY_RE.finditer(f"{result.stdout}\n{result.stderr}"))
    if not matches:
        return None
    match = matches[-1]
    passed = int(match.group("passed"))
    failed = int(match.group("failed"))
    errored = int(match.group("errored") or 0)
    return passed, passed + failed + errored


def _acceptance_case_totals(
    acceptance: tuple[AcceptanceRunResult, ...],
) -> tuple[int | None, int | None]:
    """Aggregate quantitative subcase tallies without inventing cases for scalar ACs."""
    tallies = [tally for result in acceptance if (tally := _case_tally(result)) is not None]
    if not tallies:
        return None, None
    return sum(tally[0] for tally in tallies), sum(tally[1] for tally in tallies)


def _acceptance_case_tallies(
    acceptance: tuple[AcceptanceRunResult, ...],
) -> tuple[tuple[str, int, int], ...]:
    """Return stable per-AC ``(check_id, passed, total)`` quantitative progress."""
    return tuple(
        (result.check_id, tally[0], tally[1])
        for result in acceptance
        if (tally := _case_tally(result)) is not None
    )


def _quantitative_acceptance_progress(
    previous: tuple[tuple[str, int, int], ...],
    current: tuple[tuple[str, int, int], ...],
) -> bool:
    """True only when every comparable AC is non-regressing and at least one improves."""
    previous_by_id = {check_id: (passed, total) for check_id, passed, total in previous}
    current_by_id = {check_id: (passed, total) for check_id, passed, total in current}
    if not previous_by_id or current_by_id.keys() != previous_by_id.keys():
        return False
    improved = False
    for check_id, (previous_passed, previous_total) in previous_by_id.items():
        current_passed, current_total = current_by_id[check_id]
        if current_total != previous_total or current_passed < previous_passed:
            return False
        improved = improved or current_passed > previous_passed
    return improved


def _attempt_acceptance_summary(
    attempt: int,
    acceptance: tuple[AcceptanceRunResult, ...],
) -> str:
    """Render one concise, operator-facing acceptance summary for an LLM attempt."""
    passed = sum(1 for result in acceptance if result.passed)
    skipped = tuple(result for result in acceptance if result.skipped)
    missed = tuple(result for result in acceptance if not result.passed and not result.skipped)
    failed = tuple(result for result in missed if result.binding)
    disputed = tuple(result for result in missed if not result.binding)
    line = f"acceptance: call {attempt + 1} · {passed}/{len(acceptance)} AC passed"
    if skipped:
        line += " · skipped: " + ", ".join(result.check_id for result in skipped)
    if disputed:
        line += " · disputed: " + ", ".join(result.check_id for result in disputed)
    if not failed:
        return line
    return line + " · failed: " + _acceptance_failure_details(failed)


def _acceptance_failure_details(
    failed: tuple[AcceptanceRunResult, ...],
) -> str:
    """Render failed AC ids with quantitative case tallies when available."""
    details: list[str] = []
    for result in failed:
        tally = _case_tally(result)
        cases = f" ({tally[0]}/{tally[1]} cases)" if tally is not None else ""
        details.append(f"{result.check_id}{cases}")
    return ", ".join(details)


def _console_failure_lines(result: AcceptanceRunResult, max_lines: int = 5) -> list[str]:
    """Lines that show an operator what a failed check was doing when it failed.

    Both streams matter and they carry different halves of the story: a runner prints its
    ``N passed, M failed`` tally to stdout while the assertion that tripped lands on stderr.
    A reader who sees only the assertion cannot tell a two-case shortfall from a runner
    invoked against the wrong case count; seeing the tally next to it makes that obvious at a
    glance. Each stream is tailed separately so one long stream cannot crowd out the other.
    """
    lines: list[str] = []
    for label, stream in (("stdout", result.stdout), ("stderr", result.stderr)):
        tail = [line.rstrip() for line in stream.splitlines() if line.strip()][-max_lines:]
        if not tail:
            continue
        lines.append(f"{label}:")
        lines.extend(f"  {line}" for line in tail)
    if not lines and result.error:
        lines.append(result.error)
    return lines


def _render_regression_detail(
    regressed: tuple[AcceptanceRunResult, ...],
    owners: dict[str, PlanBlock],
) -> str:
    """Name each previously proven criterion this block turned red, and who owns it."""
    lines = [
        "This block broke acceptance criteria that earlier blocks had already proven.",
        "They were green when the previous block finished and are red now.",
    ]
    for result in regressed:
        owner = owners.get(result.check_id)
        label = f' — story "{owner.name}" [{owner.block_id}]' if owner is not None else ""
        lines.append(f"  - {result.check_id} ({result.source}){label}")
        lines.extend(
            failure_detail(
                stderr=result.stderr,
                stdout=result.stdout,
                return_code=result.return_code,
                error=result.error,
                override=str(result.error) if _resource_verdict(result) else None,
                indent="      ",
            )
        )
    return "\n".join(lines)


def _render_repair_feedback(
    unit: BuildUnit,
    failed_checks: tuple[AcceptanceRunResult, ...],
    agent_report: tuple[str, str] | None,
    changed_files: tuple[str, ...],
    story_by_check: dict[str, PlanBlock],
    regressed_checks: tuple[AcceptanceRunResult, ...] = (),
) -> str:
    """Compose the repair-pass feedback appended as the prompt's recency anchor.

    The build directory already holds the previous attempt's partial work; this block
    tells the agent to iterate it toward green, names each failing check with its
    distilled assertion and output tail, and echoes the agent's own failure note.
    Content is capped so the repair prompt cannot itself trip the token gate.
    """
    lines: list[str] = [
        "## Repair pass",
        "",
        "A previous build pass wrote partial work into BUILD_DIRECTORY and did not pass",
        "every deterministic acceptance check. Iterate the existing files in",
        "BUILD_DIRECTORY to make the checks below pass. Do not restart from scratch, do",
        "not weaken or remove any declared acceptance assertion, and keep every check",
        "that already passes green.",
        "",
        "The diagnostic excerpts below are truncated. Before editing, rerun each failing",
        "acceptance assertion from its authoritative specification and inspect the complete",
        "failure output. For a conformance suite, use its section or example filters to",
        "diagnose coherent root-cause clusters, then rerun the full declared scope. Fix the",
        "general parser or renderer behavior; do not add example-specific exceptions. Keep",
        "working through failing examples while the deterministic tally is improving.",
        "",
        "If a check below cannot pass however the code is written — the command it runs",
        "succeeds and the assertion still fails — do not keep repairing. Report it with",
        "`AC_BROKEN: <check-id>` and explain the contradiction in `FAILURE_DETAIL`. That",
        "ends the repair budget and sends the criterion back for repair in the Blueprint,",
        "which is where a broken assertion has to be fixed.",
        "",
    ]
    if regressed_checks:
        # A regression outranks this block's own red criteria. The block already had working
        # code for these and deleted or broke it, so the repair is a restoration, not a new
        # implementation — and saying so stops the pass rewriting a subsystem that was correct.
        lines.extend([
            "### Regression — fix this first",
            "",
            "The criteria below belong to earlier stories that were already proven. They were",
            "green before this block ran and are red now, so this block's edits broke them.",
            "Restore the behavior they assert without discarding this block's own work, and do",
            "not edit the criteria.",
            "",
        ])
        for result in regressed_checks:
            lines.append(f"- {result.check_id} ({result.source}): {result.intent.strip()}")
            lines.append(f"    assertion: {_assertion_summary(result)}")
            tail = _output_tail(result)
            if tail:
                lines.append("    output:")
                lines.extend(f"      {line}" for line in tail)
        lines.append("")
    exhausted = tuple(result for result in failed_checks if _resource_verdict(result))
    if exhausted:
        # State the resource fact before the check list. A pass that reads only "the check
        # failed" tunes behavior, and no expectation is reachable while the code is being
        # killed. Each check's own error carries what the kill established; the heading must
        # not upgrade that into a diagnosis the harness cannot support from a timeout alone.
        lines.extend([
            "### Resource exhaustion — fix this first",
            "",
            "The following checks did not fail an expectation. The code under test was",
            "stopped by the harness for exhausting memory or time. Read each error below for",
            "what that establishes; where it points at an unbounded loop or allocation, fix",
            "that first. Tuning output to match an expectation will not clear this.",
            "",
        ])
        for result in exhausted:
            lines.append(f"- {result.check_id}: {result.error}")
        lines.append("")
    if failed_checks:
        lines.append("### Still failing")
        for result in failed_checks:
            story = story_by_check.get(result.check_id)
            owner = f" (story {story.block_id})" if story is not None else ""
            intent = result.intent.strip() or result.check_id
            lines.append(f"- {result.check_id}{owner}: {intent}")
            lines.append(f"    assertion: {_assertion_summary(result)}")
            tail = _output_tail(result)
            if tail:
                lines.append("    output:")
                lines.extend(f"      {line}" for line in tail)
        lines.append("")
    if agent_report is not None and (agent_report[0] or agent_report[1]):
        lines.append("### Previous agent note")
        if agent_report[0]:
            lines.append(f"- {agent_report[0]}")
        if agent_report[1]:
            lines.extend(f"  {line}" for line in agent_report[1].strip().splitlines())
        lines.append("")
    if changed_files:
        preview = list(changed_files[:12])
        lines.append("### Files written so far")
        lines.extend(f"- {name}" for name in preview)
        if len(changed_files) > len(preview):
            lines.append(f"- ... (+{len(changed_files) - len(preview)} more)")
        lines.append("")
    text = "\n".join(lines).rstrip()
    if len(text) > _REPAIR_FEEDBACK_CAP:
        text = text[:_REPAIR_FEEDBACK_CAP].rstrip() + "\n… (feedback truncated)"
    return text + "\n\n"


def _repair_prompt_assembly(base: PromptAssembly, feedback: str) -> PromptAssembly:
    """Layer the repair feedback onto the block prompt as the final recency anchor."""
    return replace(
        base,
        parts=(
            *base.parts,
            section_heading_part("# Repair Feedback"),
            part("Repair feedback", feedback, kind="repair"),
        ),
    )


def _failure_finding(
    status: str,
    error: str | None,
    result: object,
    acceptance: tuple[AcceptanceRunResult, ...],
) -> str | None:
    """Build a single-line failure reason to persist on a failed block's ``finding:`` field.

    The concise ``error`` classifies the failure; a trailing detail is appended from the first
    failing acceptance check, or from the provider's stderr tail for an execution failure, so
    the compass can surface *why* a step failed without opening the evidence file.
    """
    if status != "failed":
        return None
    reason = error or "build failed"
    if reason.startswith("dependency legitimacy gate failed:"):
        return _clip(reason)
    detail = ""
    failed = [check for check in acceptance if not check.passed]
    if failed:
        first = failed[0]
        detail = (first.error or first.stderr or first.stdout or "").strip()
    elif not bool(getattr(result, "ok", False)):
        detail = str(getattr(result, "stderr", "") or "").strip()
    if detail:
        lines = [line for line in detail.splitlines() if line.strip()]
        if lines:
            reason = f"{reason}: {lines[-1].strip()}"
    return _clip(reason)


def _write_evidence(
    path: Path,
    block: PlanBlock,
    assembly: StepAssembly,
    *,
    state: str,
    execution_id: str | None,
    summary: str,
    written_files: tuple[str, ...],
    pre_acceptance: tuple[AcceptanceObservation, ...],
    acceptance: tuple[AcceptanceRunResult, ...],
    today: str,
) -> None:
    lines = [
        f"# Evidence: {block.name} ({block.block_id})",
        "",
        f"- step type: {block.block_type}",
        f"- date: {today}",
        f"- resulting state: {state}",
        f"- story points (assembled cost): {assembly.total_story_points}",
        f"- execution id: {execution_id or '-'}",
        "",
    ]
    missing = assembly.missing_files()
    if missing:
        lines.append("## Missing context")
        lines.extend(f"- {f.role}: {f.name}" for f in missing)
        lines.append("")
    lines.append("## Stacked context")
    lines.extend(
        f"- {f.role}: {f.name} (SP {f.story_points})" for f in assembly.files if not f.missing
    )
    lines.append("")
    if written_files:
        lines.append("## Build directory changes")
        lines.extend(f"- {changed}" for changed in written_files)
        lines.append("")
    if pre_acceptance:
        lines.append("## Pre-build acceptance observation")
        for check in pre_acceptance:
            lines.append(f"- {_observation_mark(check)}: {check.check_id} ({check.source})")
            if check.intent:
                lines.append(f"  intent: {check.intent}")
            if check.return_code is not None:
                lines.append(f"  return code: {check.return_code}")
            if check.integrity_reasons:
                lines.append(f"  note: {'; '.join(check.integrity_reasons)}")
            if check.error:
                lines.append(f"  error: {check.error}")
            if check.stdout.strip():
                lines.append("  stdout:")
                lines.extend(f"    {line}" for line in check.stdout.strip().splitlines())
            if check.stderr.strip():
                lines.append("  stderr:")
                lines.extend(f"    {line}" for line in check.stderr.strip().splitlines())
        lines.append("")
    if acceptance:
        lines.append("## Post-build programmatic acceptance")
        for check in acceptance:
            mark = check.outcome
            lines.append(f"- {mark}: {check.check_id} ({check.source})")
            if check.intent:
                lines.append(f"  intent: {check.intent}")
            if check.interpreter:
                lines.append(f"  target interpreter: {check.interpreter}")
            lines.append(f"  provisioning: {check.provisioning_result}")
            if check.return_code is not None:
                lines.append(f"  return code: {check.return_code}")
            if check.error:
                lines.append(f"  error: {check.error}")
            if check.stdout.strip():
                lines.append("  stdout:")
                lines.extend(f"    {line}" for line in check.stdout.strip().splitlines())
            if check.stderr.strip():
                lines.append("  stderr:")
                lines.extend(f"    {line}" for line in check.stderr.strip().splitlines())
        lines.append("")
    lines.append("## Build summary")
    lines.append(summary.strip() or "(no summary returned)")
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8", newline="\n")


def _write_group_evidence(
    path: Path,
    unit: BuildUnit,
    group: StepGroup,
    *,
    state: str,
    execution_id: str | None,
    summary: str,
    written_files: tuple[str, ...],
    pre_acceptance: tuple[AcceptanceObservation, ...],
    acceptance: tuple[AcceptanceRunResult, ...],
    today: str,
    failure_summary: str = "",
    failure_detail: str = "",
    agent_report: tuple[str, str] | None = None,
    attempts: tuple[AttemptRecord, ...] = (),
    reusable_compacts: tuple[str, ...] = (),
    dependency_overrides: tuple[str, ...] = (),
    requirement_evidence: tuple[str, ...] = (),
) -> None:
    lines = [
        f"# Evidence: {unit.name} ({unit.block_id})",
        "",
        f"- block type: {unit.block_type}",
        f"- date: {today}",
        f"- resulting state: {state}",
        f"- story points (combined assembled cost): {group.total_story_points}",
        f"- execution id: {execution_id or '-'}",
        "",
        "## Stories built",
    ]
    lines.extend(f"- {step.name} ({step.block_id}) [{step.block_type}]" for step in group.steps)
    lines.append("")
    if dependency_overrides:
        lines.append("## Commander dependency overrides")
        lines.extend(f"- {item}" for item in dependency_overrides)
        lines.append("")
    if requirement_evidence:
        lines.append("## Acceptance tooling authorization")
        lines.extend(f"- {item}" for item in requirement_evidence)
        lines.append("")
    if reusable_compacts:
        lines.append("## Reusable compacts")
        lines.extend(f"- {name}" for name in reusable_compacts)
        lines.append("")
    if unit.already_verified:
        lines.append("## Stories already verified")
        lines.extend(f"- {block.name} ({block.block_id})" for block in unit.already_verified)
        lines.append("")
    missing = group.missing_files()
    if missing:
        lines.append("## Missing context")
        lines.extend(f"- {f.role}: {f.name}" for f in missing)
        lines.append("")
    lines.append("## Stacked context")
    seen: set[tuple[str, str]] = set()
    for step in group.steps:
        for step_file in step.files:
            if step_file.missing:
                continue
            key = (step_file.role, str(step_file.source or step_file.name))
            if key in seen:
                continue
            seen.add(key)
            lines.append(f"- {step_file.role}: {step_file.name} (SP {step_file.story_points})")
    lines.append("")
    if written_files:
        lines.append("## Build directory changes")
        lines.extend(f"- {changed}" for changed in written_files)
        lines.append("")
    if pre_acceptance:
        lines.append("## Pre-build acceptance observation")
        for check in pre_acceptance:
            lines.append(f"- {_observation_mark(check)}: {check.check_id} ({check.source})")
            if check.intent:
                lines.append(f"  intent: {check.intent}")
            if check.return_code is not None:
                lines.append(f"  return code: {check.return_code}")
            if check.integrity_reasons:
                lines.append(f"  note: {'; '.join(check.integrity_reasons)}")
            if check.error:
                lines.append(f"  error: {check.error}")
            if check.stdout.strip():
                lines.append("  stdout:")
                lines.extend(f"    {line}" for line in check.stdout.strip().splitlines())
            if check.stderr.strip():
                lines.append("  stderr:")
                lines.extend(f"    {line}" for line in check.stderr.strip().splitlines())
        lines.append("")
    if acceptance:
        lines.append("## Post-build programmatic acceptance")
        for check in acceptance:
            mark = check.outcome
            lines.append(f"- {mark}: {check.check_id} ({check.source})")
            if check.intent:
                lines.append(f"  intent: {check.intent}")
            if check.interpreter:
                lines.append(f"  target interpreter: {check.interpreter}")
            lines.append(f"  provisioning: {check.provisioning_result}")
            if check.return_code is not None:
                lines.append(f"  return code: {check.return_code}")
            if check.error:
                lines.append(f"  error: {check.error}")
            if check.stdout.strip():
                lines.append("  stdout:")
                lines.extend(f"    {line}" for line in check.stdout.strip().splitlines())
            if check.stderr.strip():
                lines.append("  stderr:")
                lines.extend(f"    {line}" for line in check.stderr.strip().splitlines())
        lines.append("")
    # A single pass that stopped for a stated reason still owes the reader that reason — a
    # terminal verdict reached on call 1 is exactly the case an operator will question.
    if len(attempts) > 1 or any(record.stop_reason for record in attempts):
        lines.append("## Repair attempts")
        for record in attempts:
            label = "initial build" if record.index == 0 else f"repair {record.index}"
            checks_note = (
                f"{record.passed_checks}/{record.total_checks} checks"
                if record.total_checks
                else "no checks"
            )
            cases_note = (
                f"; {record.passed_cases}/{record.total_cases} cases"
                if record.passed_cases is not None and record.total_cases is not None
                else ""
            )
            model_note = f" model={record.model}" if record.model else ""
            lines.append(
                f"- attempt {record.index} ({label}): {record.status}; {checks_note}"
                f"{cases_note}{model_note}; execution {record.execution_id or '-'}"
                + (f"; stopped: {record.stop_reason}" if record.stop_reason else "")
            )
        lines.append("")
    if agent_report is not None and (agent_report[0] or agent_report[1]):
        agent_summary, agent_detail = agent_report
        lines.append("## Agent self-report (advisory)")
        lines.append(
            "The build agent declared a failure. This is advisory only; the programmatic "
            "acceptance above is the authority for this block's outcome."
        )
        if agent_summary:
            lines.append(f"- summary: {agent_summary}")
        if agent_detail:
            lines.append("- detail:")
            lines.extend(f"    {line}" for line in agent_detail.strip().splitlines())
        lines.append("")
    if (state.endswith("failed") or state == "blocked/questions") and (
        failure_summary or failure_detail
    ):
        lines.append("## Failure" if state.endswith("failed") else "## Prerequisite authorization")
        if failure_summary:
            lines.append(f"- summary: {failure_summary}")
        if failure_detail:
            lines.append("- detail:")
            lines.extend(f"    {line}" for line in failure_detail.strip().splitlines())
        lines.append("")
    lines.append("## Build summary")
    lines.append(summary.strip() or "(no summary returned)")
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8", newline="\n")


def _observation_mark(check: AcceptanceObservation) -> str:
    if check.unverified:
        return "UNVERIFIED"
    if not check.passed:
        return "RED"
    if not check.integrity_ok:
        return "GREEN (vacuous)"
    return "GREEN (prepassed)"


def _reset_step_for_rebuild(manifest_path: Path, step_id: str) -> None:
    """Reset one story/spike or feature group and its child ACs to pending."""
    plan = parse_build_plan(manifest_path)
    block = plan.by_id().get(step_id)
    if block is None:
        raise SpecificationError(f"Build step {step_id!r} not found in {manifest_path}")
    reset_ids: list[str]
    if block.block_type == "feature":
        reset_ids = [
            child.block_id
            for child in plan.children(step_id)
            if child.block_type in {"story", "spike"}
        ]
    elif block.block_type in {"story", "spike"}:
        reset_ids = [step_id]
    else:
        raise SpecificationError(f"{step_id!r} is not a build step or feature block")
    updates: dict[str, dict[str, str | None]] = {}
    for reset_id in reset_ids:
        updates[reset_id] = {"state": "pending", "finding": None}
        for child in plan.children(reset_id):
            if child.block_type == "ac":
                updates[child.block_id] = {"state": "pending"}
    batch_set_block_fields(manifest_path, updates)


def _preview_reset(plan: BuildPlan, step_id: str) -> BuildPlan:
    """Return an in-memory plan with the same reset semantics as a scoped ``--reset``."""
    block = plan.by_id().get(step_id)
    if block is None:
        raise SpecificationError(f"Build step {step_id!r} not found in {plan.path}")

    reset_ids: set[str]
    if block.block_type == "feature":
        reset_ids = {
            child.block_id
            for child in plan.children(step_id)
            if child.block_type in {"story", "spike"}
        }
        reset_ids.add(step_id)
    elif block.block_type in {"story", "spike"}:
        reset_ids = {step_id}
    else:
        raise SpecificationError(f"{step_id!r} is not a build step or feature block")

    for reset_id in tuple(reset_ids):
        for child in plan.children(reset_id):
            if child.block_type == "ac":
                reset_ids.add(child.block_id)

    return replace(
        plan,
        blocks=tuple(
            replace(block, state="pending") if block.block_id in reset_ids else block
            for block in plan.blocks
        ),
    )


def _emit_dry_run_file_list(on_text: TextCallback | None, group: StepGroup) -> None:
    seen: set[tuple[str, str, str | None]] = set()
    files = []
    for assembly in group.steps:
        for step_file in assembly.files:
            key = (
                step_file.role,
                step_file.name,
                str(step_file.source) if step_file.source else None,
            )
            if key in seen:
                continue
            seen.add(key)
            files.append(step_file)

    _emit(on_text, "dry run assembled files")
    if not files:
        _emit(on_text, "  (none)")
        return
    _emit(on_text, f"  {'Role':<10} {'File':<34} {'Cost':>8}  Source")
    _emit(on_text, f"  {'-' * 10} {'-' * 34} {'-' * 8}  {'-' * 40}")
    for step_file in files:
        cost = "MISSING" if step_file.missing else f"SP {step_file.story_points}"
        name = f"{step_file.name}*" if step_file.compact_substituted else step_file.name
        source = _dry_run_display_path(step_file.source) if step_file.source is not None else "-"
        _emit(
            on_text,
            f"  {step_file.role:<10} {name:<34} {cost:>8}  {source}",
        )
    if any(step_file.compact_substituted for step_file in files):
        _emit(on_text, "  * compact substitute")


def _dry_run_display_path(path: Path) -> str:
    try:
        return str(path.relative_to(get_repo_root()))
    except (FileNotFoundError, ValueError):
        return str(path)


def _outstanding_blocks(manifest_path: Path) -> tuple[str, ...]:
    """Executable blocks the Manifest still owes after a run, in Manifest order.

    Only meaningful for an unscoped build: ``--step`` and ``--story`` are explicitly partial, so
    the work they leave behind is intended, not a stall.
    """
    try:
        from drydock.manifest import DrydockManifest

        manifest = DrydockManifest.load(manifest_path, compatibility=True)
    except Exception:  # noqa: BLE001 - a manifest we cannot read is reported by the caller's path
        return ()
    return tuple(
        block.block_id
        for block in manifest.blocks
        if block.block_type in {"story", "spike"} and block.state not in FINISHED_STATES
    )


def build_target(
    target: str,
    target_dir: Path,
    *,
    build_dir: Path | None = None,
    runner: RunnerFn | None = None,
    on_text: TextCallback | None = None,
    on_step: Callable[[BuildStepResult], None] | None = None,
    model: str | None = None,
    llm_provider: str | None = None,
    log_dir: Path | None = None,
    step_id: str | None = None,
    story_id: str | None = None,
    reset: bool = False,
    dry_run: bool = False,
    show_prompt: bool = False,
    repair_attempts: int = DEFAULT_REPAIR_ATTEMPTS,
    escalate_model: str | None = None,
    dependency_registry_client: RegistryClient | None = None,
    ungate: bool = False,
    override: bool = False,
) -> BuildResult:
    """Build every currently buildable step, stopping at acceptance review gates.

    The build performs no git operations of its own: it never initializes a repository,
    commits, or gates on a dirty working tree. Version control of the build directory and
    the Drydock checkout is the user's responsibility.
    """
    run = runner if runner is not None else run_prompt
    waivers: list[WaivedGate] = []

    manifest_path = target_dir / "MANIFEST.md"
    if not manifest_path.is_file():
        raise SpecificationError(
            f"MANIFEST.md not found: {manifest_path}\n  Run: drydock plan {target}"
        )

    # A build owns the current Target error record. Remove the prior run's recovery signal before
    # any new run is observed; a new terminal failure writes a fresh record below.
    if not dry_run:
        clear_error_record(target_dir)

    resolved_build_dir = build_dir or build_dir_for(target)

    # Full reset (``--reset`` with no selector): a clean slate. Reset every block to pending
    # and wipe the build directory before anything is staged or observed, so the rebuild
    # starts from scratch with no prior work to resume. Scoped resets (``--step``/``--story``
    # + ``--reset``) reset only the selected block and are applied after selection below.
    if reset and step_id is None and story_id is None:
        if dry_run:
            _emit(
                on_text,
                f"dry run: would reset all blocks to pending and wipe {resolved_build_dir}",
            )
        else:
            reset_count = reset_all_states(manifest_path)
            shutil.rmtree(resolved_build_dir, ignore_errors=True)
            # Applied-spec provenance describes work that no longer exists: every block is
            # pending and the build directory is gone. Keeping the stamps would block the
            # rebuild on Blueprint drift against code that was just discarded.
            set_applied_specs(manifest_path, {})
            _emit(
                on_text,
                f"full reset: {reset_count} block(s) to pending; wiped {resolved_build_dir}",
            )

    if not dry_run:
        resolved_build_dir.mkdir(parents=True, exist_ok=True)
        evidence_dir = target_dir / "evidence"
        evidence_dir.mkdir(parents=True, exist_ok=True)
    else:
        evidence_dir = target_dir / "evidence"

    stack_dir = get_stack_dir()
    blueprint_dir = blueprint_dir_for(target_dir)
    from drydock.question_gates import synchronize_manifest_question_gates

    synchronized_plan = synchronize_manifest_question_gates(
        manifest_path,
        blueprint_dir,
        persist=not dry_run,
        override=override,
        waivers=waivers,
    )
    for waived in waivers:
        _emit(on_text, waived.warning())
    if ungate:
        if dry_run:
            synchronized_plan, ungated_count = _ungate_acceptance_plan(synchronized_plan)
        else:
            ungated_count = _ungate_acceptance_failures(manifest_path)
            synchronized_plan = parse_build_plan(manifest_path)
        _emit(
            on_text,
            (
                f"ungate: released {ungated_count} acceptance node(s) as UNVERIFIED"
                if ungated_count
                else "ungate: no acceptance-only failure found"
            ),
        )

    # Place the imported build assets the Analysis marked `stage` before anything observes the
    # build directory. Acceptance checks run with the build directory as their working
    # directory, so a test kit that exists only in the prompt cannot be executed — and an agent
    # that finds it missing will author a substitute to satisfy an existence assertion.
    staged_assets: tuple[StagedAsset, ...] = ()
    if not dry_run:
        staged_assets, restaged = stage_build_assets(
            blueprint_dir, _source_roles(target_dir), resolved_build_dir
        )
        if staged_assets:
            _emit(on_text, f"staged build assets: {len(staged_assets)}")
        for path in restaged:
            _emit(on_text, f"restored modified build asset: {path}")

    roots = StepRoots(
        target_dir=target_dir,
        blueprint_dir=blueprint_dir,
        stack_dir=stack_dir,
        rigging_dir=get_rigging_root(),
    )

    # Read-only provenance for the dependency registry: record which stack commit a step
    # was built against, when the stack happens to be a clean git checkout. A dirty or
    # non-git stack simply yields no provenance; the build never blocks on it.
    stack_head = _git_head(stack_dir)
    if stack_head is not None and _is_dirty(stack_dir):
        stack_head = None
    plan = synchronized_plan
    if step_id is not None:
        step_id = _resolve_step_selector(plan, step_id)
    if story_id is not None:
        story_id = _resolve_step_selector(plan, story_id)
        story_block = plan.by_id().get(story_id)
        if story_block is None or story_block.block_type not in {"story", "spike"}:
            raise SpecificationError(
                f"--story {story_id!r} is not a story or spike; use --step for a feature block"
            )
    if dry_run:
        _emit(on_text, "dry run: no reusable compacts are written")
    for warning in _ensure_applied_specs_current(manifest_path, blueprint_dir):
        _emit(on_text, warning)

    prompt = load_prompt(PROMPT_NAME)
    today = date.today().isoformat()
    if not dry_run:
        set_build_state(target_dir, "building")
        set_sub_state(target_dir, "running")

    preview_plan: BuildPlan | None = None
    scoped_selector = story_id if story_id is not None else step_id
    if reset and scoped_selector is not None:
        if dry_run:
            _emit(on_text, f"dry run: would reset {scoped_selector} and child ACs to pending")
            preview_plan = _preview_reset(parse_build_plan(manifest_path), scoped_selector)
        else:
            _reset_step_for_rebuild(manifest_path, scoped_selector)

    steps: list[BuildStepResult] = []
    # Criteria earlier blocks proved, and the set of them that was green when the previous block
    # finished. A block grades only its own stories, so without this a later block can silently
    # undo an earlier block's deliverable and nothing notices until final scoring — which is how
    # Toml shipped ten blocks with its decoder's argument guard deleted at block 3. Re-running the
    # proven set after each block turns that into a regression attributable to the block that
    # caused it, because nothing but that block ran in between.
    proven_checks: dict[str, ProgrammaticAcceptance] = {}
    proven_owner: dict[str, PlanBlock] = {}
    proven_green: set[str] = set()
    guard = 0
    while True:
        plan = preview_plan if preview_plan is not None else parse_build_plan(manifest_path)
        unit = _select_build_unit(plan, step_id, target, story_id=story_id)
        if unit is None:
            break
        guard += 1
        if guard > len(plan.blocks) + 1:  # defensive; state always advances per step
            break

        reusable_compact_sources = reusable_build_compact_sources(plan, unit.steps, blueprint_dir)

        block_started = time.monotonic()
        block_started_at = _wall_time()
        compact_stack: frozenset[str] | None = None
        if stack_head is not None:
            compact_stack = frozenset(
                name for name, commit in plan.applied_registry.items() if commit == stack_head
            )
        assemblies = tuple(
            assemble_step(block, roots, compact_stack=compact_stack) for block in unit.steps
        )
        regression_assemblies = tuple(
            assemble_step(block, roots, compact_stack=compact_stack)
            for block in unit.already_verified
        )
        group = make_step_group(
            feature_id=unit.block_id if unit.is_group else None,
            name=unit.name,
            steps=assemblies,
        )
        story_points_summary = f"{group.total_story_points} SP"
        if group.story_point_savings:
            story_points_summary += f", saved {group.story_point_savings}"
        _emit(on_text, "")
        _emit(on_text, _block_header(unit.name, unit.block_id))
        _emit(
            on_text,
            f"kind: {unit.block_type} · {len(unit.steps)} run / "
            f"{len(unit.already_verified)} verified · {story_points_summary}",
        )
        _emit(on_text, f"workdir: {resolved_build_dir}")
        _emit(on_text, f"started at {block_started_at}")
        if unit.already_verified:
            _emit(
                on_text,
                "built: " + ", ".join(f"{v.name} ({v.block_id})" for v in unit.already_verified),
            )
        _emit(
            on_text,
            "run: " + ", ".join(f"{a.name} ({a.block_id})" for a in assemblies),
        )
        if unit.is_group:
            prompt_assembly = render_build_group_prompt_assembly(
                prompt.body,
                group,
                target=target,
                build_dir=resolved_build_dir,
                today=today,
                reusable_compacts=reusable_compact_sources,
                regression_steps=regression_assemblies,
                staged_assets=staged_assets,
            )
        else:
            prompt_assembly = render_build_prompt_assembly(
                prompt.body,
                assemblies[0],
                target=target,
                build_dir=resolved_build_dir,
                today=today,
                reusable_compacts=reusable_compact_sources,
                staged_assets=staged_assets,
            )
        commander_guidance = render_commander_guidance(
            load_decisions(target_dir / "DECISIONS.json")
        )
        if commander_guidance:
            prompt_assembly = PromptAssembly(
                parts=(
                    *prompt_assembly.parts,
                    part(
                        "Active Commander guidance",
                        "# Active Commander guidance\n\n" + commander_guidance + "\n",
                        kind="commander-guidance",
                    ),
                )
            )
        if dry_run:
            _emit(on_text, "-" * _RULE_WIDTH)
            _emit_dry_run_file_list(on_text, group)
            _emit(on_text, "-" * _RULE_WIDTH)
            _emit(on_text, "dry run: LLM execution skipped")
            _emit(
                on_text,
                (
                    "dry run prompt: assembled "
                    f"{prompt_assembly.total_bytes} B  "
                    f"~{prompt_assembly.total_tokens_estimate} tok  "
                    f"parts={len(prompt_assembly.records())}"
                ),
            )
            if show_prompt:
                _emit(on_text, "dry run prompt begin")
                _emit(on_text, prompt_assembly.rendered_text.rstrip())
                _emit(on_text, "dry run prompt end")
            else:
                _emit(on_text, "dry run prompt: hidden; use --show-prompt to print it")
            _emit(on_text, "result: dry-run complete")
            for block, assembly in zip(unit.steps, assemblies):
                step_result = BuildStepResult(
                    block_id=block.block_id,
                    name=block.name,
                    block_type=block.block_type,
                    status="dry-run",
                    state=block.state,
                    story_points=assembly.total_story_points,
                    prompt=prompt_assembly.rendered_text,
                )
                steps.append(step_result)
                if on_step is not None:
                    on_step(step_result)
            break
        story_by_check: dict[str, PlanBlock] = {}
        story_by_source_check: dict[tuple[str, str], PlanBlock] = {}
        gathered_checks: list[ProgrammaticAcceptance] = []
        # A spec whose acceptance container cannot be read grades nothing. That silently lowers
        # the criterion count for the unit, so it is announced on every build that touches the
        # file rather than left for the operator to notice as an absence.
        acceptance_defects: list[str] = []
        graded_blocks = (*unit.steps, *unit.already_verified)
        for block in graded_blocks:
            for check in programmatic_acceptance_for_step(
                block, blueprint_dir, defects=acceptance_defects
            ):
                gathered_checks.append(check)
                story_by_check[check.check_id] = block
                story_by_source_check[(check.source, check.check_id)] = block
        if acceptance_defects and on_text is not None:
            for message in dict.fromkeys(acceptance_defects):
                on_text(f"[build] WARNING {message}\n")
        checks = tuple(gathered_checks)
        # A criterion that invokes a staged asset without the environment that asset declares
        # required cannot be satisfied by any build: a repair pass may not rewrite a criterion,
        # and the asset is restored before grading. Left alone it spends the whole repair budget
        # against an assertion nothing can move, and then reports the result as a product defect.
        # Supply the environment here, in memory, for this grading only — the criterion then runs
        # and yields a real verdict, which is strictly more evidence than reporting it unverified.
        # Nothing is cached: this is recomputed from the criterion text on every build, so a
        # repaired Blueprint simply stops producing repairs.
        staged_asset_text = read_staged_assets(blueprint_dir)
        checks, env_repairs, env_shortfalls = repair_staged_asset_env(checks, staged_asset_text)
        if env_repairs or env_shortfalls:
            regression_repaired, _, _ = repair_staged_asset_env(
                tuple(proven_checks.values()), staged_asset_text
            )
            proven_checks = {check.check_id: check for check in regression_repaired}
            record_acceptance_env_decisions(
                env_repairs,
                env_shortfalls,
                target_dir=target_dir,
                story_for={check_id: block.block_id for check_id, block in story_by_check.items()},
            )
            for repair in env_repairs:
                _emit(
                    on_text,
                    f"ac-env: {repair.check_id} calls {repair.asset} without {repair.name} — "
                    f"supplied {repair.name}={repair.value} from the {repair.origin} "
                    f"(recorded in DECISIONS.json; repair {repair.source})",
                )
            for shortfall in env_shortfalls:
                _emit(on_text, f"ac-env: {shortfall.check_id} {shortfall.reason} — UNVERIFIED")
        unresolved_env_checks = {shortfall.check_id for shortfall in env_shortfalls}
        # Criteria this unit does not grade itself. Re-run after the block builds; never
        # injected into the prompt unless one of them goes red, because telling a model about
        # criteria it is not being asked to satisfy spends context on work it must not do.
        unit_check_ids = {check.check_id for check in checks}
        regression_checks = tuple(
            check for check_id, check in proven_checks.items() if check_id not in unit_check_ids
        )
        # Criteria owned by the stories being built now. Only these may be recorded as
        # baseline-green: a criterion carried in from an earlier block is green because that
        # block proved it, which is the opposite of the claim ``prepassed`` makes.
        owned_check_ids = {
            check.check_id
            for check in checks
            if (owner := story_by_check.get(check.check_id)) is not None
            and owner.block_id in {block.block_id for block in unit.steps}
        }
        # The governed contract is read once per unit, from the Target root. Absent, every
        # block in this unit will close ``implemented``: model-authored criteria still run and
        # still drive repair, but nothing that could establish authority is present to verify.
        acceptance_contract = load_contract(target_dir)
        if acceptance_contract.declared:
            covered = sum(
                1
                for block in unit.steps
                if acceptance_contract.stage_for(*_story_ids(block), block.block_id)
            )
            _emit(
                on_text,
                f"governed acceptance: {covered}/{len(unit.steps)} "
                f"{'story' if len(unit.steps) == 1 else 'stories'} carry a stage gate",
            )
            # A stage keyed to a story id the plan never produced gates nothing at all, and it
            # does so silently — the story ids are model-chosen, so a Commander writing the
            # contract against a previous run's names is the expected way to get this wrong.
            known_ids = {block.block_id for block in plan.blocks} | {
                story for block in plan.blocks for story in _story_ids(block)
            }
            orphaned = sorted(set(acceptance_contract.stages) - known_ids)
            if orphaned:
                _emit(
                    on_text,
                    "governed acceptance: no story matches "
                    + ", ".join(orphaned)
                    + " — these stage gates will never run",
                )
        unauthorized = []
        authorized_missing = []
        requirement_evidence: list[str] = []
        for check in checks:
            owner = story_by_source_check.get((check.source, check.check_id))
            current_approval = False
            for requirement in check.requirements:
                if requirement_available(requirement, resolved_build_dir):
                    requirement_evidence.append(
                        f"{check.source}#{check.check_id}: {requirement.kind}={requirement.name}; "
                        f"scope={requirement.scope}; authorization=existing Target environment"
                    )
                    continue
                authorization = authorization_for(
                    requirement,
                    target_dir=target_dir,
                    build_dir=resolved_build_dir,
                    current_manifest_approved=current_approval,
                )
                if authorization.authorized:
                    authorized_missing.append((check, requirement, authorization))
                    commander = (
                        f"; Commander text={authorization.commander_text}"
                        if authorization.commander_text
                        else ""
                    )
                    requirement_evidence.append(
                        f"{check.source}#{check.check_id}: {requirement.kind}={requirement.name}; "
                        f"scope={requirement.scope}; authorization={authorization.source}{commander}"
                    )
                else:
                    unauthorized.append((check, requirement))
        if unauthorized:
            for check, requirement in unauthorized:
                blueprint_path = blueprint_dir / check.source
                if blueprint_path.is_file():
                    record_requirement_decision(
                        target_dir,
                        check,
                        requirement,
                        story=owner.block_id if owner is not None else None,
                    )
            synchronize_manifest_question_gates(
                manifest_path,
                blueprint_dir,
                persist=not dry_run,
                override=override,
                waivers=waivers,
            )
            requirement_names = ", ".join(f"{r.kind}={r.name}" for _, r in unauthorized)
            if override:
                # The decision is still recorded — the authorization was never granted — but the
                # unit proceeds. An override run reaches for undeclared prerequisites, so it is
                # not hermetic; that is the cost of an unattended regression build.
                for check, requirement in unauthorized:
                    waived = WaivedGate(
                        kind=ACCEPTANCE_AUTHORIZATION,
                        subject=f"{check.source}#{check.check_id}",
                        detail=f"{requirement.kind}={requirement.name}",
                    )
                    waivers.append(waived)
                    _emit(on_text, waived.warning())
            else:
                _emit(
                    on_text,
                    "blocked/questions: acceptance prerequisite requires authorization — "
                    + requirement_names,
                )
                continue
        if authorized_missing:
            _emit(
                on_text,
                "authorized acceptance prerequisites pending Target provisioning: "
                + ", ".join(f"{r.kind}={r.name}" for _, r, _ in authorized_missing),
            )
        pre_acceptance = (
            tuple(
                AcceptanceObservation(
                    check_id=check.check_id,
                    source=check.source,
                    intent=check.intent,
                    passed=False,
                    return_code=None,
                    stdout="",
                    stderr="",
                    error="baseline unavailable: authorized Target tooling is not provisioned",
                )
                for check in checks
            )
            if authorized_missing
            else observe_programmatic_acceptance(
                checks,
                build_dir=resolved_build_dir,
                target_dir=target_dir,
                blueprint_dir=blueprint_dir,
                strict_target=True,
            )
        )
        # A baseline observation that died inside its own snippet is not a red baseline, and it
        # is not a reason to refuse the build either. It settles as UNVERIFIED wherever it is
        # read, so it costs the story nothing; the other assertions on the same story are still
        # worth running. Reported loudly so the author repairs the assertion.
        malformed = tuple(check for check in pre_acceptance if _malformed_verdict(check))
        if malformed:
            _emit(
                on_text,
                f"pre-ac: {len(malformed)} assertion"
                f"{'' if len(malformed) == 1 else 's'} fail in their own frame and will report "
                f"UNVERIFIED — repair the assertion in the Blueprint specification",
            )
            for check in malformed:
                _emit(on_text, f"  - {check.source} [{check.check_id}]: {check.error}")
        # Persist the baseline-green set for ``drydock score ac``, which grades a built tree and
        # so cannot observe it. Recording only — a criterion green here is either exercising
        # nothing or measuring a deliverable that legitimately already existed, and the baseline
        # cannot tell those apart, so failing on it would break correct builds.
        record_prepassed_acceptance(
            evidence_dir,
            (
                check.check_id
                for check in pre_acceptance
                if check.passed and check.check_id in owned_check_ids
            ),
        )
        if pre_acceptance:
            baseline_red = sum(1 for check in pre_acceptance if not check.passed)
            weak_checks = [check.check_id for check in pre_acceptance if check.passed]
            vacuous_checks = [
                check.check_id
                for check in pre_acceptance
                if check.passed and not check.integrity_ok
            ]
            _emit(
                on_text,
                "pre-ac: "
                f"{baseline_red} red baseline · {len(weak_checks)} prepassed"
                + (f" · {len(vacuous_checks)} vacuous" if vacuous_checks else ""),
            )
            if vacuous_checks:
                _emit(on_text, "vacuous: " + ", ".join(vacuous_checks))
            remaining_weak = [check for check in weak_checks if check not in vacuous_checks]
            if remaining_weak:
                _emit(on_text, "prepassed: " + ", ".join(remaining_weak))
        # Snapshot once before the first attempt so ``changed_files`` reflects everything
        # the block wrote across all passes.
        before_files = _snapshot_files(resolved_build_dir)

        base_model = model or prompt.model
        max_attempt = max(0, repair_attempts)
        attempt_records: list[AttemptRecord] = []
        gate_results: dict[str, GateResult] = {}
        # Consecutive flat passes. Reset by any pass that moves the deterministic acceptance
        # score, so progress/flat/progress/flat never accumulates into a stop.
        consecutive_stalls = 0
        # Loop invariant: each attempt runs one full LLM pass and grades it. A failed pass
        # whose classification is repairable, whose deterministic acceptance score improved,
        # and whose budget remains feeds its diagnostics back and re-runs against the persisted
        # partial work. Any other outcome (green, a terminal failure, or ``max_consecutive_stalls``
        # flat passes in a row) ends the loop. Progress is what buys another pass; the budget is
        # only the outer bound on how much progress is worth paying for.
        state = status = error = failure_detail = ""
        acceptance: tuple[AcceptanceRunResult, ...] = ()
        regressed_checks: tuple[AcceptanceRunResult, ...] = ()
        agent_report: tuple[str, str] | None = None
        changed_files: tuple[str, ...] = ()
        execution_id: str | None = None
        summary = ""
        result: object | None = None
        feedback_checks: tuple[AcceptanceRunResult, ...] = ()
        seed_feedback: str | None = None
        dependency_overrides: tuple[str, ...] = ()
        if unit.resume:
            # A resumed step keeps its prior partial work in the build directory. Re-run its
            # acceptance live so the first pass is seeded with the real, current failure — the
            # same feedback repair passes use — rather than a clean prompt that must rediscover
            # it. If the checks already pass (a step fixed out of band), close green with no
            # LLM pass.
            resume_live = run_programmatic_acceptance(
                checks,
                build_dir=resolved_build_dir,
                target_dir=target_dir,
                blueprint_dir=blueprint_dir,
                strict_target=True,
            )
            resume_failed = tuple(check for check in resume_live if not check.passed)
            if not resume_failed:
                acceptance = resume_live
                state, status, error, failure_detail = "closed/verified", "built", None, ""
                _emit(
                    on_text,
                    "resume: acceptance already green — no rebuild needed",
                )
            else:
                seed_feedback = _render_repair_feedback(
                    unit, resume_failed, None, (), story_by_check
                )
                feedback_checks = resume_failed
                _emit(
                    on_text,
                    f"resume: seeding first pass with {len(resume_failed)} failing check(s)",
                )
        attempt = 0
        while True:
            if unit.resume and seed_feedback is None:
                # Resume found the step already green; skip the build and grade what exists.
                break
            if attempt == 0:
                active_assembly = (
                    _repair_prompt_assembly(prompt_assembly, seed_feedback)
                    if seed_feedback is not None
                    else prompt_assembly
                )
                attempt_model = base_model
            else:
                attempt_model = base_model
                if attempt == max_attempt and escalate_model:
                    attempt_model = escalate_model
                    _emit(
                        on_text,
                        f"repair: escalation — final attempt using {attempt_model}",
                    )
                _emit(
                    on_text,
                    f"repair: attempt {attempt}/{max_attempt} · "
                    f"{len(feedback_checks) or 'agent-reported'} failing check(s)",
                )
                active_assembly = _repair_prompt_assembly(
                    prompt_assembly,
                    _render_repair_feedback(
                        unit,
                        feedback_checks,
                        agent_report,
                        changed_files,
                        story_by_check,
                        regressed_checks,
                    ),
                )
            if attempt == 0:
                call_kind = "resumed repair" if unit.resume else "initial build"
            else:
                call_kind = f"automatic repair {attempt} of {max_attempt}"
            _emit(on_text, f"LLM BUILD: {unit.name} [{unit.block_id}]")
            _emit(
                on_text,
                "  stories: "
                + ", ".join(f"{block.name} [{block.block_id}]" for block in unit.steps),
            )
            if unit.already_verified:
                _emit(
                    on_text,
                    "  regression gates: "
                    + ", ".join(
                        f"{block.name} [{block.block_id}]" for block in unit.already_verified
                    ),
                )
            _emit(
                on_text,
                f"  call: {attempt + 1} of up to {max_attempt + 1} · {call_kind} · "
                f"{llm_provider}/{attempt_model or '-'}",
            )
            if feedback_checks:
                _emit(
                    on_text,
                    "  failing: " + _acceptance_failure_details(feedback_checks),
                )
            elif agent_report is not None:
                _emit(on_text, "  failing: agent-reported failure")
            _emit(on_text, f"{_clock()}  calling {llm_provider}/{attempt_model or '-'} …")
            try:
                result = run(
                    active_assembly.rendered_text,
                    resolved_build_dir,
                    llm=llm_provider,
                    model=attempt_model,
                    command_name="build",
                    parameters={
                        "step": unit.block_id,
                        "step_type": unit.block_type,
                        "steps": tuple(block.block_id for block in unit.steps),
                        "attempt": attempt,
                    },
                    allow_tools=True,
                    log_dir=log_dir,
                    target=target,
                    on_text=None,
                    announce=False,
                    prompt_assembly=active_assembly,
                )
            except Exception as exc:
                evidence_path = evidence_dir / f"{unit.block_id}.md"
                write_error_record(
                    target_dir,
                    command="build",
                    phase="LLM execution",
                    classification="LLM execution failed",
                    detail=str(exc),
                    evidence=evidence_path,
                    recovery=f"Inspect the execution evidence, then run: drydock build {target}",
                    state="Error",
                )
                from drydock.quarterdeck_state import refresh_commanders_chair as _refresh_chair

                _refresh_chair(target_dir)
                raise
            after_files = _snapshot_files(resolved_build_dir)
            changed_files = _written_files(before_files, after_files)

            ok = bool(getattr(result, "ok", False))
            summary = str(getattr(result, "text", "") or "")
            execution_id = getattr(result, "execution_id", None)
            returncode = getattr(result, "returncode", None)
            execution_bits = ["ok" if ok else "failed"]
            if returncode is not None:
                execution_bits.append(f"rc={returncode}")
            if execution_id:
                execution_bits.append(execution_id)
            _emit(on_text, "returned: " + " · ".join(execution_bits))
            # Token accounting is not build progress. The execution's own ``.llm.log`` already
            # carries it, and the receipt links that log beside the command's streams.
            token_line = format_token_summary(getattr(result, "stats", None), llm=llm_provider)
            if token_line:
                artifacts = getattr(result, "artifacts", None)
                if artifacts is not None and hasattr(artifacts, "record_activity"):
                    artifacts.record_activity(f"  tokens: {token_line}")
            state, status, error, failure_detail = _build_outcome(
                summary,
                ok=ok,
                wrote_files=changed_files,
                stderr=str(getattr(result, "stderr", "") or ""),
                provider_error=_result_provider_error(result),
            )
            # A build agent's self-declared FAILURE is advisory, not authoritative. When the
            # agent still wrote files and the block carries programmatic acceptance criteria,
            # the deterministic gate below decides the outcome and produces a measured result.
            # This stops an agent from failing a block whose own acceptance criteria it actually
            # met by editorializing about work that is not this block's definition of done. With
            # no checks to measure, the self-report stands; hard failures (sandbox, token limit,
            # non-zero exit, empty/no output) are not prefixed ``agent-reported failure`` and
            # stay terminal.
            agent_report = None
            if (
                status == "failed"
                and (error or "").startswith(_AGENT_REPORTED_PREFIX)
                and changed_files
                and checks
            ):
                agent_report = _parse_agent_failure(summary)
                _emit(
                    on_text,
                    "agent self-reported failure (advisory) "
                    "— deterministic acceptance is authoritative",
                )
                state, status, error, failure_detail = "", "", None, ""
            elif status == "failed" and (error or "").startswith(_AGENT_REPORTED_PREFIX):
                # A surviving agent-reported failure (no checks, or no files) carries the note
                # into the repair feedback so a rerun sees what the agent claimed went wrong.
                agent_report = _parse_agent_failure(summary)
            # An empty file delta is measured by content hash, so a step that rewrites an
            # already-correct file with identical bytes reports zero changes while having done
            # exactly the right thing. Treating that as terminal skips acceptance entirely,
            # which also discards the agent's ``AC_BROKEN`` report — the one signal that stops
            # a repair loop against a criterion no implementation can satisfy. With checks to
            # measure, let the deterministic gate decide; with none, an agent that changed
            # nothing has genuinely produced nothing and the failure stands.
            if status == "failed" and error == _NO_FILES_WRITTEN and checks:
                _emit(
                    on_text,
                    "no files changed (advisory) — deterministic acceptance is authoritative",
                )
                state, status, error, failure_detail = "", "", None, ""
            if changed_files:
                preview = ", ".join(changed_files[:5])
                suffix = "" if len(changed_files) <= 5 else f", ... (+{len(changed_files) - 5})"
                _emit(on_text, f"files: {len(changed_files)} changed — {preview}{suffix}")
            else:
                _emit(on_text, "files: 0 changed")

            # Restore any staged asset the step rewrote, before acceptance runs. A step that
            # edits its own test kit would otherwise be graded against a test suite of its own
            # making. The snapshot above already recorded the write, so evidence survives it.
            if staged_assets and status != "failed":
                tampered = verify_staged_assets(staged_assets, resolved_build_dir)
                if tampered:
                    state, status = "closed/failed", "failed"
                    error = "staged build asset modified: " + ", ".join(tampered)
                    failure_detail = (
                        "The step rewrote imported build assets, which have been restored from "
                        "the Blueprint. Staged assets are read-only inputs.\n  "
                        + "\n  ".join(tampered)
                    )
                    _emit(on_text, f"staged asset modified — {len(tampered)} restored")

            acceptance = ()
            if status != "failed":
                try:
                    dependency_gate = check_python_dependency_manifests(
                        resolved_build_dir,
                        changed_files,
                        client=dependency_registry_client,
                        today=date.today(),
                    )
                except Exception as exc:
                    state, status = "closed/failed", "failed"
                    error = "dependency legitimacy gate failed: registry lookup error"
                    failure_detail = str(exc)
                else:
                    if dependency_gate.blocked:
                        remaining_issues = []
                        overrides = []
                        for issue in dependency_gate.issues:
                            declared = next(
                                (
                                    requirement
                                    for check in checks
                                    for requirement in check.requirements
                                    if requirement.kind == "python-package"
                                    and canonicalize_package_name(requirement.name)
                                    == issue.normalized_name
                                ),
                                None,
                            )
                            requirement = declared or AcceptanceRequirement(
                                "python-package", issue.package_name, "runtime"
                            )
                            authorization = authorization_for(
                                requirement,
                                target_dir=target_dir,
                                build_dir=resolved_build_dir,
                            )
                            if authorization.authorized and authorization.commander_text:
                                overrides.append(
                                    f"{issue.package_name}: {issue.verdict}; overridden by "
                                    f"{authorization.source}: {authorization.commander_text}"
                                )
                            else:
                                remaining_issues.append(issue)
                        dependency_overrides = tuple(overrides)
                        if dependency_overrides:
                            for override in dependency_overrides:
                                _emit(on_text, "dependency override: " + override)
                        dependency_gate = DependencyGateResult(
                            dependency_gate.scanned_files,
                            dependency_gate.checked_dependencies,
                            tuple(remaining_issues),
                        )
                    if dependency_gate.blocked:
                        state, status = "closed/failed", "failed"
                        error, failure_detail = _dependency_gate_failure(dependency_gate)
                        _emit(
                            on_text,
                            f"dependency gate failed — {len(dependency_gate.issues)} issue(s)",
                        )
                    else:
                        provisioning_result = "not required"
                        missing_after_build = [
                            requirement
                            for check in checks
                            for requirement in check.requirements
                            if not requirement_available(requirement, resolved_build_dir)
                        ]
                        if any(item.kind == "python-package" for item in missing_after_build):
                            provisioned = provision_uv_environment(resolved_build_dir)
                            if provisioned.interpreter is None:
                                state, status = "closed/failed", "failed"
                                error = "acceptance environment provisioning failed"
                                failure_detail = provisioned.detail
                            else:
                                provisioning_result = provisioned.provisioning_result
                                _emit(
                                    on_text,
                                    f"acceptance environment: {provisioned.provisioning_result}",
                                )
                        unavailable_after_provision = [
                            item
                            for item in missing_after_build
                            if not requirement_available(item, resolved_build_dir)
                        ]
                        if unavailable_after_provision and status != "failed":
                            state, status = "closed/failed", "failed"
                            error = "authorized acceptance prerequisite unavailable"
                            failure_detail = ", ".join(
                                f"{item.kind}={item.name}" for item in unavailable_after_provision
                            )
                        acceptance = (
                            run_programmatic_acceptance(
                                checks,
                                build_dir=resolved_build_dir,
                                target_dir=target_dir,
                                blueprint_dir=blueprint_dir,
                                strict_target=True,
                            )
                            if status != "failed"
                            else ()
                        )
                        if acceptance:
                            acceptance = tuple(
                                replace(item, provisioning_result=provisioning_result)
                                for item in acceptance
                            )
                        # A criterion whose staged-asset environment could not be resolved never
                        # reaches the code under test, whatever its exit status. Settle it as
                        # UNVERIFIED so it neither drives a repair pass nor is charged to the
                        # product; the decision recorded above carries the repair back to the
                        # author.
                        if unresolved_env_checks and acceptance:
                            acceptance = tuple(
                                replace(item, skipped=True)
                                if item.check_id in unresolved_env_checks and not item.passed
                                else item
                                for item in acceptance
                            )
                        skipped_checks = tuple(check for check in acceptance if check.skipped)
                        if skipped_checks:
                            record_skipped_acceptance_decisions(
                                tuple(
                                    (
                                        check,
                                        next(
                                            item
                                            for item in checks
                                            if item.check_id == check.check_id
                                        ),
                                        (
                                            owner.block_id
                                            if (
                                                owner := story_by_source_check.get((
                                                    check.source,
                                                    check.check_id,
                                                ))
                                            )
                                            is not None
                                            else None
                                        ),
                                    )
                                    for check in skipped_checks
                                ),
                                target_dir=target_dir,
                            )
                        # A criterion that missed its expectation splits two ways. If its
                        # expected value is one it could not have invented, the miss is evidence
                        # about the product and fails the block. If the author re-typed the
                        # expected bytes by hand, the miss is as likely to be the criterion's
                        # fault, so it settles DISPUTED: reported in full, charged to nothing.
                        missed = tuple(
                            check for check in acceptance if not check.passed and not check.skipped
                        )
                        failed_checks = tuple(check for check in missed if check.binding)
                        disputed_checks = tuple(check for check in missed if not check.binding)
                        if failed_checks:
                            undeclared = next(
                                (
                                    (check, requirement)
                                    for check in failed_checks
                                    if (requirement := discover_missing_requirement(check.stderr))
                                    is not None
                                    and all(
                                        declared.kind != requirement.kind
                                        or declared.name != requirement.name
                                        for declared in next(
                                            item
                                            for item in checks
                                            if item.check_id == check.check_id
                                        ).requirements
                                    )
                                ),
                                None,
                            )
                            if undeclared is not None:
                                failed_result, requirement = undeclared
                                declared_check = next(
                                    item
                                    for item in checks
                                    if item.check_id == failed_result.check_id
                                )
                                owner = story_by_source_check.get((
                                    declared_check.source,
                                    declared_check.check_id,
                                ))
                                record_requirement_decision(
                                    target_dir,
                                    declared_check,
                                    requirement,
                                    story=owner.block_id if owner is not None else None,
                                )
                                synchronize_manifest_question_gates(
                                    manifest_path,
                                    blueprint_dir,
                                    persist=True,
                                    override=override,
                                    waivers=waivers,
                                )
                                if override:
                                    waived = WaivedGate(
                                        kind=ACCEPTANCE_AUTHORIZATION,
                                        subject=(
                                            f"{declared_check.source}#{declared_check.check_id}"
                                        ),
                                        detail=(
                                            f"undeclared {requirement.kind}={requirement.name} "
                                            "discovered during acceptance"
                                        ),
                                    )
                                    waivers.append(waived)
                                    _emit(on_text, waived.warning())
                                    # The prerequisite is genuinely absent and acceptance has
                                    # already failed on it. Override makes that loud (a failure)
                                    # rather than parking the story on an unanswerable question.
                                    state, status = "closed/failed", "failed"
                                else:
                                    state, status = "blocked/questions", "blocked"
                                    error = "acceptance prerequisite requires authorization"
                                    failure_detail = (
                                        f"Undeclared {requirement.kind}={requirement.name} was "
                                        "discovered during acceptance. Partial work is preserved; "
                                        "answer the blocking DECISIONS.json authorization to "
                                        "resume this story."
                                    )
                                    _emit(on_text, "blocked/questions: " + failure_detail)
                            else:
                                state, status = "closed/failed", "failed"
                            # Keep the repairable prefix — a resource kill is still driven
                            # green by another informed pass — but name the category so the
                            # manifest finding does not read as an ordinary missed assertion.
                            if status != "blocked":
                                category = (
                                    " (resource exhaustion)"
                                    if any(_resource_verdict(check) for check in failed_checks)
                                    else ""
                                )
                                error = f"programmatic acceptance failed{category}: " + ", ".join(
                                    check.check_id for check in failed_checks
                                )
                                failure_detail = _render_ac_failure_chain(
                                    unit, failed_checks, story_by_check
                                )
                        else:
                            state, status, error = "closed/verified", "built", None
                            failure_detail = ""
                        # ── Regression sweep ─────────────────────────────────────────────
                        #
                        # Re-run what earlier blocks proved. Only when this block's own
                        # criteria are green: a block that is still red repairs anyway, and
                        # it cannot close without reaching this point green, so nothing
                        # escapes the sweep. Attribution needs no second baseline run — the
                        # previous sweep established the state, and only this block has run
                        # since, so a criterion that was green then and is red now was broken
                        # here.
                        regressed_checks = ()
                        if regression_checks and status == "built":
                            swept = run_programmatic_acceptance(
                                regression_checks,
                                build_dir=resolved_build_dir,
                                target_dir=target_dir,
                                blueprint_dir=blueprint_dir,
                                strict_target=True,
                            )
                            regressed_checks = tuple(
                                result
                                for result in swept
                                if not result.passed
                                and not result.skipped
                                and result.check_id in proven_green
                            )
                            # The observed state replaces the recorded one, so a criterion
                            # that stays red is reported against the block that broke it and
                            # not again against every block that follows.
                            proven_green -= {result.check_id for result in swept}
                            proven_green |= {result.check_id for result in swept if result.passed}
                            _emit(
                                on_text,
                                f"regression sweep: {len(swept)} prior criteria · "
                                + (
                                    f"{len(regressed_checks)} regressed"
                                    if regressed_checks
                                    else "all green"
                                ),
                            )
                            if regressed_checks:
                                state, status = "closed/failed", "failed"
                                error = f"{REGRESSION_FAILURE_PREFIX}: " + ", ".join(
                                    result.check_id for result in regressed_checks
                                )
                                failure_detail = _render_regression_detail(
                                    regressed_checks, proven_owner
                                )
                        if checks:
                            _emit(
                                on_text,
                                _attempt_acceptance_summary(attempt, acceptance),
                            )
                            if disputed_checks:
                                # Loud, because silence here would read as coverage the run does
                                # not have. The criterion ran and missed; what is withheld is the
                                # conclusion that the product is what missed.
                                _emit(
                                    on_text,
                                    f"disputed: {len(disputed_checks)} criteri"
                                    f"{'on' if len(disputed_checks) == 1 else 'a'} missed an "
                                    "expectation the author re-typed rather than derived — "
                                    "reported, not charged against the build",
                                )
                                for check in disputed_checks:
                                    _emit(on_text, f"  {check.check_id}: {check.intent}")
                                    for line in _console_failure_lines(check):
                                        _emit(on_text, f"    {line}")
                            if failed_checks:
                                # Show what each check was doing when it failed. Without this
                                # the console carries only check ids, and the tally or failing
                                # cases that make the defect obvious to a reader stay buried in
                                # the evidence file.
                                for check in failed_checks:
                                    _emit(on_text, f"  {check.check_id}: {check.intent}")
                                    for line in _console_failure_lines(check):
                                        _emit(on_text, f"    {line}")
                                # The verdict fed to the repair pass stays about the defect —
                                # an LLM told "raise the limit" would do exactly that. The
                                # operator's escape hatch belongs on the console instead.
                                for check in failed_checks:
                                    if _resource_verdict(check):
                                        _emit(
                                            on_text,
                                            f"  {check.check_id}: code under test exhausted "
                                            "its resource budget — stopped by the harness",
                                        )
                                        _emit(
                                            on_text,
                                            "  bound: "
                                            f"{get_sandbox_mem_limit_mb()} MB · raise with "
                                            "'drydock config set sandbox_mem_limit <MB>' "
                                            "(0 disables; JVM/Go stacks reserve more)",
                                        )

            # The governed gates run on every attempt, not once after the budget is spent.
            # A gate that reports only at the end drives no repair at all: the block simply
            # fails with the whole budget unused. Running it here makes it the red/green signal
            # the repair loop is steering by, which is the point of a stage gate.
            gate_results = {}
            for gated_block in unit.steps:
                stage = acceptance_contract.stage_for(
                    *_story_ids(gated_block), gated_block.block_id
                )
                if stage is None:
                    continue
                stage_name, argv = stage
                gate = run_gate(stage_name, argv, build_dir=resolved_build_dir)
                gate_results[gated_block.block_id] = gate
                _emit(on_text, f"gate: {gate.rendered}")
            if any(gate.blocks for gate in gate_results.values()):
                # A red gate is a product failure whatever the criteria said, and it is
                # repairable: another informed pass is exactly what can move it.
                status = "failed"
                error = f"{GOVERNED_FAILURE_PREFIX}: " + ", ".join(
                    gate.name for gate in gate_results.values() if gate.blocks
                )
                failure_detail = "\n".join(
                    f"{gate.rendered}\n{(gate.stdout or gate.stderr)[-4000:]}"
                    for gate in gate_results.values()
                    if gate.blocks
                )
            previous_record = attempt_records[-1] if attempt_records else None
            passed_check_ids = tuple(check.check_id for check in acceptance if check.passed)
            passed_checks = len(passed_check_ids)
            passed_cases, total_cases = _acceptance_case_totals(acceptance)
            case_tallies = _acceptance_case_tallies(acceptance)
            previous_passed_ids = (
                frozenset(previous_record.passed_check_ids) if previous_record is not None else None
            )
            current_passed_ids = frozenset(passed_check_ids)
            ac_progress = (
                previous_passed_ids is not None and current_passed_ids > previous_passed_ids
            )
            quantitative_progress = (
                previous_record is not None
                and current_passed_ids == previous_passed_ids
                and _quantitative_acceptance_progress(
                    previous_record.case_tallies,
                    case_tallies,
                )
            )
            stalled = (
                status == "failed"
                and _is_repairable(error)
                and bool(acceptance or gate_results)
                and previous_record is not None
                and not ac_progress
                and not quantitative_progress
            )
            # A flat pass is a signal, not always a verdict: one can be noise between two
            # productive passes. A run of them is the verdict, because a model that has stopped
            # moving the score will not start. Every build tolerates one flat pass as noise and
            # stops on the second consecutive flat pass.
            consecutive_stalls = consecutive_stalls + 1 if stalled else 0
            stall_budget = max_consecutive_stalls()
            stop_on_stall = stalled and consecutive_stalls >= stall_budget
            # An agent's claim that a criterion is broken is evidence, not a verdict. It used to
            # be terminal, which handed the party under test the power to end its own
            # examination — and a criterion still reaches this point only when its expected value
            # is one it could not have invented, so the claim is now the less likely explanation.
            # It is recorded and shown; the loop keeps its budget.
            defective_ids: tuple[str, ...] = ()
            if status == "failed" and _is_repairable(error) and acceptance:
                unmet = tuple(check for check in acceptance if not check.passed)
                # The ``AC_BROKEN:`` token is read straight from the agent's response and does
                # not depend on ``RESULT: FAILED``. An agent that runs a criterion, sees the
                # tool succeed, and concludes the assertion itself is wrong may well report
                # SUCCESS — the token still has to stop the loop.
                defective_ids = _ac_broken_claim(summary, unmet)
                if not defective_ids:
                    # Fallback for an agent that describes the defect without the token. The
                    # scan stays confined to the declared failure fields: raw agent output
                    # routinely contains claim vocabulary as ordinary content (a conformance
                    # tally prints "invalid tests: ... failed").
                    _, blockers = _parse_build_report(summary)
                    prose = (agent_report or ("", ""))[:2] + (blockers,)
                    defective_ids = _defective_acceptance_claim(prose, unmet)
            # A repair pass rewrites the implementation, never the criterion or the machine it
            # runs on. When every remaining failure is a kit fault — malformed snippet, absent
            # tool, exhausted memory or time — no further pass can move any of them, and the ids
            # name exactly what a human has to fix instead.
            if defective_ids:
                sources = sorted({
                    check.source
                    for check in checks
                    if check.check_id in defective_ids and check.source
                })
                _emit(
                    on_text,
                    "agent reports defective (recorded, not accepted): "
                    + ", ".join(defective_ids)
                    + (f" — in {', '.join(sources)}" if sources else ""),
                )
            unmet_checks = tuple(check for check in acceptance if not check.passed)
            terminal_ids = (
                tuple(
                    check.check_id
                    for check in unmet_checks
                    if is_terminal_check_failure(check.error)
                )
                if unmet_checks
                else ()
            )
            all_terminal = bool(unmet_checks) and len(terminal_ids) == len(unmet_checks)
            stop_on_kit_fault = status == "failed" and all_terminal
            stop_reason = None
            if stop_on_kit_fault:
                stop_reason = "every failing criterion is a kit fault, not a product defect"
                _emit(
                    on_text,
                    "repair: stopped — no repair pass can move these criteria: "
                    + ", ".join(terminal_ids),
                )
            elif stop_on_stall:
                # A single-pass stop keeps the original wording: naming a count of 1 would read
                # as though a run of passes was measured when only one was.
                stop_reason = "deterministic acceptance score did not improve"
                if consecutive_stalls > 1:
                    stop_reason += f" on {consecutive_stalls} consecutive calls"
                _emit(on_text, f"repair: stopped — {stop_reason}")
            elif stalled and attempt < max_attempt:
                # No ``stop_reason``: the attempt record must not name a stop that never
                # happened, or the build report reads as though the budget was cut short.
                _emit(
                    on_text,
                    f"repair: no acceptance progress on call {attempt + 1} "
                    f"({consecutive_stalls} of {stall_budget}) — continuing",
                )
            attempt_records.append(
                AttemptRecord(
                    index=attempt,
                    execution_id=execution_id,
                    model=attempt_model,
                    passed_checks=passed_checks,
                    total_checks=len(checks),
                    passed_check_ids=passed_check_ids,
                    passed_cases=passed_cases,
                    total_cases=total_cases,
                    case_tallies=case_tallies,
                    status=status or "built",
                    stop_reason=stop_reason,
                )
            )
            feedback_checks = tuple(check for check in acceptance if not check.passed)
            if (
                status == "failed"
                and _is_repairable(error)
                and not stop_on_stall
                and not stop_on_kit_fault
                and attempt < max_attempt
            ):
                attempt += 1
                continue
            break

        # ── The governed gate decides ────────────────────────────────────────────────────
        #
        # Everything above this point is model-authored: the criteria, their inputs, their
        # expected values, and the code meant to satisfy them, all from one author working from
        # one set of assumptions. It is worth running, worth reporting, and worth spending a
        # bounded repair budget on — it is the only red/green signal the agent has while it
        # works. It is not worth handing the verdict to, because when it disagrees with the
        # product nothing can recover which of the two is wrong.
        #
        # A governed command can. It comes from ``ACCEPTANCE.json``, which the Commander owns and
        # no LLM-assisted command may write, and Drydock executes its argv directly rather than
        # inspecting a wrapper the model generated. Where one exists for this block's story, it
        # is the verdict. Where none exists, the block is *implemented* rather than verified —
        # the work is done and nothing with standing examined it.
        # A model-authored criterion no longer decides whether the run continues. Stopping the
        # build on one is what left Toml with blocks 4-8 unbuilt while a fabricated backslash
        # expectation held the line at block 3; the authoritative suite never got the chance to
        # drive the rest of the implementation. Only a governed FAIL, or a failure that is not
        # about acceptance at all, ends a block now.
        # A governed gate outranks a model-authored criterion; a model-authored criterion
        # outranks nothing at all. Where a gate covers the block, its verdict is the verdict and
        # the criteria are diagnostic — an oracle disagreeing with a criterion means the
        # criterion is wrong. Where no gate covers it, a binding criterion is the only evidence
        # there is, and discarding it would leave an ungoverned project with no failure signal
        # whatsoever. Non-binding criteria never decide anything in either case.
        governed_blocks = {block.block_id for block in unit.steps if block.block_id in gate_results}
        failing_gates = [gate for gate in gate_results.values() if gate.blocks]
        if failing_gates:
            status, state = "failed", "closed/failed"
        elif status == "failed" and _is_repairable(error) and governed_blocks:
            # Every governed gate passed or could not run. The criteria that stayed red belong
            # to a story an oracle already judged, so they are evidence about the criteria.
            overruled = ", ".join(
                check.check_id
                for check in acceptance
                if not check.passed
                and not check.skipped
                and (owner := story_by_check.get(check.check_id)) is not None
                and owner.block_id in governed_blocks
            )
            if overruled:
                status, error, failure_detail = "built", None, ""
                _emit(
                    on_text,
                    f"diagnostic: {overruled} — model-authored criteria red where the governed "
                    "gate passed; recorded against the criteria, not the product",
                )

        # What this block proved joins the set every later block is swept against. Only green
        # criteria owned by the stories just built: a red one was never proven, and a criterion
        # carried in from an earlier block is already in the set.
        if status not in {"failed", "blocked"}:
            for result in acceptance:
                if not result.passed or result.check_id not in owned_check_ids:
                    continue
                declared = next((item for item in checks if item.check_id == result.check_id), None)
                if declared is None:
                    continue
                proven_checks[result.check_id] = declared
                proven_green.add(result.check_id)
                if (owner := story_by_check.get(result.check_id)) is not None:
                    proven_owner[result.check_id] = owner

        written_reusable_compacts: tuple[str, ...] = ()
        if status not in {"failed", "blocked"} and reusable_compact_sources:
            written_reusable_compacts = _persist_reusable_compacts(
                summary,
                reusable_compact_sources,
                blueprint_dir=blueprint_dir,
                today=today,
            )
            if written_reusable_compacts:
                _emit(on_text, "reusable compacts: " + ", ".join(written_reusable_compacts))

        written_decisions: tuple[Path, ...] = ()
        if status not in {"failed", "blocked"}:
            allowed_specs = frozenset(
                str(name)
                for block in unit.steps
                for name in (
                    block.fields.get("implements", ())
                    if isinstance(block.fields.get("implements", ()), tuple)
                    else (block.fields.get("implements", ""),)
                )
                if name
            )
            written_decisions = record_build_decisions(
                summary,
                blueprint_dir=blueprint_dir,
                allowed_specs=allowed_specs,
                target_dir=target_dir,
            )
            if written_decisions:
                _emit(
                    on_text,
                    "Shipyard decisions: " + ", ".join(path.name for path in written_decisions),
                )

        evidence_path = evidence_dir / f"{unit.block_id}.md"
        _write_group_evidence(
            evidence_path,
            unit,
            group,
            state=state,
            execution_id=execution_id,
            summary=summary,
            written_files=changed_files,
            pre_acceptance=pre_acceptance,
            acceptance=acceptance,
            today=today,
            failure_summary=error or "",
            failure_detail=failure_detail,
            agent_report=agent_report,
            attempts=tuple(attempt_records),
            reusable_compacts=written_reusable_compacts,
            dependency_overrides=dependency_overrides,
            requirement_evidence=tuple(requirement_evidence),
        )
        # A block that needed repeated repair to go green is a decomposition signal, not a build
        # failure: the work inside it was too large or too entangled for one informed pass. Say so
        # where the Manifest author will see it. Advisory only — it never changes the verdict.
        if status != "failed" and len(attempt_records) > _SIZING_ADVISORY_CALLS:
            _emit(
                on_text,
                f"sizing: {unit.block_id} needed {len(attempt_records)} calls to pass its "
                f"acceptance — consider decomposing this block",
            )
        finding = _failure_finding(status, error, result, acceptance)
        if status == "failed":
            failure_state = (
                "Failed"
                if error
                and (
                    error.startswith("programmatic acceptance failed")
                    or error.startswith(_AGENT_REPORTED_PREFIX)
                    or error.startswith("dependency legitimacy gate failed")
                )
                else "Error"
            )
            # A failed block is left ``closed/failed``; a plain ``drydock build`` resumes it in
            # place, seeding the first pass with the live failure. Name the exact continue command
            # so recovery is one copy-paste; ``--reset`` discards its work instead of continuing.
            rebuild_cmd = f"drydock build {target} --step {unit.block_id}"
            acceptance_recovery = (
                (
                    f"Run: drydock build {target}\n"
                    "  to continue the build. This story resumes where it left off and is "
                    "retried against the checks it failed."
                )
                if failure_state == "Failed"
                and (error or "").startswith("programmatic acceptance failed")
                else None
            )
            write_error_record(
                target_dir,
                command="build",
                phase="build step" if failure_state == "Failed" else "LLM execution",
                classification=error or "build failed",
                detail=failure_detail or finding or "The build block did not complete.",
                execution_id=execution_id,
                evidence=evidence_path,
                recovery=(
                    acceptance_recovery
                    or f"Review the evidence, correct the failure, then run: {rebuild_cmd}"
                    if failure_state == "Failed"
                    else f"Inspect the execution evidence, correct the execution issue, then run: {rebuild_cmd}"
                ),
                state=failure_state,
            )
        # Attribute failure per story: we fail stories by AC. When acceptance ran and the unit
        # failed on a check, only the story that owns a failed check is ``closed/failed``; a
        # story whose own checks all passed verifies rather than inheriting a group-mate's
        # finding. A non-AC failure (execution error, tampered asset, dependency gate, or no
        # checks at all) is not attributable to one story, so every member fails as before.
        ac_attributable = status == "failed" and (
            any(gate.blocks for gate in gate_results.values())
            or any(not check.passed and not check.skipped and check.binding for check in acceptance)
        )
        manifest_updates: dict[str, dict[str, str | None]] = {}
        for block in unit.steps:
            own_checks = tuple(
                check
                for check in acceptance
                if (owner := story_by_check.get(check.check_id)) is not None
                and owner.block_id == block.block_id
            )
            gate = gate_results.get(block.block_id)
            # A story that declared criteria and closed without one of them passing produced no
            # evidence at all: every criterion settled UNVERIFIED, so nothing was measured
            # against the built code. That is not a failure — the product may be entirely
            # correct and the criteria broken — but it is emphatically not verification, and
            # closing it green would report a single-criterion conformance story as verified
            # with its suite never executed. ``implemented`` is the state that already means
            # exactly this: the work is done and nothing with standing examined it.
            unexamined = bool(own_checks) and not any(check.passed for check in own_checks)
            if ac_attributable:
                # Per-block attribution: only the story whose own governed gate failed is
                # closed/failed. A group-mate that passed its own gate, or has none, does not
                # inherit the finding.
                own_failed = tuple(
                    check for check in own_checks if not check.passed and check.binding
                )
                if gate is not None:
                    # Governed: the gate is the verdict for this story, and its own criteria are
                    # diagnostic whatever they said.
                    if gate.blocks:
                        block_state: str = "closed/failed"
                        block_finding: str | None = _failure_finding(
                            "failed", f"governed acceptance failed: {gate.name}", result, own_checks
                        )
                    elif gate.passed:
                        block_state, block_finding = "closed/verified", None
                    else:
                        block_state = "closed/implemented"
                        block_finding = (
                            f"ADVISORY: governed gate {gate.name} {gate.outcome} — {gate.detail}"
                        )
                elif own_failed:
                    # Ungoverned: a binding criterion is the only evidence there is.
                    block_state = "closed/failed"
                    block_finding = _failure_finding(
                        "failed",
                        "programmatic acceptance failed: "
                        + ", ".join(check.check_id for check in own_failed),
                        result,
                        own_checks,
                    )
                elif unexamined:
                    block_state, block_finding = "closed/implemented", UNEXAMINED_FINDING
                elif acceptance_contract.declared:
                    block_state, block_finding = "closed/implemented", UNGOVERNED_FINDING
                else:
                    block_state, block_finding = "closed/verified", None
            elif status in {"failed", "blocked"}:
                block_state = state
                block_finding = finding
            elif gate is not None and gate.passed:
                block_state = "closed/verified"
                block_finding = None
            elif gate is None and unexamined:
                block_state = "closed/implemented"
                block_finding = UNEXAMINED_FINDING
            elif gate is not None:
                # The gate could not run. That is a fault in the kit, not the product, so it
                # never fails the block — but it also cannot verify it.
                block_state = "closed/implemented"
                block_finding = (
                    f"ADVISORY: governed gate {gate.name} {gate.outcome} — {gate.detail}. "
                    "The product was not judged; repair the harness and rerun."
                )
            elif acceptance_contract.declared and state == "closed/verified":
                # The project declares governed acceptance and this story is not covered by it.
                # Its criteria passed, which is worth recording and is not verification: the
                # same author wrote the criteria and the code. The distinction is only drawn for
                # a project that has opted into governance — telling a project with no contract
                # at all that nothing it builds is verified would be noise, not information.
                block_state = "closed/implemented"
                block_finding = UNGOVERNED_FINDING
            else:
                block_state = state
                block_finding = finding
            block_fields: dict[str, str | None] = {
                "state": block_state,
                "evidence": _rel(evidence_path, target_dir),
            }
            if block_finding is not None:
                block_fields["finding"] = block_finding
            elif block.block_type != "spike":
                # Clear any stale failure reason when a story succeeds; a spike's
                # ``finding:`` records research output and is never cleared here.
                block_fields["finding"] = None
            manifest_updates[block.block_id] = block_fields
            if block_state != "closed/failed" and _has_child_acs(plan.blocks, block.block_id):
                for child_id in _child_ac_ids(plan.blocks, block.block_id):
                    manifest_updates[child_id] = {"state": "closed/verified"}
        if ac_attributable:
            for block in unit.already_verified:
                own_checks = tuple(
                    check
                    for check in acceptance
                    if (owner := story_by_check.get(check.check_id)) is not None
                    and owner.block_id == block.block_id
                )
                own_failed = tuple(check for check in own_checks if not check.passed)
                if not own_failed:
                    continue
                manifest_updates[block.block_id] = {
                    "state": "closed/failed",
                    "evidence": _rel(evidence_path, target_dir),
                    "finding": _failure_finding(
                        "failed",
                        "programmatic acceptance failed: "
                        + ", ".join(check.check_id for check in own_failed),
                        result,
                        own_checks,
                    ),
                }
        if unit.has_manifest_container and status == "failed":
            feature_fields: dict[str, str | None] = {
                "state": "closed/failed",
                "evidence": _rel(evidence_path, target_dir),
            }
            if finding is not None:
                feature_fields["finding"] = finding
            manifest_updates[unit.block_id] = feature_fields
        if unit.has_manifest_container and status not in {"failed", "blocked"}:
            children = plan.children(unit.block_id)
            executable_children = tuple(
                child for child in children if child.block_type in {"story", "spike"}
            )
            if executable_children and all(
                manifest_updates.get(child.block_id, {}).get("state", child.state)
                == "closed/verified"
                for child in executable_children
            ):
                manifest_updates[unit.block_id] = {
                    "state": "closed/verified",
                    "evidence": _rel(evidence_path, target_dir),
                }
        batch_set_block_fields(manifest_path, manifest_updates)
        if status not in {"failed", "blocked"} and stack_head is not None:
            updated_registry = dict(plan.applied_registry)
            changed = False
            for block in unit.steps:
                for field_key in ("stack", "rules", "context", "implements"):
                    field_val = block.fields.get(field_key, ())
                    if isinstance(field_val, tuple):
                        for name in field_val:
                            updated_registry[name] = stack_head
                            changed = True
            if changed:
                set_applied_registry(manifest_path, updated_registry)
        if status not in {"failed", "blocked"}:
            applied_specs = dict(parse_build_plan(manifest_path).applied_specs)
            applied_at = datetime.now(UTC).isoformat(timespec="seconds")
            changed = False
            for assembly in assemblies:
                for rel_path, source in _blueprint_spec_files(assembly, blueprint_dir):
                    applied_specs[rel_path] = AppliedSpecRecord(
                        path=rel_path,
                        sha256=_file_sha256(source),
                        commit=_git_file_commit(source),
                        applied_by=unit.block_id,
                        applied_at=applied_at,
                        build_sha256=build_relevant_sha256(source),
                    )
                    changed = True
            if changed:
                set_applied_specs(manifest_path, applied_specs)

        block_elapsed = _elapsed_text(time.monotonic() - block_started)
        graded = acceptance or pre_acceptance
        if graded:
            prepassed_ids = {
                check.check_id for check in pre_acceptance if check.passed and check.integrity_ok
            }
            vacuous_ids = {
                check.check_id
                for check in pre_acceptance
                if check.passed and not check.integrity_ok
            }
            _emit(on_text, "")
            _emit(on_text, "Definition of Done")
            for check in graded:
                # "X" reads as a ticked checkbox under Markdown convention — exactly wrong
                # directly above "result: FAILED". "!" cannot be misread as done.
                mark = "ok" if check.passed else "!!"
                if check.check_id in prepassed_ids:
                    note = "  (prepassed)"
                elif check.check_id in vacuous_ids:
                    note = "  (vacuous)"
                else:
                    note = ""
                detail = f"  {check.error}" if not check.passed and check.error else ""
                _emit(on_text, f"[{mark}] {check.check_id}  {check.intent}{note}{detail}")
        _emit(on_text, "")
        if status == "failed":
            _emit(
                on_text,
                f"result: FAILED — {error or 'build failed'} · {block_elapsed}",
            )
        elif status == "blocked":
            _emit(on_text, f"result: BLOCKED/QUESTIONS — {error} · {block_elapsed}")
            _emit(on_text, f"evidence: {_rel(evidence_path, target_dir)}")
        else:
            _emit(on_text, f"result: {status} · {state} · {block_elapsed}")
            _emit(on_text, f"evidence: {_rel(evidence_path, target_dir)}")
        agent_summary, agent_blockers = _parse_build_report(summary)
        last_attempt = attempt_records[-1] if attempt_records else None
        step_stop_reason = (last_attempt.stop_reason or "") if last_attempt is not None else ""
        for block, assembly in zip(unit.steps, assemblies):
            owned_check_ids = {
                check_id
                for check_id, owner in story_by_check.items()
                if owner.block_id == block.block_id
            }
            owned_pre_acceptance = tuple(
                check for check in pre_acceptance if check.check_id in owned_check_ids
            )
            owned_acceptance = tuple(
                check for check in acceptance if check.check_id in owned_check_ids
            )
            step_status = status
            step_state = state
            step_error = error
            step_failure_detail = failure_detail
            step_result = BuildStepResult(
                block_id=block.block_id,
                name=block.name,
                block_type=block.block_type,
                container_block_id=unit.block_id,
                container_name=unit.name,
                status=step_status,
                state=step_state,
                story_points=assembly.total_story_points,
                execution_id=execution_id,
                evidence_path=evidence_path,
                error=step_error,
                failure_detail=step_failure_detail,
                written_files=changed_files,
                pre_acceptance=pre_acceptance,
                acceptance=acceptance,
                owned_pre_acceptance=owned_pre_acceptance,
                owned_acceptance=owned_acceptance,
                agent_summary=agent_summary,
                agent_blockers=agent_blockers,
                stop_reason=step_stop_reason,
                calls_used=len(attempt_records),
                calls_budget=max_attempt + 1,
            )
            steps.append(step_result)
            if on_step is not None:
                on_step(step_result)
        if status == "failed" or step_id is not None or story_id is not None:
            break

    build_failed = any(step.status == "failed" for step in steps)

    from drydock.quarterdeck_state import refresh_commanders_chair as _refresh_chair

    readme_path: Path | None = None
    env_result: EnvMaterialization | None = None
    if (
        not dry_run
        and not build_failed
        and any(step.status in {"built", "implemented"} for step in steps)
    ):
        set_build_state(target_dir, "built")
        set_sub_state(target_dir, "complete")
        stamp_last(target_dir, "built")
        from drydock.readme_generate import generate_readme

        # The built project's .env is written before the README so the documented setup
        # describes the configuration file that now exists.
        env_result = materialize_env_file(resolved_build_dir)
        readme_path = generate_readme(target_dir, resolved_build_dir)

    if not dry_run:
        _refresh_chair(target_dir)

    unique_waivers = dedupe_waivers(waivers)
    stamp_override(target_dir, unique_waivers)

    return BuildResult(
        target=target,
        build_dir=resolved_build_dir,
        steps=steps,
        readme_path=readme_path,
        dry_run=dry_run,
        env_result=env_result,
        waivers=unique_waivers,
        stalled_blocks=_outstanding_blocks(manifest_path)
        if step_id is None and story_id is None
        else (),
    )

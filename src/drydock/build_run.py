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
    AcceptanceObservation,
    AcceptanceRunResult,
    ProgrammaticAcceptance,
    observe_programmatic_acceptance,
    programmatic_acceptance_for_step,
    run_programmatic_acceptance,
)
from drydock.build import (
    StepAssembly,
    StepGroup,
    StepRoots,
    assemble_step,
    make_step_group,
    render_build_group_prompt_assembly,
    render_build_prompt_assembly,
    required_auto_compact_sources,
    work_kind_of,
)
from drydock.build_plan import (
    AppliedSpecRecord,
    BuildPlan,
    PlanBlock,
    foundational_source,
    parse_build_plan,
    set_applied_registry,
    set_applied_specs,
    stale_applied_specs,
)
from drydock.config import blueprint_dir_for, build_dir_for
from drydock.dependency_gate import (
    DependencyGateResult,
    RegistryClient,
    check_python_dependency_manifests,
)
from drydock.errors import SpecificationError, clear_error_record, write_error_record
from drydock.llm import render_rate_limit_error_block, run_prompt
from drydock.manifest_edit import reset_all_states, set_block_fields
from drydock.metadata import set_build_state, set_sub_state, stamp_last
from drydock.paths import get_repo_root, get_rigging_root, get_stack_dir
from drydock.prompt_assembly import PromptAssembly, part, section_heading_part
from drydock.prompts import load_prompt
from drydock.proof_integrity import analyze_literals
from drydock.rigging_compact import ensure_compact_files
from drydock.source_roles import (
    SourceRole,
    StagedAsset,
    parse_source_roles,
    stage_build_assets,
    verify_staged_assets,
)

BUILD_FAILURE_HINT = (
    "rerun drydock build to continue this step (repairs in place); "
    "add --reset to discard its work and rebuild from scratch"
)

PROMPT_NAME = "build"
RunnerFn = Callable[..., object]
TextCallback = Callable[[str], None]


def _emit(on_text: TextCallback | None, message: str = "") -> None:
    if on_text is not None:
        on_text(message)


def _wall_time() -> str:
    return datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")


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
    execution_id: str | None = None
    evidence_path: Path | None = None
    error: str | None = None
    failure_detail: str = ""
    written_files: tuple[str, ...] = ()
    pre_acceptance: tuple[AcceptanceObservation, ...] = ()
    acceptance: tuple[AcceptanceRunResult, ...] = ()
    prompt: str | None = None


@dataclass(frozen=True)
class BuildResult:
    target: str
    build_dir: Path
    steps: list[BuildStepResult]
    readme_path: Path | None = None
    dry_run: bool = False

    def built(self) -> list[BuildStepResult]:
        return [s for s in self.steps if s.status in ("built", "implemented")]

    def failed(self) -> list[BuildStepResult]:
        return [s for s in self.steps if s.status == "failed"]

    def exit_code(self) -> int:
        return 1 if self.failed() else 0


@dataclass(frozen=True)
class BuildUnit:
    block_id: str
    name: str
    block_type: str
    steps: tuple[PlanBlock, ...]
    already_verified: tuple[PlanBlock, ...] = ()

    @property
    def is_group(self) -> bool:
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


# A step is a selection candidate when it is unbuilt (``pending``) or when it failed a
# prior pass (``closed/failed``). A failed step is resumed in place: continue is the
# default, and the reset path (``--reset``, optionally with ``--step``/``--story``) flips a
# block back to ``pending`` before selection, so a reset block is selected as a fresh build.
SELECTABLE_STATES = frozenset({"pending", "closed/failed"})


def _is_buildable(block: PlanBlock, by_id: dict[str, PlanBlock]) -> bool:
    def verified(block_id: str) -> bool:
        dependency = by_id.get(block_id)
        return dependency is not None and dependency.state == "closed/verified"

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
    return dependency is not None and dependency.state == "closed/verified"


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
    already_verified = tuple(child for child in executable if child.state == "closed/verified")
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


def _ensure_applied_specs_current(plan_path: Path, blueprint_dir: Path) -> None:
    plan = parse_build_plan(plan_path)
    stale = stale_applied_specs(plan, blueprint_dir)
    if not stale:
        return
    foundational = sorted({
        name for spec in stale if (name := foundational_source(spec.rel_path)) is not None
    })
    lines = ["Build blocked: previously applied Blueprint specifications changed."]
    for name in foundational:
        lines.append(
            f"{name} is a sealed foundational specification. Create a change ticket in "
            f"blueprint/changes/ (Amends: {name}) and run 'drydock refit'. Foundational "
            "changes rebuild all dependent blocks."
        )
    if any(foundational_source(spec.rel_path) is None for spec in stale):
        lines.append("Run 'drydock refit' to reset the affected blocks for rebuild.")
    lines.extend(f"  - {detail}" for detail in _stale_applied_specs(plan_path, blueprint_dir))
    raise SpecificationError("\n".join(lines))


def _reject_unsatisfiable_acceptance(checks: tuple[ProgrammaticAcceptance, ...]) -> None:
    """Block the build when a Blueprint assertion cannot pass by construction.

    A mis-authored expectation is not a red baseline the build can drive green: no correct
    implementation satisfies it, so the step would spend a full LLM cycle and fail. Fail here
    instead, naming the Blueprint file to repair.
    """
    lines: list[str] = []
    for check in checks:
        for defect in analyze_literals(check.code):
            lines.append(f"  - {check.source} [{check.check_id}]: {defect.message}")
    if not lines:
        return
    raise SpecificationError(
        "Build blocked: unsatisfiable Programmatic Acceptance assertion.\n"
        + "\n".join(lines)
        + "\nRepair the assertion in the Blueprint specification, then rerun the build."
    )


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

# Category prefix for a build agent's own declared failure. Such a self-report is advisory:
# when the agent still wrote files, the deterministic acceptance gate is the authority.
_AGENT_REPORTED_PREFIX = "agent-reported failure"


def _parse_agent_failure(summary: str) -> tuple[str, str]:
    """Extract the agent's structured ``FAILURE_SUMMARY`` / ``FAILURE_DETAIL`` report."""
    summary_match = _FAILURE_SUMMARY_RE.search(summary)
    detail_match = _FAILURE_DETAIL_RE.search(summary)
    agent_summary = summary_match.group(1).strip() if summary_match else ""
    agent_detail = detail_match.group(1).strip() if detail_match else ""
    return agent_summary, agent_detail


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
        return "no build files written", "The build agent completed but changed no files."

    return None


def _assertion_summary(result: AcceptanceRunResult) -> str:
    """The concrete reason a programmatic check failed, in one line.

    A file-backed run's stderr carries the source line and the exception, so the failing
    assertion is recoverable: ``assert a + b == c`` → ``AssertionError``. Falls back to the
    check's own error (e.g. a timeout) when no traceback is present.
    """
    lines = [line.rstrip() for line in (result.stderr or "").splitlines() if line.strip()]
    assertion = next(
        (line.strip() for line in reversed(lines) if line.strip().startswith("assert ")), ""
    )
    exception = next(
        (line.strip() for line in reversed(lines) if re.match(r"^\w+(Error|Exception)\b", line)),
        "",
    )
    parts = [part for part in (assertion, exception) if part]
    if parts:
        return " → ".join(parts)
    if result.error:
        return result.error
    return "failed with no diagnostic output"


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
            lines.append(f"        {_assertion_summary(result)}")
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
    status: str


_REPAIR_FEEDBACK_CAP = 4000


def _is_repairable(error: str | None) -> bool:
    """True when a failed block can be driven green by another informed LLM pass.

    Only a programmatic-acceptance miss or a surviving agent-reported failure is
    repairable: the build directory holds the partial work and the failing checks name
    what remains. Every other classification (token/context limit, sandbox unavailable,
    provider error, dependency gate, staged-asset tamper, no files written) is terminal
    and never loops — re-running it only wastes a pass.
    """
    if not error:
        return False
    return error.startswith("programmatic acceptance failed") or error.startswith(
        _AGENT_REPORTED_PREFIX
    )


def _output_tail(result: AcceptanceRunResult, max_lines: int = 6) -> list[str]:
    """Return the most informative tail of a failed check's captured output.

    A conformance suite prints its ``N passed, M failed`` tally to stdout; a bare
    assertion carries its traceback on stderr. Prefer whichever stream has content.
    """
    source = result.stdout if result.stdout.strip() else result.stderr
    lines = [line.rstrip() for line in source.splitlines() if line.strip()]
    return lines[-max_lines:]


def _render_repair_feedback(
    unit: BuildUnit,
    failed_checks: tuple[AcceptanceRunResult, ...],
    agent_report: tuple[str, str] | None,
    changed_files: tuple[str, ...],
    story_by_check: dict[str, PlanBlock],
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
    ]
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
            mark = "PASS" if check.passed else "FAIL"
            lines.append(f"- {mark}: {check.check_id} ({check.source})")
            if check.intent:
                lines.append(f"  intent: {check.intent}")
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
            mark = "PASS" if check.passed else "FAIL"
            lines.append(f"- {mark}: {check.check_id} ({check.source})")
            if check.intent:
                lines.append(f"  intent: {check.intent}")
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
    if len(attempts) > 1:
        lines.append("## Repair attempts")
        for record in attempts:
            label = "initial build" if record.index == 0 else f"repair {record.index}"
            checks_note = (
                f"{record.passed_checks}/{record.total_checks} checks"
                if record.total_checks
                else "no checks"
            )
            model_note = f" model={record.model}" if record.model else ""
            lines.append(
                f"- attempt {record.index} ({label}): {record.status}; {checks_note}"
                f"{model_note}; execution {record.execution_id or '-'}"
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
    if state.endswith("failed") and (failure_summary or failure_detail):
        lines.append("## Failure")
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
    for reset_id in reset_ids:
        set_block_fields(manifest_path, reset_id, state="pending", finding=None)
        for child in plan.children(reset_id):
            if child.block_type == "ac":
                set_block_fields(manifest_path, child.block_id, state="pending")


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

    _emit(on_text, "DRY RUN ASSEMBLED FILES")
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
    repair_attempts: int = 1,
    escalate_model: str | None = None,
    dependency_registry_client: RegistryClient | None = None,
) -> BuildResult:
    """Build every currently buildable step, stopping at acceptance review gates.

    The build performs no git operations of its own: it never initializes a repository,
    commits, or gates on a dirty working tree. Version control of the build directory and
    the Drydock checkout is the user's responsibility.
    """
    run = runner if runner is not None else run_prompt

    manifest_path = target_dir / "MANIFEST.md"
    if not manifest_path.is_file():
        raise SpecificationError(
            f"MANIFEST.md not found: {manifest_path}\n  Run: drydock plan {target}"
        )

    resolved_build_dir = build_dir or build_dir_for(target)

    # Full reset (``--reset`` with no selector): a clean slate. Reset every block to pending
    # and wipe the build directory before anything is staged or observed, so the rebuild
    # starts from scratch with no prior work to resume. Scoped resets (``--step``/``--story``
    # + ``--reset``) reset only the selected block and are applied after selection below.
    if reset and step_id is None and story_id is None:
        if dry_run:
            _emit(
                on_text,
                f"DRY RUN: would reset all blocks to pending and wipe {resolved_build_dir}",
            )
        else:
            reset_count = reset_all_states(manifest_path)
            shutil.rmtree(resolved_build_dir, ignore_errors=True)
            _emit(
                on_text,
                f"Full reset: {reset_count} block(s) to pending; wiped {resolved_build_dir}",
            )

    if not dry_run:
        resolved_build_dir.mkdir(parents=True, exist_ok=True)
        evidence_dir = target_dir / "evidence"
        evidence_dir.mkdir(parents=True, exist_ok=True)
    else:
        evidence_dir = target_dir / "evidence"

    stack_dir = get_stack_dir()
    blueprint_dir = blueprint_dir_for(target_dir)

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
            _emit(on_text, f"Staged build assets: {len(staged_assets)}")
        for path in restaged:
            _emit(on_text, f"Restored modified build asset: {path}")

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
    plan = parse_build_plan(manifest_path)
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
        _emit(on_text, "DRY RUN: skipping build-block compact refresh")
    _ensure_applied_specs_current(manifest_path, blueprint_dir)

    prompt = load_prompt(PROMPT_NAME)
    today = date.today().isoformat()
    if not dry_run:
        set_build_state(target_dir, "building")
        set_sub_state(target_dir, "running")

    preview_plan: BuildPlan | None = None
    scoped_selector = story_id if story_id is not None else step_id
    if reset and scoped_selector is not None:
        if dry_run:
            _emit(on_text, f"DRY RUN: would reset {scoped_selector} and child ACs to pending")
            preview_plan = _preview_reset(parse_build_plan(manifest_path), scoped_selector)
        else:
            _reset_step_for_rebuild(manifest_path, scoped_selector)

    steps: list[BuildStepResult] = []
    guard = 0
    while True:
        plan = preview_plan if preview_plan is not None else parse_build_plan(manifest_path)
        unit = _select_build_unit(plan, step_id, target, story_id=story_id)
        if unit is None:
            break
        guard += 1
        if guard > len(plan.blocks) + 1:  # defensive; state always advances per step
            break

        if not dry_run:
            compact_sources: list[Path] = []
            seen_compact_sources: set[Path] = set()
            for block in unit.steps:
                for source in required_auto_compact_sources(block, blueprint_dir):
                    if source not in seen_compact_sources:
                        seen_compact_sources.add(source)
                        compact_sources.append(source)
            ensure_compact_files(
                blueprint_dir,
                sources=compact_sources,
                reason=f"build block {unit.block_id} context refresh",
                log_dir=log_dir,
                target=target,
                on_text=on_text,
                model=model,
                llm_provider=llm_provider,
            )

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
        group = make_step_group(
            feature_id=unit.block_id if unit.is_group else None,
            name=unit.name,
            steps=assemblies,
        )
        story_points_line = f"  Combined Story Points: {group.total_story_points}"
        if group.story_point_savings:
            story_points_line += (
                f"  (summed {group.summed_story_points}, saved {group.story_point_savings})"
            )
        _emit(on_text, "")
        _emit(on_text, "=" * 80)
        _emit(on_text, f"BUILD BLOCK: {unit.name} [{unit.block_id}]")
        _emit(on_text, f"  Type: {unit.block_type}")
        _emit(
            on_text,
            (
                f"  Stories Included: {len(unit.steps)} run, "
                f"{len(unit.already_verified)} already verified"
            ),
        )
        _emit(on_text, story_points_line)
        _emit(on_text, f"  Started: {block_started_at}")
        _emit(on_text, "-" * 80)
        _emit(on_text, f"Workdir: {resolved_build_dir}")
        for verified in unit.already_verified:
            _emit(on_text, f"  [built] {verified.name} ({verified.block_id})")
        for assembly in assemblies:
            _emit(on_text, f"  [run] {assembly.name} ({assembly.block_id})")
        if unit.is_group:
            prompt_assembly = render_build_group_prompt_assembly(
                prompt.body,
                group,
                target=target,
                build_dir=resolved_build_dir,
                today=today,
            )
        else:
            prompt_assembly = render_build_prompt_assembly(
                prompt.body,
                assemblies[0],
                target=target,
                build_dir=resolved_build_dir,
                today=today,
            )
        if dry_run:
            _emit(on_text, "-" * 80)
            _emit_dry_run_file_list(on_text, group)
            _emit(on_text, "-" * 80)
            _emit(on_text, f"DRY RUN: LLM execution skipped for {unit.name} [{unit.block_id}]")
            _emit(
                on_text,
                (
                    "DRY RUN PROMPT: assembled "
                    f"{prompt_assembly.total_bytes} B  "
                    f"~{prompt_assembly.total_tokens_estimate} tok  "
                    f"parts={len(prompt_assembly.records())}"
                ),
            )
            if show_prompt:
                _emit(on_text, "DRY RUN PROMPT BEGIN")
                _emit(on_text, prompt_assembly.rendered_text.rstrip())
                _emit(on_text, "DRY RUN PROMPT END")
            else:
                _emit(on_text, "DRY RUN PROMPT: hidden; use --show-prompt to print it")
            _emit(on_text, f"BUILD BLOCK DRY-RUN COMPLETE: {unit.name} [{unit.block_id}]")
            _emit(on_text, "=" * 80)
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
        gathered_checks: list[ProgrammaticAcceptance] = []
        for block in unit.steps:
            for check in programmatic_acceptance_for_step(block, blueprint_dir):
                gathered_checks.append(check)
                story_by_check[check.check_id] = block
        checks = tuple(gathered_checks)
        _reject_unsatisfiable_acceptance(checks)
        pre_acceptance = observe_programmatic_acceptance(
            checks,
            build_dir=resolved_build_dir,
            target_dir=target_dir,
            blueprint_dir=blueprint_dir,
        )
        if pre_acceptance:
            baseline_red = sum(1 for check in pre_acceptance if not check.passed)
            weak_checks = [check.check_id for check in pre_acceptance if check.passed]
            vacuous_checks = [
                check.check_id
                for check in pre_acceptance
                if check.passed and not check.integrity_ok
            ]
            _emit(on_text, "")
            _emit(
                on_text,
                "Pre-build Acceptance: "
                f"{baseline_red} red baseline, {len(weak_checks)} prepassed"
                + (f", {len(vacuous_checks)} vacuous" if vacuous_checks else ""),
            )
            if vacuous_checks:
                _emit(on_text, "  GREEN (vacuous): " + ", ".join(vacuous_checks))
            remaining_weak = [check for check in weak_checks if check not in vacuous_checks]
            if remaining_weak:
                _emit(on_text, "  GREEN (prepassed): " + ", ".join(remaining_weak))
        # Snapshot once before the first attempt so ``changed_files`` reflects everything
        # the block wrote across all passes, then retire any prior current error.
        before_files = _snapshot_files(resolved_build_dir)
        clear_error_record(target_dir)

        base_model = model or prompt.model
        max_attempt = max(0, repair_attempts)
        attempt_records: list[AttemptRecord] = []
        # Loop invariant: each attempt runs one full LLM pass and grades it. A failed pass
        # whose classification is repairable, with budget remaining, feeds its own failure
        # diagnostics back and re-runs against the persisted partial work. Any other outcome
        # (green, or a terminal failure) ends the loop.
        state = status = error = failure_detail = ""
        acceptance: tuple[AcceptanceRunResult, ...] = ()
        agent_report: tuple[str, str] | None = None
        changed_files: tuple[str, ...] = ()
        execution_id: str | None = None
        summary = ""
        result: object | None = None
        feedback_checks: tuple[AcceptanceRunResult, ...] = ()
        seed_feedback: str | None = None
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
            )
            resume_failed = tuple(check for check in resume_live if not check.passed)
            if not resume_failed:
                acceptance = resume_live
                state, status, error, failure_detail = "closed/verified", "built", None, ""
                _emit(
                    on_text,
                    f"RESUME: acceptance already green for {unit.name} [{unit.block_id}]; "
                    "no rebuild needed",
                )
            else:
                seed_feedback = _render_repair_feedback(
                    unit, resume_failed, None, (), story_by_check
                )
                _emit(
                    on_text,
                    f"RESUME: seeding first pass for {unit.name} [{unit.block_id}] with "
                    f"{len(resume_failed)} failing check(s)",
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
                        f"REPAIR ESCALATION: final attempt using {attempt_model}",
                    )
                _emit(
                    on_text,
                    f"REPAIR ATTEMPT {attempt}/{max_attempt}: "
                    f"{len(feedback_checks) or 'agent-reported'} failing check(s)",
                )
                active_assembly = _repair_prompt_assembly(
                    prompt_assembly,
                    _render_repair_feedback(
                        unit, feedback_checks, agent_report, changed_files, story_by_check
                    ),
                )
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
            execution_bits = [f"ok={ok}"]
            if returncode is not None:
                execution_bits.append(f"rc={returncode}")
            if execution_id:
                execution_bits.append(f"id={execution_id}")
            _emit(
                on_text,
                f"BUILD BLOCK RETURNED: {unit.name} [{unit.block_id}]  "
                + "  ".join(execution_bits),
            )
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
                    f"AGENT SELF-REPORTED FAILURE (advisory): {unit.name} [{unit.block_id}]"
                    "  — deterministic acceptance is authoritative",
                )
                state, status, error, failure_detail = "", "", None, ""
            elif status == "failed" and (error or "").startswith(_AGENT_REPORTED_PREFIX):
                # A surviving agent-reported failure (no checks, or no files) carries the note
                # into the repair feedback so a rerun sees what the agent claimed went wrong.
                agent_report = _parse_agent_failure(summary)
            if changed_files:
                preview = ", ".join(changed_files[:5])
                suffix = "" if len(changed_files) <= 5 else f", ... (+{len(changed_files) - 5})"
                _emit(
                    on_text,
                    f"BUILD BLOCK FILES: {unit.name} [{unit.block_id}]  "
                    f"{len(changed_files)} changed: {preview}{suffix}",
                )
            else:
                _emit(on_text, f"BUILD BLOCK FILES: {unit.name} [{unit.block_id}]  0 changed")

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
                    _emit(
                        on_text,
                        f"STAGED ASSET MODIFIED: {unit.name} [{unit.block_id}]  "
                        f"{len(tampered)} restored",
                    )

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
                        state, status = "closed/failed", "failed"
                        error, failure_detail = _dependency_gate_failure(dependency_gate)
                        _emit(
                            on_text,
                            f"DEPENDENCY GATE FAILED: {unit.name} [{unit.block_id}]  "
                            f"{len(dependency_gate.issues)} issue(s)",
                        )
                    else:
                        if checks:
                            _emit(on_text, "")
                            _emit(on_text, "Testing...")
                        acceptance = run_programmatic_acceptance(
                            checks,
                            build_dir=resolved_build_dir,
                            target_dir=target_dir,
                            blueprint_dir=blueprint_dir,
                        )
                        failed_checks = tuple(check for check in acceptance if not check.passed)
                        if failed_checks:
                            state, status = "closed/failed", "failed"
                            error = "programmatic acceptance failed: " + ", ".join(
                                check.check_id for check in failed_checks
                            )
                            failure_detail = _render_ac_failure_chain(
                                unit, failed_checks, story_by_check
                            )
                        else:
                            state, status, error = "closed/verified", "built", None
                            failure_detail = ""
                        if checks:
                            passed = sum(1 for check in acceptance if check.passed)
                            if not failed_checks:
                                _emit(on_text, "OK")
                            else:
                                _emit(
                                    on_text,
                                    f"FAILED ({passed}/{len(checks)}): "
                                    + ", ".join(check.check_id for check in failed_checks),
                                )

            attempt_records.append(
                AttemptRecord(
                    index=attempt,
                    execution_id=execution_id,
                    model=attempt_model,
                    passed_checks=sum(1 for check in acceptance if check.passed),
                    total_checks=len(checks),
                    status=status or "built",
                )
            )
            feedback_checks = tuple(check for check in acceptance if not check.passed)
            if status == "failed" and _is_repairable(error) and attempt < max_attempt:
                attempt += 1
                continue
            break

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
            write_error_record(
                target_dir,
                command="build",
                phase="build step" if failure_state == "Failed" else "LLM execution",
                classification=error or "build failed",
                detail=failure_detail or finding or "The build block did not complete.",
                execution_id=execution_id,
                evidence=evidence_path,
                recovery=(
                    f"Review the evidence, correct the failure, then run: {rebuild_cmd}"
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
        ac_attributable = status == "failed" and any(not check.passed for check in acceptance)
        for block in unit.steps:
            own_checks = tuple(
                check
                for check in acceptance
                if (owner := story_by_check.get(check.check_id)) is not None
                and owner.block_id == block.block_id
            )
            own_failed = tuple(check for check in own_checks if not check.passed)
            if ac_attributable:
                if own_failed:
                    block_state: str = "closed/failed"
                    block_finding: str | None = _failure_finding(
                        "failed",
                        "programmatic acceptance failed: "
                        + ", ".join(check.check_id for check in own_failed),
                        result,
                        own_checks,
                    )
                else:
                    block_state = "closed/verified"
                    block_finding = None
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
            set_block_fields(manifest_path, block.block_id, **block_fields)
            if block_state != "closed/failed" and _has_child_acs(plan.blocks, block.block_id):
                for child_id in _child_ac_ids(plan.blocks, block.block_id):
                    set_block_fields(manifest_path, child_id, state="closed/verified")
        if unit.is_group and status == "failed":
            feature_fields: dict[str, str | None] = {
                "state": "closed/failed",
                "evidence": _rel(evidence_path, target_dir),
            }
            if finding is not None:
                feature_fields["finding"] = finding
            set_block_fields(manifest_path, unit.block_id, **feature_fields)
        if unit.is_group and status != "failed":
            refreshed = parse_build_plan(manifest_path)
            children = refreshed.children(unit.block_id)
            executable_children = tuple(
                child for child in children if child.block_type in {"story", "spike"}
            )
            if executable_children and all(
                child.state == "closed/verified" for child in executable_children
            ):
                set_block_fields(
                    manifest_path,
                    unit.block_id,
                    state="closed/verified",
                    evidence=_rel(evidence_path, target_dir),
                )
        if status != "failed" and stack_head is not None:
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
        if status != "failed":
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
                    )
                    changed = True
            if changed:
                set_applied_specs(manifest_path, applied_specs)

        _emit(on_text, "-" * 80)
        if status == "failed":
            _emit(on_text, f"BUILD BLOCK FAILED: {unit.name} [{unit.block_id}]")
            _emit(on_text, f"  Completed: {_wall_time()}")
            _emit(on_text, f"  Elapsed: {_elapsed_text(time.monotonic() - block_started)}")
            _emit(on_text, f"  Error: {error or 'build failed'}")
        else:
            _emit(on_text, f"BUILD BLOCK COMPLETE: {unit.name} [{unit.block_id}]")
            _emit(on_text, f"  State: {state}")
            _emit(on_text, f"  Completed: {_wall_time()}")
            _emit(on_text, f"  Elapsed: {_elapsed_text(time.monotonic() - block_started)}")
            _emit(on_text, f"  Evidence: {_rel(evidence_path, target_dir)}")
        _emit(on_text, "=" * 80)
        for block, assembly in zip(unit.steps, assemblies):
            step_result = BuildStepResult(
                block_id=block.block_id,
                name=block.name,
                block_type=block.block_type,
                status=status,
                state=state,
                story_points=assembly.total_story_points,
                execution_id=execution_id,
                evidence_path=evidence_path,
                error=error,
                failure_detail=failure_detail,
                written_files=changed_files,
                pre_acceptance=pre_acceptance,
                acceptance=acceptance,
            )
            steps.append(step_result)
            if on_step is not None:
                on_step(step_result)
        if status == "failed" or step_id is not None or story_id is not None:
            break

    build_failed = any(step.status == "failed" for step in steps)

    from drydock.quarterdeck_state import refresh_commanders_chair as _refresh_chair

    readme_path: Path | None = None
    if (
        not dry_run
        and not build_failed
        and any(step.status in {"built", "implemented"} for step in steps)
    ):
        set_build_state(target_dir, "built")
        set_sub_state(target_dir, "complete")
        stamp_last(target_dir, "built")
        from drydock.readme_generate import generate_readme

        readme_path = generate_readme(target_dir, resolved_build_dir)

    if not dry_run:
        _refresh_chair(target_dir)

    return BuildResult(
        target=target,
        build_dir=resolved_build_dir,
        steps=steps,
        readme_path=readme_path,
        dry_run=dry_run,
    )

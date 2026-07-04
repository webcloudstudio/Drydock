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
returns a summary; the build directory is git-initialized on first use and any
resulting changes are committed after the build run. Tests inject a fake runner
so no credits or network are used.
"""

from __future__ import annotations

import json
import re
import subprocess
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime
from hashlib import sha256
from pathlib import Path

from drydock.acceptance import (
    AcceptanceRunResult,
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
    required_plan_auto_compact_sources,
)
from drydock.build_plan import (
    AppliedSpecRecord,
    BuildPlan,
    PlanBlock,
    parse_build_plan,
    set_applied_registry,
    set_applied_specs,
)
from drydock.config import blueprint_dir_for, build_dir_for
from drydock.errors import SpecificationError
from drydock.llm import run_prompt
from drydock.manifest_edit import set_block_fields
from drydock.metadata import set_build_state, set_sub_state, stamp_last
from drydock.paths import get_repo_root, get_rigging_root, get_stack_dir
from drydock.prompts import load_prompt
from drydock.rigging_compact import ensure_compact_files

BUILD_FAILURE_FORCE_HINT = "rerun drydock build with --force to override errors"

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


def _dirty_paths(path: Path) -> tuple[str, ...]:
    """Return porcelain status lines for the git repo rooted at ``path``."""
    try:
        result = subprocess.run(
            ["git", "-C", str(path), "status", "--porcelain"],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ()
    if result.returncode != 0:
        return ()
    return tuple(line for line in result.stdout.splitlines() if line.strip())


def _ensure_drydock_source_clean() -> None:
    """Block build agents when the Drydock implementation checkout is dirty."""
    try:
        repo_root = get_repo_root()
    except FileNotFoundError:
        return
    dirty = _dirty_paths(repo_root)
    if not dirty:
        return
    preview = "\n".join(f"  {line}" for line in dirty[:20])
    omitted = len(dirty) - 20
    suffix = f"\n  ... {omitted} more" if omitted > 0 else ""
    raise SpecificationError(
        "Build blocked: uncommitted changes exist in the Drydock repository. "
        "Commit or stash Drydock changes before running `drydock build`.\n"
        f"{preview}{suffix}"
    )


def _ensure_git_repo(path: Path) -> bool:
    """Initialize ``path`` as a git repo when needed. Returns True if created."""
    if (path / ".git").is_dir():
        return False
    try:
        result = subprocess.run(
            ["git", "-C", str(path), "init"],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise SpecificationError(f"git init failed for build directory {path}: {exc}") from exc
    if result.returncode != 0:
        message = (result.stderr or result.stdout).strip() or "git init failed"
        raise SpecificationError(f"git init failed for build directory {path}: {message}")
    return True


def _commit_build_dir(path: Path, target: str, today: str) -> tuple[str | None, str | None]:
    """Commit dirty build-directory changes. Returns ``(commit, message)``."""
    if not _is_dirty(path):
        return None, None
    try:
        add_result = subprocess.run(
            ["git", "-C", str(path), "add", "-A"],
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise SpecificationError(f"git add failed for build directory {path}: {exc}") from exc
    if add_result.returncode != 0:
        message = (add_result.stderr or add_result.stdout).strip() or "git add failed"
        raise SpecificationError(f"git add failed for build directory {path}: {message}")

    message = f"drydock build {target} {today}"
    try:
        commit_result = subprocess.run(
            [
                "git",
                "-C",
                str(path),
                "-c",
                "user.name=Drydock Build",
                "-c",
                "user.email=drydock@local",
                "commit",
                "-m",
                message,
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise SpecificationError(f"git commit failed for build directory {path}: {exc}") from exc
    if commit_result.returncode != 0:
        detail = (commit_result.stderr or commit_result.stdout).strip() or "git commit failed"
        raise SpecificationError(f"git commit failed for build directory {path}: {detail}")

    return _git_head(path), message


@dataclass(frozen=True)
class BuildStepResult:
    block_id: str
    name: str
    block_type: str
    status: str  # built | implemented | failed
    state: str  # resulting manifest block state
    story_points: int
    execution_id: str | None = None
    evidence_path: Path | None = None
    error: str | None = None
    written_files: tuple[str, ...] = ()
    acceptance: tuple[AcceptanceRunResult, ...] = ()


@dataclass(frozen=True)
class BuildResult:
    target: str
    build_dir: Path
    steps: list[BuildStepResult]
    git_initialized: bool = False
    git_commit: str | None = None
    git_commit_message: str | None = None
    drydock_commit_skipped_after_build: bool = False
    readme_path: Path | None = None

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


def _rel(path: Path, base: Path) -> str:
    try:
        return str(path.relative_to(base))
    except ValueError:
        return str(path)


def _has_child_acs(blocks: tuple[PlanBlock, ...], block_id: str) -> bool:
    return any(b.block_type == "ac" and b.parent == block_id for b in blocks)


def _child_ac_ids(blocks: tuple[PlanBlock, ...], block_id: str) -> tuple[str, ...]:
    return tuple(b.block_id for b in blocks if b.block_type == "ac" and b.parent == block_id)


def _is_buildable(block: PlanBlock, by_id: dict[str, PlanBlock]) -> bool:
    def verified(block_id: str) -> bool:
        dependency = by_id.get(block_id)
        return dependency is not None and dependency.state == "closed/verified"

    return block.state == "pending" and all(verified(dep) for dep in block.depends)


def _feature_build_unit(plan: BuildPlan, feature: PlanBlock) -> BuildUnit | None:
    by_id = plan.by_id()
    executable = tuple(
        child for child in plan.children(feature.block_id) if child.block_type in {"story", "spike"}
    )
    if not executable:
        return None
    already_verified = tuple(child for child in executable if child.state == "closed/verified")
    pending = tuple(child for child in executable if child.state == "pending")
    if not pending:
        return None
    if not all(_is_buildable(child, by_id) for child in pending):
        return None
    return BuildUnit(
        block_id=feature.block_id,
        name=feature.name,
        block_type="feature",
        steps=pending,
        already_verified=already_verified,
    )


def _select_build_unit(plan: BuildPlan, step_id: str | None) -> BuildUnit | None:
    by_id = plan.by_id()
    if step_id is not None:
        block = by_id.get(step_id)
        if block is None:
            raise SpecificationError(f"Build step {step_id!r} not found in MANIFEST.md")
        if block.block_type == "feature":
            unit = _feature_build_unit(plan, block)
            if unit is None:
                raise SpecificationError(
                    f"{step_id!r} is not buildable; state={block.state!r}, "
                    "dependencies must be closed/verified"
                )
            return unit
        if block.block_type not in {"story", "spike"} or not _is_buildable(block, by_id):
            raise SpecificationError(
                f"{step_id!r} is not buildable; state={block.state!r}, "
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
    for block in plan.blocks:
        if (
            block.block_type in {"story", "spike"}
            and block.parent is None
            and _is_buildable(block, by_id)
        ):
            return BuildUnit(
                block_id=block.block_id,
                name=block.name,
                block_type=block.block_type,
                steps=(block,),
            )
    return None


def _snapshot_files(root: Path) -> dict[str, FileFingerprint]:
    """Return a stable fingerprint map for regular files under ``root``."""
    snapshots: dict[str, FileFingerprint] = {}
    if not root.is_dir():
        return snapshots
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        rel = str(path.relative_to(root))
        data = path.read_bytes()
        snapshots[rel] = FileFingerprint(size=len(data), digest=sha256(data).hexdigest())
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
    stale: list[str] = []
    for rel_path, record in sorted(plan.applied_specs.items()):
        source = blueprint_dir / rel_path
        if not source.is_file():
            stale.append(
                f"{rel_path}: missing (applied_by={record.applied_by}, "
                f"recorded_commit={record.commit})"
            )
            continue
        current_hash = _file_sha256(source)
        if current_hash == record.sha256:
            continue
        current_commit = _git_file_commit(source)
        stale.append(
            f"{rel_path}: recorded_commit={record.commit}, current_commit={current_commit}, "
            f"recorded_sha256={record.sha256[:12]}, current_sha256={current_hash[:12]}"
        )
    return tuple(stale)


def _ensure_applied_specs_current(plan_path: Path, blueprint_dir: Path) -> None:
    stale = _stale_applied_specs(plan_path, blueprint_dir)
    if not stale:
        return
    raise SpecificationError(
        "Build blocked: previously applied Blueprint specifications changed.\n"
        "Run the appropriate refit or planning workflow before continuing.\n"
        + "\n".join(f"  - {line}" for line in stale)
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
        category = (
            f"agent-reported failure: {agent_summary}"
            if agent_summary
            else "agent-reported failure"
        )
        detail = agent_detail or agent_summary or text.strip()
        return category, detail

    if not wrote_files:
        return "no build files written", "The build agent completed but changed no files."

    return None


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


def _clip(text: str, limit: int = 240) -> str:
    """Collapse whitespace to a single line and truncate to ``limit`` characters."""
    collapsed = " ".join(text.split())
    return collapsed if len(collapsed) <= limit else collapsed[: limit - 1].rstrip() + "…"


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
    if acceptance:
        lines.append("## Programmatic acceptance")
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
    acceptance: tuple[AcceptanceRunResult, ...],
    today: str,
    failure_summary: str = "",
    failure_detail: str = "",
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
    if acceptance:
        lines.append("## Programmatic acceptance")
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
        set_block_fields(manifest_path, reset_id, state="pending")
        for child in plan.children(reset_id):
            if child.block_type == "ac":
                set_block_fields(manifest_path, child.block_id, state="pending")


_MANIFEST_TO_TICKET_STATUS: dict[str, str] = {
    "closed/verified": "done",
    "implemented": "review",
    "closed/failed": "in_progress",
}


def _sync_ticket_status(target_dir: Path, block_id: str, manifest_state: str) -> None:
    """Update tickets.json status for the ticket whose id matches block_id, if present."""
    new_status = _MANIFEST_TO_TICKET_STATUS.get(manifest_state)
    if new_status is None:
        return
    tickets_path = target_dir / "QuarterDeck" / "tickets.json"
    if not tickets_path.is_file():
        return
    try:
        data = json.loads(tickets_path.read_text(encoding="utf-8"))
        changed = False
        for ticket in data.get("tickets", []):
            if ticket.get("id") == block_id:
                ticket["status"] = new_status
                changed = True
                break
        if changed:
            tickets_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    except (OSError, json.JSONDecodeError):
        pass


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
    force: bool = False,
) -> BuildResult:
    """Build every currently buildable step, stopping at acceptance review gates."""
    run = runner if runner is not None else run_prompt
    _ensure_drydock_source_clean()

    manifest_path = target_dir / "MANIFEST.md"
    if not manifest_path.is_file():
        raise SpecificationError(
            f"MANIFEST.md not found: {manifest_path}\n  Run: drydock plan {target}"
        )

    resolved_build_dir = build_dir or build_dir_for(target)
    resolved_build_dir.mkdir(parents=True, exist_ok=True)
    git_initialized = _ensure_git_repo(resolved_build_dir)
    evidence_dir = target_dir / "evidence"
    evidence_dir.mkdir(parents=True, exist_ok=True)

    stack_dir = get_stack_dir()
    blueprint_dir = blueprint_dir_for(target_dir)
    roots = StepRoots(
        target_dir=target_dir,
        blueprint_dir=blueprint_dir,
        stack_dir=stack_dir,
        rigging_dir=get_rigging_root(),
    )

    stack_head = _git_head(stack_dir)
    if stack_head is not None and _is_dirty(stack_dir):
        raise SpecificationError(
            "Build blocked: uncommitted changes in the stack directory. "
            "Commit or stash changes before building."
        )
    plan = parse_build_plan(manifest_path)
    ensure_compact_files(
        blueprint_dir,
        sources=list(required_plan_auto_compact_sources(plan.blocks, blueprint_dir)),
        reason="pre-build context refresh",
        log_dir=log_dir,
        target=target,
        on_text=on_text,
        model=model,
        llm_provider=llm_provider,
    )
    _ensure_applied_specs_current(manifest_path, blueprint_dir)

    prompt = load_prompt(PROMPT_NAME)
    today = date.today().isoformat()
    set_build_state(target_dir, "building")
    set_sub_state(target_dir, "running")

    if force and step_id is None:
        raise SpecificationError("--force requires --step <step-id>")
    if force and step_id is not None:
        _reset_step_for_rebuild(manifest_path, step_id)

    steps: list[BuildStepResult] = []
    guard = 0
    while True:
        plan = parse_build_plan(manifest_path)
        unit = _select_build_unit(plan, step_id)
        if unit is None:
            break
        guard += 1
        if guard > len(plan.blocks) + 1:  # defensive; state always advances per step
            break

        block_started = time.monotonic()
        block_started_at = _wall_time()
        _emit(on_text, "\n")
        _emit(on_text, "BUILD QUEUE: 1 ready block")
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
        _emit(
            on_text,
            (
                f"BUILD BLOCK START: {unit.block_id}  {unit.name}  "
                f"type={unit.block_type}  SP={group.total_story_points}  "
                f"started={block_started_at}"
            ),
        )
        _emit(
            on_text,
            (
                f"BUILD STORIES: {len(unit.steps)} run, "
                f"{len(unit.already_verified)} already verified"
            ),
        )
        _emit(on_text, f"BUILD WORKDIR: {resolved_build_dir}")
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
        before_files = _snapshot_files(resolved_build_dir)
        result = run(
            prompt_assembly.rendered_text,
            resolved_build_dir,
            llm=llm_provider,
            model=model or prompt.model,
            command_name="build",
            parameters={
                "step": unit.block_id,
                "step_type": unit.block_type,
                "steps": tuple(block.block_id for block in unit.steps),
            },
            allow_tools=True,
            log_dir=log_dir,
            target=target,
            on_text=on_text,
            prompt_assembly=prompt_assembly,
        )
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
        _emit(on_text, f"BUILD BLOCK RETURNED: {unit.block_id}  " + "  ".join(execution_bits))
        state, status, error, failure_detail = _build_outcome(
            summary,
            ok=ok,
            wrote_files=changed_files,
            stderr=str(getattr(result, "stderr", "") or ""),
            provider_error=_result_provider_error(result),
        )
        if changed_files:
            preview = ", ".join(changed_files[:5])
            suffix = "" if len(changed_files) <= 5 else f", ... (+{len(changed_files) - 5})"
            _emit(
                on_text,
                f"BUILD BLOCK FILES: {unit.block_id}  {len(changed_files)} changed: {preview}{suffix}",
            )
        else:
            _emit(on_text, f"BUILD BLOCK FILES: {unit.block_id}  0 changed")
        acceptance: tuple[AcceptanceRunResult, ...] = ()
        if status != "failed":
            checks = tuple(
                check
                for block in unit.steps
                for check in programmatic_acceptance_for_step(block, blueprint_dir)
            )
            if checks:
                _emit(on_text, f"BUILD ACCEPTANCE START: {unit.block_id}  {len(checks)} check(s)")
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
                # Per-check errors are already rendered in the evidence acceptance section.
                failure_detail = ""
            else:
                state, status, error = "closed/verified", "built", None
                failure_detail = ""
            if checks:
                passed = sum(1 for check in acceptance if check.passed)
                _emit(
                    on_text,
                    f"BUILD ACCEPTANCE RESULT: {unit.block_id}  {passed}/{len(checks)} passed",
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
            acceptance=acceptance,
            today=today,
            failure_summary=error or "",
            failure_detail=failure_detail,
        )
        finding = _failure_finding(status, error, result, acceptance)
        for block in unit.steps:
            block_fields: dict[str, str | None] = {
                "state": state,
                "evidence": _rel(evidence_path, target_dir),
            }
            if finding is not None:
                block_fields["finding"] = finding
            elif block.block_type != "spike":
                # Clear any stale failure reason when a story succeeds; a spike's
                # ``finding:`` records research output and is never cleared here.
                block_fields["finding"] = None
            set_block_fields(manifest_path, block.block_id, **block_fields)
            if status != "failed" and _has_child_acs(plan.blocks, block.block_id):
                for child_id in _child_ac_ids(plan.blocks, block.block_id):
                    set_block_fields(manifest_path, child_id, state="closed/verified")
            _sync_ticket_status(target_dir, block.block_id, state)
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

        if status == "failed":
            _emit(
                on_text,
                (
                    f"BUILD BLOCK FAILED: {unit.block_id}  "
                    f"completed={_wall_time()}  "
                    f"elapsed={_elapsed_text(time.monotonic() - block_started)}  "
                    f"{error or 'build failed'}"
                ),
            )
        else:
            _emit(
                on_text,
                (
                    f"BUILD BLOCK COMPLETE: {unit.block_id}  state={state}  "
                    f"completed={_wall_time()}  "
                    f"elapsed={_elapsed_text(time.monotonic() - block_started)}  "
                    f"evidence={_rel(evidence_path, target_dir)}"
                ),
            )
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
                written_files=changed_files,
                acceptance=acceptance,
            )
            steps.append(step_result)
            if on_step is not None:
                on_step(step_result)
        if status == "failed" or step_id is not None:
            break

    git_commit, git_commit_message = _commit_build_dir(resolved_build_dir, target, today)
    drydock_commit_skipped_after_build = git_commit is None and any(
        step.status in {"built", "implemented"} and step.written_files for step in steps
    )

    from drydock.quarterdeck_state import refresh_commanders_chair as _refresh_chair

    readme_path: Path | None = None
    if any(step.status in {"built", "implemented"} for step in steps):
        set_build_state(target_dir, "built")
        set_sub_state(target_dir, "complete")
        stamp_last(target_dir, "built")
        from drydock.readme_generate import generate_readme

        readme_path = generate_readme(target_dir, resolved_build_dir)

    _refresh_chair(target_dir)

    return BuildResult(
        target=target,
        build_dir=resolved_build_dir,
        steps=steps,
        git_initialized=git_initialized,
        git_commit=git_commit,
        git_commit_message=git_commit_message,
        drydock_commit_skipped_after_build=drydock_commit_skipped_after_build,
        readme_path=readme_path,
    )

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
returns a summary; tests inject a fake runner so no credits or network are used.
"""

from __future__ import annotations

import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from hashlib import sha256
from pathlib import Path

from drydock.build import StepAssembly, StepRoots, assemble_step, render_build_prompt_assembly
from drydock.build_plan import PlanBlock, parse_build_plan, set_applied_registry
from drydock.config import blueprint_dir_for, build_dir_for
from drydock.errors import SpecificationError
from drydock.llm import run_prompt
from drydock.manifest_edit import set_block_fields
from drydock.paths import get_rigging_root, get_stack_dir
from drydock.prompts import load_prompt

PROMPT_NAME = "build"
RunnerFn = Callable[..., object]
TextCallback = Callable[[str], None]


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
    status: str  # built | implemented | failed
    state: str  # resulting manifest block state
    story_points: int
    execution_id: str | None = None
    evidence_path: Path | None = None
    error: str | None = None


@dataclass(frozen=True)
class BuildResult:
    target: str
    build_dir: Path
    steps: list[BuildStepResult]

    def built(self) -> list[BuildStepResult]:
        return [s for s in self.steps if s.status in ("built", "implemented")]

    def failed(self) -> list[BuildStepResult]:
        return [s for s in self.steps if s.status == "failed"]

    def exit_code(self) -> int:
        return 1 if self.failed() else 0


def _rel(path: Path, base: Path) -> str:
    try:
        return str(path.relative_to(base))
    except ValueError:
        return str(path)


def _has_child_acs(blocks: tuple[PlanBlock, ...], block_id: str) -> bool:
    return any(b.block_type == "ac" and b.parent == block_id for b in blocks)


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


def _parse_build_report(summary: str) -> tuple[str | None, tuple[str, ...] | None]:
    """Extract ``RESULT`` and ``FILES CHANGED`` from the final build report."""
    lines = summary.splitlines()
    result: str | None = None
    files: list[str] = []
    in_files = False
    for line in lines:
        stripped = line.strip()
        if not stripped:
            if in_files:
                in_files = False
            continue
        if stripped.startswith("RESULT:"):
            result = stripped.partition(":")[2].strip().upper()
            in_files = False
            continue
        if stripped == "FILES CHANGED:":
            in_files = True
            continue
        if stripped.endswith(":") and stripped != "FILES CHANGED:":
            in_files = False
            continue
        if in_files and stripped.startswith("- "):
            files.append(stripped[2:].strip())
    return result, tuple(files) if files else None


def _build_outcome(
    summary: str,
    *,
    ok: bool,
    wrote_files: tuple[str, ...],
) -> tuple[str, str, str | None]:
    """Map provider result + report contract + file delta to manifest outcome."""
    if not ok:
        return "closed/failed", "failed", "LLM execution failed"
    if not summary.strip():
        return "closed/failed", "failed", "empty output"

    result, reported_files = _parse_build_report(summary)
    if result is None or reported_files is None:
        return "closed/failed", "failed", "missing structured build report"
    if result != "SUCCESS":
        return "closed/failed", "failed", "build agent reported failure"
    if not wrote_files:
        return "closed/failed", "failed", "no build files written"
    return "", "", None


def _write_evidence(
    path: Path,
    block: PlanBlock,
    assembly: StepAssembly,
    *,
    state: str,
    execution_id: str | None,
    summary: str,
    written_files: tuple[str, ...],
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
    lines.append("## Build summary")
    lines.append(summary.strip() or "(no summary returned)")
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8", newline="\n")


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
) -> BuildResult:
    """Build every currently buildable step, stopping at acceptance review gates."""
    run = runner if runner is not None else run_prompt

    manifest_path = target_dir / "MANIFEST.md"
    if not manifest_path.is_file():
        raise SpecificationError(
            f"MANIFEST.md not found: {manifest_path}\n  Run: drydock plan {target}"
        )

    resolved_build_dir = build_dir or build_dir_for(target)
    resolved_build_dir.mkdir(parents=True, exist_ok=True)
    evidence_dir = target_dir / "evidence"
    evidence_dir.mkdir(parents=True, exist_ok=True)

    stack_dir = get_stack_dir()
    roots = StepRoots(
        target_dir=target_dir,
        blueprint_dir=blueprint_dir_for(target_dir),
        stack_dir=stack_dir,
        rigging_dir=get_rigging_root(),
    )

    stack_head = _git_head(stack_dir)
    if stack_head is not None and _is_dirty(stack_dir):
        raise SpecificationError(
            "Build blocked: uncommitted changes in the stack directory. "
            "Commit or stash changes before building."
        )

    prompt = load_prompt(PROMPT_NAME)
    today = date.today().isoformat()

    steps: list[BuildStepResult] = []
    guard = 0
    while True:
        plan = parse_build_plan(manifest_path)
        frontier = plan.buildable_steps()
        if not frontier:
            break
        guard += 1
        if guard > len(plan.blocks) + 1:  # defensive; state always advances per step
            break

        block = frontier[0]
        compact_stack: frozenset[str] | None = None
        if stack_head is not None:
            compact_stack = frozenset(
                name
                for name, commit in plan.applied_registry.items()
                if commit == stack_head
            )
        assembly = assemble_step(block, roots, compact_stack=compact_stack)
        prompt_assembly = render_build_prompt_assembly(
            prompt.body,
            assembly,
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
            parameters={"step": block.block_id, "step_type": block.block_type},
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
        state, status, error = _build_outcome(summary, ok=ok, wrote_files=changed_files)
        if status == "failed":
            pass
        elif _has_child_acs(plan.blocks, block.block_id):
            state, status, error = "implemented", "implemented", None
        else:
            state, status, error = "closed/verified", "built", None

        evidence_path = evidence_dir / f"{block.block_id}.md"
        _write_evidence(
            evidence_path,
            block,
            assembly,
            state=state,
            execution_id=execution_id,
            summary=summary,
            written_files=changed_files,
            today=today,
        )
        set_block_fields(
            manifest_path,
            block.block_id,
            state=state,
            evidence=_rel(evidence_path, target_dir),
        )
        if status != "failed" and stack_head is not None:
            updated_registry = dict(plan.applied_registry)
            changed = False
            for field_key in ("stack", "rules", "context", "implements"):
                field_val = block.fields.get(field_key, ())
                if isinstance(field_val, tuple):
                    for name in field_val:
                        updated_registry[name] = stack_head
                        changed = True
            if changed:
                set_applied_registry(manifest_path, updated_registry)

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
        )
        steps.append(step_result)
        if on_step is not None:
            on_step(step_result)
        if status == "failed":
            break

    return BuildResult(target=target, build_dir=resolved_build_dir, steps=steps)

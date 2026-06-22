"""``drydock build`` — execute the Manifest's buildable frontier.

Build walks the MANIFEST.md work graph and, for each story or spike whose
``depends:`` are all ``closed/verified``, assembles one prompt (the same stack the
compass costs) and runs a tool-enabled agent that writes the application into the
build working directory. After each step it writes reviewable evidence and
transitions the block's state through the decision writer: a step with child
acceptance checks goes to ``implemented`` (a review gate); a step with none closes
automatically. Running build is the approval — it is not gated by plan state.

The module owns evidence and state writes. The agent writes application files and
returns a summary; tests inject a fake runner so no credits or network are used.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from drydock.build import StepAssembly, StepRoots, assemble_step, render_build_prompt
from drydock.build_plan import PlanBlock, parse_build_plan
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


def _write_evidence(
    path: Path,
    block: PlanBlock,
    assembly: StepAssembly,
    *,
    state: str,
    execution_id: str | None,
    summary: str,
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

    roots = StepRoots(
        target_dir=target_dir,
        blueprint_dir=blueprint_dir_for(target_dir),
        stack_dir=get_stack_dir(),
        rigging_dir=get_rigging_root(),
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
        assembly = assemble_step(block, roots)
        prompt_text = render_build_prompt(
            prompt.body,
            assembly,
            target=target,
            build_dir=resolved_build_dir,
            today=today,
        )
        result = run(
            prompt_text,
            resolved_build_dir,
            llm=llm_provider,
            model=model or prompt.model,
            command_name="build",
            parameters={"step": block.block_id, "step_type": block.block_type},
            allow_tools=True,
            log_dir=log_dir,
            target=target,
            on_text=on_text,
        )

        ok = bool(getattr(result, "ok", False))
        summary = str(getattr(result, "text", "") or "")
        execution_id = getattr(result, "execution_id", None)
        if not ok or not summary.strip():
            state, status = "closed/failed", "failed"
            error = "empty output" if ok else "LLM execution failed"
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
            today=today,
        )
        set_block_fields(
            manifest_path,
            block.block_id,
            state=state,
            evidence=_rel(evidence_path, target_dir),
        )

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

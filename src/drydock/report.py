"""Deterministic Target reports over existing Drydock projections and evidence."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from drydock.errors import UsageError


@dataclass(frozen=True)
class ReportContext:
    target: str
    target_dir: Path
    workspace: Path


@dataclass(frozen=True)
class ReportType:
    name: str
    description: str
    render: Callable[[ReportContext], str]

    @property
    def command(self) -> str:
        return f"drydock report {self.name} <Target>"


def _status(ctx: ReportContext) -> str:
    from drydock.status import status_blueprint_target

    result = status_blueprint_target(
        ctx.target, ctx.target, ctx.target_dir / "blueprint", ctx.target_dir.parent
    )
    info = result.target_info
    assert info is not None
    lines = [f"Target: {info.display_name}", f"Phase: {info.phase}", f"State: {info.phase_detail}"]
    if info.analysis:
        lines.append(
            f"Analysis: {info.analysis.quality or 'unknown'} · "
            f"{info.analysis.story_count} stories · {info.analysis.question_count} questions · "
            f"{info.analysis.blocker_count} blockers"
        )
    if info.plan_summary:
        from drydock.status import format_story_states

        lines.append(f"Plan: {format_story_states(info.plan_summary)}")
        lines.append(
            "Frontier: " + (", ".join(block.block_id for block in result.frontier) or "none")
        )
    else:
        lines.append("Plan: not created")
    lines.append(f"Next step: {info.next_operation}")
    return "\n".join(lines) + "\n"


def _manifest(ctx: ReportContext) -> str:
    from drydock.build_plan import parse_build_plan
    from drydock.build_status import build_status

    path = ctx.target_dir / "MANIFEST.md"
    if not path.is_file():
        return f"Manifest: {ctx.target}\nNo MANIFEST.md exists.\n"
    plan = parse_build_plan(path)
    state = build_status(plan)
    lines = [
        f"Manifest: {ctx.target}",
        f"Plan state: {plan.state}",
        f"Steps: {state.steps_total} total · {state.steps_verified} verified · "
        f"{state.steps_built + state.steps_implemented} built · "
        f"{state.steps_pending} pending · {state.steps_failed} failed",
        f"Complete: {state.percent_complete()}%",
        "Buildable now: " + (", ".join(state.buildable_ids) or "none"),
        "Failed: " + (", ".join(state.failed_ids) or "none"),
        "",
        "Groups",
    ]
    for group in state.groups:
        lines.append(f"  {group.name} [{group.group_id}]: {group.completed}/{group.total} complete")
        for step in group.steps:
            block = step.block
            ready = " · ready" if step.buildable else ""
            lines.append(f"    {block.block_id}: {block.state}{ready} · {block.name}")
    if not state.groups:
        lines.append("  none")
    return "\n".join(lines) + "\n"


def _run(ctx: ReportContext) -> str:
    from drydock.project_status import LABEL_LADDER, latest_per_label, read_status, standing_state

    entries = read_status(ctx.target_dir)
    current = standing_state(entries)
    held = latest_per_label(entries)
    lines = [f"Run state: {ctx.target}"]
    if current is None:
        return "\n".join([*lines, "No project state recorded.", ""])
    lines.append(f"Current: {current.label} · {'PASS' if current.passed else 'FAIL'}")
    if current.detail:
        lines.append(f"Detail: {current.detail}")
    lines.extend(["", "Lifecycle"])
    for label in LABEL_LADDER:
        entry = held.get(label)
        result = "—" if entry is None else ("PASS" if entry.passed else "FAIL")
        suffix = f" · {entry.at} · attempt {entry.attempts}" if entry else ""
        lines.append(f"  {label}: {result}{suffix}")
    return "\n".join(lines) + "\n"


def _build(ctx: ReportContext) -> str:
    from drydock.build_report import build_score_report

    result = build_score_report(
        ctx.target, ctx.target_dir, records_path=ctx.workspace / "logs" / "llm.jsonl"
    )
    verified = sum(block.verified for block in result.blocks)
    lines = [
        f"Build report: {ctx.target}",
        f"Blocks: {verified}/{len(result.blocks)} verified · {len(result.repaired_blocks)} repaired",
        f"Acceptance: {result.passed_checks}/{result.total_checks} checks passed",
        f"Usage: {result.calls} calls · {result.cached_input:,} cached input · "
        f"{result.fresh_input:,} fresh input · {result.output:,} output",
        "",
        "Blocks",
    ]
    for block in result.blocks:
        lines.append(
            f"  {block.block_id}: {block.state or 'unknown'} · "
            f"{block.passed_checks}/{block.total_checks} checks · {block.calls} calls"
        )
        if block.failed_check_ids:
            lines.append(f"    Failed checks: {', '.join(block.failed_check_ids)}")
    if not result.blocks:
        lines.append("  No build evidence recorded.")
    if result.missing_usage:
        lines.append(f"Missing usage records: {len(result.missing_usage)}")
    return "\n".join(lines) + "\n"


def _history(ctx: ReportContext) -> str:
    from drydock.config import read_command_history

    records = read_command_history(ctx.workspace, ctx.target, limit=1_000_000)
    lines = [f"Run history: {ctx.target}"]
    if not records:
        return "\n".join([*lines, "No command history recorded.", ""])
    for record in reversed(records):
        command = str(record.get("command") or " ".join(record.get("argv") or ()))
        when = str(record.get("time") or record.get("stamp") or "")
        code = record.get("return_code", record.get("returncode", "?"))
        lines.append(f"{when} · exit {code} · {command}")
    return "\n".join(lines) + "\n"


def _llm(ctx: ReportContext) -> str:
    from drydock.llm_report import LlmReportError, build_llm_score_report

    try:
        result = build_llm_score_report(ctx.workspace, ctx.target_dir, ctx.target)
    except LlmReportError:
        # An absent or unusable init boundary still leaves reportable raw evidence.
        result = build_llm_score_report(ctx.workspace, ctx.target_dir, ctx.target, all_history=True)
    scope = f"since init {result.init_stamp}" if result.since_init else "all recorded history"
    lines = [
        f"LLM usage: {ctx.target}",
        f"Scope: {scope}",
        f"Calls: {result.calls} · input {result.total_input_tokens:,} · "
        f"cached {result.cached_input_tokens:,} · output {result.output_tokens:,}",
        "",
        "Verb | Subclass | Model | Calls | Total tokens",
    ]
    lines.extend(
        f"{row.verb} | {row.subclass} | {row.model} | {row.calls} | {row.total_tokens:,}"
        for row in result.rows
    )
    if not result.rows:
        lines.append("No LLM executions recorded.")
    if result.invalid_records:
        lines.append(f"Invalid records skipped: {result.invalid_records}")
    return "\n".join(lines) + "\n"


def _token(ctx: ReportContext) -> str:
    from drydock.llm_report import LlmReportError, build_llm_score_report

    try:
        result = build_llm_score_report(
            ctx.workspace, ctx.target_dir, ctx.target, include_incomplete=True
        )
    except LlmReportError:
        result = build_llm_score_report(ctx.workspace, ctx.target_dir, ctx.target, all_history=True)
    runs = sorted(result.runs, key=lambda run: run.started_at)
    scope = f"since init {result.init_stamp}" if result.since_init else "all recorded history"
    lines = [
        f"Prompt sizes: {ctx.target}",
        f"Scope: {scope}",
        f"Calls: {len(runs)} · prompt {sum(run.prompt_bytes for run in runs):,} bytes · "
        f"~{sum(run.prompt_tokens_estimate for run in runs):,} tokens · "
        f"run time {_duration(sum(run.elapsed_ms for run in runs))}",
        "",
        "Started (UTC) | Stage | Call | Model | Prompt bytes | ~Prompt tokens | Run time | Status",
    ]
    lines.extend(
        f"{run.started_at[:19].replace('T', ' ')} | {run.verb}/{run.subclass} | {run.detail} | "
        f"{run.model or run.provider or 'unknown'} | {run.prompt_bytes:,} | "
        f"{run.prompt_tokens_estimate:,} | {_duration(run.elapsed_ms)} | {run.status}"
        for run in runs
    )
    if not runs:
        lines.append("No LLM executions recorded.")
    return "\n".join(lines) + "\n"


def _duration(elapsed_ms: int) -> str:
    seconds = elapsed_ms // 1000
    return f"{seconds // 60}m{seconds % 60:02d}s" if seconds >= 60 else f"{elapsed_ms / 1000:.1f}s"


def _scores(ctx: ReportContext) -> str:
    from drydock.score_summary import render_summary, summarize_scores

    result = summarize_scores(ctx.target, ctx.workspace, ctx.target_dir)
    return "\n".join(render_summary(result)) + "\n"


REPORT_TYPES = (
    ReportType("status", "Target phase, plan, frontier, and next step", _status),
    ReportType("manifest", "Manifest groups, step states, and buildable frontier", _manifest),
    ReportType("run", "Recorded lifecycle state and attempts", _run),
    ReportType("build", "Recorded build evidence, repairs, and usage", _build),
    ReportType("history", "Target command execution history", _history),
    ReportType("llm", "Lifecycle LLM usage by command and model", _llm),
    ReportType("token", "Prompt size, model, and run time of each LLM call", _token),
    ReportType("scores", "Last score runs and artifact locations", _scores),
)


def report_help() -> str:
    widths = (
        max(len(item.name) for item in REPORT_TYPES),
        max(len(item.command) for item in REPORT_TYPES),
    )
    lines = ["ReportName | Command | Description", "--- | --- | ---"]
    lines.extend(
        f"{item.name.ljust(widths[0])} | {item.command.ljust(widths[1])} | {item.description}"
        for item in REPORT_TYPES
    )
    lines.extend([
        "",
        "All Targets: drydock report --all",
        "One Target: drydock report --all <Target>",
        "Passed UAT runs (workspace, printed): drydock report uat_report",
    ])
    return "\n".join(lines)


def write_reports(ctx: ReportContext, names: tuple[str, ...]) -> tuple[Path, ...]:
    """Render selected reports first, then persist their text in one Target directory."""
    catalog = {item.name: item for item in REPORT_TYPES}
    unknown = set(names) - catalog.keys()
    if unknown:
        raise UsageError(f"Unknown report: {', '.join(sorted(unknown))}. Run: drydock report help")
    rendered = [(name, catalog[name].render(ctx)) for name in names]
    directory = ctx.target_dir / "reports"
    directory.mkdir(exist_ok=True)
    paths = []
    for name, body in rendered:
        path = directory / f"{name}.txt"
        path.write_text(body, encoding="utf-8", newline="\n")
        paths.append(path)
    return tuple(paths)

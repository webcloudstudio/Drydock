"""Drydock CLI — argparse-based command dispatcher."""

from __future__ import annotations

import argparse
import logging
import sys
import traceback
from pathlib import Path

from drydock import __copyright__, __version__
from drydock.errors import DrydockError, UsageError
from drydock.stubs import not_implemented

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Output helpers
# ---------------------------------------------------------------------------


_SEVERITY_ICON = {"PASS": "✓", "WARN": "⚠", "FAIL": "✗"}

# Post-command "Next step:" hints, centralized in one place because the workflow is still
# evolving. Keyed by command; value is a template formatted with the resolved target.
_NEXT_STEP_HINTS: dict[str, str] = {
    "import": "drydock analyze {target}",
}


def _print_next_step(command: str, target: str) -> None:
    hint = _NEXT_STEP_HINTS.get(command)
    if hint:
        print()
        print(f"Next step: {hint.format(target=target)}")


def _print_findings(result, verbose: bool) -> None:
    from drydock.validate_specification import Severity

    sections: dict[str, list] = {}
    for finding in result.findings:
        sections.setdefault(finding.section, []).append(finding)

    for section, findings in sections.items():
        visible = [f for f in findings if f.severity != Severity.PASS or verbose]
        if not visible:
            continue
        print(f"\n{section}:")
        for finding in visible:
            icon = _SEVERITY_ICON.get(finding.severity.value, "?")
            print(f"  {icon}  {finding.message}")

    print()
    total_fail = len(result.failures())
    total_warn = len(result.warnings())
    if total_fail > 0:
        print(f"✗ FAIL ({total_fail} errors, {total_warn} warnings)")
    elif total_warn > 0:
        print(f"⚠ PASS with warnings ({total_warn} warnings)")
    else:
        print("✓ PASS")


# ---------------------------------------------------------------------------
# Command implementations
# ---------------------------------------------------------------------------


def cmd_config_show(_args: argparse.Namespace) -> int:
    from drydock.config import config_show

    rows = config_show()
    for display_key, value, source in rows:
        print(f"  {display_key:<30} {value}  ({source})")
    return 0


def cmd_config_set(args: argparse.Namespace) -> int:
    from drydock.config import config_set

    cfg_file = config_set(args.key, args.value)
    print(f"Set {args.key} -> {args.value}")
    print(f"Saved to {cfg_file}")
    return 0


def cmd_init(args: argparse.Namespace) -> int:
    from drydock.config import (
        get_target_directory,
        record_activity,
    )
    from drydock.init_target import init_target

    logger.debug("cmd_init: target=%s", args.Target)
    targets_root = get_target_directory()
    result = init_target(
        args.Target,
        targets_root,
        display_name=getattr(args, "display_name", ""),
        short_description=getattr(args, "short_description", ""),
    )

    print(f"Target: {result.target_dir}")
    for path in result.created:
        print(f"  CREATED  {path.relative_to(result.target_dir)}")
    if result.skipped:
        print(f"  ({len(result.skipped)} existing baseline files preserved)")
    if not result.created:
        print("  Nothing to do — target baseline is already initialized.")

    record_activity("init", target=args.Target)
    t = args.Target
    print()
    print("Next steps:")
    print(f"  1. Import source material:  drydock import {t} <source> --format markdown")
    print(f"  2. Analyze the spec:        drydock analyze {t}")
    print(f"  3. Create a plan:           drydock plan create {t}")
    print(f"  4. Review and approve:      drydock run quarterdeck {t}")
    return 0


def cmd_validate(args: argparse.Namespace) -> int:
    from drydock.config import get_target_directory
    from drydock.validate_specification import validate_specification

    target_dir = get_target_directory() / args.Target
    result = validate_specification(args.Target, target_dir, verbose=args.verbose)

    print(f"Validating Blueprint: {args.Target}  ({result.spec_dir})")
    _print_findings(result, args.verbose)
    return result.exit_code()


def cmd_rigging_compact(args: argparse.Namespace) -> int:
    from drydock.config import blueprint_dir_for, get_target_directory
    from drydock.rigging_compact import CompactItem, compact

    blueprint_dir = blueprint_dir_for(get_target_directory() / args.Target)

    def report(item: CompactItem) -> None:
        src = item.source.name
        dst = item.compact.name
        if item.status == "compacted":
            pct = f" ({item.percent:.0f}% of source)" if item.percent is not None else ""
            print(f"  [done]     {src} → {dst}  {item.compact_bytes} B{pct}  {item.execution_id}")
        elif item.status == "skipped-fresh":
            print(f"  [fresh]    {src} → {dst}  (compact is newer; use --force)")
        else:
            print(f"  [failed]   {src}: {item.error}  see logs/ ({item.execution_id})")

    print(f"Compacting Blueprint: {args.Target}")
    result = compact(
        args.Target,
        blueprint_dir,
        include_rigging=args.include_rigging,
        force=args.force,
        on_item=report,
    )

    if not result.items:
        print("  Nothing to compact — no compactable files found.")
    print()
    print(
        f"RESULT: {len(result.compacted())} compacted, "
        f"{len(result.skipped())} fresh, {len(result.failed())} failed"
    )
    return result.exit_code()


def cmd_analyze(args: argparse.Namespace) -> int:
    from drydock.analyze import analyze
    from drydock.config import get_target_directory

    target_dir = get_target_directory() / args.Target
    print(f"Analyzing Blueprint: {args.Target}")
    print("Running analysis...", flush=True)
    result = analyze(args.Target, target_dir)
    print()
    if not result.ok:
        print(f"Error: {result.error}", file=sys.stderr)
        return 1
    tdir = result.target_dir
    print(f"  ANALYSIS.md   →  {result.analysis_path.relative_to(tdir)}")
    print(f"  SEA_TRIALS.md →  {result.sea_trials_path.relative_to(tdir)}")
    print(f"  SOUNDINGS.md  →  {result.soundings_path.relative_to(tdir)}")
    if result.compass_path:
        print(f"  COMPASS.md    →  {result.compass_path.relative_to(tdir)}  (created)")
    for spike_path in result.spike_paths:
        print(f"  {spike_path.name:<20} →  {spike_path.relative_to(tdir)}")
    if result.captains_chair_path:
        print(
            f"  captains_chair  →  {result.captains_chair_path.relative_to(tdir)}  (lifecycle: analyzed)"
        )
    print()
    _quality_icon = {"Ready": "✓", "Questions": "⚠", "Blocked": "✗"}.get(result.quality, "?")
    print(
        f"Quality: {_quality_icon}  {result.quality}  "
        f"({result.story_count} stories · {result.question_count} questions · "
        f"{result.blocker_count} blockers)"
    )
    print()
    if result.quality == "Ready":
        print(f"Next step: drydock plan create {args.Target}")
    elif result.quality == "Questions":
        print("Review open questions in ANALYSIS.md, then run:")
        print(f"  drydock plan create {args.Target}")
    else:
        print("Resolve blockers listed in ANALYSIS.md, then re-run:")
        print(f"  drydock analyze {args.Target}")
    return 0


def _print_plan_blocks(plan, *, frontier_ids: set[str] | None = None) -> None:
    frontier_ids = frontier_ids or set()
    for block in plan.blocks:
        marker = "RUNNABLE" if block.block_id in frontier_ids else block.state.upper()
        print(f"  {marker:<15} {block.block_type:<5} {block.block_id:<24} {block.name}")


def _print_plan_summary(plan) -> None:
    counts = plan.state_counts()
    print()
    print(
        "Summary: "
        + ", ".join(
            f"{state}={counts[state]}"
            for state in (
                "pending",
                "implemented",
                "closed/verified",
                "closed/failed",
            )
        )
    )
    print(f"Plan state: {plan.state}")


def cmd_plan_create(args: argparse.Namespace) -> int:
    from drydock.config import get_target_directory
    from drydock.planning_session import create_plan

    result = create_plan(
        args.Target,
        args.Target,
        get_target_directory(),
    )
    print(f"Blueprint: {result.plan.project}")
    print(f"Plan: {result.plan.path}")
    print(f"Plan state: {result.plan.state}")
    print(f"Planning Session: {result.quarterdeck_dir}")
    print()
    _print_plan_blocks(result.plan)
    _print_plan_summary(result.plan)
    print()
    print("Next step: review and approve the plan in the Planning Session.")
    return 0


def cmd_survey(args: argparse.Namespace) -> int:
    from pathlib import Path as _Path

    from drydock.config import get_target_directory
    from drydock.errors import UsageError
    from drydock.survey import (
        import_specs,
        load_records,
        render_scoreboard,
        run_survey,
        survey_dir_for,
    )

    target_dir = get_target_directory() / args.Target
    if not target_dir.is_dir():
        raise UsageError(f"Target not found: {args.Target}")

    if args.import_path:
        written = import_specs(args.Target, target_dir, _Path(args.import_path))
        print(f"Regenerated {len(written)} acceptance-criteria file(s):")
        for path in written:
            print(f"  {path.name}")
        return 0

    if args.run:
        print(f"Surveying: {args.Target}")
        records = run_survey(args.Target, target_dir, command=args.command_filter)
        print(f"  scored {len(records)} command(s)")

    records = load_records(survey_dir_for(target_dir))
    if args.raw:
        import json as _json

        for rec in records:
            print(_json.dumps(rec))
        return 0

    print(render_scoreboard(records, command=args.command_filter))
    return 0


def cmd_prompt_review(args: argparse.Namespace) -> int:
    from drydock.paths import get_repo_root
    from drydock.prompt_review import review_prompt

    print(f"Reviewing prompt: {args.Component}")
    result = review_prompt(args.Component)
    repo_root = get_repo_root()
    print(f"  review      →  {result.review_path.relative_to(repo_root)}")
    if result.archive_path:
        print(f"  archived    →  {result.archive_path.relative_to(repo_root)}")
    print()
    print(
        f"Score: {result.overall_score:.1f}/10  "
        f"({result.rating_band}; model: {result.review_model})"
    )
    return 0


def cmd_import(args: argparse.Namespace) -> int:
    from drydock.config import get_target_directory
    from drydock.import_markdown import detect_import_format

    source = Path(args.Source)
    fmt = args.format
    if fmt == "auto":
        fmt = detect_import_format(source)

    td = get_target_directory()

    if fmt == "markdown":
        from drydock.import_markdown import import_markdown

        result = import_markdown(args.Target, args.Target, source, td)
        print(f"Blueprint: {result.blueprint_dir}")
        print(f"Source: {result.source}")
        for path in result.imported:
            print(f"  IMPORTED  {path.relative_to(result.blueprint_dir)}")
            print(f"  SAVED AS  {path}")
        _print_next_step("import", args.Target)
        return 0

    if fmt == "source":
        from drydock.import_source import import_source

        result = import_source(args.Target, args.Target, source, td)
        print(f"Blueprint: {result.blueprint_dir}")
        print(f"Source: {result.source}")
        for path in result.imported:
            print(f"  IMPORTED  {path.relative_to(result.blueprint_dir)}")
            print(f"  SAVED AS  {path}")
        _print_next_step("import", args.Target)
        return 0

    if fmt == "speckit":
        from drydock.import_speckit import import_speckit

        result = import_speckit(args.Target, args.Target, source, td)
        print(f"Blueprint: {result.blueprint_dir}")
        print(f"Source: {result.source}")
        print(f"Features: {', '.join(result.features_found) or '(none)'}")
        for path in result.imported:
            print(f"  IMPORTED  {path.relative_to(result.blueprint_dir)}")
            print(f"  SAVED AS  {path}")
        _print_next_step("import", args.Target)
        return 0

    if fmt == "intent":
        from drydock.import_markdown import import_intent

        result = import_intent(args.Target, source, td)
        print(f"Blueprint: {result.blueprint_dir}")
        print(f"Source: {result.source}")
        for path in result.imported:
            print(f"  IMPORTED  {path.relative_to(result.blueprint_dir)}")
            print(f"  SAVED AS  {path}")
        print()
        print("COMPASS.md placed at Target root. Edit it to match the required format,")
        print("then run: drydock analyze", args.Target)
        return 0

    raise UsageError(f"Unknown format: {fmt!r}")


def cmd_document_assemble(argv: list[str]) -> int:
    from drydock.build_documentation import main as _build_doc_main

    return _build_doc_main(argv)


def _is_target_dir(path: Path) -> bool:
    return (
        (path / "QuarterDeck" / "console.yaml").is_file()
        or (path / "blueprint").is_dir()
        or (path / "METADATA.md").is_file()
    )


def _resolve_sole_target(targets_root: Path) -> Path:
    """Resolve the single initialized Target under the workspace, or error."""
    candidates = (
        [p for p in sorted(targets_root.iterdir()) if p.is_dir() and _is_target_dir(p)]
        if targets_root.is_dir()
        else []
    )
    if len(candidates) == 1:
        return candidates[0]
    if not candidates:
        raise DrydockError(
            f"No initialized Target found under {targets_root}\n  Run: drydock init <Target>"
        )
    names = ", ".join(p.name for p in candidates)
    raise DrydockError(
        f"Multiple Targets found ({names}); specify one: drydock run quarterdeck <Target>"
    )


def cmd_run_quarterdeck(args: argparse.Namespace) -> int:
    from drydock import quarterdeck_run as _qd
    from drydock.config import get_quarterdeck_port, get_target_directory

    targets_root = get_target_directory()
    target_dir = targets_root / args.Target if args.Target else _resolve_sole_target(targets_root)
    port = args.port if args.port is not None else get_quarterdeck_port()
    host = args.host

    print(f"QuarterDeck: {target_dir}")
    print(f"  http://{host}:{port}")

    result = _qd.run_quarterdeck(target_dir, port=port, host=host)
    return result.exit_code


def _render_status(result) -> None:
    """Print compact one-screen status output."""
    header = f"Drydock status — {result.blueprint}"
    if result.target:
        header += f" / {result.target}"
    print(header)
    print()

    col = 14

    if result.last_command:
        print(f"  {'Last command':<{col}}  {result.last_command:<22}  {result.last_time}")

    if result.validation is not None:
        from drydock.validate_specification import Severity

        v = result.validation
        n_fail = len(v.failures())
        n_warn = len(v.warnings())
        state_icon = "✗" if n_fail else ("⚠" if n_warn else "✓")
        detail = f"{n_fail} errors · {n_warn} warnings"
        print(f"  {'Blueprint':<{col}}  {state_icon}  {detail}")
        if n_fail or n_warn:
            for finding in v.findings:
                if finding.severity != Severity.PASS:
                    icon = _SEVERITY_ICON.get(finding.severity.value, "?")
                    print(f"    {icon}  {finding.section}: {finding.message}")

    if result.plan is not None:
        counts = result.plan.state_counts()
        total = len(result.plan.blocks)
        verified = counts.get("closed/verified", 0)
        pending = counts.get("pending", 0)
        impl = counts.get("implemented", 0)
        failed = counts.get("closed/failed", 0)
        progress = f"{verified}/{total} verified"
        detail = f"pending {pending} · implemented {impl} · failed {failed}"
        print(f"  {'Plan':<{col}}  {progress:<22}  {detail}")

        if result.frontier:
            for i, block in enumerate(result.frontier):
                label = "Frontier" if i == 0 else ""
                print(f"  {label:<{col}}  {block.block_id}: {block.name}")
        else:
            print(f"  {'Frontier':<{col}}  (none)")


def cmd_status_blueprint_target(blueprint: str, target: str) -> int:
    from drydock.config import blueprint_dir_for, get_target_directory, record_activity
    from drydock.status import status_blueprint_target

    targets_root = get_target_directory()
    target_dir = targets_root / target
    blueprint_dir = blueprint_dir_for(target_dir)
    result = status_blueprint_target(blueprint, target, blueprint_dir, targets_root)
    try:
        from drydock.validate_specification import validate_specification

        result.validation = validate_specification(blueprint, target_dir)
    except Exception:
        pass
    _render_status(result)
    record_activity("status", blueprint, target)
    return 0


def cmd_status_blueprint(blueprint: str) -> int:
    from drydock.config import get_target_directory, record_activity
    from drydock.status import status_blueprint

    target_dir = _resolve_sole_target(get_target_directory())
    result = status_blueprint(blueprint, target_dir)
    _render_status(result)
    record_activity("status", blueprint)
    return 0


def _render_workspace_status(ws) -> None:
    """Print the workspace-level dashboard for `drydock status` with no args."""
    if not ws.targets:
        print("No targets found.")
        print("  Next Step: drydock init <Target>")
        return

    for info in ws.targets:
        print(f"Target: {info.name}")
        print(f"   Status:    {info.phase_detail}")
        print(f"   Next Step: {info.next_operation}")
        for rec in reversed(info.history):
            cmd = rec.get("command", "")
            rc = rec.get("return_code")
            icon = "·" if rc is None else ("✓" if rc == 0 else "✗")
            print(f"   {icon} {cmd}")
        print()


def cmd_status_current() -> int:
    from drydock.config import get_target_directory, get_workspace
    from drydock.status import status_workspace

    logger.debug("cmd_status_current")
    workspace = get_workspace()
    targets_root = get_target_directory()
    ws = status_workspace(workspace, targets_root)
    _render_workspace_status(ws)
    return 0


def cmd_build_status(blueprint: str, target: str) -> int:
    from drydock.build_plan import load_target_plan
    from drydock.config import get_target_directory

    plan = load_target_plan(target, get_target_directory())
    target_path = get_target_directory() / target
    frontier = plan.runnable_frontier()
    frontier_ids = {block.block_id for block in frontier}

    print(f"Blueprint: {plan.project}")
    print(f"Target: {target_path}")
    print(f"Plan state: {plan.state}")
    print()
    _print_plan_blocks(plan, frontier_ids=frontier_ids)
    _print_plan_summary(plan)
    print("Runnable frontier: " + (", ".join(block.block_id for block in frontier) or "(none)"))
    return 0


# ---------------------------------------------------------------------------
# Parser construction
# ---------------------------------------------------------------------------


def _canonical_refit_mode(value: str) -> str:
    """Normalize the deprecated SPEC refit mode."""
    return "BLUEPRINT" if value == "SPEC" else value


def _add_stub(
    sub: argparse._SubParsersAction, name: str, help_text: str, args_spec: list[tuple]
) -> argparse.ArgumentParser:  # noqa: SLF001
    """Add a deferred stub subcommand."""
    p = sub.add_parser(name, help=help_text)
    for arg_name, kwargs in args_spec:
        p.add_argument(arg_name, **kwargs)
    return p


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="drydock",
        description=(f"Drydock — governed Blueprint-driven software delivery.\n{__copyright__}"),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"drydock {__version__}\n{__copyright__}",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        default=False,
        help="Show full traceback on unexpected errors.",
    )

    sub = parser.add_subparsers(dest="command", metavar="<command>")

    # ── config ──────────────────────────────────────────────────────────────
    p_config = sub.add_parser("config", help="Show or set Drydock configuration.")
    cfg_sub = p_config.add_subparsers(dest="config_command", metavar="<subcommand>")
    cfg_sub.add_parser("show", help="Display current configuration values and sources.")
    p_set = cfg_sub.add_parser("set", help="Set a configuration value.")
    p_set.add_argument(
        "key",
        choices=[
            "drydock_workspace",
            "llm_provider",
            "prompt_warn_kb",
            "quarterdeck_port",
        ],
    )
    p_set.add_argument("value", metavar="<value>")

    # ── init ─────────────────────────────────────────────────────────────────
    p_init = sub.add_parser("init", help="Initialize a target workspace.")
    p_init.add_argument("Target", metavar="<Target>")
    p_init.add_argument(
        "--display-name",
        dest="display_name",
        default="",
        metavar="<name>",
        help="Human-readable project name (default: target name).",
    )
    p_init.add_argument(
        "--description",
        dest="short_description",
        default="",
        metavar="<desc>",
        help="One-line project description.",
    )

    # ── status ────────────────────────────────────────────────────────────────
    # Handles: status
    #          status <Target>
    p_status = sub.add_parser(
        "status",
        help="Show project status and orientation.",
        description=(
            "drydock status           — compact dashboard of all targets\n"
            "drydock status <Target>  — validation summary and plan state"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p_status.add_argument("args", nargs=argparse.REMAINDER, metavar="[<Target>]")

    # ── validate ─────────────────────────────────────────────────────────────
    p_val = sub.add_parser("validate", help="Validate a Blueprint's Typed Specification.")
    p_val.add_argument("Target", metavar="<Target>")
    p_val.add_argument("--verbose", action="store_true", help="Also show passing checks.")

    # ── document ─────────────────────────────────────────────────────────────
    # Handles: document <Target>
    #          document generate <Target>
    #          document assemble <Target>
    # Strategy: use REMAINDER args and dispatch on first token.
    p_doc = sub.add_parser(
        "document",
        help="Generate and assemble Blueprint documentation.",
        description=(
            "drydock document <Target>           — full pipeline\n"
            "drydock document generate <Target>  — AI pass only\n"
            "drydock document assemble <Target>  — assembly only"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p_doc.add_argument("args", nargs=argparse.REMAINDER, metavar="[generate|assemble] <Target>")

    # ── rigging ──────────────────────────────────────────────────────────────
    p_rig = sub.add_parser("rigging", help="Manage Drydock Rigging.")
    rig_sub = p_rig.add_subparsers(dest="rigging_command", metavar="<subcommand>")
    p_rig_c = rig_sub.add_parser(
        "compact", help="Compact stale rules/data/spec files to _compact.md siblings."
    )
    p_rig_c.add_argument("Target", metavar="<Target>")
    p_rig_c.add_argument(
        "--all",
        dest="include_rigging",
        action="store_true",
        help="Also refresh Drydock's own Rigging engine compacts.",
    )
    p_rig_c.add_argument(
        "--force", action="store_true", help="Ignore the freshness gate and recompact everything."
    )
    p_rig_u = rig_sub.add_parser("update", help="Propagate rigging to a target project.")
    p_rig_u.add_argument("Target", metavar="<Target>")
    p_rig_v = rig_sub.add_parser("verify", help="Verify target project rigging compliance.")
    p_rig_v.add_argument("Target", metavar="<Target>")

    # ── plan ─────────────────────────────────────────────────────────────────
    p_plan = sub.add_parser("plan", help="Manage the build plan.")
    plan_sub = p_plan.add_subparsers(dest="plan_command", metavar="<subcommand>")
    p_plan_create = plan_sub.add_parser(
        "create", help="Create a draft executable plan and target Planning Session."
    )
    p_plan_create.add_argument("Target", metavar="<Target>")

    # ── build ─────────────────────────────────────────────────────────────────
    # Handles: build <Target>
    #          build status <Target>
    #          build score <Target>
    p_build = sub.add_parser(
        "build",
        help="Build or inspect build state.",
        description=(
            "drydock build <Target>          — build next frontier\n"
            "drydock build status <Target>   — show build state\n"
            "drydock build score <Target>    — generate SCORECARD.md"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p_build.add_argument("args", nargs=argparse.REMAINDER, metavar="[status|score] <Target>")

    # ── refit ─────────────────────────────────────────────────────────────────
    p_iter = sub.add_parser("refit", help="Update Blueprint and target software together.")
    p_iter.add_argument("Target", metavar="<Target>")
    p_iter.add_argument(
        "Mode",
        metavar="<BOTH|BLUEPRINT|TGT>",
        choices=["BOTH", "BLUEPRINT", "TGT"],
        type=_canonical_refit_mode,
    )
    p_iter.add_argument("Scope", metavar="<Scope>")
    p_iter.add_argument("Change", metavar="<Change>")

    # ── analyze ───────────────────────────────────────────────────────────────
    p_analyze = sub.add_parser("analyze", help="Decompose imported sources into stories, blockers, and acceptance milestones.")
    p_analyze.add_argument("Target", metavar="<Target>")

    # ── survey ────────────────────────────────────────────────────────────────
    p_survey = sub.add_parser(
        "survey",
        help="Score a target's build process against its acceptance criteria.",
        description=(
            "drydock survey <Target>            — render the latest scoreboard\n"
            "drydock survey <Target> --run      — score (LLM-assisted) and append results\n"
            "drydock survey <Target> --import D  — regenerate AC files from a spec directory\n"
            "drydock survey <Target> --command status   — filter to one command"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p_survey.add_argument("Target", metavar="<Target>")
    p_survey.add_argument(
        "--command",
        dest="command_filter",
        default=None,
        metavar="<name>",
        help="Filter to one command.",
    )
    p_survey.add_argument(
        "--import",
        dest="import_path",
        default=None,
        metavar="<path>",
        help="Re-read a Blueprint/sources directory and regenerate AC files.",
    )
    p_survey.add_argument(
        "--run",
        action="store_true",
        help="Perform a fresh survey (LLM-assisted) and append scores.",
    )
    p_survey.add_argument("--raw", action="store_true", help="Print raw score records as JSON.")

    # ── prompt ────────────────────────────────────────────────────────────────
    p_prompt = sub.add_parser("prompt", help="Review Drydock prompt contracts.")
    prompt_sub = p_prompt.add_subparsers(dest="prompt_command", metavar="<subcommand>")
    p_prompt_review = prompt_sub.add_parser(
        "review",
        help="Evaluate one prompt against the spec, matching notes, and consumer contracts.",
    )
    p_prompt_review.add_argument("Component", metavar="<component>")

    # ── run ───────────────────────────────────────────────────────────────────
    p_run = sub.add_parser("run", help="Start a Drydock service.")
    run_sub = p_run.add_subparsers(dest="run_command", metavar="<subcommand>")
    p_run_qd = run_sub.add_parser("quarterdeck", help="Start the QuarterDeck for a target project.")
    p_run_qd.add_argument(
        "Target",
        metavar="<Target>",
        nargs="?",
        help="Configured target name; omit to run the current directory's QuarterDeck.",
    )
    p_run_qd.add_argument(
        "--port",
        type=int,
        default=None,
        metavar="PORT",
        help="Port to listen on (default: quarterdeck_port config or 8080).",
    )
    p_run_qd.add_argument(
        "--host",
        default="127.0.0.1",
        metavar="HOST",
        help="Host to bind to (default: 127.0.0.1).",
    )

    # ── import ────────────────────────────────────────────────────────────────
    p_import = sub.add_parser("import", help="Reverse-engineer a project into a Blueprint.")
    p_import.add_argument("Target", metavar="<Target>")
    p_import.add_argument("Source", metavar="<Source>")
    p_import.add_argument(
        "--format", choices=["auto", "markdown", "source", "speckit", "intent"], default="auto"
    )

    return parser


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------


def _dispatch_status(args: argparse.Namespace) -> int:
    tokens = args.args
    if len(tokens) == 0:
        return cmd_status_current()
    elif len(tokens) == 1:
        return cmd_status_blueprint_target(tokens[0], tokens[0])
    else:
        raise UsageError("Usage: drydock status [<Target>]")


def _dispatch_document(args: argparse.Namespace) -> int:
    tokens = args.args
    if not tokens:
        not_implemented("document")
    first = tokens[0] if tokens else ""
    if first == "generate":
        not_implemented("document generate")
    elif first == "assemble":
        return cmd_document_assemble(tokens[1:])
    else:
        not_implemented("document")
    return 2  # unreachable; not_implemented exits


def _dispatch_build(args: argparse.Namespace) -> int:
    tokens = args.args
    if not tokens:
        not_implemented("build")
    first = tokens[0] if tokens else ""
    if first == "status":
        if len(tokens) != 2:
            raise UsageError("Usage: drydock build status <Target>")
        rc = cmd_build_status(tokens[1], tokens[1])
        if rc == 0:
            from drydock.config import record_activity

            record_activity("build status", tokens[1], tokens[1])
        return rc
    elif first == "score":
        not_implemented("build score")
    else:
        not_implemented("build")
    return 2


def _dispatch(args: argparse.Namespace, parser: argparse.ArgumentParser) -> int:
    command = args.command

    if command is None:
        parser.print_help()
        return 0

    if command == "status":
        return _dispatch_status(args)

    if command == "config":
        if args.config_command == "show":
            return cmd_config_show(args)
        if args.config_command == "set":
            return cmd_config_set(args)
        parser.parse_args(["config", "--help"])
        return 0

    if command == "init":
        return cmd_init(args)

    if command == "validate":
        rc = cmd_validate(args)
        if rc == 0:
            from drydock.config import record_activity

            record_activity("validate", args.Target)
        return rc

    if command == "document":
        return _dispatch_document(args)

    if command == "rigging":
        sub = getattr(args, "rigging_command", None)
        if sub == "compact":
            rc = cmd_rigging_compact(args)
            if rc == 0:
                from drydock.config import record_activity

                record_activity("rigging compact", args.Target)
            return rc
        elif sub == "update":
            not_implemented("rigging update")
        elif sub == "verify":
            not_implemented("rigging verify")
        else:
            not_implemented("rigging")

    if command == "plan":
        sub = getattr(args, "plan_command", None)
        if sub == "create":
            rc = cmd_plan_create(args)
            if rc == 0:
                from drydock.config import record_activity

                record_activity("plan create", args.Target, args.Target)
            return rc
        else:
            not_implemented("plan")

    if command == "build":
        return _dispatch_build(args)

    if command == "refit":
        not_implemented("refit")

    if command == "analyze":
        rc = cmd_analyze(args)
        if rc == 0:
            from drydock.config import record_activity

            record_activity("analyze", args.Target, args.Target)
        return rc

    if command == "survey":
        rc = cmd_survey(args)
        if rc == 0:
            from drydock.config import record_activity

            record_activity("survey", args.Target, args.Target)
        return rc

    if command == "prompt":
        sub = getattr(args, "prompt_command", None)
        if sub == "review":
            rc = cmd_prompt_review(args)
            if rc == 0:
                from drydock.config import record_activity

                record_activity("prompt review", args.Component)
            return rc
        parser.parse_args(["prompt", "--help"])
        return 0

    if command == "run":
        sub = getattr(args, "run_command", None)
        if sub == "quarterdeck":
            return cmd_run_quarterdeck(args)
        else:
            parser.parse_args(["run", "--help"])
            return 0

    if command == "import":
        rc = cmd_import(args)
        if rc == 0:
            from drydock.config import record_activity

            record_activity("import", args.Target)
        return rc

    return 0


# Commands that are pure reports and are never recorded in history.jsonl.
# Everything else (including failures) is logged with its return code.
def _log_command_history(args: argparse.Namespace, argv: list[str] | None, rc: int) -> None:
    """Append one history line for any non-report command. Must never raise to the caller."""
    command = getattr(args, "command", None)
    if command is None:
        return  # bare `drydock` / help text
    if command == "status":
        return  # pure report
    if command == "config" and getattr(args, "config_command", None) == "show":
        return  # pure report

    from drydock.config import append_command_history, get_workspace

    tokens = argv if argv is not None else sys.argv[1:]
    cmd_str = "drydock " + " ".join(tokens)
    target = getattr(args, "Target", "") or ""
    append_command_history(get_workspace(), cmd_str, target=target, return_code=rc)


def main(argv: list[str] | None = None) -> None:
    parser = _build_parser()
    args = parser.parse_args(argv)
    print(f"Drydock {__version__}  {__copyright__}", file=sys.stderr)
    debug = getattr(args, "debug", False)

    try:
        from drydock.config import get_workspace
        from drydock.logging import setup_run_logger

        log_dir = get_workspace() / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        setup_run_logger(log_dir / "run.log", debug=debug)
        logger.info("command: %s", " ".join(sys.argv if argv is None else argv))
    except Exception:
        pass  # log setup failure must not prevent the command from running

    exit_code = 0
    try:
        exit_code = _dispatch(args, parser)
    except UsageError as exc:
        print(f"error: {exc}", file=sys.stderr)
        exit_code = 2
    except DrydockError as exc:
        print(f"error: {exc}", file=sys.stderr)
        exit_code = 1
    except SystemExit as exc:
        exit_code = exc.code if isinstance(exc.code, int) else 1
    except Exception as exc:
        if debug:
            traceback.print_exc()
        else:
            print(f"error: {type(exc).__name__}: {exc}", file=sys.stderr)
            print("Run with --debug for a full traceback.", file=sys.stderr)
        exit_code = 1

    try:
        _log_command_history(args, argv, exit_code)
    except Exception:
        pass  # history logging must never change the command's outcome

    sys.exit(exit_code)

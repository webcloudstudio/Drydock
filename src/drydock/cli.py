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
        append_command_history,
        get_target_directory,
        get_workspace,
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
    append_command_history(get_workspace(), f"drydock init {args.Target}", target=args.Target, return_code=0)
    t = args.Target
    print()
    print("Next steps:")
    print(f"  1. Import source material:  drydock import {t} {t} <source> --format markdown")
    print(f"  2. Create a plan:           drydock plan create {t} {t}")
    print(f"  3. Review and approve:      drydock run quarterdeck {t}")
    return 0


def cmd_validate(args: argparse.Namespace) -> int:
    from drydock.config import get_target_directory
    from drydock.validate_specification import validate_specification

    target_dir = get_target_directory() / args.Target
    result = validate_specification(args.Blueprint, target_dir, verbose=args.verbose)

    print(f"Validating Blueprint: {args.Blueprint}  ({result.spec_dir})")
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

    print(f"Compacting Blueprint: {args.Blueprint}")
    result = compact(
        args.Blueprint,
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
        args.Blueprint,
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


def _detect_import_format(source: Path) -> str:
    """Infer import format from source layout."""
    if (source / ".specify").is_dir():
        return "speckit"
    code_exts = {".py", ".js", ".ts", ".jsx", ".tsx", ".go", ".rs", ".rb", ".java", ".cpp", ".c"}
    if source.is_dir() and any(p.suffix in code_exts for p in source.rglob("*") if p.is_file()):
        return "source"
    if source.suffix.lower() == ".md":
        return "markdown"
    if source.is_dir() and any(
        p.suffix.lower() == ".md" for p in source.rglob("*") if p.is_file()
    ):
        return "markdown"
    raise UsageError(
        f"Cannot detect import format for: {source}\n"
        "  Specify --format markdown, --format source, or --format speckit."
    )


def cmd_import(args: argparse.Namespace) -> int:
    from drydock.config import get_target_directory

    source = Path(args.Source)
    fmt = args.format
    if fmt == "auto":
        fmt = _detect_import_format(source)

    td = get_target_directory()

    if fmt == "markdown":
        from drydock.import_markdown import import_markdown

        result = import_markdown(args.Blueprint, args.Target, source, td)
        print(f"Blueprint: {result.blueprint_dir}")
        print(f"Source: {result.source}")
        for path in result.imported:
            print(f"  IMPORTED  {path.relative_to(result.blueprint_dir)}")
        print()
        print(f"Next step: drydock plan create {args.Blueprint} {args.Target}")
        return 0

    if fmt == "source":
        from drydock.import_source import import_source

        result = import_source(args.Blueprint, args.Target, source, td)
        print(f"Blueprint: {result.blueprint_dir}")
        print(f"Source: {result.source}")
        for name in result.files_written:
            print(f"  IMPORTED  {name}")
        print()
        print(f"Next step: drydock plan create {args.Blueprint} {args.Target}")
        return 0

    if fmt == "speckit":
        from drydock.import_speckit import import_speckit

        result = import_speckit(args.Blueprint, args.Target, source, td)
        print(f"Blueprint: {result.blueprint_dir}")
        print(f"Source: {result.source}")
        print(f"Features: {', '.join(result.features_found) or '(none)'}")
        for name in result.files_written:
            print(f"  IMPORTED  {name}")
        print(f"  REPORT    {result.conversion_report.relative_to(result.blueprint_dir)}")
        print()
        print(f"Next step: drydock plan create {args.Blueprint} {args.Target}")
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
    blueprint_dir = blueprint_dir_for(targets_root / target)
    result = status_blueprint_target(blueprint, target, blueprint_dir, targets_root)
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
    p_init.add_argument("--display-name", dest="display_name", default="", metavar="<name>",
                        help="Human-readable project name (default: target name).")
    p_init.add_argument("--description", dest="short_description", default="", metavar="<desc>",
                        help="One-line project description.")

    # ── status ────────────────────────────────────────────────────────────────
    # Handles: status
    #          status <Blueprint>
    #          status <Blueprint> <Target>
    p_status = sub.add_parser(
        "status",
        help="Show project status and orientation.",
        description=(
            "drydock status                          — compact dashboard of last active project\n"
            "drydock status <Blueprint>              — Blueprint validation summary\n"
            "drydock status <Blueprint> <Target>     — plan state and runnable frontier"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p_status.add_argument("args", nargs=argparse.REMAINDER, metavar="[<Blueprint> [<Target>]]")

    # ── validate ─────────────────────────────────────────────────────────────
    p_val = sub.add_parser("validate", help="Validate a Blueprint's Typed Specification.")
    p_val.add_argument("Blueprint", metavar="<Blueprint>")
    p_val.add_argument("Target", metavar="<Target>")
    p_val.add_argument("--verbose", action="store_true", help="Also show passing checks.")

    # ── document ─────────────────────────────────────────────────────────────
    # Handles: document <Blueprint> <Target>
    #          document generate <Blueprint> <Target>
    #          document assemble <Blueprint> <Target>
    # Strategy: use REMAINDER args and dispatch on first token.
    p_doc = sub.add_parser(
        "document",
        help="Generate and assemble Blueprint documentation.",
        description=(
            "drydock document <Blueprint> <Target>           — full pipeline\n"
            "drydock document generate <Blueprint> <Target>  — AI pass only\n"
            "drydock document assemble <Blueprint> <Target>  — assembly only"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p_doc.add_argument(
        "args", nargs=argparse.REMAINDER, metavar="[generate|assemble] <Blueprint> <Target>"
    )

    # ── rigging ──────────────────────────────────────────────────────────────
    p_rig = sub.add_parser("rigging", help="Manage Drydock Rigging.")
    rig_sub = p_rig.add_subparsers(dest="rigging_command", metavar="<subcommand>")
    p_rig_c = rig_sub.add_parser(
        "compact", help="Compact stale rules/data/spec files to _compact.md siblings."
    )
    p_rig_c.add_argument("Blueprint", metavar="<Blueprint>")
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
    p_plan_create.add_argument("Blueprint", metavar="<Blueprint>")
    p_plan_create.add_argument("Target", metavar="<Target>")

    # ── build ─────────────────────────────────────────────────────────────────
    # Handles: build <Blueprint> <Target>
    #          build status <Blueprint> <Target>
    #          build score <Blueprint> <Target>
    p_build = sub.add_parser(
        "build",
        help="Build or inspect build state.",
        description=(
            "drydock build <Blueprint> <Target>          — build next frontier\n"
            "drydock build status <Blueprint> <Target>   — show build state\n"
            "drydock build score <Blueprint> <Target>    — generate SCORECARD.md"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p_build.add_argument(
        "args", nargs=argparse.REMAINDER, metavar="[status|score] <Blueprint> <Target>"
    )

    # ── refit ─────────────────────────────────────────────────────────────────
    p_iter = sub.add_parser("refit", help="Update Blueprint and target software together.")
    p_iter.add_argument("Blueprint", metavar="<Blueprint>")
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
    p_analyze = sub.add_parser("analyze", help="Read-only advisory: surface gaps and drift.")
    p_analyze.add_argument("Blueprint", metavar="<Blueprint>")
    p_analyze.add_argument("Target", metavar="<Target>", nargs="?")

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
    p_import.add_argument("Blueprint", metavar="<Blueprint>")
    p_import.add_argument("Target", metavar="<Target>")
    p_import.add_argument("Source", metavar="<Source>")
    p_import.add_argument(
        "--format", choices=["auto", "markdown", "source", "speckit"], default="auto"
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
        return cmd_status_blueprint(tokens[0])
    elif len(tokens) == 2:
        return cmd_status_blueprint_target(tokens[0], tokens[1])
    else:
        raise UsageError("Usage: drydock status [<Blueprint> [<Target>]]")


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
        if len(tokens) != 3:
            raise UsageError("Usage: drydock build status <Blueprint> <Target>")
        rc = cmd_build_status(tokens[1], tokens[2])
        if rc == 0:
            from drydock.config import record_activity

            record_activity("build status", tokens[1], tokens[2])
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

            record_activity("validate", args.Blueprint)
        return rc

    if command == "document":
        return _dispatch_document(args)

    if command == "rigging":
        sub = getattr(args, "rigging_command", None)
        if sub == "compact":
            rc = cmd_rigging_compact(args)
            if rc == 0:
                from drydock.config import record_activity

                record_activity("rigging compact", args.Blueprint)
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

                record_activity("plan create", args.Blueprint, args.Target)
            return rc
        else:
            not_implemented("plan")

    if command == "build":
        return _dispatch_build(args)

    if command == "refit":
        not_implemented("refit")

    if command == "analyze":
        not_implemented("analyze")

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

            record_activity("import", args.Blueprint)
        return rc

    return 0


def main(argv: list[str] | None = None) -> None:
    parser = _build_parser()
    args = parser.parse_args(argv)
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

    try:
        rc = _dispatch(args, parser)
    except UsageError as exc:
        print(f"error: {exc}", file=sys.stderr)
        sys.exit(2)
    except DrydockError as exc:
        print(f"error: {exc}", file=sys.stderr)
        sys.exit(1)
    except SystemExit:
        raise
    except Exception as exc:
        if debug:
            traceback.print_exc()
        else:
            print(f"error: {type(exc).__name__}: {exc}", file=sys.stderr)
            print("Run with --debug for a full traceback.", file=sys.stderr)
        sys.exit(1)

    sys.exit(rc)

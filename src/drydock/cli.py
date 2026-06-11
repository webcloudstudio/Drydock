"""Drydock CLI — argparse-based command dispatcher."""

from __future__ import annotations

import argparse
import sys
import traceback

from drydock import __copyright__, __version__
from drydock.errors import DrydockError, UsageError
from drydock.stubs import not_implemented

# ---------------------------------------------------------------------------
# Output helpers
# ---------------------------------------------------------------------------


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
            print(f"  {finding.severity.value:<4}  {finding.message}")

    print()
    total_fail = len(result.failures())
    total_warn = len(result.warnings())
    if total_fail > 0:
        print(f"RESULT: FAIL ({total_fail} errors, {total_warn} warnings)")
    elif total_warn > 0:
        print(f"RESULT: PASS with warnings ({total_warn} warnings)")
    else:
        print("RESULT: PASS")


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
    from drydock.config import get_blueprint_directory
    from drydock.init_specification import init_specification

    blueprint_dir = get_blueprint_directory()
    result = init_specification(
        args.Blueprint,
        blueprint_dir,
        update=args.update,
        force=args.force,
    )

    print(f"Blueprint: {result.spec_dir}")
    for fname in result.created():
        print(f"  CREATED  {fname}")
    for fname in result.updated():
        print(f"  UPDATED  {fname}")
    if result.skipped():
        print(f"  ({len(result.skipped())} existing files skipped — use --force to overwrite)")
    if not result.created() and not result.updated():
        print("  Nothing to do — all template files already exist.")

    print()
    print("Next steps:")
    print("  1. Edit INTENT.md — why does this project exist?")
    print("  2. Edit METADATA.md — add stack, status, description")
    print(f"  3. Run: drydock validate {args.Blueprint}")
    return 0


def cmd_validate(args: argparse.Namespace) -> int:
    from drydock.config import get_blueprint_directory
    from drydock.validate_specification import validate_specification

    blueprint_dir = get_blueprint_directory()
    result = validate_specification(args.Blueprint, blueprint_dir, verbose=args.verbose)

    print(f"Validating Blueprint: {args.Blueprint}  ({result.spec_dir})")
    _print_findings(result, args.verbose)
    return result.exit_code()


def cmd_rigging_compact(args: argparse.Namespace) -> int:
    from drydock.config import get_blueprint_directory
    from drydock.rigging_compact import CompactItem, compact

    blueprint_dir = get_blueprint_directory()

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


def cmd_plan_show(args: argparse.Namespace) -> int:
    from drydock.build_plan import load_blueprint_plan
    from drydock.config import get_blueprint_directory

    plan = load_blueprint_plan(args.Blueprint, get_blueprint_directory())
    print(f"Blueprint: {plan.project}")
    print(f"Plan: {plan.path}")
    if plan.updated:
        print(f"Updated: {plan.updated}")
    if plan.plan_hash:
        print(f"Plan hash: {plan.plan_hash}")
    print()
    _print_plan_blocks(plan)
    _print_plan_summary(plan)
    return 0


def cmd_build_status(blueprint: str, target: str) -> int:
    from drydock.build_plan import load_blueprint_plan
    from drydock.config import get_blueprint_directory, get_target_directory

    plan = load_blueprint_plan(blueprint, get_blueprint_directory())
    target_path = get_target_directory() / target
    frontier = plan.runnable_frontier()
    frontier_ids = {block.block_id for block in frontier}

    print(f"Blueprint: {plan.project}")
    print(f"Target: {target_path}")
    print()
    _print_plan_blocks(plan, frontier_ids=frontier_ids)
    _print_plan_summary(plan)
    print("Runnable frontier: " + (", ".join(block.block_id for block in frontier) or "(none)"))
    return 0


# ---------------------------------------------------------------------------
# Parser construction
# ---------------------------------------------------------------------------


def _canonical_config_key(value: str) -> str:
    """Normalize deprecated public configuration aliases."""
    return "blueprint_directory" if value == "specification_directory" else value


def _canonical_iterate_mode(value: str) -> str:
    """Normalize the deprecated SPEC iterate mode."""
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
            "blueprint_directory",
            "target_directory",
            "llm_provider",
            "prompt_warn_kb",
        ],
        type=_canonical_config_key,
    )
    p_set.add_argument("value", metavar="<path>")

    # ── init ─────────────────────────────────────────────────────────────────
    p_init = sub.add_parser("init", help="Create or update a Blueprint from templates.")
    p_init.add_argument("Blueprint", metavar="<Blueprint>")
    p_init.add_argument("--update", action="store_true", help="Add only missing template files.")
    p_init.add_argument(
        "--force", action="store_true", help="Overwrite all template-managed files."
    )

    # ── validate ─────────────────────────────────────────────────────────────
    p_val = sub.add_parser("validate", help="Validate a Blueprint's Typed Specification.")
    p_val.add_argument("Blueprint", metavar="<Blueprint>")
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
    for verb, help_str in [
        ("init", "Create or update BUILD_PLAN_INTENT.md."),
        ("create", "Run LLM analysis and produce BUILD_PLAN.md."),
        ("show", "Show the current build plan."),
    ]:
        pp = plan_sub.add_parser(verb, help=help_str)
        pp.add_argument("Blueprint", metavar="<Blueprint>")

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

    # ── iterate ───────────────────────────────────────────────────────────────
    p_iter = sub.add_parser("iterate", help="Update Blueprint and target software together.")
    p_iter.add_argument("Blueprint", metavar="<Blueprint>")
    p_iter.add_argument("Target", metavar="<Target>")
    p_iter.add_argument(
        "Mode",
        metavar="<BOTH|BLUEPRINT|TGT>",
        choices=["BOTH", "BLUEPRINT", "TGT"],
        type=_canonical_iterate_mode,
    )
    p_iter.add_argument("Scope", metavar="<Scope>")
    p_iter.add_argument("Change", metavar="<Change>")

    # ── analyze ───────────────────────────────────────────────────────────────
    p_analyze = sub.add_parser("analyze", help="Read-only advisory: surface gaps and drift.")
    p_analyze.add_argument("Blueprint", metavar="<Blueprint>")
    p_analyze.add_argument("Target", metavar="<Target>", nargs="?")

    # ── import ────────────────────────────────────────────────────────────────
    p_import = sub.add_parser("import", help="Reverse-engineer a project into a Blueprint.")
    p_import.add_argument("Blueprint", metavar="<Blueprint>")
    p_import.add_argument("Target", metavar="<Target>")
    p_import.add_argument("--format", choices=["auto", "source", "speckit"], default="auto")

    return parser


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------


def _dispatch_document(args: argparse.Namespace) -> int:
    tokens = args.args
    if not tokens:
        not_implemented("document")
    first = tokens[0] if tokens else ""
    if first == "generate":
        not_implemented("document generate")
    elif first == "assemble":
        not_implemented("document assemble")
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
        return cmd_build_status(tokens[1], tokens[2])
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
        return cmd_validate(args)

    if command == "document":
        return _dispatch_document(args)

    if command == "rigging":
        sub = getattr(args, "rigging_command", None)
        if sub == "compact":
            return cmd_rigging_compact(args)
        elif sub == "update":
            not_implemented("rigging update")
        elif sub == "verify":
            not_implemented("rigging verify")
        else:
            not_implemented("rigging")

    if command == "plan":
        sub = getattr(args, "plan_command", None)
        if sub == "init":
            not_implemented("plan init")
        elif sub == "create":
            not_implemented("plan create")
        elif sub == "show":
            return cmd_plan_show(args)
        else:
            not_implemented("plan")

    if command == "build":
        return _dispatch_build(args)

    if command == "iterate":
        not_implemented("iterate")

    if command == "analyze":
        not_implemented("analyze")

    if command == "import":
        not_implemented("import")

    return 0


def main(argv: list[str] | None = None) -> None:
    parser = _build_parser()
    args = parser.parse_args(argv)
    debug = getattr(args, "debug", False)

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

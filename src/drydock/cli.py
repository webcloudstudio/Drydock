"""Drydock CLI — argparse-based command dispatcher."""

from __future__ import annotations

import argparse
import logging
import os
import sys
import textwrap
import time
import traceback
from contextlib import nullcontext, redirect_stdout
from datetime import datetime
from pathlib import Path
from typing import NoReturn

from drydock import __copyright__, __version__
from drydock.errors import DrydockError, RecordedError, UsageError
from drydock.stubs import not_implemented

logger = logging.getLogger(__name__)


class DrydockArgumentParser(argparse.ArgumentParser):
    """Argument parser that shows full help on syntax errors."""

    def format_help(self) -> str:
        text = super().format_help()
        kept = [line for line in text.splitlines() if "==SUPPRESS==" not in line]
        return "\n".join(kept) + ("\n" if text.endswith("\n") else "")

    def error(self, message: str) -> NoReturn:
        self.print_help(sys.stderr)
        self.exit(2, f"\nerror: {message}\n")


# ---------------------------------------------------------------------------
# Output helpers
# ---------------------------------------------------------------------------


_SEVERITY_ICON = {"PASS": "✓", "WARN": "⚠", "FAIL": "✗"}


_STREAM_STATUS_PREFIXES = (
    "AUTO-COMPACT:",
    "BUILD ",
    "DRY RUN",
    "PROMPT ",
    "Workdir:",
    "=",
    "-",
    "  ",
    "    ",
)


def _stream_stdout(text: str) -> None:
    """Write streamed text to stdout while keeping status messages readable.

    The provider delivers model output as many small text deltas. ``print``
    appends a newline to every delta, which shreds words and sentences across
    lines (``test su``/``ite``). Writing the raw delta preserves the model's own
    line breaks. Drydock progress callbacks send whole status lines, so those
    are newline-terminated here to avoid concatenated build headers.
    """
    if text == "":
        sys.stdout.write("\n")
        sys.stdout.flush()
        _stream_stdout._at_line_start = True  # type: ignore[attr-defined]
        return
    if not text:
        return

    is_status = text.startswith(_STREAM_STATUS_PREFIXES)
    at_line_start = bool(getattr(_stream_stdout, "_at_line_start", True))
    if is_status and not at_line_start:
        text = "\n" + text
    if is_status and not text.endswith(("\n", "\r")):
        text += "\n"
    sys.stdout.write(text)
    sys.stdout.flush()
    _stream_stdout._at_line_start = text.endswith(("\n", "\r"))  # type: ignore[attr-defined]


def _stream_status_only(text: str) -> None:
    """Stream Drydock progress lines and drop model text.

    Scoring commands consume the model's output as a JSON payload: Drydock parses it,
    renders the Scorecard, and prints the summary itself. Echoing the raw deltas dumps
    that JSON into the console, so only Drydock's own status lines pass through here.
    """
    if text.startswith(_STREAM_STATUS_PREFIXES):
        _stream_stdout(text)


def _print_dimensions(dimensions: dict[str, int]) -> None:
    """Print the scored quality dimensions, marking those under the 60 gate."""
    width = max((len(name) for name in dimensions), default=0)
    for name, value in dimensions.items():
        mark = "" if value >= 60 else "   BELOW GATE"
        print(f"  {name.ljust(width)}  {value:3d}{mark}")


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
            if getattr(finding, "remediation", ""):
                print(f"     → {finding.remediation}")

    print()
    total_fail = len(result.failures())
    total_warn = len(result.warnings())
    if total_fail > 0:
        print(f"✗ FAIL ({total_fail} errors, {total_warn} warnings)")
    elif total_warn > 0:
        print(f"⚠ PASS with warnings ({total_warn} warnings)")
    else:
        print("✓ PASS")


def _add_llm_override_flags(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--model",
        default=None,
        metavar="<model>",
        help="Override LLM model (default: command prompt model or DRYDOCK_MODEL env/config).",
    )
    parser.add_argument(
        "--llm-provider",
        default=None,
        choices=["claude", "codex"],
        metavar="<provider>",
        help="Override LLM provider (default: LLM_PROVIDER env or claude).",
    )


def _extract_global_overrides(
    argv: list[str] | None,
) -> tuple[list[str] | None, dict[str, str | bool | None]]:
    """Strip invocation-wide flags from argv so every command accepts them.

    The remaining argv is parsed by the normal command parser. This allows flags like
    ``drydock status Target --debug`` and LLM overrides even for commands that otherwise
    use ``argparse.REMAINDER`` or do not consume the overrides.
    """

    if argv is None:
        return None, {"model": None, "llm_provider": None, "debug": False}

    cleaned: list[str] = []
    overrides: dict[str, str | bool | None] = {
        "model": None,
        "llm_provider": None,
        "debug": False,
    }
    index = 0

    while index < len(argv):
        token = argv[index]
        if token == "--":
            cleaned.extend(argv[index:])
            break
        if token == "--model":
            if index + 1 >= len(argv):
                raise UsageError("argument --model: expected one argument")
            overrides["model"] = argv[index + 1]
            index += 2
            continue
        if token == "--llm-provider":
            if index + 1 >= len(argv):
                raise UsageError("argument --llm-provider: expected one argument")
            provider = argv[index + 1]
            if provider not in {"claude", "codex"}:
                raise UsageError(
                    f"argument --llm-provider: invalid choice: {provider!r} (choose from 'claude', 'codex')"
                )
            overrides["llm_provider"] = provider
            index += 2
            continue
        if token == "--debug":
            overrides["debug"] = True
            index += 1
            continue
        cleaned.append(token)
        index += 1

    return cleaned, overrides


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


def _sync_workspace_skills(workspace: Path) -> None:
    """Install or upgrade Drydock's Claude Code and Codex skills, best-effort."""
    from drydock.skills import sync_skills

    try:
        outcomes = sync_skills(workspace)
    except Exception as exc:  # skill provisioning must never fail an init
        logger.debug("skill sync skipped: %s", exc)
        return

    for outcome in outcomes.values():
        if not outcome.changed:
            continue
        print(f"Skills: {outcome.dest_root}")
        for name in outcome.installed:
            print(f"  INSTALLED  {name}")
        for name in outcome.updated:
            print(f"  UPDATED    {name}")


def cmd_init(args: argparse.Namespace) -> int:
    from drydock.config import (
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

    _sync_workspace_skills(get_workspace())

    record_activity("init", target=args.Target)
    t = args.Target
    print()
    print("Next steps:")
    print(f"  1. Import source material:  drydock import {t} <source> --format markdown")
    print(f"  2. Analyze the spec:        drydock analyze {t}")
    print(f"  3. Create a plan:           drydock plan {t}")
    print(f"  4. Review the build tree:   drydock run quarterdeck {t}")
    return 0


def cmd_validate(args: argparse.Namespace) -> int:
    from drydock.config import require_target_dir
    from drydock.validate_specification import validate_specification

    target_dir = require_target_dir(args.Target)
    result = validate_specification(args.Target, target_dir, verbose=args.verbose)

    print(f"Validating Blueprint: {args.Target}  ({result.spec_dir})")
    _print_findings(result, args.verbose)
    return result.exit_code()


def cmd_rigging_compact(args: argparse.Namespace) -> int:
    from drydock.config import (
        blueprint_dir_for,
        get_llm_provider,
        get_model,
        get_workspace,
        require_target_dir,
    )
    from drydock.rigging_compact import CompactItem, compact

    include_files = [Path(f) for f in (args.include_file or [])]
    exclude_files = [Path(f) for f in (args.exclude_file or [])]
    include_dirs = [Path(d) for d in (args.include_dir or [])]

    explicit_only = bool(include_files or include_dirs) and args.Target is None
    if explicit_only:
        # No Target: use cwd as the anchor; auto-discovery finds nothing there, explicit paths drive all work.
        spec_dir = Path.cwd()
        label = str(spec_dir)
        compact_target = ""
    else:
        if args.Target is None:
            print(
                "error: <Target> is required unless --include-file or --include-dir is provided.",
                file=sys.stderr,
            )
            return 2
        target_dir = require_target_dir(args.Target)
        spec_dir = blueprint_dir_for(target_dir)
        label = args.Target
        compact_target = args.Target

    log_dir = get_workspace() / "logs"
    model = get_model(getattr(args, "model", None))
    llm_provider = get_llm_provider(getattr(args, "llm_provider", None))

    def report(item: CompactItem) -> None:
        src = item.source.name
        dst = item.compact.name
        routing = f"[{item.role} via {item.prompt_name}.md]"
        if item.status == "compacted":
            pct = f" ({item.percent:.0f}% of source)" if item.percent is not None else ""
            print(
                f"  [done]       {src} {routing} → {dst}  "
                f"{item.compact_bytes} B{pct}  {item.execution_id}"
            )
        elif item.status == "skipped-fresh":
            print(f"  [fresh]      {src} {routing} → {dst}  (compact is newer; use --force)")
        elif item.status == "skipped-unchanged":
            print(f"  [unchanged]  {src} {routing} → {dst}  (no structural change)")
        elif item.status == "no-surface":
            print(f"  [no-surface] {src} {routing}: {item.error}")
        else:
            print(f"  [failed]     {src} {routing}: {item.error}  see logs/ ({item.execution_id})")

    print(f"Compacting: {label}")
    result = compact(
        label,
        spec_dir,
        include_rigging=args.include_rigging,
        force=args.force,
        include_files=include_files or None,
        exclude_files=exclude_files or None,
        include_dirs=include_dirs or None,
        skip_autodiscovery=explicit_only,
        log_dir=log_dir,
        target=compact_target,
        on_text=_stream_stdout,
        on_item=report,
        model=model,
        llm_provider=llm_provider,
    )

    if not result.items:
        print("  Nothing to compact — no compactable files found.")
    print()
    print(
        f"RESULT: {len(result.compacted())} compacted, "
        f"{len(result.skipped())} fresh, "
        f"{len(result.unchanged())} unchanged, "
        f"{len(result.no_surface())} no-surface, "
        f"{len(result.failed())} failed"
    )
    return result.exit_code()


def cmd_refit(args: argparse.Namespace) -> int:
    from drydock.config import get_llm_provider, get_model, get_workspace, require_target_dir
    from drydock.refit import RefitItem, refit_target

    target_dir = require_target_dir(args.Target)
    log_dir = get_workspace() / "logs"
    model = get_model(getattr(args, "model", None))
    llm_provider = get_llm_provider(getattr(args, "llm_provider", None))

    def report(item: RefitItem) -> None:
        name = item.ticket.name
        if item.status == "conformed":
            print(f"  [conformed]       {name}  {item.execution_id}")
        elif item.status == "skipped-no-amends":
            print(f"  [skipped]         {name}: {item.error}")
        else:
            print(f"  [failed]          {name}: {item.error}  see logs/ ({item.execution_id})")

    print(f"Refitting: {args.Target}")
    result = refit_target(
        target_dir,
        log_dir=log_dir,
        model=model,
        llm_provider=llm_provider,
        on_text=_stream_stdout,
    )

    for item in result.items:
        report(item)

    for reset in result.resets:
        tag = "foundational" if reset.foundational else "drift"
        blocks = ", ".join(reset.reset_ids)
        print(f"  [reset:{tag}]  {reset.path}: {len(reset.reset_ids)} blocks -> pending ({blocks})")

    for error in result.drift_errors:
        print(f"  [blocked]         {error}")

    if not result.items and not result.resets and not result.drift_errors:
        print("  No change tickets or specification drift found — nothing to do.")

    print()
    print(
        f"RESULT: {len(result.conformed())} conformed, "
        f"{len(result.skipped())} skipped, "
        f"{len(result.failed())} failed, "
        f"{len(result.resets)} reset, "
        f"{len(result.drift_errors)} blocked"
    )
    return result.exit_code()


def cmd_rigging_update(args: argparse.Namespace) -> int:
    from drydock.rigging_update import update

    target = args.Target
    dry_run = getattr(args, "dry_run", False)
    label = "[dry-run] " if dry_run else ""
    print(f"{label}Updating rigging for target: {target}")
    rc, log = update(target, dry_run=dry_run)
    for line in log:
        print(line)
    print()
    print(
        "RESULT: dry-run — no files written"
        if dry_run
        else ("RESULT: done" if rc == 0 else "RESULT: failed")
    )
    return rc


def cmd_rigging_verify(args: argparse.Namespace) -> int:
    from drydock.rigging_verify import verify

    target = args.Target
    print(f"Verifying rigging for target: {target}")
    rc, checks = verify(target)
    print()
    for c in checks:
        icon = "✓" if c.passed else "✗"
        detail = f"  — {c.message}" if c.message else ""
        print(f"  {icon}  {c.name}{detail}")
    print()
    print(f"RESULT: {'PASS' if rc == 0 else 'FAIL'}")
    return rc


def cmd_rigging_add(args: argparse.Namespace) -> int:
    from drydock.paths import get_rigging_root
    from drydock.rigging_manifest import add_to_manifest

    result = add_to_manifest(
        files=[Path(path) for path in args.file or []],
        directories=[Path(path) for path in args.dir or []],
        rigging_root=get_rigging_root(),
    )
    for path in result.added:
        print(f"  ADDED     {path.as_posix()}")
    for path in result.existing:
        print(f"  EXISTS    {path.as_posix()}")
    if not result.added and not result.existing:
        print("  Nothing to add.")
    print(f"Manifest: {result.manifest_path}")
    return 0


def cmd_analyze(args: argparse.Namespace) -> int:
    from drydock.analyze import analyze
    from drydock.config import get_llm_provider, get_model, get_workspace, require_target_dir
    from drydock.quarterdeck_state import commanders_chair_command

    target_dir = require_target_dir(args.Target)
    model = get_model(getattr(args, "model", None))
    llm_provider = get_llm_provider(getattr(args, "llm_provider", None))
    log_dir = get_workspace() / "logs"
    print(f"Analyzing Blueprint: {args.Target}")
    print("Running analysis...", flush=True)
    with commanders_chair_command(target_dir, f"drydock analyze {args.Target}"):
        result = analyze(
            args.Target, target_dir, model=model, llm_provider=llm_provider, log_dir=log_dir
        )
    print()
    if not result.ok:
        print(f"Error: {result.error}", file=sys.stderr)
        return 1
    tdir = result.target_dir
    print(f"  ANALYSIS.md   →  {result.analysis_path.relative_to(tdir)}")
    if getattr(result, "sea_trials_created", True):
        print(f"  SEA_TRIALS.md →  {result.sea_trials_path.relative_to(tdir)}")
    for warning in getattr(result, "warnings", ()):
        print(f"Warning: {warning}", file=sys.stderr)
    if result.compass_path:
        print(f"  COMPASS.md    →  {result.compass_path.relative_to(tdir)}  (created)")
    for discovery_path in result.discovery_paths:
        print(f"  {discovery_path.name:<20} →  {discovery_path.relative_to(tdir)}")
    if result.commanders_chair_path:
        print(
            f"  commanders_chair  →  {result.commanders_chair_path.relative_to(tdir)}  (lifecycle: analyzed)"
        )
    print()
    _quality_icon = {"Ready": "✓", "Questions": "⚠", "Blocked": "✗"}.get(result.quality, "?")
    feature_count = getattr(result, "feature_count", getattr(result, "screen_count", 0))
    print(
        f"Quality: {_quality_icon}  {result.quality}  "
        f"({feature_count} features · {result.story_count} stories · "
        f"{result.question_count} questionnaires · "
        f"{result.blocker_count} blockers)"
    )
    print()
    if result.quality == "Ready":
        print(f"Next step: drydock plan {args.Target}")
    elif result.quality == "Questions":
        print("Review QuarterDeck action items, then run:")
        print(f"  drydock plan {args.Target}")
    else:
        print("Resolve blockers in QuarterDeck:")
        print(f"  drydock run quarterdeck {args.Target}")
        print("Then re-run:")
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


def cmd_plan(args: argparse.Namespace) -> int:
    from drydock.config import (
        get_llm_provider,
        get_model,
        get_target_directory,
        get_workspace,
        require_target_dir,
    )
    from drydock.planning_session import create_plan
    from drydock.quarterdeck_state import commanders_chair_command

    def _progress(text: str) -> None:
        # Only surface plan's own mode/status notices; suppress the raw streamed
        # LLM response text, which for a full-rewrite plan can be very large.
        if text.startswith("[plan]"):
            print(text, end="")

    model = get_model(getattr(args, "model", None))
    llm_provider = get_llm_provider(getattr(args, "llm_provider", None))
    log_dir = get_workspace() / "logs"
    target_directory = get_target_directory()
    target_dir = require_target_dir(args.Target)
    with commanders_chair_command(target_dir, f"drydock plan {args.Target}"):
        result = create_plan(
            args.Target,
            args.Target,
            target_directory,
            overwrite=getattr(args, "overwrite", False),
            conform=not getattr(args, "no_conform", False),
            model=model,
            llm_provider=llm_provider,
            log_dir=log_dir,
            on_text=_progress,
        )
    print()
    mode_label = {
        "reuse-manifest-first": "REUSE (existing Blueprint specs preserved)",
        "full-rewrite": "OVERWRITE (Blueprint specs regenerated from analysis)",
        "speckit-translate": "SPEC-KIT (imported Spec Kit sources translated)",
    }.get(result.plan_mode, result.plan_mode or "unknown")
    print(f"Mode: {mode_label}")
    if result.conformed_files:
        print(
            f"Conformed {len(result.conformed_files)} imported spec(s) into Drydock format "
            "with authored Programmatic Acceptance."
        )
    print(f"Blueprint: {result.plan.project}")
    print(f"Plan: {result.plan.path}")
    print(f"Planning Session: {result.quarterdeck_dir}")
    if result.authored_files:
        print(f"Authored {len(result.authored_files)} Blueprint spec file(s):")
        for path in result.authored_files:
            print(f"  {path.relative_to(result.target_dir)}")
    print()
    _print_plan_blocks(result.plan)
    _print_plan_summary(result.plan)
    if result.warnings:
        print()
        print("Planning warnings:")
        for warning in result.warnings:
            print(f"  - {warning}")
    print()
    print("Next step: review the manifest build tree in the Planning Session.")
    return 0


def cmd_survey(args: argparse.Namespace) -> int:
    from pathlib import Path as _Path

    from drydock.config import get_llm_provider, get_model, require_target_dir
    from drydock.errors import UsageError
    from drydock.survey import (
        import_specs,
        load_records,
        render_scoreboard,
        run_survey,
        survey_dir_for,
    )

    target_dir = require_target_dir(args.Target)
    model = get_model(getattr(args, "model", None))
    llm_provider = get_llm_provider(getattr(args, "llm_provider", None))
    if not target_dir.is_dir():
        raise UsageError(f"Target not found: {args.Target}")

    from drydock.config import get_workspace as _get_workspace

    log_dir = _get_workspace() / "logs"

    if args.import_path:
        written = import_specs(
            args.Target,
            target_dir,
            _Path(args.import_path),
            model=model,
            llm_provider=llm_provider,
            log_dir=log_dir,
        )
        print(f"Regenerated {len(written)} acceptance-criteria file(s):")
        for path in written:
            print(f"  {path.name}")
        return 0

    if args.run:
        print(f"Surveying: {args.Target}")
        records = run_survey(
            args.Target,
            target_dir,
            command=args.command_filter,
            model=model,
            llm_provider=llm_provider,
            log_dir=log_dir,
        )
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
    from drydock.config import get_llm_provider, get_model, get_workspace
    from drydock.paths import get_repo_root
    from drydock.prompt_review import review_prompt

    print(f"Reviewing prompt: {args.Component}")
    model = get_model(getattr(args, "model", None))
    llm_provider = get_llm_provider(getattr(args, "llm_provider", None))
    log_dir = get_workspace() / "logs"
    result = review_prompt(args.Component, model=model, llm_provider=llm_provider, log_dir=log_dir)
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
        if source.expanduser().is_dir():
            raise UsageError(
                "--format auto requires a file; specify --format markdown, source, or speckit for a directory"
            )
        fmt = detect_import_format(source)

    td = get_target_directory()

    def print_import_result(
        source_path: Path, imported: tuple[Path, ...] | list[Path], destination: Path
    ) -> None:
        print(f" - Source: {source_path}")
        print(f" - Target: {destination}/")
        for path in imported:
            print(f"  {Path(path).relative_to(destination)}")

    if fmt == "markdown":
        from drydock.import_markdown import import_markdown

        result = import_markdown(args.Target, args.Target, source, td)
        print_import_result(result.source, result.imported, result.blueprint_dir / "sources")
        _print_next_step("import", args.Target)
        return 0

    if fmt == "source":
        from drydock.import_source import import_source

        source_result = import_source(args.Target, args.Target, source, td)
        print_import_result(
            source_result.source, source_result.imported, source_result.blueprint_dir / "sources"
        )
        _print_next_step("import", args.Target)
        return 0

    if fmt == "speckit":
        from drydock.import_speckit import import_speckit

        speckit_result = import_speckit(args.Target, args.Target, source, td)
        print_import_result(
            speckit_result.source, speckit_result.imported, speckit_result.blueprint_dir / "sources"
        )
        _print_next_step("import", args.Target)
        return 0

    if fmt in {"compass", "intent"}:
        from drydock.config import get_llm_provider, get_model, get_workspace
        from drydock.import_markdown import import_intent

        result = import_intent(
            args.Target,
            source,
            td,
            force=bool(getattr(args, "force", False)),
            model=get_model(getattr(args, "model", None)),
            llm_provider=get_llm_provider(getattr(args, "llm_provider", None)),
            log_dir=get_workspace() / "logs",
        )
        print_import_result(result.source, result.imported, result.blueprint_dir)
        _print_next_step("import", args.Target)
        return 0

    raise UsageError(f"Unknown format: {fmt!r}")


def cmd_document_assemble(argv: list[str]) -> int:
    import argparse as _ap
    import re as _re

    from drydock.build_documentation import DEFAULT_OUTPUT
    from drydock.build_documentation import main as _build_doc_main
    from drydock.config import get_target_directory

    rc = _build_doc_main(argv)
    if rc != 0:
        return rc

    # Derive the output path from argv to store in console.yaml.
    _p = _ap.ArgumentParser(add_help=False)
    _p.add_argument("--output", type=Path, default=None)
    _known, _ = _p.parse_known_args(argv)
    raw_output = _known.output or DEFAULT_OUTPUT

    targets_root = get_target_directory()
    if not targets_root.is_dir():
        return rc

    # Compute the output path relative to the workspace root so it can be stored
    # portably in console.yaml.  Skip if the path falls outside the workspace
    # (e.g. an absolute temp path used in tests).
    workspace_root = targets_root.parent
    abs_output = (
        (workspace_root / raw_output).resolve()
        if not Path(raw_output).is_absolute()
        else Path(raw_output).resolve()
    )
    try:
        rel_output = str(abs_output.relative_to(workspace_root))
    except ValueError:
        return rc  # output outside workspace — nothing to record

    for target_dir in sorted(targets_root.iterdir()):
        console_yaml = target_dir / "QuarterDeck" / "console.yaml"
        if not console_yaml.is_file():
            continue
        text = console_yaml.read_text(encoding="utf-8")
        new_line = f"  app_help_file_location: {rel_output}"
        if _re.search(r"^  app_help_file_location:", text, _re.MULTILINE):
            text = _re.sub(
                r"^  app_help_file_location:.*$",
                new_line,
                text,
                flags=_re.MULTILINE,
            )
        else:
            text = _re.sub(
                r"^(  state_db:.*)",
                r"\1\n" + new_line,
                text,
                count=1,
                flags=_re.MULTILINE,
            )
        console_yaml.write_text(text, encoding="utf-8", newline="\n")

    return rc


def cmd_publish(args: argparse.Namespace) -> int:
    from drydock.build_documentation import publish_document

    try:
        result = publish_document(
            args.Source,
            args.output,
            theme=args.theme,
            flatten=args.flatten,
            pdf=args.pdf,
            pdf_output=args.pdf_output,
        )
    except ValueError as exc:
        raise UsageError(str(exc)) from exc
    except RuntimeError as exc:
        raise DrydockError(str(exc)) from exc

    print(f"Published HTML: {result.html_path}")
    print(f"  Theme: {result.theme}")
    if result.pdf_path is not None:
        print(f"Published PDF: {result.pdf_path}")
    return 0


def _parse_document_args(tokens: list[str], *, prog: str) -> argparse.Namespace:
    import argparse as _ap

    p = _ap.ArgumentParser(prog=prog, add_help=False)
    p.add_argument("Target", metavar="<Target>")
    p.add_argument("--model", default=None, metavar="<model>")
    p.add_argument("--theme", default=None, metavar="<theme>")
    p.add_argument(
        "--llm-provider",
        dest="llm_provider",
        default=None,
        choices=["claude", "codex"],
        metavar="<provider>",
    )
    parsed, extra = p.parse_known_args(tokens)
    if extra:
        raise UsageError(f"Unexpected argument(s): {' '.join(extra)}")
    return parsed


def cmd_document_generate(args: argparse.Namespace) -> int:
    from drydock.config import get_llm_provider, get_model, get_target_directory
    from drydock.target_documentation import generate_documentation

    result = generate_documentation(
        args.Target,
        get_target_directory(),
        model=get_model(getattr(args, "model", None)),
        llm_provider=get_llm_provider(getattr(args, "llm_provider", None)),
    )
    print(f"Generated documentation: {result.docs_dir}")
    for path in result.files:
        print(f"  WROTE  {path.relative_to(result.docs_dir)}")
    print(f"  LLM execution: {result.execution_id}")
    return 0


def cmd_document_assemble_readme(target: str) -> int:
    from drydock.config import build_dir_for, get_target_directory
    from drydock.metadata import get_field, parse_metadata
    from drydock.readme_generate import generate_readme

    target_dir = get_target_directory() / target
    if not target_dir.is_dir():
        print(f"Error: Target not found: {target_dir}", file=sys.stderr)
        return 1

    meta = parse_metadata(target_dir / "METADATA.md")
    build_dir_str = get_field(meta, "build_dir")
    build_dir = (
        Path(build_dir_str).expanduser().resolve() if build_dir_str else build_dir_for(target)
    )

    if not build_dir.exists():
        print(f"Error: Build directory not found: {build_dir}", file=sys.stderr)
        print("  Run drydock build first.", file=sys.stderr)
        return 1

    readme_path = generate_readme(target_dir, build_dir)
    if readme_path is None:
        print("Error: README generation failed.", file=sys.stderr)
        return 1

    print(f"README: {readme_path}")
    return 0


def cmd_target_document_assemble(args: argparse.Namespace) -> int:
    from drydock.config import get_target_directory
    from drydock.target_documentation import assemble_documentation

    result = assemble_documentation(
        args.Target,
        get_target_directory(),
        theme=getattr(args, "theme", None),
    )
    print(f"Assembled documentation: {result.output}")
    print(f"  Theme: {result.theme}")
    print(f"  Guides: {', '.join(result.guides)}")
    return 0


def cmd_document_pipeline(args: argparse.Namespace) -> int:
    from drydock.config import get_llm_provider, get_model, get_target_directory
    from drydock.target_documentation import document_target

    generated, assembled = document_target(
        args.Target,
        get_target_directory(),
        model=get_model(getattr(args, "model", None)),
        llm_provider=get_llm_provider(getattr(args, "llm_provider", None)),
        theme=getattr(args, "theme", None),
    )
    print(f"Generated documentation: {generated.docs_dir}")
    for path in generated.files:
        print(f"  WROTE  {path.relative_to(generated.docs_dir)}")
    print(f"Assembled documentation: {assembled.output}")
    print(f"  Theme: {assembled.theme}")
    return 0


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

    if result.target_path is not None:
        print(f"  {'Target':<{col}}  {result.target_path}")

    if result.target_info is not None:
        info = result.target_info
        print(f"  {'Phase':<{col}}  {info.phase}")
        print(f"  {'State':<{col}}  {info.phase_detail}")
        if info.display_name and info.display_name != info.name:
            print(f"  {'Display name':<{col}}  {info.display_name}")
        metadata_detail = info.metadata_state or "init"
        if info.metadata_sub_state:
            metadata_detail += f" · {info.metadata_sub_state}"
        print(f"  {'Metadata':<{col}}  {metadata_detail}")
        print(
            f"  {'Sources':<{col}}  {info.imported_sources} imported"
            f" · {info.authored_blueprints} authored blueprint files"
        )
        if info.analysis is not None:
            analysis = info.analysis
            quality = analysis.quality or "unknown"
            analysis_detail = (
                f"{analysis.story_count} stories"
                f" · {analysis.question_count} questions"
                f" · {analysis.blocker_count} blockers"
            )
            if analysis.screen_count:
                analysis_detail += f" · {analysis.screen_count} screens"
            print(f"  {'Analysis':<{col}}  {quality:<22}  {analysis_detail}")
        if info.questionnaire_count or info.blockers_present:
            blockers = "present" if info.blockers_present else "none"
            print(
                f"  {'Review':<{col}}  BLOCKERS.md {blockers}"
                f" · {info.questionnaire_count} questionnaires"
            )

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
                    if getattr(finding, "remediation", ""):
                        print(f"       → {finding.remediation}")

    if result.plan is not None:
        counts = result.plan.state_counts()
        total = len(result.plan.blocks)
        verified = counts.get("closed/verified", 0)
        pending = counts.get("pending", 0)
        impl = counts.get("implemented", 0)
        failed = counts.get("closed/failed", 0)
        progress = f"{result.plan.state} · {verified}/{total} verified"
        detail = f"pending {pending} · implemented {impl} · failed {failed}"
        print(f"  {'Plan':<{col}}  {progress:<22}  {detail}")

        if result.frontier:
            for i, block in enumerate(result.frontier):
                label = "Frontier" if i == 0 else ""
                print(f"  {label:<{col}}  {block.block_id}: {block.name}")
        else:
            print(f"  {'Frontier':<{col}}  (none)")
    elif result.target:
        print(f"  {'Plan':<{col}}  not created")

    if result.target_info is not None and result.target_info.next_operation:
        print(f"  {'Next step':<{col}}  {result.target_info.next_operation}")
    elif result.target:
        print(f"  {'Next step':<{col}}  drydock plan {result.target}")

    recs = result.target_info.compact_recs if result.target_info is not None else []
    if recs:
        print()
        print("Recommendations")
        for rec in recs:
            total = rec.implements_count + rec.context_count
            print(
                f"  {rec.file} — used {total}×"
                f" ({rec.implements_count}× implements, {rec.context_count}× context);"
                f" compact to save ~{rec.context_count}C per build"
            )
            print(f"    drydock rigging compact {result.target} --include-file {rec.file}")
        print()
        print(f"  Breakeven: 2 context uses.  Compact all: drydock rigging compact {result.target}")


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


def cmd_status_check(target: str) -> int:
    """Print one line and exit 0 when *target* is technically complete, 1 when it is not."""
    from drydock.config import get_target_directory
    from drydock.status import completion_check

    target_dir = get_target_directory() / target
    if not target_dir.is_dir():
        raise UsageError(f"Target not found: {target_dir}")
    check = completion_check(target, target_dir)
    label = "COMPLETE" if check.complete else "INCOMPLETE"
    print(f"{label}: {target}  {check.verified}/{check.total} verified  ({check.reason})")
    return check.exit_code()


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

    print("Drydock status — workspace")
    print()
    label_width = 10
    for info in ws.targets:
        print(f"Target: {info.name}")
        print(f"   {'Phase:':<{label_width}} {info.phase}")
        print(f"   {'State:':<{label_width}} {info.phase_detail}")
        print(
            f"   {'Detail:':<{label_width}} {info.imported_sources} imported"
            f" · {info.authored_blueprints} authored"
            f" · metadata {info.metadata_state or 'init'}"
        )
        if info.analysis is not None:
            print(
                f"   {'Analysis:':<{label_width}} "
                f"{info.analysis.quality or 'unknown'}"
                f" · {info.analysis.story_count} stories"
                f" · {info.analysis.question_count} questions"
                f" · {info.analysis.blocker_count} blockers"
            )
        if info.plan_summary is not None:
            print(
                f"   {'Plan:':<{label_width}} "
                f"{info.plan_summary.state}"
                f" · {info.plan_summary.verified}/{info.plan_summary.total} verified"
                f" · {info.plan_summary.pending} pending"
            )
        if info.blockers_present or info.questionnaire_count:
            print(
                f"   {'Review:':<{label_width}} "
                f"BLOCKERS.md {'present' if info.blockers_present else 'none'}"
                f" · {info.questionnaire_count} questionnaires"
            )
        print(f"   {'Next Step:':<{label_width}} {info.next_operation}")
        if info.compact_recs:
            print(
                f"   {'Recommend:':<{label_width}} compact {len(info.compact_recs)} file(s)"
                f" — run: drydock rigging compact {info.name}"
            )
        for rec in reversed(info.history):
            cmd = rec.get("command", "")
            stamp = str(rec.get("time", "")).strip()
            rc = rec.get("return_code")
            action = "Run" if rc is None else ("✅" if rc == 0 else "❌")
            if len(stamp) >= 10:
                month = str(int(stamp[5:7]))
                day = str(int(stamp[8:10]))
                label = f"{month}-{day}:"
            else:
                label = "Date:"
            print(f"   {label:<{label_width}} {action} {cmd}")
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


def cmd_build(args: argparse.Namespace) -> int:
    from drydock.build_run import BUILD_FAILURE_HINT, BuildStepResult, build_target
    from drydock.config import (
        get_escalate_model,
        get_llm_provider,
        get_model,
        get_workspace,
        require_target_dir,
    )
    from drydock.manifest_edit import (
        normalize_order,
        render_manifest,
        split_manifest,
        write_manifest,
    )

    target_dir = require_target_dir(args.Target)
    if getattr(args, "step", None) and getattr(args, "story", None):
        raise UsageError("--step and --story are mutually exclusive.")
    if getattr(args, "continue_", False) and getattr(args, "reset", False):
        raise UsageError("--continue and --reset are mutually exclusive.")
    model = get_model(getattr(args, "model", None))
    llm_provider = get_llm_provider(getattr(args, "llm_provider", None))
    escalate_model = get_escalate_model(getattr(args, "escalate_model", None))
    repair_attempts = int(getattr(args, "repair_attempts", 1) or 0)
    if repair_attempts < 0:
        raise UsageError("--repair-attempts must be zero or greater.")
    build_dir = Path(args.build_dir).expanduser().resolve() if args.build_dir else None
    log_dir = get_workspace() / "logs"

    _marks = {
        "built": "[built]",
        "implemented": "[review]",
        "failed": "[failed]",
        "dry-run": "[dry-run]",
    }

    # Failures are collected here and rendered once at the end of the run, after the result
    # line, so the last thing on screen is the diagnosis rather than a mid-stream banner the
    # remaining step output scrolls away.
    failures: list[BuildStepResult] = []
    _fatal_shown: set[str] = set()

    def report(step: BuildStepResult) -> None:
        mark = _marks.get(step.status, f"[{step.status}]")
        extra = f"  {step.error}" if step.error else f"  {step.execution_id or ''}"
        print(f"  {mark:>9}  {step.name} [{step.block_id}]  SP {step.story_points}{extra}")
        if step.status == "failed":
            # Stories in one block share a single execution: report it once.
            fatal_key = step.execution_id or f"{step.block_id}:{step.error}"
            if fatal_key not in _fatal_shown:
                _fatal_shown.add(fatal_key)
                failures.append(step)
        if step.evidence_path is not None:
            print(f"      evidence: {step.evidence_path}")
        print(f"      files changed: {len(step.written_files)}")
        for check in step.pre_acceptance:
            if not check.passed:
                continue
            if check.integrity_ok:
                label = "GREEN (prepassed)"
                detail = ""
            else:
                label = "GREEN (vacuous)"
                detail = (
                    "  " + "; ".join(check.integrity_reasons) if check.integrity_reasons else ""
                )
            print(f"      [!] {label} {check.check_id}  {check.intent}{detail}")
        for check in step.acceptance:
            check_mark = "OK" if check.passed else "X"
            detail = f"  {check.error}" if check.error else ""
            print(f"      [{check_mark}] ac {check.check_id}  {check.intent}{detail}")

    build_started = time.monotonic()
    print(f"Building Target: {args.Target}")
    print(f"BUILD COMMAND START: {args.Target}  started={_wall_time()}")
    print(
        f"LLM: {llm_provider}/{model}  repair_attempts={repair_attempts}  "
        f"escalate={escalate_model or 'off'}"
    )
    if getattr(args, "story", None):
        print(f"Building story: {args.story}")
    elif getattr(args, "step", None):
        print(f"Building step: {args.step}")
    if getattr(args, "reset", False):
        scope = (
            getattr(args, "story", None)
            or getattr(args, "step", None)
            or "entire project (all blocks + build directory)"
        )
        print(f"Reset requested: {scope}")
    if getattr(args, "normalize_order", False):
        manifest_path = target_dir / "MANIFEST.md"
        doc = split_manifest(manifest_path)
        before = render_manifest(doc)
        normalize_order(doc)
        after = render_manifest(doc)
        changed = before != after
        if getattr(args, "dry_run", False):
            print(
                "Normalize order dry run: would "
                f"{'update' if changed else 'leave unchanged'} MANIFEST.md"
            )
        else:
            if changed:
                write_manifest(doc)
            print(f"Normalize order: {'updated' if changed else 'already normalized'} MANIFEST.md")
    if getattr(args, "dry_run", False):
        print("DRY RUN: no LLM call, file writes, evidence, state updates, README, or git commit")
        if getattr(args, "show_prompt", False):
            print("DRY RUN: full prompt output enabled by --show-prompt")
    chair_context = nullcontext()
    if not getattr(args, "dry_run", False):
        from drydock.quarterdeck_state import commanders_chair_command

        chair_context = commanders_chair_command(target_dir, f"drydock build {args.Target}")
    with chair_context:
        result = build_target(
            args.Target,
            target_dir,
            build_dir=build_dir,
            model=model,
            llm_provider=llm_provider,
            log_dir=log_dir,
            on_text=_stream_stdout,
            on_step=report,
            step_id=getattr(args, "step", None),
            story_id=getattr(args, "story", None),
            reset=bool(getattr(args, "reset", False)),
            dry_run=bool(getattr(args, "dry_run", False)),
            show_prompt=bool(getattr(args, "show_prompt", False)),
            repair_attempts=repair_attempts,
            escalate_model=escalate_model,
        )
    print()
    print(
        f"BUILD COMMAND COMPLETE: {args.Target}  completed={_wall_time()}  "
        f"elapsed={_elapsed_text(time.monotonic() - build_started)}"
    )
    print()
    if not result.steps:
        print("  Nothing buildable — no pending step has all dependencies verified.")
        reviewable = _reviewable_build_steps(target_dir)
        if reviewable:
            print("  Legacy implemented steps remain; rebuild or revise them to run acceptance.")
    print(f"Build directory: {result.build_dir}")
    if result.readme_path:
        print(f"README: {result.readme_path}")
    label = "DRY RUN RESULT" if result.dry_run else "RESULT"
    print(f"{label}: {len(result.built())} built, {len(result.failed())} failed")
    if result.failed() and not result.dry_run:
        print()
        print(
            _render_build_failures(
                args.Target, failures or result.failed(), hint=BUILD_FAILURE_HINT
            )
        )
        # An opaque build failure earns a plain-English diagnosis. The build wrote the error
        # record; print the record itself — not its filename — then route it through the same
        # standoff diagnosis that serves RecordedError, persisting the CAUSE/DO to ERRORS.md
        # and the evidence file.
        from drydock.errors import read_error_record

        record = read_error_record(target_dir)
        if record is not None:
            print()
            print(_render_recorded_error(record))
            _standoff_diagnosis(args, None, record=record)
    return result.exit_code()


def _reviewable_build_steps(target_dir: Path) -> list[tuple[str, str]]:
    from drydock.build_plan import parse_build_plan

    plan = parse_build_plan(target_dir / "MANIFEST.md")
    return [
        (block.block_id, block.name)
        for block in plan.blocks
        if block.block_type in {"story", "spike"} and block.state == "implemented"
    ]


def cmd_build_score(args: argparse.Namespace) -> int:
    from drydock.build_score import score_target
    from drydock.config import (
        get_llm_provider,
        get_model,
        get_workspace,
        require_target_dir,
    )

    target_dir = require_target_dir(args.Target)
    result = score_target(
        args.Target,
        target_dir,
        model=get_model(getattr(args, "model", None)),
        llm_provider=get_llm_provider(getattr(args, "llm_provider", None)),
        log_dir=get_workspace() / "logs",
        on_text=_stream_status_only,
    )
    print()
    print(f"Build score: {result.score}/100")
    _print_dimensions(result.dimensions)
    print(f"Completion gate: {'COMPLETE' if result.complete else 'INCOMPLETE'}")
    print(f"Scorecard: {result.scorecard_path}")
    print(f"Evidence: {result.evidence_path}")
    for blocker in result.blockers:
        print(f"  BLOCKER: {blocker}")
    return result.exit_code()


_AC_GLYPH = {"PASS": ("✓", "32"), "FAIL": ("✗", "31"), "UNVERIFIED": ("—", "33")}


def _ac_mark(status: str) -> str:
    """Colored glyph plus padded status word. Color is dropped when stdout is not a terminal or
    ``NO_COLOR`` is set, so captured output stays plain."""
    glyph, code = _AC_GLYPH.get(status, ("?", "0"))
    if sys.stdout.isatty() and not os.environ.get("NO_COLOR"):
        glyph = f"\033[{code}m{glyph}\033[0m"
    return f"{glyph} {status:<10}"


def cmd_score_ac(target: str, step: str | None = None) -> int:
    from drydock.config import require_target_dir
    from drydock.score import UNVERIFIED, verify_acs

    target_dir = require_target_dir(target)
    report = verify_acs(target, target_dir, step_id=step)
    passed = sum(1 for v in report.verdicts if v.status == "PASS")
    failed = sum(1 for v in report.verdicts if v.status == "FAIL")
    unverified = sum(1 for v in report.verdicts if v.status == UNVERIFIED)
    print()
    print(f"Acceptance verification: {target}  ({report.verified_at})")
    if report.scope:
        print(f"  Scope: {report.scope_name}  [{report.scope}]")
    print(
        f"  PASS {passed}   FAIL {failed}   UNVERIFIED {unverified}   ({len(report.verdicts)} AC)"
    )
    if not report.verdicts:
        print("  No programmatic acceptance assertions in scope.")
    else:
        print()
    # One line per AC that ran, with its owning feature/story and Blueprint file. A pass is the
    # line alone; a non-pass adds its intent and failing detail so it is legible without opening
    # the evidence.
    owners = {
        v.criterion_id: "/".join(part for part in (v.feature, v.story) if part)
        for v in report.verdicts
    }
    id_width = max((len(v.criterion_id) for v in report.verdicts), default=0)
    owner_width = max((len(owner) for owner in owners.values()), default=0)
    for verdict in report.verdicts:
        owner = owners[verdict.criterion_id].ljust(owner_width)
        mark = _ac_mark(verdict.status)
        print(
            f"  {mark}  {verdict.criterion_id.ljust(id_width)}  {owner}  {verdict.source}".rstrip()
        )
        if verdict.status == "PASS":
            continue
        if verdict.summary.strip():
            print(f"        intent: {verdict.summary.strip()}")
        for line in (verdict.evidence or "").strip().splitlines() or ["(no detail captured)"]:
            print(f"        {line}")
        print()
    if report.wrote_soundings:
        print()
        print(f"Soundings: {report.soundings_path}")
    return report.exit_code()


def cmd_score_release(target: str) -> int:
    from drydock.config import (
        get_llm_provider,
        get_model,
        get_workspace,
        require_target_dir,
    )
    from drydock.quarterdeck_state import refresh_commanders_chair
    from drydock.score import score_release

    target_dir = require_target_dir(target)
    result = score_release(
        target,
        target_dir,
        model=get_model(None),
        llm_provider=get_llm_provider(None),
        log_dir=get_workspace() / "logs",
        on_text=_stream_status_only,
    )
    refresh_commanders_chair(target_dir)
    print()
    print(f"Release score: {result.score}/100")
    _print_dimensions(result.dimensions)
    print(f"Release gate: {target}  {'COMPLETE' if result.complete else 'INCOMPLETE'}")
    print(f"Scorecard: {result.scorecard_path}")
    print(f"Evidence: {result.evidence_path}")
    for blocker in result.blockers:
        print(f"  BLOCKER: {blocker}")
    return result.exit_code()


_BUILD_STATE_MARK = {
    "closed/verified": "[done]",
    "implemented": "[review]",
    "pending": "[pending]",
    "closed/failed": "[FAILED]",
}


def cmd_build_status(blueprint: str, target: str) -> int:
    from drydock.build_plan import load_target_plan
    from drydock.build_score import score_evidence_state
    from drydock.build_status import build_status
    from drydock.config import get_target_directory, require_target_dir

    target_path = require_target_dir(target)
    plan = load_target_plan(target, get_target_directory())
    report = build_status(plan)

    reviewable = _reviewable_build_steps(target_path)
    if reviewable:
        print("Next: resolve legacy implemented steps by rebuilding or revising them")
    elif report.buildable_ids:
        print(f"Next: drydock build {target}")
    elif report.failed_ids:
        first = report.failed_ids[0]
        print(f"Next: resume a failed step — drydock build {target} --step {first}")
    else:
        print("Next: (no actionable steps — all done or blocked)")
    print()

    print(f"Blueprint: {report.project}")
    print(f"Target: {target_path}")
    # Each row reads: <state> <type>  <Name>  [<id>]. The Name is the human label; the bracketed
    # [<id>] is the token to pass to drydock build --step <id> and drydock score ac --step <id>.
    print("Rows: <state> <type>  <Name>  [<id>]   — pass [<id>] to --step")
    if not report.groups:
        print("  No build steps in the plan.")
    for group in report.groups:
        feature_id = group.feature.block_id if group.feature else "ungrouped"
        print(
            f"\nFeature: {group.name}  [{feature_id}]"
            f"   — {group.verified}/{group.total} stories done"
        )
        for step in group.steps:
            mark = _BUILD_STATE_MARK.get(step.block.state, step.block.state)
            if step.block.state == "closed/failed":
                arrow = "  <- resume (repairs in place)"
            elif step.buildable:
                arrow = "  <- next"
            else:
                arrow = ""
            print(
                f"  {mark:<9} {step.block.block_type:<6} "
                f"{step.block.name}  [{step.block.block_id}]{arrow}"
            )
            for ac in step.acs:
                ac_mark = _BUILD_STATE_MARK.get(ac.state, ac.state)
                print(f"      {ac_mark:<9} ac     {ac.name}  [{ac.block_id}]")
        for ac in group.feature_acs:
            mark = _BUILD_STATE_MARK.get(ac.state, ac.state)
            print(f"    {mark:<9} ac     {ac.name}  [{ac.block_id}]")

    print()
    print(
        f"Steps: {report.steps_total} total — "
        f"{report.steps_verified} done, "
        f"{report.steps_implemented} in review, "
        f"{report.steps_pending} pending, "
        f"{report.steps_failed} failed "
        f"({report.percent_complete()}% complete)"
    )
    print("Buildable now: " + (", ".join(report.buildable_ids) or "(none)"))
    if report.failed_ids:
        print(
            "Failed (resume with drydock build, or --step <id>; --reset discards work instead): "
            + ", ".join(report.failed_ids)
        )
    score_state = score_evidence_state(target, target_path)
    detail = f" ({'; '.join(score_state.reasons)})" if score_state.reasons else ""
    print(f"Build score evidence: {score_state.state}{detail}")
    return 0


def cmd_build_verify(target: str, step_id: str) -> int:
    from drydock.build_review import verify_build_step
    from drydock.config import require_target_dir
    from drydock.quarterdeck_state import refresh_commanders_chair

    target_dir = require_target_dir(target)
    result = verify_build_step(target_dir / "MANIFEST.md", step_id)
    if result.already_verified:
        print(f"Already verified: {result.step_id}  {result.step_name}")
    else:
        print(f"Verified: {result.step_id}  {result.step_name}")
    if result.ac_ids:
        print("Acceptance checks: " + ", ".join(result.ac_ids))
    refresh_commanders_chair(target_dir)
    print(f"Next: drydock build status {target}")
    return 0


# ---------------------------------------------------------------------------
# Parser construction
# ---------------------------------------------------------------------------


def _add_stub(
    sub: argparse._SubParsersAction, name: str, help_text: str, args_spec: list[tuple]
) -> argparse.ArgumentParser:  # noqa: SLF001
    """Add a deferred stub subcommand."""
    p = sub.add_parser(name, help=help_text)
    for arg_name, kwargs in args_spec:
        p.add_argument(arg_name, **kwargs)
    return p


def _build_parser() -> argparse.ArgumentParser:
    parser = DrydockArgumentParser(
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
        help="Show internal diagnostics and full tracebacks on the console.",
    )
    parser.add_argument(
        "--no-diagnose",
        action="store_true",
        default=False,
        help="Do not call the LLM to diagnose an opaque failure.",
    )

    sub = parser.add_subparsers(
        dest="command",
        metavar="<command>",
        parser_class=DrydockArgumentParser,
    )

    # ── config ──────────────────────────────────────────────────────────────
    p_config = sub.add_parser("config", help="Show or set Drydock configuration.")
    _add_llm_override_flags(p_config)
    cfg_sub = p_config.add_subparsers(dest="config_command", metavar="<subcommand>")
    cfg_sub.add_parser("show", help="Display current configuration values and sources.")
    p_set = cfg_sub.add_parser("set", help="Set a configuration value.")
    p_set.add_argument(
        "key",
        choices=[
            "drydock_build_directory",
            "drydock_workspace",
            "drydock_model",
            "llm_provider",
            "prompt_warn_tokens",
            "quarterdeck_port",
        ],
    )
    p_set.add_argument("value", metavar="<value>")

    # ── init ─────────────────────────────────────────────────────────────────
    p_init = sub.add_parser("init", help="Initialize a target workspace.")
    _add_llm_override_flags(p_init)
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
            "drydock status                   — compact dashboard of all targets\n"
            "drydock status <Target>          — validation summary and plan state\n"
            "drydock status <Target> --check  — completion gate for pipelines"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    _add_llm_override_flags(p_status)
    p_status.add_argument(
        "--check",
        action="store_true",
        help="Print one line and exit 0 when the Target is complete, 1 when work remains.",
    )
    p_status.add_argument("args", nargs=argparse.REMAINDER, metavar="[<Target>]")

    # ── validate ─────────────────────────────────────────────────────────────
    p_val = sub.add_parser("validate", help="Validate a Blueprint's Typed Specification.")
    _add_llm_override_flags(p_val)
    p_val.add_argument("Target", metavar="<Target>")
    p_val.add_argument("--verbose", action="store_true", help="Also show passing checks.")

    # ── document ─────────────────────────────────────────────────────────────
    # Handles: document <Target>
    #          document generate <Target>
    #          document assemble <Target>
    #          document assemble readme <Target>
    # Strategy: use REMAINDER args and dispatch on first token.
    p_doc = sub.add_parser(
        "document",
        help="Generate and assemble Blueprint documentation.",
        description=(
            "drydock document <Target>                    — full pipeline\n"
            "drydock document generate <Target>           — AI pass only\n"
            "drydock document assemble <Target>           — assembly only\n"
            "drydock document assemble readme <Target>    — regenerate README.md"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    _add_llm_override_flags(p_doc)
    p_doc.add_argument("args", nargs=argparse.REMAINDER, metavar="[generate|assemble] <Target>")

    # ── publish ──────────────────────────────────────────────────────────────
    p_publish = sub.add_parser(
        "publish",
        help="Render frontmatter Markdown into publishable HTML.",
        description=(
            "drydock publish <Source.md> --output <Output.html>\n"
            "drydock publish <Source.md> --output <Output.html> [--flatten] [--pdf]"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p_publish.add_argument("Source", metavar="<Source.md>", type=Path)
    p_publish.add_argument(
        "--output",
        required=True,
        metavar="<Output.html>",
        type=Path,
        help="HTML output path.",
    )
    p_publish.add_argument(
        "--theme",
        choices=("sail", "slate", "paper"),
        default=None,
        metavar="<theme>",
        help="Override the frontmatter theme.",
    )
    p_publish.add_argument(
        "--flatten",
        action="store_true",
        help="Publish H1/H2 sections as separate HTML pages with table-of-contents navigation.",
    )
    p_publish.add_argument(
        "--pdf",
        action="store_true",
        help="Also render a PDF using local Playwright/Chromium.",
    )
    p_publish.add_argument(
        "--pdf-output",
        type=Path,
        default=None,
        metavar="<Output.pdf>",
        help="PDF output path; defaults to the HTML path with .pdf.",
    )

    # ── rigging ──────────────────────────────────────────────────────────────
    p_rig = sub.add_parser("rigging", help="Manage Drydock Rigging.")
    _add_llm_override_flags(p_rig)
    p_rig.add_argument(
        "--add", action="store_true", help="Add supplied Rigging files to its selection manifest."
    )
    rigging_add_group = p_rig.add_mutually_exclusive_group()
    rigging_add_group.add_argument(
        "--file",
        action="append",
        metavar="<path>",
        help="Register one regular file under Rigging/ (repeatable).",
    )
    rigging_add_group.add_argument(
        "--dir",
        action="append",
        metavar="<path>",
        help="Register all regular files below a directory under Rigging/ (repeatable).",
    )
    rig_sub = p_rig.add_subparsers(dest="rigging_command", metavar="<subcommand>")
    p_rig_c = rig_sub.add_parser(
        "compact", help="Compact stale rules/data/spec files to _compact.md siblings."
    )
    p_rig_c.add_argument(
        "Target",
        nargs="?",
        default=None,
        metavar="<Target>",
        help="Blueprint target name. Optional when --include-file or --include-dir is provided.",
    )
    p_rig_c.add_argument(
        "--all",
        dest="include_rigging",
        action="store_true",
        help="Also refresh Drydock's own Rigging engine compacts.",
    )
    p_rig_c.add_argument(
        "--force", action="store_true", help="Ignore the freshness gate and recompact everything."
    )
    p_rig_c.add_argument(
        "--include-file",
        dest="include_file",
        action="append",
        metavar="<file.md>",
        help="Add a specific Markdown file to the compaction set (repeatable).",
    )
    p_rig_c.add_argument(
        "--exclude-file",
        dest="exclude_file",
        action="append",
        metavar="<file.md>",
        help="Exclude a specific file from the auto-discovered compaction set (repeatable).",
    )
    p_rig_c.add_argument(
        "--include-dir",
        dest="include_dir",
        action="append",
        metavar="<dir>",
        help="Add all Markdown files under a directory to the compaction set (repeatable).",
    )
    _add_llm_override_flags(p_rig_c)
    p_rig_u = rig_sub.add_parser("update", help="Propagate rigging to a target project.")
    p_rig_u.add_argument("Target", metavar="<Target>")
    p_rig_u.add_argument(
        "--dry-run", action="store_true", help="Preview changes without writing any files."
    )
    p_rig_v = rig_sub.add_parser("verify", help="Verify target project rigging compliance.")
    p_rig_v.add_argument("Target", metavar="<Target>")

    # ── plan ─────────────────────────────────────────────────────────────────
    p_plan = sub.add_parser(
        "plan",
        help="Create a draft executable plan and target Planning Session.",
    )
    _add_llm_override_flags(p_plan)
    p_plan.add_argument(
        "--overwrite",
        action="store_true",
        help="Regenerate the Blueprint specs and MANIFEST.md from the analysis, discarding the "
        "existing specs, instead of reusing them.",
    )
    p_plan.add_argument(
        "--no-conform",
        action="store_true",
        help="In reuse mode, skip the LLM conform pass that authors Programmatic Acceptance "
        "assertions for imported specs whose acceptance is empty.",
    )
    p_plan.add_argument("Target", metavar="<Target>")

    # ── build ─────────────────────────────────────────────────────────────────
    # Handles: build <Target>
    #          build status <Target>
    #          build score <Target>
    p_build = sub.add_parser(
        "build",
        help="Build or inspect build state.",
        description=(
            "drydock build <Target>          — build/resume the frontier (failed blocks resume in place)\n"
            "drydock build <Target> --continue      — explicit alias for the default resume behavior\n"
            "drydock build <Target> --step <id>     — build/resume only that block\n"
            "drydock build <Target> --story <id>    — build/resume exactly one story, even in a feature\n"
            "drydock build <Target> --reset         — reset all blocks + wipe build dir, then rebuild\n"
            "drydock build <Target> --step <id> --reset  — reset that block, then rebuild clean\n"
            "drydock build <Target> --normalize-order  — normalize MANIFEST order, then build\n"
            "drydock build <Target> --dry-run       — preview next build block without writes\n"
            "drydock build status <Target>   — show build state\n"
            "drydock build score <Target>    — generate SCORECARD.md"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    _add_llm_override_flags(p_build)
    p_build.add_argument("args", nargs=argparse.REMAINDER, metavar="[status|score] <Target>")

    # ── score ─────────────────────────────────────────────────────────────────
    # Handles: score ac <Target> (deterministic), score release <Target> (LLM-assisted).
    p_score = sub.add_parser(
        "score",
        help="Verify acceptance criteria (deterministic) and judge the release gate (LLM).",
        description=(
            "drydock score ac <Target> [--step <id>]  — verify acceptance criteria (whole target,\n"
            "                                            or scoped to one feature/story), update Soundings\n"
            "drydock score release <Target>           — LLM release gate over Sea Trials; writes SCORECARD.md"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p_score.add_argument("args", nargs=argparse.REMAINDER, metavar="<ac|release> <Target>")

    # ── refit ─────────────────────────────────────────────────────────────────
    p_iter = sub.add_parser(
        "refit",
        help="Conform change tickets in blueprint/changes/ to the build process and update the manifest.",
    )
    _add_llm_override_flags(p_iter)
    p_iter.add_argument("Target", metavar="<Target>")

    # ── analyze ───────────────────────────────────────────────────────────────
    p_analyze = sub.add_parser(
        "analyze",
        help="Decompose imported sources into stories, blockers, and acceptance milestones.",
    )
    p_analyze.add_argument("Target", metavar="<Target>")
    _add_llm_override_flags(p_analyze)

    # ── survey ────────────────────────────────────────────────────────────────
    p_survey = sub.add_parser(
        "survey",
        help=argparse.SUPPRESS,
        description=(
            "drydock survey <Target>            — render the latest scoreboard\n"
            "drydock survey <Target> --run      — score (LLM-assisted) and append results\n"
            "drydock survey <Target> --import D  — regenerate AC files from a spec directory\n"
            "drydock survey <Target> --command status   — filter to one command"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    _add_llm_override_flags(p_survey)
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
    p_prompt = sub.add_parser("prompt", help=argparse.SUPPRESS)
    _add_llm_override_flags(p_prompt)
    prompt_sub = p_prompt.add_subparsers(dest="prompt_command", metavar="<subcommand>")
    p_prompt_review = prompt_sub.add_parser(
        "review",
        help="Evaluate one prompt against the spec, matching notes, and consumer contracts.",
    )
    p_prompt_review.add_argument("Component", metavar="<component>")
    _add_llm_override_flags(p_prompt_review)

    # ── run ───────────────────────────────────────────────────────────────────
    p_run = sub.add_parser("run", help="Start a Drydock service.")
    _add_llm_override_flags(p_run)
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
    _add_llm_override_flags(p_import)
    p_import.add_argument("Target", metavar="<Target>")
    p_import.add_argument("Source", metavar="<Source>")
    p_import.add_argument(
        "--format",
        choices=["auto", "markdown", "source", "speckit", "compass", "intent"],
        default="auto",
    )
    p_import.add_argument(
        "--force",
        action="store_true",
        help="Compass imports: overwrite an existing COMPASS.md (normalized by LLM at import).",
    )

    return parser


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------


def _dispatch_status(args: argparse.Namespace) -> int:
    # REMAINDER swallows flags that follow the Target, so --check is honored from either side.
    tokens = [token for token in args.args if token != "--check"]
    check = getattr(args, "check", False) or len(tokens) != len(args.args)
    if check:
        if len(tokens) != 1:
            raise UsageError("Usage: drydock status <Target> --check")
        return cmd_status_check(tokens[0])
    if len(tokens) == 0:
        return cmd_status_current()
    elif len(tokens) == 1:
        return cmd_status_blueprint_target(tokens[0], tokens[0])
    else:
        raise UsageError("Usage: drydock status [<Target>] [--check]")


def _dispatch_document(args: argparse.Namespace) -> int:
    tokens = args.args
    if not tokens:
        raise UsageError("Usage: drydock document <Target> [--model <model>] [--theme <theme>]")
    first = tokens[0] if tokens else ""
    if first == "generate":
        if len(tokens) < 2:
            raise UsageError("Usage: drydock document generate <Target> [--model <model>]")
        parsed = _parse_document_args(tokens[1:], prog="drydock document generate")
        if args.model and parsed.model is None:
            parsed.model = args.model
        if args.llm_provider and parsed.llm_provider is None:
            parsed.llm_provider = args.llm_provider
        return cmd_document_generate(parsed)
    elif first == "assemble":
        if len(tokens) < 2:
            raise UsageError(
                "Usage: drydock document assemble <Target> [--theme <theme>]\n"
                "       drydock document assemble readme <Target>"
            )
        if tokens[1] == "readme":
            if len(tokens) < 3:
                raise UsageError("Usage: drydock document assemble readme <Target>")
            return cmd_document_assemble_readme(tokens[2])
        parsed = _parse_document_args(tokens[1:], prog="drydock document assemble")
        return cmd_target_document_assemble(parsed)
    else:
        parsed = _parse_document_args(tokens, prog="drydock document")
        if args.model and parsed.model is None:
            parsed.model = args.model
        if args.llm_provider and parsed.llm_provider is None:
            parsed.llm_provider = args.llm_provider
        return cmd_document_pipeline(parsed)


def _parse_build_args(tokens: list[str]) -> argparse.Namespace:
    """Parse Target and optional flags for ``drydock build <Target>``."""
    import argparse as _ap

    p = _ap.ArgumentParser(prog="drydock build", add_help=False)
    p.add_argument("Target", metavar="<Target>")
    p.add_argument(
        "--build-dir",
        dest="build_dir",
        default=None,
        metavar="<path>",
        help="Directory where built code is written (overrides METADATA.md and config).",
    )
    p.add_argument(
        "--step",
        dest="step",
        default=None,
        metavar="<id|name>",
        help="Build only the named MANIFEST block (a feature group, or a story/spike "
        "resolved to its containing block).",
    )
    p.add_argument(
        "--story",
        dest="story",
        default=None,
        metavar="<id|name>",
        help="Build exactly one story/spike, even inside a feature group. "
        "Mutually exclusive with --step.",
    )
    p.add_argument(
        "--continue",
        dest="continue_",
        action="store_true",
        help="Resume in place (the default): explicit alias for the default build behavior.",
    )
    p.add_argument(
        "--reset",
        dest="reset",
        action="store_true",
        help="Discard prior work and rebuild clean. With --step/--story resets that block; "
        "with no selector resets every block and wipes the build directory.",
    )
    p.add_argument(
        "--normalize-order",
        "--normalize_order",
        dest="normalize_order",
        action="store_true",
        help="Normalize MANIFEST group order before building.",
    )
    p.add_argument(
        "--dry-run",
        dest="dry_run",
        action="store_true",
        help="Preview the next build block without invoking the LLM or writing files.",
    )
    p.add_argument(
        "--show-prompt",
        dest="show_prompt",
        action="store_true",
        help="With --dry-run, print the full assembled prompt including file contents.",
    )
    p.add_argument(
        "--repair-attempts",
        dest="repair_attempts",
        type=int,
        default=1,
        metavar="<n>",
        help="Repair passes after a failed block (0 disables; default 1).",
    )
    p.add_argument(
        "--escalate-model",
        dest="escalate_model",
        default=None,
        metavar="<model>",
        help="Model used on the final repair attempt "
        "(default: DRYDOCK_BUILD_ESCALATE_MODEL env or off).",
    )
    p.add_argument(
        "--model",
        default=None,
        metavar="<model>",
        help="Override LLM model (default: DRYDOCK_MODEL env or sonnet).",
    )
    p.add_argument(
        "--llm-provider",
        dest="llm_provider",
        default=None,
        choices=["claude", "codex"],
        metavar="<provider>",
        help="Override LLM provider (default: LLM_PROVIDER env or claude).",
    )
    parsed, _ = p.parse_known_args(tokens)
    return parsed


def _dispatch_build(args: argparse.Namespace) -> int:
    tokens = args.args
    if not tokens:
        not_implemented("build")
        raise AssertionError("unreachable")
    first = tokens[0] if tokens else ""
    if first == "status":
        if len(tokens) != 2:
            raise UsageError("Usage: drydock build status <Target>")
        rc = cmd_build_status(tokens[1], tokens[1])
        if rc == 0:
            from drydock.config import record_activity

            record_activity("build status", tokens[1], tokens[1])
        return rc
    elif first == "verify":
        if len(tokens) < 2:
            raise UsageError("Usage: drydock build verify <Target> [<step-id>]")
        if len(tokens) == 2:
            from drydock.config import get_target_directory

            target_dir = get_target_directory() / tokens[1]
            steps = _reviewable_build_steps(target_dir)
            if not steps:
                print("No legacy implemented steps.")
            else:
                print("Legacy implemented steps:")
                for step_id, name in steps:
                    print(f"  {step_id}  # {name}")
            return 0
        rc = cmd_build_verify(tokens[1], tokens[2])
        if rc == 0:
            from drydock.config import record_activity

            record_activity("build verify", tokens[1], tokens[1])
        return rc
    elif first == "score":
        if len(tokens) != 2:
            raise UsageError("Usage: drydock build score <Target>")
        score_args = argparse.Namespace(
            Target=tokens[1],
            model=getattr(args, "model", None),
            llm_provider=getattr(args, "llm_provider", None),
        )
        rc = cmd_build_score(score_args)
        from drydock.config import record_activity

        record_activity("build score", tokens[1], tokens[1])
        return rc
    else:
        build_args = _parse_build_args(tokens)
        # Invocation-wide --model/--llm-provider are stripped from argv before the
        # build sub-parser runs, so carry them across unless a token set them here.
        for key in ("model", "llm_provider"):
            if getattr(build_args, key, None) is None:
                setattr(build_args, key, getattr(args, key, None))
        rc = cmd_build(build_args)
        if rc == 0:
            from drydock.config import record_activity

            record_activity("build", build_args.Target, build_args.Target)
        return rc


def _parse_score_ac_args(rest: list[str]) -> tuple[str, str | None]:
    """Parse ``<Target> [--step <id>]`` for ``drydock score ac``."""
    step: str | None = None
    positional: list[str] = []
    index = 0
    while index < len(rest):
        token = rest[index]
        if token == "--step":
            if index + 1 >= len(rest):
                raise UsageError("Usage: drydock score ac <Target> [--step <id>]")
            step = rest[index + 1]
            index += 2
            continue
        if token.startswith("--step="):
            step = token.split("=", 1)[1]
            index += 1
            continue
        positional.append(token)
        index += 1
    if len(positional) != 1:
        raise UsageError("Usage: drydock score ac <Target> [--step <id>]")
    return positional[0], step


def _dispatch_score(args: argparse.Namespace) -> int:
    tokens = args.args
    first = tokens[0] if tokens else ""
    if first == "ac":
        target, step = _parse_score_ac_args(tokens[1:])
        rc = cmd_score_ac(target, step=step)
        from drydock.config import record_activity

        record_activity("score ac", target, target)
        return rc
    if first == "release" and len(tokens) == 2:
        rc = cmd_score_release(tokens[1])
        from drydock.config import record_activity

        record_activity("score release", tokens[1], tokens[1])
        return rc
    raise UsageError("Usage: drydock score <ac|release> <Target>")


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

    if command == "publish":
        return cmd_publish(args)

    if command == "rigging":
        sub = getattr(args, "rigging_command", None)
        if args.add:
            if sub is not None:
                raise UsageError("--add cannot be combined with a rigging subcommand")
            if not (args.file or args.dir):
                raise UsageError("--add requires exactly one of --file or --dir")
            return cmd_rigging_add(args)
        if args.file or args.dir:
            raise UsageError("--file and --dir require --add")
        if sub == "compact":
            rc = cmd_rigging_compact(args)
            if rc == 0:
                from drydock.config import record_activity

                record_activity("rigging compact", args.Target)
            return rc
        elif sub == "update":
            return cmd_rigging_update(args)
        elif sub == "verify":
            return cmd_rigging_verify(args)
        else:
            not_implemented("rigging")

    if command == "plan":
        rc = cmd_plan(args)
        if rc == 0:
            from drydock.config import record_activity

            record_activity("plan", args.Target, args.Target)
        return rc

    if command == "build":
        return _dispatch_build(args)

    if command == "score":
        return _dispatch_score(args)

    if command == "refit":
        rc = cmd_refit(args)
        if rc == 0:
            from drydock.config import record_activity

            record_activity("refit", args.Target, args.Target)
        return rc

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
    if command in {"status", "validate"}:
        return  # pure report
    if command == "config" and getattr(args, "config_command", None) == "show":
        return  # pure report

    from drydock.config import append_command_history, get_workspace

    tokens = argv if argv is not None else sys.argv[1:]
    cmd_str = "drydock " + " ".join(tokens)
    target = getattr(args, "Target", "") or ""
    append_command_history(get_workspace(), cmd_str, target=target, return_code=rc)


def _render_build_failures(target: str, steps, *, hint: str) -> str:
    """Format every failed build step as one closing block.

    The build prints this after the result line so the failure is the last thing on screen. It
    carries the cause, the nested acceptance detail, and the identifiers needed to reproduce.
    """
    width = 72
    border = "=" * width
    plural = "step" if len(steps) == 1 else "steps"
    lines = [border, f"BUILD FAILED: {target}  ({len(steps)} {plural})", border]
    for step in steps:
        lines += [
            "",
            f"  {step.name} [{step.block_id}]",
            f"    cause: {step.error or 'build failed'}",
        ]
        for line in (step.failure_detail or "").strip().splitlines():
            lines.append(f"    {line}")
        if step.execution_id:
            lines.append(f"    execution: {step.execution_id}")
        if step.evidence_path is not None:
            lines.append(f"    evidence: {step.evidence_path}")
    lines += ["", "  Next"]
    lines += textwrap.wrap(hint, width=width - 4, initial_indent="    ", subsequent_indent="    ")
    lines.append(border)
    return "\n".join(lines)


def _render_recorded_error(record) -> str:
    """Format a post-LLM failure for the terminal: the diagnostic itself, not just a filename."""
    width = 72
    border = "=" * width
    indent = "  "

    def _block(text: str, pad: str = indent) -> list[str]:
        wrapped: list[str] = []
        for paragraph in text.splitlines() or [""]:
            paragraph = paragraph.rstrip()
            if not paragraph:
                wrapped.append("")
                continue
            wrapped.extend(
                textwrap.wrap(
                    paragraph,
                    width=width - len(pad),
                    initial_indent=pad,
                    subsequent_indent=pad,
                    break_long_words=False,
                    break_on_hyphens=False,
                )
                or [pad + paragraph]
            )
        return wrapped

    heading = f"POST-LLM FAILURE  ·  {record.command}  ·  {record.classification}"
    lines = [border, heading, border, ""]
    lines += _block(record.detail.strip())
    if record.recovery.strip():
        lines += ["", indent + "Recovery"]
        lines += _block(record.recovery.strip(), pad=indent + "  ")
    lines += ["", border]
    return "\n".join(lines)


def _standoff_diagnosis(
    args,
    argv: list[str] | None,
    *,
    record=None,
    exc: BaseException | None = None,
    runner=None,
) -> None:
    """Have the selected LLM diagnose an opaque failure, then print and persist the result.

    Advisory only: any failure here is swallowed so the original error and exit code stand.
    """
    try:
        from drydock.config import get_diagnose_enabled, get_llm_provider, get_model, get_workspace
        from drydock.diagnose import diagnose, render_standoff_banner, should_diagnose

        if getattr(args, "no_diagnose", False) or not get_diagnose_enabled():
            return
        if not should_diagnose(record=record, exc=exc):
            return

        from drydock.config import get_target_directory
        from drydock.errors import append_diagnosis, append_diagnosis_to_evidence

        target = getattr(args, "Target", "") or ""
        target_dir = get_target_directory() / target if target else Path.cwd()
        tokens = argv if argv is not None else sys.argv[1:]
        command = "drydock " + " ".join(tokens)
        llm_provider = get_llm_provider(getattr(args, "llm_provider", None))
        model = get_model(getattr(args, "model", None))

        print(
            render_standoff_banner(llm=llm_provider, model=model, command=command),
            file=sys.stderr,
        )
        text = diagnose(
            target_dir,
            command=command,
            target=target,
            record=record,
            exc=exc,
            llm=llm_provider,
            model=model,
            log_dir=get_workspace() / "logs",
            runner=runner,
        )
        if not text:
            print("  No diagnosis was available.", file=sys.stderr)
            return
        print(text, file=sys.stderr)
        print("=" * 72, file=sys.stderr)
        append_diagnosis(target_dir, text)
        if record is not None and record.evidence:
            evidence_path = Path(record.evidence)
            if not evidence_path.is_absolute():
                evidence_path = target_dir / evidence_path
            append_diagnosis_to_evidence(evidence_path, text)
    except Exception:  # noqa: BLE001 - diagnosis must never change the command's outcome
        return


def _command_log_name(args: argparse.Namespace) -> str:
    parts = [getattr(args, "command", None) or "drydock"]
    for attribute in ("config_command", "rigging_command", "prompt_command", "run_command"):
        value = getattr(args, attribute, None)
        if value:
            parts.append(value)
    return "_".join(parts)


def main(argv: list[str] | None = None) -> None:
    parser = _build_parser()
    raw_argv = argv if argv is not None else sys.argv[1:]
    normalized_argv, global_overrides = _extract_global_overrides(raw_argv)
    args = parser.parse_args(normalized_argv)
    for key, value in global_overrides.items():
        if key == "debug":
            args.debug = bool(getattr(args, "debug", False) or value)
        elif getattr(args, key, None) is None:
            setattr(args, key, value)
    print(f"Drydock {__version__}  {__copyright__}", file=sys.stderr)
    debug = getattr(args, "debug", False)

    command_logging = None
    try:
        from drydock.config import get_workspace
        from drydock.logging import setup_command_logging

        log_dir = get_workspace() / "logs"
        command_logging = setup_command_logging(
            log_dir,
            _command_log_name(args),
            stdout=sys.stdout,
            debug=debug,
        )
        logger.info("command: %s", " ".join(sys.argv if argv is None else argv))
    except Exception:
        pass  # log setup failure must not prevent the command from running

    exit_code = 0
    stdout_context = (
        redirect_stdout(command_logging.stdout) if command_logging is not None else nullcontext()
    )
    try:
        with stdout_context:
            try:
                exit_code = _dispatch(args, parser)
            except UsageError as exc:
                print(f"error: {exc}", file=sys.stderr)
                exit_code = 2
            except RecordedError as exc:
                print(_render_recorded_error(exc.record), file=sys.stderr)
                exit_code = 1
                _standoff_diagnosis(args, argv, record=exc.record)
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
                _standoff_diagnosis(args, argv, exc=exc)

            try:
                _log_command_history(args, argv, exit_code)
            except Exception:
                pass  # history logging must never change the command's outcome
    finally:
        if command_logging is not None:
            command_logging.close()

    sys.exit(exit_code)

"""Drydock CLI — argparse-based command dispatcher."""

from __future__ import annotations

import argparse
import logging
import os
import re
import sys
import textwrap
import time
import traceback
from collections import Counter
from contextlib import nullcontext, redirect_stdout
from datetime import datetime
from pathlib import Path
from typing import NoReturn

from drydock import __copyright__, __version__
from drydock.config import DEFAULT_REPAIR_ATTEMPTS, settable_config_keys
from drydock.errors import DrydockError, RecordedError, UsageError
from drydock.stubs import not_implemented

logger = logging.getLogger(__name__)

# Console glyph tiers, richest first after ``auto``. See ``drydock.console``.
GLYPH_TIERS = ("auto", "emoji", "text", "ascii")


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


def _stream_build(text: str) -> None:
    """Render each Drydock build status message as its own newline-terminated stdout line.

    During ``drydock build`` the LLM runs with ``on_text=None``, so every message
    delivered here is one of Drydock's own status lines, never a model delta. An empty
    message is a blank separator between chunks.
    """
    sys.stdout.write("\n" if text == "" else text + "\n")
    sys.stdout.flush()


def _stream_build_summary(text: str) -> None:
    """Show concise LLM scope and acceptance in normal output without debug chatter."""
    if text.startswith("LLM BUILD:"):
        _stream_build("")
        _stream_build(text)
    elif text.startswith((
        "  stories:",
        "  regression gates:",
        "  call:",
        "  failing:",
    )):
        _stream_build(text)
    elif text.startswith("acceptance:"):
        _stream_build(text)
    elif text.startswith("WARNING:"):
        _stream_build(text)
    # A repair loop that stops below its budget must say why here. Hiding the reason behind
    # --debug leaves an operator reading "call 2 of up to 4" with no account of the shortfall.
    # ``repair: attempt`` stays hidden — the ``call:`` line already carries that count.
    elif text.startswith(("repair: stopped", "repair: escalation")):
        _stream_build(text)


def _stream_status_only(text: str) -> None:
    """Stream Drydock progress lines and drop model text and provider tool activity.

    Scoring commands consume the model's output as a JSON payload: Drydock parses it,
    renders the Scorecard, and prints the summary itself. Echoing the raw deltas dumps
    that JSON into the console. Codex command events are preserved in the raw LLM
    artifact; they are implementation evidence rather than scoring progress.
    """
    if text.startswith(("  $ ", "  -> exit ")):
        return
    if text.startswith(_STREAM_STATUS_PREFIXES):
        _stream_stdout(text)


_HEAVY_RULE = "═" * 72


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
        help="Override LLM model (default: the command's declared model or DRYDOCK_MODEL env/config).",
    )
    parser.add_argument(
        "--llm-provider",
        default=None,
        choices=["claude", "codex"],
        metavar="<provider>",
        help="Override LLM provider (default: LLM_PROVIDER env or claude).",
    )
    from drydock.config import EFFORT_LEVELS

    parser.add_argument(
        "--effort",
        default=None,
        choices=list(EFFORT_LEVELS),
        metavar="<level>",
        help=(
            "Override reasoning effort ("
            + "|".join(EFFORT_LEVELS)
            + "; default: the command's declared effort or DRYDOCK_EFFORT env/config)."
        ),
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
        return None, {
            "model": None,
            "llm_provider": None,
            "effort": None,
            "debug": False,
            "ascii": None,
            "glyphs": None,
        }

    from drydock.config import EFFORT_LEVELS

    cleaned: list[str] = []
    overrides: dict[str, str | bool | None] = {
        "model": None,
        "llm_provider": None,
        "effort": None,
        "debug": False,
        "ascii": None,
        "glyphs": None,
    }
    index = 0

    while index < len(argv):
        token = argv[index]
        if token == "--":
            cleaned.extend(argv[index:])
            break
        option, separator, inline = token.partition("=")
        if option == "--effort":
            if separator:
                level, consumed = inline, 1
            elif index + 1 < len(argv):
                level, consumed = argv[index + 1], 2
            else:
                raise UsageError("argument --effort: expected one argument")
            if level.strip().lower() not in EFFORT_LEVELS:
                raise UsageError(
                    f"argument --effort: invalid choice: {level!r}\n"
                    f"  Valid values: {', '.join(EFFORT_LEVELS)} (lowest to highest)\n"
                    "  Omit it to keep the provider's own default."
                )
            overrides["effort"] = level.strip().lower()
            index += consumed
            continue
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
        if token in {"--ascii", "--unicode"}:
            overrides["ascii"] = token == "--ascii"
            index += 1
            continue
        if option == "--glyphs":
            if separator:
                tier, consumed = inline, 1
            elif index + 1 < len(argv):
                tier, consumed = argv[index + 1], 2
            else:
                raise UsageError("argument --glyphs: expected one argument")
            tier = tier.strip().lower()
            if tier not in GLYPH_TIERS:
                raise UsageError(
                    f"argument --glyphs: invalid choice: {tier!r}\n"
                    f"  Valid values: {', '.join(GLYPH_TIERS)}\n"
                    "  auto detects what the terminal renders; run `drydock status console`."
                )
            overrides["glyphs"] = tier
            index += consumed
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


def cmd_config_env(args: argparse.Namespace) -> int:
    """Print resolved Drydock paths as shell assignments for ``eval``.

    Scripts that drive Drydock should not restate where the workspace, targets root, or build
    root live; those are configuration and can move. Naming a Target adds its directory and its
    build directory. The Target need not exist yet — a driver that clears and regenerates a
    Target has to learn the paths before creating it.
    """
    import shlex

    from drydock.config import build_dir_for, get_build_directory, get_target_directory
    from drydock.config import get_workspace as _get_workspace

    rows: list[tuple[str, str]] = [
        ("DRYDOCK_WORKSPACE", str(_get_workspace())),
        ("DRYDOCK_TARGETS_ROOT", str(get_target_directory())),
        ("DRYDOCK_BUILD_DIRECTORY", str(get_build_directory())),
    ]
    target = getattr(args, "Target", None)
    if target:
        from drydock.metadata import METADATA_NAME, get_build_dir

        target_dir = get_target_directory() / target
        # An initialized Target may redirect its build directory in METADATA.md; honor that
        # rather than assuming the default layout.
        build_dir = (
            get_build_dir(target, target_dir)
            if (target_dir / METADATA_NAME).is_file()
            else build_dir_for(target)
        )
        rows.extend([
            ("DRYDOCK_TARGET", target),
            ("DRYDOCK_TARGET_DIR", str(target_dir)),
            ("DRYDOCK_TARGET_BUILD_DIR", str(build_dir)),
        ])
    for key, value in rows:
        print(f"{key}={shlex.quote(value)}")
    return 0


def cmd_config_set(args: argparse.Namespace) -> int:
    from drydock.config import config_set

    cfg_file = config_set(args.key, args.value)
    print(f"Set {args.key} -> {args.value}")
    print(f"Saved to {cfg_file}")
    return 0


def _uat_kit_roots(
    uat_root: Path, selected: str | None, *, report: bool = False
) -> tuple[Path, ...]:
    """Resolve and validate the direct kit repositories selected by a UAT command."""
    if not uat_root.is_dir():
        raise UsageError(f"No UAT kits found under {uat_root}")
    if selected and not (report and selected == "all"):
        candidate = Path(selected)
        kits = [candidate if report and candidate.is_absolute() else uat_root / selected]
    else:
        kits = sorted(path for path in uat_root.iterdir() if (path / "uat.json").is_file())
    if not kits:
        raise UsageError(f"No UAT kits found under {uat_root}")
    for kit_root in kits:
        if not (kit_root / "uat.json").is_file():
            raise UsageError(f"Not a UAT kit directory: {kit_root}")
    return tuple(kits)


def _uat_report(kits: tuple[Path, ...]) -> int:
    """Rebuild the proof kits for the selected repositories."""
    from drydock.uat_report import build_kit_index

    for kit_root in kits:
        index = build_kit_index(kit_root)
        print(f"Proof kit: {index}")
    return 0


def _uat_one_fixture(uat_root: Path, selected: str | None, flag: str):
    """Resolve the single kit a step-numbered operation names, rejecting an ambiguous sweep."""
    from drydock.uat import discover_fixtures

    if not selected:
        raise UsageError(f"{flag} requires <Project>: step numbers belong to one kit's run")
    fixtures = discover_fixtures(uat_root, selected)
    if len(fixtures) != 1:
        raise UsageError(f"{flag} requires exactly one kit, matched {len(fixtures)}")
    return fixtures[0]


def _uat_steps(uat_root: Path, selected: str | None, run: str | None) -> int:
    """Print a recorded run's numbered steps and the stage each one resumes into."""
    from drydock.uat import render_steps

    print(render_steps(_uat_one_fixture(uat_root, selected, "--steps"), run))
    return 0


def _uat_stage_for_step(uat_root: Path, selected: str | None, run: str | None, step: int) -> str:
    """Translate ``--from-step <n>`` into the stage a resume re-enters, stating the translation."""
    from drydock.uat import resolve_step_stage

    fixture = _uat_one_fixture(uat_root, selected, "--from-step")
    run_id, resolved, entry = resolve_step_stage(fixture, run, step)
    print(f"{fixture.name} run {run_id}: step {resolved.number} ({resolved.label})")
    print(f"  stage {resolved.stage!r} replays in full, starting at step {entry.number}")
    if entry.number != resolved.number:
        print(f"  step {resolved.number} runs again once the stage reaches it")
    print(f"  steps {entry.number} and later are superseded; their logs move to superseded/")
    return resolved.stage


def _add_bound_arguments(parser: argparse.ArgumentParser) -> None:
    """Attach the execution bounds shared by every command that runs the code under test.

    ``drydock build`` and ``drydock uat`` both hand control to a target, so both expose the same
    three bounds under the same names. A default of ``None`` means "unset": the configured value
    stands, and the flag is an override for one run rather than a second source of truth.
    """
    from drydock.config import (
        DEFAULT_CAPTURE_OUTPUT_LIMIT_MB,
        DEFAULT_SANDBOX_MEM_LIMIT_MB,
        MAX_CONSECUTIVE_REPAIR_STALLS,
    )

    parser.add_argument(
        "--repair-stall-limit",
        dest="repair_stall_limit",
        type=int,
        default=None,
        metavar="<n>",
        help=(
            "Consecutive repair passes without acceptance progress before a block is stopped "
            f"(default: {MAX_CONSECUTIVE_REPAIR_STALLS}, or "
            "'drydock config set repair_stall_limit <n>')."
        ),
    )
    parser.add_argument(
        "--capture-output-limit",
        dest="capture_output_limit",
        type=int,
        default=None,
        metavar="<MB>",
        help=(
            "Output Drydock will hold from one acceptance command before stopping it and "
            f"failing the gate (default: {DEFAULT_CAPTURE_OUTPUT_LIMIT_MB} MB, 0 disables; or "
            "'drydock config set capture_output_limit <MB>')."
        ),
    )
    parser.add_argument(
        "--sandbox-mem-limit",
        dest="sandbox_mem_limit",
        type=int,
        default=None,
        metavar="<MB>",
        help=(
            "Address-space ceiling for an acceptance run and everything it spawns "
            f"(default: {DEFAULT_SANDBOX_MEM_LIMIT_MB} MB, 0 disables; or "
            "'drydock config set sandbox_mem_limit <MB>')."
        ),
    )


def _apply_bound_overrides(args: argparse.Namespace) -> None:
    """Let a command-line bound override the configured one for this process only.

    The bounds are read where they are enforced, several call layers below the parser, so a flag
    is published into the environment rather than threaded through every signature between here
    and the child process. The precedence an operator sees is the usual one: flag, then
    environment, then ``drydock config``, then the shipped default.
    """
    for attribute, env_var in (
        ("repair_stall_limit", "DRYDOCK_REPAIR_STALL_LIMIT"),
        ("capture_output_limit", "DRYDOCK_CAPTURE_OUTPUT_LIMIT"),
        ("sandbox_mem_limit", "DRYDOCK_SANDBOX_MEM_LIMIT"),
    ):
        value = getattr(args, attribute, None)
        if value is not None:
            os.environ[env_var] = str(value)


def _resolved_repair_attempts(args: argparse.Namespace) -> int:
    """The repair budget for this run: the flag when given, otherwise the configured value."""
    from drydock.config import get_repair_attempts

    value = getattr(args, "repair_attempts", None)
    return get_repair_attempts() if value is None else int(value)


def cmd_uat(args: argparse.Namespace) -> int:
    """Run known project fixtures through an isolated unattended lifecycle."""
    from drydock.config import get_effort, get_llm_provider, get_model, get_workspace
    from drydock.uat import make_streaming_runner, render_summary, run_uat
    from drydock.uat_console import StepConsole

    workspace = get_workspace().resolve()
    uat_root = args.uat_root.resolve() if args.uat_root is not None else workspace / "uat"
    report = args.report is not None
    # Step numbers belong to one kit's recorded run, so the selection is settled before any kit
    # is touched: a sweep has no step 16 to resolve.
    if not report and not args.Project:
        for flag, given in (("--from-step", args.from_step is not None), ("--steps", args.steps)):
            if given:
                raise UsageError(f"{flag} requires <Project>: step numbers belong to one kit's run")
    kits = _uat_kit_roots(uat_root, args.report if report else args.Project, report=report)
    from drydock.uat_git import checkpoint_kit_repositories, ensure_kit_repositories

    ensure_kit_repositories(kits)
    try:
        if report:
            return _uat_report(kits)
        if args.max_build_passes < 1:
            raise UsageError("--max-build-passes must be at least 1")
        if args.repair_attempts is not None and args.repair_attempts < 0:
            raise UsageError("--repair-attempts must be zero or greater")
        if args.steps:
            return _uat_steps(uat_root, args.Project, args.run)
        if args.run is not None and args.stage is None and args.from_step is None:
            raise UsageError("--run requires --stage or --from-step")
        start_stage = args.stage or "init"
        if args.from_step is not None:
            start_stage = _uat_stage_for_step(uat_root, args.Project, args.run, args.from_step)
        _apply_bound_overrides(args)
        repair_attempts = _resolved_repair_attempts(args)
        step_console = StepConsole(sys.stdout, quiet=args.quiet)
        _, results = run_uat(
            workspace,
            selected=args.Project,
            uat_root=uat_root,
            model=get_model(getattr(args, "model", None)),
            provider=get_llm_provider(getattr(args, "llm_provider", None)),
            effort=get_effort(getattr(args, "effort", None)),
            max_build_passes=args.max_build_passes,
            repair_attempts=repair_attempts,
            runner=make_streaming_runner(step_console),
            on_event=step_console.event,
            start_stage=start_stage,
            run=args.run,
        )
        if not args.quiet:
            print()
            print(render_summary(results, uat_root))
        passed = sum(result.status == "passed" for result in results)
        print(f"UAT: {passed}/{len(results)} kit(s) passed")
        # A passing kit can still owe a manual test. Print it after the tally, where it survives
        # --quiet: a prohibition nobody was told about is a prohibition nobody checks.
        for result in results:
            for attestation in result.attestations:
                print(f"  MANUAL TEST REQUIRED: {result.fixture}: {attestation}")
        for result in results:
            print(f"Report: {Path(result.output_dir) / 'README.md'}")
        return 0 if passed == len(results) else 1
    finally:
        checkpoint_kit_repositories(kits)


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
    # .gitkeep placeholders are directory scaffolding, not project artifacts; the
    # directory they hold open is what the operator cares about.
    for path in result.created:
        if path.name == ".gitkeep":
            continue
        print(f"  CREATED  {path.relative_to(result.target_dir)}")
    if result.skipped:
        print(f"  ({len(result.skipped)} existing baseline files preserved)")
    if not result.created:
        print("  Nothing to do — target baseline is already initialized.")

    _sync_workspace_skills(get_workspace())

    record_activity("init", target=args.Target)
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

    if getattr(args, "sources", False) and getattr(args, "relineage", False):
        raise UsageError("drydock refit: --sources and --relineage are mutually exclusive")

    if getattr(args, "relineage", False):
        from drydock.lineage_backfill import relineage_target

        result = relineage_target(
            target_dir,
            log_dir=log_dir,
            model=model,
            llm_provider=llm_provider,
        )
        for source in result.sources:
            print(
                f"  [source]          {source.path}  "
                f"{source.versions} version(s), {source.attributed} story attribution(s)"
            )
        for warning in result.warnings:
            print(f"  [warning]         {warning}")
        if result.unattached:
            print(f"  [unattached]      {', '.join(result.unattached)}  (origin: plan)")
        _commit_and_stamp(target_dir, "Backfill source lineage")
        print(
            f"RESULT: {len(result.sources)} source(s) relineaged, "
            f"{len(result.unattached)} story(ies) unattached"
        )
        return 0

    if getattr(args, "sources", False):
        from drydock.source_refit import commit_target, source_refit_target

        result = source_refit_target(
            target_dir,
            log_dir=log_dir,
            model=model,
            llm_provider=llm_provider,
        )
        if not result.items:
            print("  No pending source versions.")
            return 0
        for item in result.items:
            print(
                f"  [ticket]          {item.ticket.relative_to(target_dir)}  "
                f"({item.scope}, {item.blueprint})  {', '.join(item.stories)}"
            )
        # A contract change never gates the build; the Commander decides whether to rebuild the
        # consumers now or defer them.
        for consumer in result.downstream:
            print(f"  [downstream]      {consumer}")
        commit_target(target_dir, "Author source-driven refit tickets")
        print(f"RESULT: {len(result.items)} change ticket(s) authored")
        return 0

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
    # Warnings print on stdout: the command transcript tees stdout only, so a warning sent to
    # stderr never reaches the run log and is lost the moment the terminal scrolls.
    for warning in getattr(result, "warnings", ()):
        print(f"Warning: {warning}")
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
        print(_render_analyze_blockers(args.Target, result.blockers_path))
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


OVERRIDE_HELP = (
    "Waive the gates that wait on a human answer — unanswered Analyze questionnaire decisions, "
    "blocking DECISIONS.json records, and acceptance prerequisites awaiting authorization — and "
    "report them instead of stopping. A blocked analysis (BLOCKERS.md, Quality: Blocked) is still "
    "fatal. Intended for unattended regression runs; the Target is stamped as ungoverned."
)


def _print_override_summary(waivers: object) -> None:
    """Print the bypassed-gate block after a command's result line, if any gate was waived."""
    from drydock.override import format_override_summary

    items = tuple(waivers or ())  # type: ignore[arg-type]
    if not items:
        return
    print()
    print(format_override_summary(items))  # type: ignore[arg-type]


#: Sub-verbs under ``drydock plan``. Everything else in the operand slot is a Target name.
_PLAN_SUB_VERBS = ("verify", "repair")


def _parse_plan_args(args: argparse.Namespace) -> tuple[str, str]:
    """Return ``(sub_verb, target)`` from the REMAINDER operands. ``""`` means plan creation.

    Options are declared on the dispatcher *and* re-parsed here, the same shape ``build`` uses:
    argparse consumes a flag written before the Target, and this recovers one written after it.
    Both spellings have always worked and neither is being retired by the sub-verbs.
    """
    operands = [item for item in (getattr(args, "args", None) or []) if item != "--"]
    trailing = argparse.ArgumentParser(prog="drydock plan", add_help=False)
    _add_llm_override_flags(trailing)
    trailing.add_argument("--overwrite", action="store_true", default=None)
    trailing.add_argument("--no-conform", action="store_true", default=None)
    trailing.add_argument("--override", action="store_true", default=None)
    trailing.add_argument("--continue-attempts", dest="continue_attempts", type=int, default=None)
    try:
        parsed, positional = trailing.parse_known_args(operands)
    except SystemExit as exc:  # argparse already printed the usage error
        raise UsageError("Invalid option for drydock plan.") from exc
    for name, value in vars(parsed).items():
        if value is not None and value is not False:
            setattr(args, name, value)
    if unknown := [item for item in positional if item.startswith("-")]:
        raise UsageError(f"Unrecognized option for drydock plan: {unknown[0]}")
    sub_verb = ""
    if positional and positional[0] in _PLAN_SUB_VERBS:
        sub_verb = positional.pop(0)
    if not positional:
        raise UsageError(
            f"drydock plan {sub_verb} requires a Target.".replace("  ", " ")
            if sub_verb
            else "drydock plan requires a Target."
        )
    if len(positional) > 1:
        raise UsageError(f"Unexpected operand for drydock plan: {positional[1]}")
    return sub_verb, positional[0]


def cmd_plan_verify(target: str) -> int:
    """Report every acceptance criterion that cannot run. Read-only; exit status is the verdict."""
    from drydock.config import require_target_dir
    from drydock.plan_verify import render, verify

    result = verify(target, require_target_dir(target))
    print(render(result))
    return result.exit_code()


def cmd_plan_repair(args: argparse.Namespace, target: str) -> int:
    """Make unrunnable criteria runnable in one pass, then report what is still broken."""
    from drydock.config import get_llm_provider, get_model, get_workspace, require_target_dir
    from drydock.plan_repair import render, repair
    from drydock.plan_verify import render as render_verify
    from drydock.plan_verify import verify

    target_dir = require_target_dir(target)
    result = repair(
        target,
        target_dir,
        model=get_model(getattr(args, "model", None)),
        llm_provider=get_llm_provider(getattr(args, "llm_provider", None)),
        log_dir=get_workspace() / "logs",
        on_text=lambda text: print(text, end="", flush=True),
    )
    print(render(result))
    if result.nothing_to_repair:
        return 0
    # Re-verify from disk rather than trusting the repair's own bookkeeping. The plan is about to
    # be built against these files, so the last word belongs to the same check the build uses.
    print(render_verify(verify(target, target_dir)))
    return result.exit_code()


def cmd_plan(args: argparse.Namespace) -> int:
    from drydock.config import (
        get_diagnose_enabled,
        get_llm_provider,
        get_model,
        get_target_directory,
        get_workspace,
        require_target_dir,
    )
    from drydock.planning_session import PlanDeferredResult, create_plan
    from drydock.quarterdeck_state import commanders_chair_command

    sub_verb, target = _parse_plan_args(args)
    # The Target is resolved from the operand slot now that ``plan`` carries sub-verbs. Setting it
    # back keeps the post-dispatch activity record and every downstream reader unchanged.
    args.Target = target
    args.plan_sub_verb = sub_verb
    if sub_verb == "verify":
        return cmd_plan_verify(target)
    if sub_verb == "repair":
        return cmd_plan_repair(args, target)

    def _progress(text: str) -> None:
        # Only surface plan's own mode/status notices; suppress the raw streamed
        # LLM response text, which for a full-rewrite plan can be very large.
        if text.startswith("[plan-score]"):
            print(text.removeprefix("[plan-score]"), end="", flush=True)
        elif getattr(args, "debug", False) and text.startswith("[plan]"):
            print(text, end="")

    model = get_model(getattr(args, "model", None))
    llm_provider = get_llm_provider(getattr(args, "llm_provider", None))
    log_dir = get_workspace() / "logs"
    target_directory = get_target_directory()
    target_dir = require_target_dir(args.Target)
    continue_attempts = int(getattr(args, "continue_attempts", 3) or 0)
    if continue_attempts < 0:
        raise UsageError("--continue-attempts must be zero or greater.")
    plan_started = time.monotonic()
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
            allow_diagnostic_recovery=(
                get_diagnose_enabled() and not getattr(args, "no_diagnose", False)
            ),
            continue_attempts=continue_attempts,
            override=bool(getattr(args, "override", False)),
        )
    if isinstance(result, PlanDeferredResult):
        print()
        print(_render_plan_deferred(result, target=args.Target))
        return 2
    print()
    mode_label = {
        "reuse-manifest-first": "REUSE (existing Blueprint specs preserved)",
        "full-rewrite": "OVERWRITE (Blueprint specs regenerated from analysis)",
        "speckit-translate": "SPEC-KIT (imported Spec Kit sources translated)",
    }.get(result.plan_mode, result.plan_mode or "unknown")
    print(f"Mode: {mode_label}")
    print(f"Provider: {llm_provider} / {model}")
    counts = Counter(block.block_type for block in result.plan.blocks)
    print(
        "Graph: "
        f"{counts['feature']} features, {counts['story']} stories, "
        f"{counts['spike']} spikes, {counts['ac']} acceptance gates"
    )
    print(f"Warnings: {len(result.warnings)}")
    print(f"Outcome: {'updated' if getattr(result, 'changed', True) else 'unchanged'}")
    print(f"Execution: {getattr(result, 'execution_id', None) or '-'}")
    print(f"Elapsed: {_elapsed_text(time.monotonic() - plan_started)}")
    print(f"Review: {result.quarterdeck_dir}")
    _print_override_summary(getattr(result, "waivers", ()))
    if not getattr(args, "debug", False):
        return 0
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
    # A removed criterion changed the Blueprint the author is about to review, so it is
    # reported above the graph rather than buried in the advisory list below it.
    from drydock.planning_session import ACCEPTANCE_REMOVED_MARKER

    removed = [w for w in result.warnings if ACCEPTANCE_REMOVED_MARKER in w]
    if removed:
        print()
        print(f"⚠  Acceptance criteria removed ({len(removed)}):")
        for warning in removed:
            print(f"  - {warning}")
        print("   These could never pass. Re-author them if the behavior still needs a gate.")
    print()
    _print_plan_blocks(result.plan)
    _print_plan_summary(result.plan)
    remaining = [w for w in result.warnings if ACCEPTANCE_REMOVED_MARKER not in w]
    if remaining:
        print()
        print("Planning warnings:")
        for warning in remaining:
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


def _commit_and_stamp(target_dir: Path, message: str) -> str | None:
    """Commit the Target, then record the resulting sha against the versions it just introduced.

    A version's commit cannot be known until the commit exists, so lineage is written with a null
    sha and stamped afterwards. The stamp is its own follow-up commit: amending would rewrite the
    commit the record points at, leaving every recorded sha unreachable.
    """
    from drydock.lineage import load_lineage, stamp_pending_commits, write_lineage
    from drydock.target_git import commit_paths, commit_target

    commit = commit_target(target_dir, message)
    if not commit:
        return None
    lineage = load_lineage(target_dir)
    if stamp_pending_commits(lineage, commit):
        write_lineage(target_dir, lineage)
        commit_paths(target_dir, ["LINEAGE.json"], "Record source lineage")
    return commit


def cmd_import(args: argparse.Namespace) -> int:
    from drydock.config import get_target_directory
    from drydock.import_markdown import detect_import_format

    td = get_target_directory()

    # --update refreshes the snapshot from the import root recorded in LINEAGE.json, so no
    # <Source> argument is accepted or needed.
    if getattr(args, "update", False):
        from drydock.source_refit import update_import

        if args.Source is not None:
            raise UsageError("--update refreshes the recorded source root; do not pass <Source>")
        target_dir = td / args.Target
        result = update_import(target_dir)
        _commit_and_stamp(target_dir, "Refresh imported source snapshot")
        print(
            f"Source update: {len(result.added)} added, {len(result.changed)} changed, "
            f"{len(result.deleted)} deleted, {len(result.unchanged)} unchanged"
        )
        if result.pending_versions:
            print(
                f"  {result.pending_versions} source version(s) pending; "
                f"run: drydock refit {args.Target} --sources"
            )
        return 0

    if args.Source is None:
        raise UsageError("import requires <Source> (or --update to refresh a prior import)")

    source = Path(args.Source)
    fmt = args.format
    if fmt == "auto":
        if source.expanduser().is_dir():
            raise UsageError(
                "--format auto requires a file; specify --format markdown, source, or speckit for a directory"
            )
        fmt = detect_import_format(source)

    def print_import_result(
        source_path: Path, imported: tuple[Path, ...] | list[Path], destination: Path
    ) -> None:
        print(f"Source: {source_path}")
        print(f"Target: {destination}/")
        for path in imported:
            print(Path(path).relative_to(destination))

    if fmt == "markdown":
        from drydock.import_markdown import import_markdown
        from drydock.source_refit import commit_target

        result = import_markdown(args.Target, args.Target, source, td)
        _commit_and_stamp(td / args.Target, "Import source snapshot")
        print_import_result(result.source, result.imported, result.blueprint_dir / "sources")
        return 0

    if fmt == "source":
        from drydock.import_source import import_source
        from drydock.source_refit import commit_target

        source_result = import_source(args.Target, args.Target, source, td)
        _commit_and_stamp(td / args.Target, "Import source snapshot")
        print_import_result(
            source_result.source, source_result.imported, source_result.blueprint_dir / "sources"
        )
        return 0

    if fmt == "speckit":
        from drydock.import_speckit import import_speckit
        from drydock.source_refit import commit_target

        speckit_result = import_speckit(args.Target, args.Target, source, td)
        _commit_and_stamp(td / args.Target, "Import source snapshot")
        print_import_result(
            speckit_result.source, speckit_result.imported, speckit_result.blueprint_dir / "sources"
        )
        return 0

    if fmt in {"compass", "intent"}:
        from drydock.config import get_llm_provider, get_model, get_workspace
        from drydock.import_markdown import import_intent
        from drydock.source_refit import commit_target

        result = import_intent(
            args.Target,
            source,
            td,
            force=bool(getattr(args, "force", False)),
            model=get_model(getattr(args, "model", None)),
            llm_provider=get_llm_provider(getattr(args, "llm_provider", None)),
            log_dir=get_workspace() / "logs",
        )
        commit_target(td / args.Target, "Import Compass source")
        print_import_result(result.source, result.imported, result.blueprint_dir)
        print("normalized")
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


def _target_last_updated(target_dir: Path) -> int:
    """Return the newest modification timestamp in an initialized Target tree."""
    try:
        latest = target_dir.lstat().st_mtime_ns
    except OSError:
        latest = 0
    for path in target_dir.rglob("*"):
        try:
            latest = max(latest, path.lstat().st_mtime_ns)
        except OSError:
            # A concurrent command may replace an artifact while Targets are scanned.
            continue
    return latest


def _resolve_latest_target(targets_root: Path) -> Path:
    """Resolve the most recently modified initialized Target under the workspace."""
    candidates = (
        [path for path in targets_root.iterdir() if path.is_dir() and _is_target_dir(path)]
        if targets_root.is_dir()
        else []
    )
    if not candidates:
        raise DrydockError(
            f"No initialized Target found under {targets_root}\n  Run: drydock init <Target>"
        )
    updated = [(path, _target_last_updated(path)) for path in candidates]
    return min(updated, key=lambda item: (-item[1], item[0].name.casefold(), item[0].name))[0]


def cmd_run_quarterdeck(args: argparse.Namespace) -> int:
    from drydock import quarterdeck_run as _qd
    from drydock.config import get_quarterdeck_port, get_target_directory

    targets_root = get_target_directory()
    target_dir = targets_root / args.Target if args.Target else _resolve_latest_target(targets_root)
    port = args.port if args.port is not None else get_quarterdeck_port()
    host = args.host

    print(f"QuarterDeck: {target_dir}")
    print(f"  http://{host}:{port}")

    result = _qd.run_quarterdeck(target_dir, port=port, host=host)
    return result.exit_code


def _render_status(result) -> None:
    """Print compact one-screen status output."""
    import shutil
    import textwrap

    def counted(value: int, singular: str, plural: str | None = None) -> str:
        noun = singular if value == 1 else (plural or f"{singular}s")
        return f"{value} {noun}"

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
                f"{counted(analysis.story_count, 'story', 'stories')}"
                f" · {counted(analysis.question_count, 'question')}"
                f" · {counted(analysis.blocker_count, 'blocker')}"
            )
            if analysis.screen_count:
                analysis_detail += f" · {counted(analysis.screen_count, 'screen')}"
            print(f"  {'Analysis':<{col}}  {quality} · {analysis_detail}")
        if info.questionnaire_count or info.blockers_present or info.decision_blocker_count:
            if info.blockers_present:
                blockers = "Blockers present"
            elif info.decision_blocker_count:
                blockers = counted(info.decision_blocker_count, "open blocking decision")
            else:
                blockers = "No blockers"
            print(
                f"  {'Review':<{col}}  {blockers}"
                f" · {counted(info.questionnaire_count, 'questionnaire')}"
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
            finding_indent = " " * 7
            finding_width = max(40, shutil.get_terminal_size(fallback=(120, 24)).columns - 7)
            for finding in v.findings:
                if finding.severity != Severity.PASS:
                    icon = _SEVERITY_ICON.get(finding.severity.value, "?")
                    finding_text = f"{finding.section}: {finding.message}"
                    wrapped = textwrap.wrap(
                        finding_text,
                        width=finding_width,
                        subsequent_indent=finding_indent,
                    ) or [finding_text]
                    print(f"    {icon}  {wrapped[0]}")
                    for line in wrapped[1:]:
                        print(line)
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


def _resolve_check_target(target: str):
    from drydock.config import get_target_directory
    from drydock.status import completion_check

    target_dir = get_target_directory() / target
    if not target_dir.is_dir():
        raise UsageError(f"Target not found: {target_dir}")
    return completion_check(target, target_dir)


def cmd_status_check(target: str) -> int:
    """Print one line and exit 0 complete, 1 buildable work remains, 2 blocked."""
    check = _resolve_check_target(target)
    # Every outcome here — complete, incomplete, blocked — is a successful status report.
    # The exit code carries the verdict; stderr stays reserved for command failures.
    print(f"{check.label}: {target}  {check.verified}/{check.total} verified  ({check.reason})")
    return check.exit_code()


def cmd_status_ready(target: str) -> int:
    """Loop guard: exit 0 while a build can advance *target*, non-zero once it cannot.

    Designed for ``while drydock status <Target> --ready; do drydock build <Target>; done``.
    Returns 0 only when buildable work remains; complete and blocked Targets both stop the loop.
    """
    check = _resolve_check_target(target)
    ready = False
    reason = check.reason
    if not check.complete and not check.blocked:
        from drydock.build_plan import parse_build_plan
        from drydock.build_status import build_status
        from drydock.config import get_target_directory

        plan = parse_build_plan(get_target_directory() / target / "MANIFEST.md")
        frontier = build_status(plan).buildable_ids
        ready = bool(frontier)
        reason = f"frontier: {', '.join(frontier)}" if frontier else "no buildable frontier"
    if ready:
        headline = "READY TO BUILD"
    elif check.complete:
        headline = "BUILD COMPLETE"
    else:
        headline = "NOT READY"
    # Ready, complete, and not-ready are all healthy build-loop verdicts reported by a
    # command that succeeded. The exit code carries the verdict; stderr means an error.
    print(f"{headline}: {target}  ({reason})")
    return 0 if ready else 1


def cmd_status_console() -> int:
    """Report how this terminal was classified, and show what it does with each glyph tier.

    A user whose icons come out wrong runs one command and sends one screenshot. The sample
    lines are the evidence: the raw line is written past the tier wrapper, so tofu there is
    proof that the downgrade below it was correct.
    """
    from drydock import console

    rows = console.console_report(sys.stdout)
    width = max(len(name) for name, _ in rows)
    print("\nConsole capability")
    for name, value in rows:
        print(f"  {name.ljust(width)}   {value}")

    # Written past the tier wrapper, so each line shows what this terminal really does with
    # that tier's characters rather than what the resolved tier would have made of them.
    print("\nGlyph samples")
    for tier in (console.EMOJI, console.TEXT, console.ASCII):
        label = f"  {tier.ljust(width)}   "
        sample = console.render(console.SAMPLE, tier)
        if not console.write_raw(sys.stdout, label + sample + "\n"):
            print(f"{label}(the stream refused these characters outright)")

    print(
        "\n  Any tier whose sample line shows boxes or question marks is not supported here.\n"
        "  Override with `drydock --glyphs <emoji|text|ascii> <command>` or DRYDOCK_GLYPHS."
    )
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
        if info.blockers_present or info.questionnaire_count or info.decision_blocker_count:
            review = (
                f"BLOCKERS.md {'present' if info.blockers_present else 'none'}"
                f" · {info.questionnaire_count} questionnaires"
            )
            if info.decision_blocker_count:
                review += f" · {info.decision_blocker_count} open blocking decisions"
            print(f"   {'Review:':<{label_width}} {review}")
        print(f"   {'Next Step:':<{label_width}} {info.next_operation}")
        if info.compact_recs:
            print(
                f"   {'Recommend:':<{label_width}} compact {len(info.compact_recs)} file(s)"
                f" — run: drydock rigging compact {info.name}"
            )
        # The outcome mark is chosen here rather than left to the stream wrapper: an emoji
        # occupies two cells and a text glyph one, so the column width depends on the tier.
        from drydock.console import EMOJI, active_tier, pad_display

        passed, failed = ("✅", "❌") if active_tier() == EMOJI else ("✓", "✗")
        for rec in reversed(info.history):
            cmd = rec.get("command", "")
            stamp = str(rec.get("time", "")).strip()
            rc = rec.get("return_code")
            action = "Run" if rc is None else (passed if rc == 0 else failed)
            if len(stamp) >= 10:
                month = str(int(stamp[5:7]))
                day = str(int(stamp[8:10]))
                label = f"{month}-{day}:"
            else:
                label = "Date:"
            print(f"   {label:<{label_width}} {pad_display(action, 3)} {cmd}")
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
    from drydock.build_run import (
        BUILD_FAILURE_HINT,
        BuildStepResult,
        _select_build_unit,
        build_target,
    )
    from drydock.config import (
        get_escalate_model,
        get_llm_provider,
        get_model,
        get_workspace,
        require_target_dir,
    )
    from drydock.manifest_edit import (
        optimize_build_blocks,
    )

    target_dir = require_target_dir(args.Target)
    from drydock.errors import clear_error_record

    clear_error_record(target_dir)
    if getattr(args, "step", None) and getattr(args, "story", None):
        raise UsageError("--step and --story are mutually exclusive.")
    if getattr(args, "continue_", False) and getattr(args, "reset", False):
        raise UsageError("--continue and --reset are mutually exclusive.")
    model = get_model(getattr(args, "model", None))
    llm_provider = get_llm_provider(getattr(args, "llm_provider", None))
    from drydock.llm import provider_model_conflict

    # Fail before staging assets or calling the agent when the resolved provider and
    # model disagree (e.g. codex + opus), so the misconfiguration is obvious up front.
    conflict = provider_model_conflict(llm_provider, model)
    if conflict is not None:
        raise UsageError(conflict)
    escalate_model = get_escalate_model(getattr(args, "escalate_model", None))
    if escalate_model:
        escalate_conflict = provider_model_conflict(llm_provider, escalate_model)
        if escalate_conflict is not None:
            raise UsageError(f"escalate model: {escalate_conflict}")
    if getattr(args, "repair_attempts", None) is not None and args.repair_attempts < 0:
        raise UsageError("--repair-attempts must be zero or greater.")
    _apply_bound_overrides(args)
    repair_attempts = _resolved_repair_attempts(args)
    build_dir = Path(args.build_dir).expanduser().resolve() if args.build_dir else None
    log_dir = get_workspace() / "logs"

    # Failures are collected here and rendered once at the end of the run, after the result
    # line, so the last thing on screen is the diagnosis rather than a mid-stream banner the
    # remaining step output scrolls away. The per-block progress and Definition of Done are
    # streamed by build_target itself; report only harvests the failures for that closing block.
    failures: list[BuildStepResult] = []
    _fatal_shown: set[str] = set()
    _reported_units: set[str] = set()
    _build_unit_ids: dict[str, str] = {}
    debug = bool(getattr(args, "debug", False))

    def report(step: BuildStepResult) -> None:
        unit_key = step.execution_id or step.block_id
        if unit_key not in _reported_units:
            _reported_units.add(unit_key)
            reference = f" · execution {step.execution_id}" if step.execution_id else ""
            unit_id = _build_unit_ids.get(step.block_id, step.block_id)
            print(f"{step.status}: {unit_id} — {step.state}{reference}")
        if step.status == "failed":
            # Stories in one block share a single execution: report it once.
            fatal_key = step.execution_id or f"{step.block_id}:{step.error}"
            if fatal_key not in _fatal_shown:
                _fatal_shown.add(fatal_key)
                failures.append(step)

    build_started = time.monotonic()
    print(f"Build: {args.Target}")
    if debug:
        print(f"Started: {_wall_time()}")
        print(f"Provider: {llm_provider} / {model}")
        attempts_word = "attempt" if repair_attempts == 1 else "attempts"
        print(f"Repair: {repair_attempts} {attempts_word} · escalate {escalate_model or 'off'}")
    if getattr(args, "story", None):
        print(f"scope: story {args.story}")
    elif getattr(args, "step", None):
        print(f"scope: step {args.step}")
    else:
        print("scope: entire project")
    from drydock.question_gates import synchronize_manifest_question_gates

    plan = synchronize_manifest_question_gates(
        target_dir / "MANIFEST.md",
        target_dir / "blueprint",
        persist=not bool(getattr(args, "dry_run", False)),
        override=bool(getattr(args, "override", False)),
    )
    frontier = plan.buildable_steps()
    frontier_text = ", ".join(block.block_id for block in frontier) or "empty"
    if not getattr(args, "story", None) and not getattr(args, "step", None):
        by_id = {block.block_id: block for block in plan.blocks}
        _build_unit_ids.update({
            block.block_id: block.parent
            for block in plan.blocks
            if block.parent
            and block.parent in by_id
            and by_id[block.parent].block_type == "feature"
        })
        if not getattr(args, "reset", False):
            try:
                selected = _select_build_unit(plan, None, args.Target)
            except DrydockError:
                selected = None
            if selected is not None and selected.resume:
                frontier_text = f"resume {selected.block_id}"
    print("frontier: " + frontier_text)
    if getattr(args, "reset", False):
        reset_scope = (
            getattr(args, "story", None)
            or getattr(args, "step", None)
            or "entire project (all blocks + build directory)"
        )
        print(f"reset: {reset_scope}")
    if getattr(args, "normalize_order", False):
        manifest_path = target_dir / "MANIFEST.md"
        changed = optimize_build_blocks(
            manifest_path, persist=not bool(getattr(args, "dry_run", False))
        )
        if getattr(args, "dry_run", False):
            print(
                "normalize order dry run: would "
                f"{'update' if changed else 'leave unchanged'} MANIFEST.md"
            )
        else:
            print(
                "optimize build blocks: "
                f"{'updated' if changed else 'already optimized'} MANIFEST.md"
            )
    if getattr(args, "dry_run", False):
        print("mode: DRY RUN — no LLM call, writes, evidence, state, README, or git commit")
        if getattr(args, "show_prompt", False):
            print("mode: full prompt output enabled by --show-prompt")
    chair_context = nullcontext()
    if not getattr(args, "dry_run", False):
        from drydock.quarterdeck_state import commanders_chair_command

        chair_context = commanders_chair_command(target_dir, _build_running_command(args))
    with chair_context:
        result = build_target(
            args.Target,
            target_dir,
            build_dir=build_dir,
            model=model,
            llm_provider=llm_provider,
            log_dir=log_dir,
            on_text=(
                _stream_build
                if debug or bool(getattr(args, "dry_run", False))
                else _stream_build_summary
            ),
            on_step=report,
            step_id=getattr(args, "step", None),
            story_id=getattr(args, "story", None),
            reset=bool(getattr(args, "reset", False)),
            dry_run=bool(getattr(args, "dry_run", False)),
            show_prompt=bool(getattr(args, "show_prompt", False)),
            repair_attempts=repair_attempts,
            escalate_model=escalate_model,
            ungate=bool(getattr(args, "ungate", False)),
            override=bool(getattr(args, "override", False)),
        )
    print()
    label = "dry-run result" if result.dry_run else "result"
    print(
        f"{label}: {len(result.built())} built, {len(result.failed())} failed, "
        f"{len(result.steps) - len(result.built()) - len(result.failed())} unchanged"
    )
    print(f"elapsed: {_elapsed_text(time.monotonic() - build_started)}")
    if not result.steps:
        print("nothing buildable — no pending step has all dependencies verified")
        reviewable = _reviewable_build_steps(target_dir)
        if reviewable:
            print("legacy implemented steps remain; rebuild or revise them to run acceptance")
    if result.stalled():
        # A stalled run used to be indistinguishable from a finished Target. Name the outstanding
        # work and fail, so an unattended driver stops here instead of reporting success.
        print()
        print(
            f"BUILD STALLED — {len(result.stalled_blocks)} block(s) outstanding and none could "
            "advance:"
        )
        for block_id in result.stalled_blocks[:20]:
            print(f"  {block_id}")
        if len(result.stalled_blocks) > 20:
            print(f"  ... and {len(result.stalled_blocks) - 20} more")
    _print_override_summary(getattr(result, "waivers", ()))
    if debug:
        print(f"completed at {_wall_time()}")
        print(f"build dir: {result.build_dir}")
        if result.readme_path:
            print(f"readme: {result.readme_path}")
    if result.failed() and not result.dry_run:
        story_recovery = _failed_story_recovery_commands(
            target_dir,
            args.Target,
            failed_steps=result.failed(),
            repair_attempts=max(2, repair_attempts),
        )
        print()
        print(
            _render_build_failures(
                args.Target,
                failures or result.failed(),
                hint=BUILD_FAILURE_HINT,
                story_recovery=story_recovery,
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
    exit_code = result.exit_code()
    if exit_code and not result.dry_run:
        # A nonzero build states its cause on the error stream too. The console rendering above
        # is the operator's record; a harness that captured only stderr must still be told which
        # block failed and why, instead of inferring it from an exit code alone.
        from drydock.score import emit_failure

        if result.failed():
            emit_failure(
                f"build failed for {args.Target}: {len(result.failed())} step(s)",
                tuple(
                    f"{step.block_id} — {step.state}" + (f": {step.error}" if step.error else "")
                    for step in (failures or result.failed())
                ),
            )
        elif result.stalled():
            emit_failure(
                f"build stalled for {args.Target}: "
                f"{len(result.stalled_blocks)} block(s) outstanding and none could advance",
                tuple(result.stalled_blocks[:20]),
            )
        else:
            emit_failure(f"build did not complete for {args.Target}")
    return exit_code


def _build_running_command(args: argparse.Namespace) -> str:
    """Render the command and non-default build options for the Chair."""
    command = ["drydock", "build", args.Target]
    options: tuple[tuple[str, str, object], ...] = (
        ("--build-dir", "value", getattr(args, "build_dir", None)),
        ("--step", "value", getattr(args, "step", None)),
        ("--story", "value", getattr(args, "story", None)),
        ("--continue", "flag", getattr(args, "continue_", False)),
        ("--reset", "flag", getattr(args, "reset", False)),
        ("--ungate", "flag", getattr(args, "ungate", False)),
        ("--normalize-order", "flag", getattr(args, "normalize_order", False)),
        ("--dry-run", "flag", getattr(args, "dry_run", False)),
        ("--show-prompt", "flag", getattr(args, "show_prompt", False)),
        (
            "--repair-attempts",
            "value",
            getattr(args, "repair_attempts", None),
        ),
        ("--escalate-model", "value", getattr(args, "escalate_model", None)),
        ("--model", "value", getattr(args, "model", None)),
        ("--llm-provider", "value", getattr(args, "llm_provider", None)),
        ("--effort", "value", getattr(args, "effort", None)),
    )
    for option, kind, value in options:
        if kind == "flag" and value:
            command.append(option)
        elif kind == "value" and value is not None:
            # An unset ``--repair-attempts`` is ``None`` and is omitted here, so the echoed
            # command names only what the operator actually chose. The configured budget is not
            # echoed as a flag: it would freeze this run's value into a command that should keep
            # following the configuration.
            command.extend((option, str(value)))
    return " ".join(command)


def _reviewable_build_steps(target_dir: Path) -> list[tuple[str, str]]:
    from drydock.build_plan import parse_build_plan

    plan = parse_build_plan(target_dir / "MANIFEST.md")
    return [
        (block.block_id, block.name)
        for block in plan.blocks
        if block.block_type in {"story", "spike"} and block.state == "implemented"
    ]


def cmd_build_score(args: argparse.Namespace) -> int:
    from drydock.build_score import gate_label, score_target
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
    print(f"Completion gate: {gate_label(result.complete, result.attestations)}")
    print(f"Scorecard: {result.scorecard_path}")
    print(f"Evidence: {result.evidence_path}")
    for blocker in result.blockers:
        print(f"  BLOCKER: {blocker}")
    for attestation in result.attestations:
        print(f"  ATTESTATION REQUIRED: {attestation}")
    return result.exit_code()


_AC_GLYPH = {
    "PASS": ("✓", "32"),
    "FAIL": ("✗", "31"),
    "UNVERIFIED": ("—", "33"),
    "PREPASSED": ("~", "33"),
}


def _ac_mark(status: str) -> str:
    """Colored glyph plus padded status word. Color is dropped when the terminal will not
    render an escape sequence, so captured output and legacy consoles stay plain."""
    from drydock.console import color_enabled

    glyph, code = _AC_GLYPH.get(status, ("?", "0"))
    if color_enabled(sys.stdout):
        glyph = f"\033[{code}m{glyph}\033[0m"
    return f"{glyph} {status:<10}"


def cmd_score_ac(target: str, step: str | None = None) -> int:
    from drydock.config import require_target_dir
    from drydock.score import (
        PREPASSED,
        UNVERIFIED,
        ac_failure_lines,
        emit_failure,
        proof_coverage_lines,
        verify_acs,
    )

    target_dir = require_target_dir(target)
    report = verify_acs(target, target_dir, step_id=step)
    passed = sum(1 for v in report.verdicts if v.status == "PASS")
    failed = sum(1 for v in report.verdicts if v.status == "FAIL")
    unverified = sum(1 for v in report.verdicts if v.status == UNVERIFIED)
    prepassed = sum(1 for v in report.verdicts if v.status == PREPASSED)
    print()
    print(f"Acceptance verification: {target}  ({report.verified_at})")
    if report.scope:
        print(f"  Scope: {report.scope_name}  [{report.scope}]")
    counts = f"  PASS {passed}   FAIL {failed}   UNVERIFIED {unverified}"
    if prepassed:
        counts += f"   PREPASSED {prepassed}"
    print(f"{counts}   ({len(report.verdicts)} AC)")
    # Above the board, not below it: these files produced no verdicts, so nothing further down
    # the report mentions them at all.
    if report.defects:
        print()
        for message in report.defects:
            print(f"  WARNING  {message}")
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
        # The detail block states the assertion, the exit, and what the check itself reported.
        # It replaces the one-line evidence cell wherever it exists: that cell is a table entry
        # for SOUNDINGS.md, not a diagnosis an operator can act on.
        if verdict.detail:
            for line in verdict.detail:
                print(f"        {line}")
        else:
            for line in (verdict.evidence or "").strip().splitlines() or ["(no detail captured)"]:
                print(f"        {line}")
        print()
    # The board says which criteria are green. This says which of them are evidence.
    coverage = proof_coverage_lines(report)
    if coverage:
        print()
        for line in coverage:
            print(f"  {line}" if line else "")
    if report.wrote_soundings:
        print()
        print(f"Soundings: {report.soundings_path}")
    exit_code = report.exit_code()
    if exit_code:
        emit_failure(
            f"acceptance verification failed for {target}: {failed} of "
            f"{len(report.verdicts)} criteria",
            ac_failure_lines(report),
        )
    return exit_code


def _compact_clock(milliseconds: int) -> str:
    """Render a duration for a table column: ``7m 10s``, ``48s``, ``1h 03m``."""
    total = max(0, milliseconds) // 1000
    hours, rem = divmod(total, 3600)
    minutes, seconds = divmod(rem, 60)
    if hours:
        return f"{hours}h {minutes:02d}m"
    if minutes:
        return f"{minutes}m {seconds:02d}s"
    return f"{seconds}s"


def _rate(value: float | None) -> str:
    return "—" if value is None else f"{value * 100:.1f}%"


def _render_build_score(report) -> list[str]:
    """Render the post-build report. Pure formatting over an already-built report."""
    lines = [
        "",
        f"Build report: {report.target}",
        f"  evidence: {report.evidence_dir}",
        f"  usage:    {report.records_path}",
        "",
    ]
    if not report.blocks:
        lines.append("  No build evidence found. Run: drydock build " + report.target)
        return lines

    # Cached and uncached rather than total input: that is how the providers bill it.
    headers = ("Block", "AC", "Calls", "Cached", "Uncached", "Hit", "Output", "Time")
    rows: list[tuple[str, ...]] = []
    for block in report.blocks:
        mark = "✓" if block.verified else "✗"
        rows.append((
            f"{mark} {block.name}",
            f"{block.passed_checks}/{block.total_checks}",
            str(block.calls),
            f"{block.cached_input:,}",
            f"{block.fresh_input:,}",
            _rate(block.cache_hit_rate),
            f"{block.output:,}",
            _compact_clock(block.elapsed_ms),
        ))
    total_row = (
        "TOTAL",
        f"{report.passed_checks}/{report.total_checks}",
        str(report.calls),
        f"{report.cached_input:,}",
        f"{report.fresh_input:,}",
        _rate(report.cache_hit_rate),
        f"{report.output:,}",
        _compact_clock(report.elapsed_ms),
    )
    widths = [
        max(len(headers[i]), len(total_row[i]), *(len(row[i]) for row in rows))
        for i in range(len(headers))
    ]

    def _line(cells: tuple[str, ...]) -> str:
        # First column reads as a label; the numeric columns right-align so magnitudes compare.
        rendered = [cells[0].ljust(widths[0])]
        rendered += [cells[i].rjust(widths[i]) for i in range(1, len(cells))]
        return "  " + "  ".join(rendered).rstrip()

    lines.append(_line(headers))
    lines.append("  " + "─" * (sum(widths) + 2 * (len(widths) - 1)))
    lines.extend(_line(row) for row in rows)
    lines.append("  " + "─" * (sum(widths) + 2 * (len(widths) - 1)))
    lines.append(_line(total_row))
    lines.append("")

    verified = sum(1 for block in report.blocks if block.verified)
    summary = (
        f"  Blocks: {verified}/{len(report.blocks)} verified · "
        f"{report.first_call_blocks} on first call · {len(report.repaired_blocks)} repaired"
    )
    lines.append(summary)
    if report.models:
        lines.append(f"  Model:  {', '.join(report.models)}")
    lines.append(
        f"  Tokens: {report.cached_input:,} cached · {report.fresh_input:,} uncached · "
        f"{report.output:,} out"
    )

    # Every pass of any block that needed more than one, so a repair is legible without
    # opening the evidence: what it scored, and what changed between calls.
    if report.repaired_blocks:
        lines += ["", "  Repairs"]
        for block in report.repaired_blocks:
            lines.append(f"    {block.name} [{block.block_id}]")
            for attempt in block.attempts:
                score = (
                    f"{attempt.passed_checks}/{attempt.total_checks} AC"
                    if attempt.total_checks
                    else "no AC"
                )
                cases = (
                    f" · {attempt.passed_cases}/{attempt.total_cases} cases"
                    if attempt.passed_cases is not None and attempt.total_cases is not None
                    else ""
                )
                lines.append(
                    f"      {attempt.label:<14} {attempt.status:<7} {score}{cases} · "
                    f"{attempt.total_input:,} in · {_rate(attempt.cache_hit_rate)} hit · "
                    f"{_compact_clock(attempt.elapsed_ms)}"
                )
                if attempt.stop_reason:
                    lines.append(f"      {'':<14} stopped: {attempt.stop_reason}")

    failed = report.failed_blocks
    if failed:
        lines += ["", "  Not verified"]
        for block in failed:
            lines.append(f"    {block.name} [{block.block_id}] — {block.state or 'unknown state'}")
            if block.failed_check_ids:
                lines.append(f"      failing AC: {', '.join(block.failed_check_ids)}")
            if block.stop_reason:
                lines.append(f"      stopped: {block.stop_reason}")

    if report.missing_usage:
        lines += [
            "",
            f"  Note: {len(report.missing_usage)} execution(s) have no usage record; "
            "their tokens read as zero.",
        ]
    return lines


def cmd_score_build(target: str) -> int:
    """Print the deterministic post-build report. Reads evidence and usage logs only."""
    from drydock.build_report import build_score_report
    from drydock.config import get_workspace, require_target_dir
    from drydock.score import emit_failure

    target_dir = require_target_dir(target)
    report = build_score_report(
        target, target_dir, records_path=get_workspace() / "logs" / "llm.jsonl"
    )
    for line in _render_build_score(report):
        print(line)
    print()
    if not report.blocks:
        emit_failure(f"no build evidence for {target}", (f"run: drydock build {target}",))
        return 1
    if report.failed_blocks:
        emit_failure(
            f"{len(report.failed_blocks)} build block(s) unverified in {target}",
            tuple(
                f"{block.block_id} {block.name}: {block.state or 'not verified'}"
                + (
                    f"; failed: {', '.join(block.failed_check_ids)}"
                    if block.failed_check_ids
                    else ""
                )
                for block in report.failed_blocks
            ),
        )
        return 1
    return 0


def cmd_score_report(target: str) -> int:
    """Publish the Target's build receipt. Reads the journals and Target only; runs nothing."""
    from drydock.config import build_dir_for, get_workspace, require_target_dir
    from drydock.score_report import ReportError, write_report

    target_dir = require_target_dir(target)
    build_dir = build_dir_for(target)
    try:
        index = write_report(target, get_workspace(), target_dir, build_dir)
    except ReportError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(f"Receipt: {index}")
    print(f"Open with: file://{index}")
    return 0


def cmd_score_release(target: str) -> int:
    from drydock.config import (
        get_llm_provider,
        get_model,
        get_workspace,
        require_target_dir,
    )
    from drydock.quarterdeck_state import refresh_commanders_chair
    from drydock.score import emit_failure, score_release

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
    # The listing is the whole answer: every criterion and what was observed of it. A reader who
    # sees only the blockers cannot tell a project that failed one criterion from one that was
    # never built, and both are ordinary outcomes of this command.
    print(result.statement)
    print()
    print(f"Scorecard: {result.scorecard_path}")
    print(f"Evidence: {result.evidence_path}")
    for attestation in result.attestations:
        print(f"  MANUAL VERIFICATION: {attestation}")
    exit_code = result.exit_code()
    if exit_code:
        emit_failure(
            f"release gate {result.verdict} for {target}",
            result.blockers or (f"see {result.scorecard_path}",),
        )
    return exit_code


def cmd_score_spec(
    target: str,
    model: str | None = None,
    llm_provider: str | None = None,
    effort: str | None = None,
    debug: bool = False,
) -> int:
    """Audit imported raw specifications and print the report the operator acts on.

    Normal output is the inventory line and the findings table; ``--debug`` prints the full
    scorecard. Either way the complete report is written to the Target.
    """
    from drydock.config import (
        get_effort,
        get_llm_provider,
        get_model,
        get_workspace,
        require_target_dir,
    )
    from drydock.score_spec import render_console_report, score_spec

    target_dir = require_target_dir(target)
    result = score_spec(
        target,
        target_dir,
        model=get_model(model),
        effort=get_effort(effort),
        llm_provider=get_llm_provider(llm_provider),
        log_dir=get_workspace() / "logs",
        debug=debug,
    )
    if debug:
        sys.stdout.write(result.report)
    else:
        sys.stdout.write(render_console_report(result.inventory, result.findings))
    return result.exit_code()


def cmd_score_drydock(
    model: str | None = None,
    llm_provider: str | None = None,
    effort: str | None = None,
) -> int:
    """Adversarially assess Drydock itself and write a ranked feature plan.

    Unlike the other LLM-assisted commands this one does not fall back to the configured build
    model or provider: the assessment is a single deep reasoning pass, so the prompt's declared
    highest model and effort stand, and the provider that serves the model is pinned with it.
    ``--model``, ``--effort``, and ``--llm-provider`` override.
    """
    from drydock.config import get_workspace
    from drydock.paths import get_repo_root
    from drydock.score_drydock import score_drydock

    repo_root = get_repo_root()
    print("Adversarial self-assessment: drydock")
    result = score_drydock(
        model=model,
        effort=effort,
        llm_provider=llm_provider,
        log_dir=get_workspace() / "logs",
        repo_root=repo_root,
        on_text=_stream_status_only,
    )
    print()
    print(f"Assessment model: {result.review_model}")
    print(f"Features: {len(result.assessment.features)}")
    print(f"Project-type gaps: {len(result.assessment.project_type_gaps)}")
    print()
    for rank, feature in enumerate(result.assessment.features, start=1):
        print(
            f"  {rank:>2}. [{feature.feature_id}] impact {feature.impact:>2}/10  "
            f"complexity {feature.complexity:>2}/10  {feature.title}"
        )
    print()
    print(f"Index: {result.index_path}")
    print(f"Features: {result.planning_dir}")
    if result.archive_path:
        print(f"Archived previous plan: {result.archive_path}")
    return result.exit_code()


_BUILD_STATE_MARK = {
    "closed/verified": "[done]",
    "closed/implemented": "[built]",
    "implemented": "[review]",
    "pending": "[pending]",
    "blocked/questions": "[QUESTIONS]",
    "closed/failed": "[FAILED]",
}


def cmd_build_status(blueprint: str, target: str) -> int:
    from drydock.build_plan import load_target_plan
    from drydock.build_score import score_evidence_state
    from drydock.build_status import build_status
    from drydock.config import get_target_directory, require_target_dir
    from drydock.question_gates import synchronize_manifest_question_gates

    target_path = require_target_dir(target)
    synchronize_manifest_question_gates(target_path / "MANIFEST.md", target_path / "blueprint")
    plan = load_target_plan(target, get_target_directory())
    report = build_status(plan)

    reviewable = _reviewable_build_steps(target_path)
    if reviewable:
        print("Next: resolve legacy implemented steps by rebuilding or revising them")
    elif report.steps_implemented:
        print(f"Next: drydock verify {target}")
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
        group_kind = (
            "Feature" if group.feature is not None or group.group_id == "ungrouped" else "Block"
        )
        print(
            f"\n{group_kind}: {group.name}  [{group.group_id}]"
            f"   — {group.verified}/{group.total} stories done"
        )
        for step in group.steps:
            mark = _BUILD_STATE_MARK.get(step.block.state, step.block.state)
            if step.block.state == "closed/failed":
                arrow = "  <- resume (repairs in place)"
            elif step.block.state == "closed/implemented":
                arrow = "  <- verify"
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
        f"{report.steps_built} built (await verify), "
        f"{report.steps_implemented} in review, "
        f"{report.steps_pending} pending, "
        f"{report.steps_questions} blocked by questions, "
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


def _add_build_arguments(parser: argparse.ArgumentParser) -> None:
    """Add the operand arguments accepted by ``drydock build <Target>``.

    ``build`` retains its REMAINDER dispatcher so that its state subcommands and
    build operands can be selected at runtime.  Keep this declaration shared by
    the dispatcher parser and the parent command's help text: otherwise an
    accepted build option can silently disappear from ``drydock build --help``.
    """
    parser.add_argument("Target", metavar="<Target>")
    _add_build_options(parser)


def _add_build_options(parser: argparse.ArgumentParser) -> None:
    """Add build flags shared by the top-level dispatcher and operand parser."""
    parser.add_argument(
        "--build-dir",
        dest="build_dir",
        default=None,
        metavar="<path>",
        help="Directory where built code is written (overrides METADATA.md and config).",
    )
    parser.add_argument(
        "--step",
        dest="step",
        default=None,
        metavar="<id|name>",
        help="Build only the named MANIFEST block (a feature group, or a story/spike "
        "resolved to its containing block).",
    )
    parser.add_argument(
        "--story",
        dest="story",
        default=None,
        metavar="<id|name>",
        help="Build exactly one story/spike, even inside a feature group. "
        "Mutually exclusive with --step.",
    )
    parser.add_argument(
        "--continue",
        dest="continue_",
        action="store_true",
        help="Resume in place (the default): explicit alias for the default build behavior.",
    )
    parser.add_argument(
        "--reset",
        dest="reset",
        action="store_true",
        help="Discard prior work and rebuild clean. With --step/--story resets that block; "
        "with no selector resets every block and wipes the build directory.",
    )
    parser.add_argument(
        "--ungate",
        dest="ungate",
        action="store_true",
        help="Release prior acceptance-only failures as UNVERIFIED, then continue with the "
        "next buildable step.",
    )
    parser.add_argument(
        "--override",
        dest="override",
        action="store_true",
        help=OVERRIDE_HELP,
    )
    parser.add_argument(
        "--normalize-order",
        "--normalize_order",
        dest="normalize_order",
        action="store_true",
        help="Normalize MANIFEST group order before building.",
    )
    parser.add_argument(
        "--dry-run",
        dest="dry_run",
        action="store_true",
        help="Preview the next build block without invoking the LLM or writing files.",
    )
    parser.add_argument(
        "--show-prompt",
        dest="show_prompt",
        action="store_true",
        help="With --dry-run, print the full assembled prompt including file contents.",
    )
    parser.add_argument(
        "--repair-attempts",
        dest="repair_attempts",
        type=int,
        default=None,
        metavar="<n>",
        help=(
            "Repair passes after a failed block (0 disables; default "
            f"{DEFAULT_REPAIR_ATTEMPTS}, or 'drydock config set repair_attempts <n>')."
        ),
    )
    _add_bound_arguments(parser)
    parser.add_argument(
        "--escalate-model",
        dest="escalate_model",
        default=None,
        metavar="<model>",
        help="Model used on the final repair attempt "
        "(default: DRYDOCK_BUILD_ESCALATE_MODEL env or off).",
    )
    _add_llm_override_flags(parser)


def _build_operand_parser() -> argparse.ArgumentParser:
    """Return the parser for the operands of ``drydock build <Target>``."""
    parser = DrydockArgumentParser(
        prog="drydock build",
        description="Build or inspect build state.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    _add_build_arguments(parser)
    return parser


def _build_help_details() -> str:
    """Return the build operand help rendered from its actual parser."""
    parser = _build_operand_parser()
    return parser.format_help().partition("\n\n")[2].rstrip()


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
        help=(
            "Show detailed command output, DEBUG log messages, LLM execution "
            "diagnostics, and full tracebacks."
        ),
    )
    parser.add_argument(
        "--no-diagnose",
        action="store_true",
        default=False,
        help="Do not call the LLM to diagnose an opaque failure.",
    )
    # Console capability is detected per run and needs no flag. These override that decision
    # when the detection is wrong for a particular terminal; `drydock status console` reports
    # what was detected and why.
    parser.add_argument(
        "--glyphs",
        dest="glyphs",
        choices=GLYPH_TIERS,
        default=None,
        metavar="<tier>",
        help=("Override console detection: emoji (✅), text (✓), ascii (v), or auto (default)."),
    )
    parser.add_argument(
        "--ascii",
        dest="ascii",
        action="store_true",
        default=None,
        help="Override console detection: render plain ASCII.",
    )
    parser.add_argument(
        "--unicode",
        dest="ascii",
        action="store_false",
        default=None,
        help="Override console detection: keep Unicode glyphs.",
    )
    # Invocation-wide: stripped from argv before this parser runs, and declared here so the
    # top-level help documents what every command accepts.
    _add_llm_override_flags(parser)

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
    p_env = cfg_sub.add_parser(
        "env",
        help="Print resolved paths as shell KEY=value assignments.",
        description=(
            "drydock config env             — workspace, targets root, and build root\n"
            "drydock config env <Target>    — also that Target's directory and build directory\n"
            "\n"
            'Consume with: eval "$(drydock config env <Target>)"'
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p_env.add_argument("Target", metavar="<Target>", nargs="?", default=None)
    p_set = cfg_sub.add_parser("set", help="Set a configuration value.")
    # Derived from the config module's key map, never restated here: a hand-maintained copy
    # silently drops keys, and a key absent from this list is unsettable however correctly
    # ``config_set`` and ``config show`` handle it.
    p_set.add_argument("key", choices=list(settable_config_keys()))
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

    # ── uat ──────────────────────────────────────────────────────────────────
    p_uat = sub.add_parser(
        "uat",
        help="Build known project fixtures unattended in isolated run directories.",
        description=(
            "drydock uat                    — run every kit under uat/\n"
            "drydock uat <Project>          — run one kit\n"
            "drydock uat --report [<kit>]   — rebuild proof kits from completed runs\n"
            "drydock uat <Project> --stage <stage>\n"
            "                               — resume the newest run at <stage>\n"
            "\n"
            "A kit is uat/<Project>/: uat.json, its sources/ bundle, and its own runs/ history.\n"
            "Each kit runs in an isolated workspace from the explicit source bundle in uat.json.\n"
            "Ordered updates refresh that bundle, run refit --sources, and rebuild.\n"
            "Each child command's output streams to the console as it runs; --quiet reports\n"
            "only stage names. Complete output is preserved as evidence either way.\n"
            "The required test_command runs from the completed application directory.\n"
            "Acceptance and release scores are advisory and are recorded with token and time data.\n"
            "Each selected uat/<Project> repository is initialized when absent and committed "
            "before exit."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    _add_llm_override_flags(p_uat)
    p_uat.add_argument("Project", nargs="?", default=None, metavar="<Project>")
    p_uat.add_argument(
        "--uat-root",
        type=Path,
        default=None,
        metavar="<path>",
        help="Directory holding the kits (default: <workspace>/uat).",
    )
    p_uat.add_argument(
        "--report",
        nargs="?",
        const="",
        default=None,
        metavar="<kit>",
        help="Rebuild index.html and SHA256SUMS from completed runs (default: every kit).",
    )
    p_uat.add_argument(
        "--max-build-passes",
        type=int,
        default=25,
        metavar="<n>",
        help="Maximum build passes per initial or refit stage (default: 25).",
    )
    p_uat.add_argument(
        "--repair-attempts",
        dest="repair_attempts",
        type=int,
        default=None,
        metavar="<n>",
        help=(
            "Repairs one build block may spend "
            f"(default: {DEFAULT_REPAIR_ATTEMPTS}, or 'drydock config set repair_attempts <n>'). "
            "Consecutive passes without acceptance progress end a block before this bound."
        ),
    )
    _add_bound_arguments(p_uat)
    p_uat.add_argument(
        "--quiet",
        action="store_true",
        help="Report only stage names instead of streaming each child command's output.",
    )
    p_resume = p_uat.add_mutually_exclusive_group()
    p_resume.add_argument(
        "--stage",
        default=None,
        choices=("import", "analyze", "plan", "build", "refit", "test", "score"),
        metavar="<stage>",
        help=(
            "Resume an existing run at this stage, reusing everything the earlier attempt "
            "produced. Development affordance: a resumed run is not a clean-room measurement."
        ),
    )
    p_resume.add_argument(
        "--from-step",
        dest="from_step",
        type=int,
        default=None,
        metavar="<n>",
        help=(
            "Resume at the stage that owns recorded step <n>, named as the step table numbers "
            "it. Requires <Project>; list the steps with --steps."
        ),
    )
    p_uat.add_argument(
        "--steps",
        action="store_true",
        help="List the recorded steps of a run with the stage each resumes into, then exit.",
    )
    p_uat.add_argument(
        "--run",
        default=None,
        metavar="<run-id>",
        help="Run directory to resume (default: the newest). Requires --stage or --from-step.",
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
            "drydock status <Target> --check  — completion gate: exit 0/1/2\n"
            "drydock status <Target> --ready  — build-loop guard: exit 0 while buildable\n"
            "drydock status console           — terminal capability report and glyph samples"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    _add_llm_override_flags(p_status)
    p_status.add_argument(
        "--check",
        action="store_true",
        help="Exit 0 complete, 1 buildable work remains, 2 blocked (needs a human).",
    )
    p_status.add_argument(
        "--ready",
        action="store_true",
        help="Exit 0 while a build can advance the Target; use as a while-loop guard.",
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
            "drydock document assemble readme <Target>    — regenerate README.md\n\n"
            "Options for document <Target> and document assemble <Target>:\n"
            "  --theme <theme>          Documentation theme override.\n"
            "Options for document <Target> and document generate <Target>:\n"
            "  --model <model>          Override the LLM model.\n"
            "  --effort <level>         Override reasoning effort (low|medium|high|xhigh|max).\n"
            "  --llm-provider <provider>  Override the LLM provider (claude or codex)."
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
        help="PDF output path; implies --pdf. Defaults to the HTML path with .pdf.",
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
    # ── plan ──────────────────────────────────────────────────────────────────
    # Handles: plan <Target>
    #          plan verify <Target>
    #          plan repair <Target>
    p_plan = sub.add_parser(
        "plan",
        help="Create, verify, or repair an executable plan.",
        description=(
            "drydock plan <Target>          — create the Blueprint specs and MANIFEST.md\n"
            "drydock plan verify <Target>   — report acceptance criteria that cannot run\n"
            "                                   (deterministic, read-only, no LLM call)\n"
            "drydock plan repair <Target>   — one LLM pass making those criteria runnable\n\n"
            "verify is free and repair is not, so the intended workflow pays for repair only\n"
            "when it is needed:\n"
            "    drydock plan verify <Target> || drydock plan repair <Target>"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
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
    p_plan.add_argument("--override", action="store_true", help=OVERRIDE_HELP)
    p_plan.add_argument(
        "--continue-attempts",
        dest="continue_attempts",
        type=int,
        default=3,
        metavar="<n>",
        help="Consecutive retry allowance for malformed or no-progress Blueprint batches after "
        "TOPOLOGY.md is frozen (0 disables Stage 2; default 3).",
    )
    p_plan.add_argument("args", nargs=argparse.REMAINDER, metavar="[verify|repair] <Target>")

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
            "drydock build <Target> --ungate         — release acceptance-only failures as UNVERIFIED\n"
            "drydock build <Target> --reset         — reset all blocks + wipe build dir, then rebuild\n"
            "drydock build <Target> --step <id> --reset  — reset that block, then rebuild clean\n"
            "drydock build <Target> --normalize-order  — normalize MANIFEST order, then build\n"
            "drydock build <Target> --dry-run       — preview next build block without writes\n"
            "drydock build status <Target>   — show build state\n"
            "drydock build verify <Target> [<step-id>] — list or verify legacy implemented steps\n"
            "drydock build score <Target>    — generate SCORECARD.md"
        ),
        epilog="Build operands:\n" + _build_help_details(),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    # Declare build options on the dispatcher as well as in the REMAINDER operand parser. This
    # lets argparse consume a flag before the Target (``build --ungate Marina``); flags after the
    # Target remain in ``args`` and are parsed by ``_parse_build_args``.
    _add_build_options(p_build)
    p_build.add_argument("args", nargs=argparse.REMAINDER, metavar="[status|score] <Target>")

    # ── score ─────────────────────────────────────────────────────────────────
    # Handles: score spec <Target> (advisory), score ac <Target> (deterministic),
    # score release <Target> (LLM-assisted), score report <Target> (deterministic),
    # score drydock (LLM-assisted self-assessment of Drydock itself; no Target).
    p_score = sub.add_parser(
        "score",
        help="Audit specifications, verify acceptance, and judge release readiness.",
        description=(
            "drydock score spec <Target>             — audit imported raw specifications; writes\n"
            "                                            SPECIFICATION_SCORECARD.md\n"
            "drydock score ac <Target> [--step <id>]  — verify acceptance criteria (whole target,\n"
            "                                            or scoped to one feature/story), update Soundings\n"
            "drydock score build <Target>             — post-build report: acceptance, repairs, tokens,\n"
            "                                            cache hit rate (deterministic; reads logs only)\n"
            "drydock score release <Target>           — LLM release gate over Sea Trials; writes SCORECARD.md\n"
            "drydock score report <Target>            — publish the build receipt to\n"
            "                                            <build>/<Target>/drydock/index.html with its evidence\n"
            "drydock score drydock                    — adversarial self-assessment of Drydock; writes\n"
            "                                            ranked feature files to docs/drydock_planning/\n\n"
            "--step <id> is accepted only with score ac.\n"
            "--effort <low|medium|high|xhigh|max> applies to any LLM-assisted command."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p_score.add_argument(
        "args",
        nargs=argparse.REMAINDER,
        metavar="<spec|ac|build|release|report|drydock> [<Target>]",
    )

    # ── refit ─────────────────────────────────────────────────────────────────
    p_iter = sub.add_parser(
        "refit",
        help="Conform change tickets in blueprint/changes/ to the build process and update the manifest.",
    )
    _add_llm_override_flags(p_iter)
    p_iter.add_argument("Target", metavar="<Target>")
    p_iter.add_argument(
        "--sources",
        action="store_true",
        help="Route imported source changes into change tickets and Manifest stories.",
    )
    p_iter.add_argument(
        "--relineage",
        action="store_true",
        help="Rebuild LINEAGE.json from the Target's git history and attribute existing stories.",
    )

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
        help="Configured target name; omit to use the most recently updated target.",
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
    p_import.add_argument("Source", metavar="<Source>", nargs="?", default=None)
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
    p_import.add_argument(
        "--update",
        action="store_true",
        help="Refresh the previously imported source snapshot; takes no <Source>.",
    )

    return parser


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------


def _is_machine_readable_query(args: argparse.Namespace) -> bool:
    """True for stdout that a script consumes verbatim, which the masthead would corrupt.

    ``status --check``/``--ready`` emit a bare status token; ``config env`` emits shell
    assignments meant for ``eval``.
    """
    command = getattr(args, "command", None)
    if command == "config":
        return getattr(args, "config_command", None) == "env"
    if command != "status":
        return False
    trailing = set(getattr(args, "args", None) or []) & {"--check", "--ready"}
    return bool(getattr(args, "check", False) or getattr(args, "ready", False) or trailing)


def _dispatch_status(args: argparse.Namespace) -> int:
    # REMAINDER swallows flags that follow the Target, so --check/--ready work on either side.
    flags = {"--check", "--ready"}
    tokens = [token for token in args.args if token not in flags]
    trailing = set(args.args) & flags
    if tokens == ["console"]:
        # Reserved operand: no Target may be named `console`. It is a self-report about the
        # terminal, not about a Target, and needs to work before any workspace exists.
        return cmd_status_console()
    check = getattr(args, "check", False) or "--check" in trailing
    ready = getattr(args, "ready", False) or "--ready" in trailing
    if check and ready:
        raise UsageError("drydock status: --check and --ready are mutually exclusive.")
    if check or ready:
        gate = "--ready" if ready else "--check"
        if len(tokens) != 1:
            raise UsageError(f"Usage: drydock status <Target> {gate}")
        return cmd_status_ready(tokens[0]) if ready else cmd_status_check(tokens[0])
    if len(tokens) == 0:
        return cmd_status_current()
    elif len(tokens) == 1:
        return cmd_status_blueprint_target(tokens[0], tokens[0])
    else:
        raise UsageError("Usage: drydock status [<Target>] [--check | --ready]")


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
    return _build_operand_parser().parse_args(tokens)


def _dispatch_build(args: argparse.Namespace) -> int:
    tokens = args.args
    if not tokens:
        not_implemented("build")
        raise AssertionError("unreachable")

    # ``build`` uses REMAINDER so its operands can select the state subcommands. That means
    # argparse cannot see ``--help`` once it occurs after ``build``. Handle help explicitly before
    # interpreting the first operand, making all of these equivalent:
    # ``drydock build --help``, ``drydock build Marina --help``, and ``drydock build --help Marina``.
    if "--help" in tokens or "-h" in tokens:
        _build_operand_parser().print_help()
        return 0

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
        # Options before the Target are consumed by the dispatcher; options after it are parsed
        # above. Preserve the latter when both forms are present, while carrying the former into
        # the build namespace.
        option_names = {
            "build_dir": ("--build-dir",),
            "step": ("--step",),
            "story": ("--story",),
            "continue_": ("--continue",),
            "reset": ("--reset",),
            "ungate": ("--ungate",),
            "override": ("--override",),
            "normalize_order": ("--normalize-order", "--normalize_order"),
            "dry_run": ("--dry-run",),
            "show_prompt": ("--show-prompt",),
            "repair_attempts": ("--repair-attempts",),
            "escalate_model": ("--escalate-model",),
            "model": ("--model",),
            "llm_provider": ("--llm-provider",),
            "effort": ("--effort",),
        }
        for key, names in option_names.items():
            if any(
                token == name or token.startswith(name + "=") for token in tokens for name in names
            ):
                continue
            value = getattr(args, key, None)
            if isinstance(value, bool):
                setattr(build_args, key, getattr(build_args, key, False) or value)
            elif value is not None:
                setattr(build_args, key, value)
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


def _reject_score_drydock_operands(rest: list[str]) -> None:
    """``drydock score drydock`` takes no operands; the LLM overrides are invocation-wide."""
    if not rest:
        return
    from drydock.config import EFFORT_LEVELS

    raise UsageError(
        "Usage: drydock score drydock [--effort <"
        + "|".join(EFFORT_LEVELS)
        + ">] [--model <model>] [--llm-provider <provider>]"
    )


def _dispatch_score(args: argparse.Namespace) -> int:
    tokens = args.args
    first = tokens[0] if tokens else ""
    if first == "drydock":
        # ``--model`` / ``--effort`` / ``--llm-provider`` are stripped from argv as
        # invocation-wide overrides before this command's operands are parsed, so they arrive
        # on the namespace, never in ``tokens``. Anything left is a Target, which this
        # sub-verb does not take.
        _reject_score_drydock_operands(tokens[1:])
        return cmd_score_drydock(
            model=getattr(args, "model", None),
            llm_provider=getattr(args, "llm_provider", None),
            effort=getattr(args, "effort", None),
        )
    if first == "spec" and len(tokens) == 2:
        target = tokens[1]
        rc = cmd_score_spec(
            target,
            model=getattr(args, "model", None),
            llm_provider=getattr(args, "llm_provider", None),
            effort=getattr(args, "effort", None),
            debug=bool(getattr(args, "debug", False)),
        )
        from drydock.config import record_activity

        record_activity("score spec", target, target)
        return rc
    if first == "ac":
        target, step = _parse_score_ac_args(tokens[1:])
        rc = cmd_score_ac(target, step=step)
        from drydock.config import record_activity

        record_activity("score ac", target, target)
        return rc
    if first == "build" and len(tokens) == 2:
        rc = cmd_score_build(tokens[1])
        from drydock.config import record_activity

        record_activity("score build", tokens[1], tokens[1])
        return rc
    if first == "release" and len(tokens) == 2:
        rc = cmd_score_release(tokens[1])
        from drydock.config import record_activity

        record_activity("score release", tokens[1], tokens[1])
        return rc
    if first == "report" and len(tokens) == 2:
        return cmd_score_report(tokens[1])
    raise UsageError(
        "Usage: drydock score <spec|ac|build|release|report> <Target> | drydock score drydock"
    )


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
        if args.config_command == "env":
            return cmd_config_env(args)
        parser.parse_args(["config", "--help"])
        return 0

    if command == "init":
        return cmd_init(args)

    if command == "uat":
        return cmd_uat(args)

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
        # ``verify`` and ``repair`` inspect a plan rather than producing one, so neither counts as
        # activity on the Target; only plan creation does.
        if rc == 0 and not getattr(args, "plan_sub_verb", ""):
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
def _log_command_history(
    args: argparse.Namespace,
    argv: list[str] | None,
    rc: int,
    *,
    transcript: Path | None = None,
    elapsed_ms: int | None = None,
) -> None:
    """Append one history line for any non-report command. Must never raise to the caller."""
    from drydock.logging import command_logging_enabled

    if not command_logging_enabled():
        return
    if os.environ.get("DRYDOCK_PARENT_TRANSCRIPT"):
        return  # implementation command invoked beneath a recorded top-level command
    command = getattr(args, "command", None)
    if command is None:
        return  # bare `drydock` / help text
    if command in {"status", "validate"}:
        return  # pure report
    if command == "config" and getattr(args, "config_command", None) in {"show", "env"}:
        return  # pure report

    from drydock.config import append_command_history, get_workspace

    workspace = get_workspace()
    tokens = argv if argv is not None else sys.argv[1:]
    cmd_str = "drydock " + " ".join(tokens)
    # The transcript basename is ``<stamp>_<target>_<command>_<llm>``, so its leading component
    # is the stamp every artifact this command wrote is named from. Recording it makes the
    # journal joinable to the files on disk without matching on a minute-resolution clock.
    stamp = transcript.name.partition("_")[0] if transcript is not None else ""
    relative = ""
    if transcript is not None:
        try:
            relative = transcript.relative_to(workspace).as_posix()
        except ValueError:
            relative = transcript.name
    append_command_history(
        workspace,
        cmd_str,
        target=_log_target(args),
        return_code=rc,
        argv=list(tokens),
        stamp=stamp,
        transcript=relative,
        elapsed_ms=elapsed_ms,
    )


def _render_analyze_blockers(target: str, blockers_path) -> str:
    """Format analyze's open blockers as one closing banner the Commander must clear.

    Reuses ``analyze._parse_blocker_records`` so each blocker shows its id, title, and the
    Commander-owned resolution to author, then states the exact re-run command.
    """
    from drydock.analyze import _parse_blocker_records

    width = 72
    border = "=" * width
    raw = None
    if blockers_path is not None:
        try:
            raw = Path(blockers_path).read_text(encoding="utf-8")
        except OSError:
            raw = None
    records = _parse_blocker_records(raw)
    count = len(records) or 1
    plural = "blocker" if count == 1 else "blockers"
    lines = [border, f"BLOCKER — FIX TO PROCEED: {target}  ({count} {plural})", border]
    for record in records:
        lines += ["", f"  {record.blocker_id}: {record.title}"]
        for line in textwrap.wrap(
            record.original_text or "",
            width=width - 4,
            initial_indent="    ",
            subsequent_indent="    ",
        ):
            lines.append(line)
    lines += [
        "",
        "  Fix to proceed",
        "    1. Edit BLOCKERS.md and enter each Commander Resolution.",
        f"    2. Re-run: drydock analyze {target}",
        "",
        f"  Or review in QuarterDeck: drydock run quarterdeck {target}",
        border,
    ]
    return "\n".join(lines)


def _failed_story_recovery_commands(
    target_dir: Path,
    target: str,
    *,
    failed_steps,
    repair_attempts: int,
) -> tuple[str, ...]:
    """Return ordered story-resume commands for a failed multi-story feature.

    A feature build can fail because several child stories fail their own acceptance
    criteria.  Resuming each failed story narrows the next agent context.  The
    Manifest is the authority for both the failed child state and dependency order.
    A lone failed story keeps the existing feature-level recovery hint; a command
    for it would be redundant.
    """
    from drydock.build_plan import parse_build_plan

    plan = parse_build_plan(target_dir / "MANIFEST.md")
    blocks_by_id = {block.block_id: block for block in plan.blocks}
    failed_feature_ids = {
        step.block_id for step in failed_steps if getattr(step, "block_type", "") == "feature"
    }
    failed_feature_ids.update(
        block.parent
        for step in failed_steps
        if (block := blocks_by_id.get(step.block_id)) is not None and block.parent
    )
    if not failed_feature_ids:
        return ()

    candidates = [
        block
        for block in plan.blocks
        if (
            block.block_type == "story"
            and block.parent in failed_feature_ids
            and block.state == "closed/failed"
        )
    ]
    if len(candidates) < 2:
        return ()

    by_id = {block.block_id: block for block in candidates}
    ordered: list = []
    remaining = list(candidates)
    while remaining:
        ready = next(
            (
                block
                for block in remaining
                if all(
                    dep not in by_id or dep in {item.block_id for item in ordered}
                    for dep in block.depends
                )
            ),
            None,
        )
        # Preserve Manifest order if a malformed cyclic internal dependency exists.
        selected = ready or remaining[0]
        ordered.append(selected)
        remaining.remove(selected)

    return tuple(
        f"drydock build {target} --story {block.block_id} --repair-attempts {repair_attempts}"
        for block in ordered
    )


_SUITE_TALLY_RE = re.compile(r"(?P<passed>\d+)\s+passed,\s+(?P<failed>\d+)\s+failed", re.I)


def _suite_tally(check) -> tuple[int, int] | None:
    """Extract a conformance-suite pass/fail tally from one acceptance result."""
    matches = list(_SUITE_TALLY_RE.finditer(f"{check.stdout}\n{check.stderr}"))
    if not matches:
        return None
    match = matches[-1]
    return int(match.group("passed")), int(match.group("failed"))


def _failure_check_lines(check) -> list[str]:
    """Render the concise assertion and output tail needed to continue a failed story."""
    lines = [f"      AC {check.check_id} — {check.intent or check.check_id}"]
    if check.error:
        lines.append(f"        {check.error}")
    for label, stream in (("stdout", check.stdout), ("stderr", check.stderr)):
        tail = [line.rstrip() for line in stream.splitlines() if line.strip()][-4:]
        if not tail:
            continue
        lines.append(f"        {label}:")
        lines.extend(f"          {line}" for line in tail)
    return lines


def _failure_assertion(check) -> str:
    """Return the assertion statement captured from a failed acceptance run."""
    lines = [line.strip() for line in (check.stderr or "").splitlines() if line.strip()]
    return next(
        (line for line in reversed(lines) if line.startswith("assert ")),
        "(assertion not captured)",
    )


def _failure_exception(check) -> str:
    """Return the final exception line captured from a failed acceptance run."""
    lines = [line.strip() for line in (check.stderr or "").splitlines() if line.strip()]
    return next(
        (
            line
            for line in reversed(lines)
            if re.match(r"^[A-Za-z_][A-Za-z0-9_.]*(Error|Exception)\b", line)
        ),
        "(exception not captured)",
    )


def _failure_stop_lines(step) -> list[str]:
    """Explain a repair loop that ended below its call budget.

    A run that reports "call 2 of up to 4" and then stops reads as an abandoned build unless
    the reason is stated where the failure is read.
    """
    reason = getattr(step, "stop_reason", "")
    if not reason:
        return []
    used = getattr(step, "calls_used", 0)
    budget = getattr(step, "calls_budget", 0)
    spent = f"{used} of {budget} calls · " if used and budget else ""
    lines = [f"    stopped early: {spent}{reason}"]
    if reason == "acceptance criterion reported defective":
        lines.append(
            "      repair the assertion in the Blueprint specification — a rerun cannot "
            "rewrite a staged acceptance asset"
        )
    return lines


def _failure_progress_lines(step) -> list[str]:
    """Show measured acceptance movement, including suite-level tallies when available."""
    checks = step.owned_acceptance or step.acceptance
    quarantined = getattr(step, "quarantined_acceptance", ())
    if not checks:
        return _quarantine_lines(quarantined)
    baseline = {
        check.check_id: check for check in (step.owned_pre_acceptance or step.pre_acceptance)
    }
    final_passed = sum(1 for check in checks if check.passed)
    baseline_passed = sum(
        1
        for check in checks
        if (prior := baseline.get(check.check_id)) is not None and prior.passed
    )
    lines = [f"    acceptance: {final_passed}/{len(checks)} passing"]
    if baseline:
        movement = "improved" if final_passed > baseline_passed else "unchanged"
        lines[-1] += f" · baseline {baseline_passed}/{len(checks)} · {movement}"
    for check in checks:
        tally = _suite_tally(check)
        if tally is None:
            continue
        prior = baseline.get(check.check_id)
        previous_tally = _suite_tally(prior) if prior is not None else None
        detail = f"    {check.check_id}: {tally[0]} passed, {tally[1]} failed"
        if previous_tally is not None:
            pass_delta = tally[0] - previous_tally[0]
            fail_delta = tally[1] - previous_tally[1]
            if pass_delta or fail_delta:
                detail += f" · change +{pass_delta} passed, {fail_delta:+d} failed"
            else:
                detail += " · unchanged from baseline"
        lines.append(detail)
    return lines + _quarantine_lines(quarantined)


def _quarantine_lines(quarantined) -> list[str]:
    """Name criteria excluded from grading so the tally above is not read as the whole story."""
    if not quarantined:
        return []
    lines = [
        f"    quarantined: {len(quarantined)} criteri"
        f"{'on' if len(quarantined) == 1 else 'a'} unsatisfiable by construction · not graded"
    ]
    lines.extend(f"      {entry.rendered}" for entry in quarantined)
    lines.append("      repair the assertion in the Blueprint specification to grade it")
    return lines


#: A build agent has no write authority over ``blueprint/``, so when it concludes the criterion is
#: wrong rather than the code, the only thing it can do is say so and stop. These are the phrasings
#: it says it with; matching any of them routes the operator to the command that can act.
_BLUEPRINT_REPAIR_SIGNALS = (
    "blueprint repair",
    "acceptance criteria require blueprint",
    "no code change is appropriate",
)


def _requests_blueprint_repair(step) -> bool:
    """True when the agent reported that the specification, not the product, is at fault."""
    text = f"{getattr(step, 'agent_blockers', '') or ''} {getattr(step, 'agent_summary', '') or ''}"
    return any(signal in text.lower() for signal in _BLUEPRINT_REPAIR_SIGNALS)


def _acceptance_recovery_lines(
    target: str, *, indent: str, blueprint_repair: bool = False
) -> list[str]:
    """The continue command for an acceptance failure.

    A story that fails acceptance is left ``closed/failed``, which is selectable: a plain
    ``drydock build <Target>`` continues the build and resumes that story in place.

    When the agent reported that the criterion is at fault, rebuilding is the wrong move and
    costs a full pass to learn nothing — the agent already refused to change correct code. The
    repair route is offered first in that case, because it is the only one with write authority
    over ``blueprint/``.
    """
    lines: list[str] = []
    if blueprint_repair:
        lines += [
            f"{indent}The agent reports the acceptance criteria are at fault, not the code.",
            f"{indent}Run: drydock plan verify {target}",
            f"{indent}  to confirm which criteria cannot run, then:",
            f"{indent}Run: drydock plan repair {target}",
            f"{indent}  to repair them in one pass. Rebuilding first repeats the same failure.",
        ]
    return lines + [
        f"{indent}Run: drydock build {target}",
        f"{indent}  to continue the build. This story resumes where it left off and is",
        f"{indent}  retried against the checks it failed.",
    ]


def _render_build_failures(
    target: str, steps, *, hint: str, story_recovery: tuple[str, ...] = ()
) -> str:
    """Format every failed build step as one closing block.

    The build prints this after the result line so the failure is the last thing on screen. It
    carries the cause, the nested acceptance detail, and the identifiers needed to reproduce.
    """
    width = 72
    border = "=" * width
    plural = "step" if len(steps) == 1 else "steps"
    lines = [border, f"BUILD FAILED: {target}  ({len(steps)} {plural})", border]
    seen: set[str] = set()
    for step in steps:
        if step.block_id in seen:
            continue
        seen.add(step.block_id)
        block_id = getattr(step, "container_block_id", None) or step.block_id
        block_name = getattr(step, "container_name", None) or step.name
        lines += ["", "  Failure", "    Provenance", f"      Target: {target}"]
        lines.append(f"      Block: {block_name} [{block_id}]")
        lines.append(f"      Story: {step.name} [{step.block_id}]")
        lines.append(f"    Cause: {step.error or 'build failed'}")
        if step.agent_summary:
            lines += [
                "    agent summary:",
                *textwrap.wrap(
                    step.agent_summary,
                    width=width - 6,
                    initial_indent="      ",
                    subsequent_indent="      ",
                ),
            ]
        lines.extend(_failure_stop_lines(step))
        lines.extend(_failure_progress_lines(step))
        failed_checks = tuple(
            check for check in (step.owned_acceptance or step.acceptance) if not check.passed
        )
        if failed_checks:
            lines.append("    Assertion")
            lines.append("      Acceptance checks:")
            for check in failed_checks:
                lines += [
                    f"      Acceptance: {check.check_id}",
                    f"      Intent: {check.intent or check.check_id}",
                    f"      Source: {check.source}",
                    f"      Code: {_failure_assertion(check)}",
                    "    Result",
                    "      Process exit code: "
                    f"{check.return_code if check.return_code is not None else '(not reported)'}",
                    f"      Error: {_failure_exception(check)}",
                ]
                if check.stderr.strip():
                    lines.append("      Stderr:")
                    lines.extend(
                        f"        {line}" for line in check.stderr.strip().splitlines()[-4:]
                    )
                # Retain the compact suite tally used by existing operators and scripts.
                tally = _suite_tally(check)
                if tally is not None:
                    lines.append(f"      Result tally: {tally[0]} passed, {tally[1]} failed")
            lines.append("    Recovery")
            lines.extend(
                _acceptance_recovery_lines(
                    target, indent="      ", blueprint_repair=_requests_blueprint_repair(step)
                )
            )
        if step.agent_blockers:
            lines += [
                "    agent blockers:",
                *textwrap.wrap(
                    step.agent_blockers,
                    width=width - 6,
                    initial_indent="      ",
                    subsequent_indent="      ",
                ),
            ]
        if not failed_checks:
            for line in (step.failure_detail or "").strip().splitlines():
                lines.append(f"    {line}")
        if step.execution_id:
            lines.append(f"    execution: {step.execution_id}")
        if step.evidence_path is not None:
            lines.append(f"    evidence: {step.evidence_path}")
    acceptance_failed = any(
        any(not check.passed for check in (step.owned_acceptance or step.acceptance))
        for step in steps
    )
    lines += ["", "  Next"]
    if acceptance_failed:
        lines += _acceptance_recovery_lines(
            target,
            indent="    ",
            blueprint_repair=any(_requests_blueprint_repair(step) for step in steps),
        )
    else:
        lines += textwrap.wrap(
            hint, width=width - 4, initial_indent="    ", subsequent_indent="    "
        )
    if story_recovery and not acceptance_failed:
        lines += ["", "  Story recovery (dependency order)"]
        lines += [
            f"    {index}. {command}" for index, command in enumerate(story_recovery, start=1)
        ]
    lines.append(border)
    return "\n".join(lines)


def _render_recorded_error(record, *, target: str | None = None) -> str:
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
            if paragraph.startswith((" ", "\t")):
                # An indented line is structure or code — a failure chain, an assertion, a
                # runner's tally. Reflowing it to the terminal width destroys the very thing
                # the reader came for: the assertion arrives split across two lines with its
                # regex broken at a space. Emit it as authored and let the terminal wrap.
                wrapped.append(pad + paragraph)
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

    plan_challenge_failed = (
        record.command == "plan" and record.classification == "plan conflict challenge failed"
    )
    heading = (
        f"PLAN FAILED  ·  {record.classification}"
        if plan_challenge_failed
        else f"POST-LLM FAILURE  ·  {record.command}  ·  {record.classification}"
    )
    lines = [border, heading, border, ""]
    if plan_challenge_failed:
        lines += [indent + f"Classification: {record.classification}", ""]
    lines += _block(record.detail.strip())
    if record.recovery.strip():
        lines += ["", indent + "Recovery"]
        lines += _block(record.recovery.strip(), pad=indent + "  ")
    if plan_challenge_failed:
        errors_display = "ERRORS.md"
        if target:
            from drydock.config import get_target_directory

            errors_display = str(get_target_directory() / target / "ERRORS.md")
        lines += [
            "",
            f"{indent}ERRORS.md: {errors_display}",
            f"{indent}Initial execution: {record.execution_id or '-'}",
            f"{indent}Challenge execution: {record.challenge_execution_id or '-'}",
        ]
        if target:
            lines += [
                f"{indent}QuarterDeck: drydock run quarterdeck {target}",
                f"{indent}Retry: drydock plan {target}",
            ]
    lines += ["", border]
    return "\n".join(lines)


def _render_plan_deferred(result, *, target: str) -> str:
    """Render a prominent, actionable handoff for a model-declared planning conflict."""
    width = 72
    border = "=" * width

    def _block(text: str, pad: str = "  ") -> list[str]:
        wrapped: list[str] = []
        for paragraph in text.splitlines() or [""]:
            if not paragraph.strip():
                wrapped.append("")
                continue
            wrapped.extend(
                textwrap.wrap(
                    paragraph.rstrip(),
                    width=width - len(pad),
                    initial_indent=pad,
                    subsequent_indent=pad,
                    break_long_words=False,
                    break_on_hyphens=False,
                )
                or [pad + paragraph]
            )
        return wrapped

    record = result.error_record
    lines = [
        border,
        "PLAN DEFERRED",
        border,
        "",
        f"  Classification: {record.classification}",
        "",
        "  Diagnostic",
    ]
    lines += _block(result.detail, pad="    ")
    lines += ["", "  Required action"]
    lines += _block(record.recovery, pad="    ")
    lines += [
        "",
        "  No model-generated Blueprint or Manifest artifacts were written.",
        f"  ERRORS.md: {result.errors_path}",
        f"  QuarterDeck: drydock run quarterdeck {target}",
        f"  Retry: drydock plan {target}",
        f"  Initial execution: {result.initial_execution_id or '-'}",
        f"  Challenge execution: {result.challenge_execution_id or '-'}",
        "",
        border,
    ]
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

        # The Target is on the command line even when the command collects it with REMAINDER,
        # so a standoff diagnosis is written against that Target's workspace. The working
        # directory is a fallback for a command that names no Target at all.
        target = _log_target(args)
        target_dir = get_target_directory() / target if target else Path.cwd()
        if not target_dir.is_dir():
            target_dir = Path.cwd()
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


# Leading positional sub-verbs of the REMAINDER commands; they precede the Target token.
_LOG_TARGET_SUBVERBS = frozenset({
    "status",
    "score",
    "ac",
    "release",
    "generate",
    "assemble",
    "readme",
})

# Options accepted inside a REMAINDER command's operands. A value-taking option hides the
# next token, so both must be stepped over to reach the Target; a switch hides only itself.
_LOG_VALUE_OPTIONS = frozenset({
    "--build-dir",
    "--effort",
    "--escalate-model",
    "--llm-provider",
    "--model",
    "--repair-attempts",
    "--step",
    "--story",
    "--theme",
})
_LOG_SWITCH_OPTIONS = frozenset({
    "--check",
    "--continue",
    "--dry-run",
    "--normalize-order",
    "--normalize_order",
    "--ready",
    "--reset",
    "--show-prompt",
})


def _log_target(args: argparse.Namespace) -> str:
    """Resolve the Target for a log filename before the command parses its own arguments.

    ``build``, ``status``, ``score``, and ``document`` collect their operands with
    ``argparse.REMAINDER``, so they expose no ``Target`` attribute here and their transcripts
    would otherwise be named without a target. Options are stepped over in either order, so
    ``build --step x <Target>`` and ``build <Target> --step x`` both resolve. Scanning stops at
    an unrecognized option, whose value cannot be distinguished from a Target: omitting the
    component is better than naming the transcript after the wrong thing.
    """
    declared = getattr(args, "Target", None)
    if declared:
        return str(declared)
    tokens = list(getattr(args, "args", None) or [])
    index = 0
    while index < len(tokens):
        token = tokens[index]
        if token.startswith("-"):
            option = token.split("=", 1)[0]
            if "=" in token or option in _LOG_SWITCH_OPTIONS:
                index += 1
                continue
            if option in _LOG_VALUE_OPTIONS:
                index += 2
                continue
            return ""
        if token not in _LOG_TARGET_SUBVERBS:
            return token
        index += 1
    return ""


# Commands that always reach a model.
_LLM_COMMANDS = frozenset({"analyze", "plan", "refit", "survey", "import", "uat"})

# Commands whose sub-verb decides. ``build status`` reports state, ``build`` and ``build score``
# call a model; ``score ac`` verifies acceptance deterministically, ``score release`` judges with
# a model; ``document assemble`` renders what is already written, ``document generate`` writes it.
_LLM_SUB_COMMANDS = {"rigging": "compact", "prompt": "review", "run": "quarterdeck"}
_DETERMINISTIC_OPERANDS = {"build": {"status"}, "document": {"assemble"}}
_LLM_OPERANDS = {"score": {"release", "drydock"}}


def _invocation_uses_llm(args: argparse.Namespace) -> bool:
    """Whether this invocation reaches a model, deciding if its log names a provider.

    ``drydock run quarterdeck`` counts: the QuarterDeck itself calls no model, but the commands
    it starts append to its transcript, so that transcript holds provider-bound work.
    """
    command = getattr(args, "command", None) or ""
    if command in _LLM_COMMANDS:
        return True
    if command in _LLM_SUB_COMMANDS:
        for attribute in ("rigging_command", "prompt_command", "run_command"):
            value = getattr(args, attribute, None)
            if value:
                return value == _LLM_SUB_COMMANDS[command]
        return False
    operand = next(
        (token for token in (getattr(args, "args", None) or []) if not token.startswith("-")),
        "",
    )
    if command in _DETERMINISTIC_OPERANDS:
        return operand not in _DETERMINISTIC_OPERANDS[command]
    if command in _LLM_OPERANDS:
        return operand in _LLM_OPERANDS[command]
    return False


def _log_llm(args: argparse.Namespace) -> str:
    """Resolve the LLM provider this invocation will use, for the log filename.

    An LLM-assisted command records the provider in force — the ``--llm-provider`` override when
    given, otherwise the configured default — so its transcript names the same provider as the
    evidence files beneath it. A deterministic command names none: no model runs, so claiming one
    in the filename would be false.
    """
    if not _invocation_uses_llm(args):
        return ""
    override = getattr(args, "llm_provider", None)
    if not override:
        # ``score`` declares no override flag of its own; the operand list still carries one.
        tokens = list(getattr(args, "args", None) or [])
        for index, token in enumerate(tokens):
            if token.startswith("--llm-provider="):
                override = token.split("=", 1)[1]
                break
            if token == "--llm-provider" and index + 1 < len(tokens):
                override = tokens[index + 1]
                break
    try:
        from drydock.config import get_llm_provider

        return get_llm_provider(override)
    except Exception:  # noqa: BLE001 - an unnamable provider must not cost us the transcript
        return ""


def _command_log_name(args: argparse.Namespace) -> str:
    parts = [getattr(args, "command", None) or "drydock"]
    for attribute in ("config_command", "rigging_command", "prompt_command", "run_command"):
        value = getattr(args, attribute, None)
        if value:
            parts.append(value)
    return " ".join(parts)


#: Commands that only observe a Target. They neither create its Git store nor checkpoint it: a
#: query must not mutate what it reports on, and the store's one-line banners would corrupt the
#: machine-readable stdout of ``status --check``/``--ready`` that scripts consume verbatim.
_READ_ONLY_COMMANDS = frozenset({"status"})


def _target_repository(args: argparse.Namespace) -> Path | None:
    """Resolve an existing Target workspace for invocation-level Git checkpoints."""
    if getattr(args, "command", None) in _READ_ONLY_COMMANDS:
        return None
    target = _log_target(args)
    if not target:
        return None
    from drydock.config import get_target_directory

    target_dir = get_target_directory() / target
    return target_dir if target_dir.is_dir() else None


def _prepare_target_repository(args: argparse.Namespace) -> None:
    """Upgrade an existing Target before commands that may need Git history."""
    target_dir = _target_repository(args)
    if target_dir is None:
        return
    from drydock.target_git import commit_target, setup_target

    if setup_target(target_dir):
        commit_target(target_dir, "Initialize project workspace")


def _commit_target_repository(args: argparse.Namespace) -> None:
    """Checkpoint all Target workspace changes made by one command."""
    target_dir = _target_repository(args)
    if target_dir is None:
        return
    from drydock.target_git import commit_target

    command = _command_log_name(args)
    commit_target(target_dir, f"Complete drydock {command}")


def main(argv: list[str] | None = None) -> None:
    from drydock.console import configure_stdio

    # Encoding is settled before anything is written, so a console that cannot carry Drydock's
    # glyphs degrades to ASCII instead of failing partway through a command.
    configure_stdio()
    parser = _build_parser()
    raw_argv = argv if argv is not None else sys.argv[1:]
    try:
        normalized_argv, global_overrides = _extract_global_overrides(raw_argv)
    except UsageError as exc:
        # Invocation-wide flags are read before the parser and before logging exists, so
        # their rejections need the same clean usage report the parsed commands get.
        print(f"error: {exc}", file=sys.stderr)
        sys.exit(2)
    args = parser.parse_args(normalized_argv)
    for key, value in global_overrides.items():
        if key == "debug":
            args.debug = bool(getattr(args, "debug", False) or value)
        elif getattr(args, key, None) is None:
            setattr(args, key, value)
    glyphs = getattr(args, "glyphs", None)
    if glyphs is None and getattr(args, "ascii", None) is not None:
        glyphs = "ascii" if args.ascii else "emoji"
    if glyphs is not None:
        os.environ["DRYDOCK_GLYPHS"] = glyphs
        os.environ["DRYDOCK_ASCII"] = "1" if glyphs == "ascii" else "0"
    # Invocation-wide, and published to the environment whether it was chosen or detected, so
    # every Drydock subprocess and LLM runner started by this command renders the same way. The
    # child's own stdout is a pipe, so left to itself it would resolve a different tier.
    os.environ["DRYDOCK_GLYPHS"] = configure_stdio()
    if getattr(args, "effort", None):
        # ``--effort`` is invocation-wide: publish it as the configured effort so every
        # LLM-assisted command, and any Drydock subprocess it starts, resolves the same
        # level without threading the flag through each capability signature.
        os.environ["DRYDOCK_EFFORT"] = args.effort
    debug = getattr(args, "debug", False)
    if debug:
        os.environ["DRYDOCK_DEBUG"] = "1"
    else:
        os.environ.pop("DRYDOCK_DEBUG", None)

    command_logging = None
    inherited_transcript = os.environ.get("DRYDOCK_PARENT_TRANSCRIPT")
    try:
        from drydock.config import get_workspace
        from drydock.logging import command_logging_enabled, setup_command_logging

        if command_logging_enabled():
            log_dir = get_workspace() / "logs"
            command_logging = setup_command_logging(
                log_dir,
                _command_log_name(args),
                stdout=sys.stdout,
                target=_log_target(args),
                llm=_log_llm(args),
                debug=debug,
            )
            if not inherited_transcript:
                # The LLM runner and any commands it starts inherit this process environment.
                # One user command therefore has one transcript and history entry.
                os.environ["DRYDOCK_PARENT_TRANSCRIPT"] = str(command_logging.transcript_path)
        logger.info("command: %s", " ".join(sys.argv if argv is None else argv))
    except Exception:
        pass  # log setup failure must not prevent the command from running

    exit_code = 0
    started = time.monotonic()
    stdout_context = (
        redirect_stdout(command_logging.stdout) if command_logging is not None else nullcontext()
    )
    try:
        with stdout_context:
            # The masthead is standard for every command and prints on stdout (status, not an
            # error). Emitting it inside the redirect keeps the transcript an exact copy of stdout.
            # The machine-readable status gates (--check/--ready) are consumed by scripts, so they
            # stay masthead-free: their stdout is a single status token or nothing.
            if not _is_machine_readable_query(args):
                print(f"Drydock {__version__}  {__copyright__}")
            try:
                _prepare_target_repository(args)
                exit_code = _dispatch(args, parser)
                _commit_target_repository(args)
            except UsageError as exc:
                print(f"error: {exc}", file=sys.stderr)
                exit_code = 2
            except RecordedError as exc:
                print(
                    _render_recorded_error(exc.record, target=getattr(args, "Target", None)),
                    file=sys.stderr,
                )
                exit_code = 1
                deterministic_validation = (
                    exc.record.phase == "post-output validation"
                    or "validation failed" in exc.record.classification.lower()
                )
                if not deterministic_validation:
                    _standoff_diagnosis(args, argv, record=exc.record)
            except DrydockError as exc:
                print(f"error: {exc}", file=sys.stderr)
                if debug:
                    from drydock.manifest import ManifestError

                    if isinstance(exc, ManifestError):
                        traceback.print_exc()
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

            if not inherited_transcript:
                # Child processes need the inherited transcript only while the top-level
                # command runs. Clear it before recording that top-level command itself.
                os.environ.pop("DRYDOCK_PARENT_TRANSCRIPT", None)
            try:
                _log_command_history(
                    args,
                    argv,
                    exit_code,
                    transcript=(
                        command_logging.transcript_path if command_logging is not None else None
                    ),
                    elapsed_ms=int((time.monotonic() - started) * 1000),
                )
            except Exception:
                pass  # history logging must never change the command's outcome
    finally:
        if command_logging is not None:
            command_logging.close()
        if not inherited_transcript:
            os.environ.pop("DRYDOCK_PARENT_TRANSCRIPT", None)
        os.environ.pop("DRYDOCK_DEBUG", None)

    sys.exit(exit_code)

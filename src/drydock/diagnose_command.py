"""``drydock diagnose`` — explain why the latest run stopped, and offer to stop it recurring.

The command is three things in order, and the order matters. It prints what Drydock already
knows, for free, before spending anything. It then makes exactly one model call. It then asks the
operator, one amendment at a time, whether to apply what came back.

Every exit says what to do next. That is the contract this command is held to: an operator who
runs it and is left holding a report with no idea what happens now has not been helped, however
accurate the report was.
"""

from __future__ import annotations

import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from drydock.diagnose_apply import Outcome, resolve
from drydock.diagnose_console import (
    BOLD,
    DIM,
    GREEN,
    INDENT,
    RED,
    YELLOW,
    Style,
    render_banner,
    render_findings,
    render_ladder_lines,
    render_report_paths,
)
from drydock.diagnose_evidence import BLUEPRINT_PREFIX, collect
from drydock.diagnose_report import diagnose_run, write_report
from drydock.errors import UsageError

#: Printed when the operator has to do something before this command can work.
NEXT_STEP = "Next: {command}"


@dataclass(frozen=True)
class Result:
    """What the command did, so the CLI can report it without re-deriving anything."""

    exit_code: int
    report_path: Path | None = None
    outcome: Outcome | None = None


def run(
    target: str = "",
    *,
    run_stamp: str = "",
    mode: str = "confirm",
    llm: str | None = None,
    model: str | None = None,
    runner: Callable[..., object] | None = None,
    confirm: Callable[[str], bool] | None = None,
    out: Callable[[str], None] = print,
    style: Style | None = None,
) -> Result:
    """Diagnose a Target's latest run.

    ``mode`` is ``"confirm"``, ``"apply"``, or ``"none"``; see :func:`drydock.diagnose_apply.resolve`.
    ``runner`` and ``confirm`` are injected so tests spend nothing and touch no terminal;
    ``style`` defaults to what stdout supports.
    """
    from drydock.config import get_target_directory, get_workspace

    workspace = get_workspace()
    targets_root = get_target_directory()
    target = target or _last_target(targets_root)
    if not target:
        out("No Target to diagnose.")
        out(NEXT_STEP.format(command="drydock status"))
        return Result(exit_code=2)

    target_dir = targets_root / target
    if not target_dir.is_dir():
        out(f"Target '{target}' does not exist under {targets_root}.")
        out(NEXT_STEP.format(command=f"drydock init {target}"))
        return Result(exit_code=2)

    style = style or Style.detect()
    bundle = collect(target, workspace, target_dir, run=run_stamp)
    headline = (
        bundle.stop.headline if bundle.stop else f"Drydock recorded no live failure for {target}"
    )
    out(render_banner(target, headline, bundle.stop is not None, style))
    out("")
    out(render_ladder_lines(bundle.ladder, style))
    out("")

    if not bundle.commands and not any(row.state != "not run" for row in bundle.ladder):
        out(f"Target '{target}' has recorded no commands, so there is nothing to diagnose.")
        out(NEXT_STEP.format(command=f"drydock analyze {target}"))
        return Result(exit_code=2)

    reason = _provider_unavailable(llm)
    if reason:
        out(reason)
        out(NEXT_STEP.format(command="drydock config set llm-provider <name>"))
        return Result(exit_code=2)

    out(style.rule("Diagnosing"))
    try:
        diagnosis = diagnose_run(bundle, llm=llm, model=model, runner=runner)
    except Exception as error:  # noqa: BLE001 — a failed call still owes the operator a next step
        out(INDENT + style.paint(f"✗ Diagnosis could not run: {error}", RED, BOLD))
        _next(out, style, f"drydock diagnose {target}")
        return Result(exit_code=1)

    written = write_report(bundle, diagnosis)
    report_path = written.markdown
    out("")
    out(render_findings(bundle, diagnosis, style))
    out("")
    out(render_report_paths(written.markdown, written.html, style))

    if not diagnosis.ok:
        out("")
        out(
            INDENT
            + style.paint(
                "✗ Diagnosis incomplete — the model's answer did not satisfy the output contract.",
                RED,
                BOLD,
            )
        )
        _next(out, style, f"drydock diagnose {target}")
        return Result(exit_code=1, report_path=report_path)

    if not diagnosis.amendments:
        out("")
        out(
            INDENT
            + style.paint(
                "No amendments proposed."
                if not diagnosis.unapplicable
                else _unapplicable_line(diagnosis),
                DIM,
            )
        )
        return Result(exit_code=_verdict(bundle), report_path=report_path)

    if mode == "confirm" and not _interactive(confirm):
        out("")
        out(
            f"{INDENT}{len(diagnosis.amendments)} amendment(s) proposed; this session cannot prompt."
        )
        out(f"{INDENT}They are recorded in {target_dir / 'DECISIONS.json'}.")
        _next(out, style, f"drydock diagnose {target} --apply")
        outcome = resolve(diagnosis.amendments, target_dir, mode="none", report_path=report_path)
        return Result(exit_code=1, report_path=report_path, outcome=outcome)

    outcome = resolve(
        diagnosis.amendments,
        target_dir,
        mode=mode,
        confirm=confirm,
        report_path=report_path,
        style=style,
    )
    rebuild = _rebuild_repaired_blueprints(outcome, target_dir)
    command = _report_outcome(
        outcome, target, target_dir, report_path, out, rebuild, style, unreviewed=mode == "apply"
    )
    _commit_repairs(outcome, target_dir, out, style)
    if command:
        _next(out, style, command)
    return Result(exit_code=_verdict(bundle), report_path=report_path, outcome=outcome)


def parse_mode(*, apply_all: bool, no_apply: bool) -> str:
    """Translate the two flags into one mode, rejecting the contradictory pair."""
    if apply_all and no_apply:
        raise UsageError("--apply and --no-apply cannot be used together.")
    if apply_all:
        return "apply"
    if no_apply:
        return "none"
    return "confirm"


def _verdict(bundle) -> int:
    """``0`` when the run has no live failure, ``1`` when it does."""
    return 1 if bundle.stop is not None else 0


def _rebuild_repaired_blueprints(outcome: Outcome, target_dir: Path) -> tuple[str, ...]:
    """Reset every Manifest block that consumes a repaired Blueprint; return the reset ids.

    A repaired Blueprint's ``_compact.md`` derivative is deleted: build never regenerates an
    existing compact, so a later consumer would otherwise read the unrepaired text.
    """
    from drydock.config import blueprint_dir_for
    from drydock.refit import reset_blueprint_consumers

    names = [
        amendment.file.removeprefix(BLUEPRINT_PREFIX)
        for amendment in outcome.applied
        if amendment.file.startswith(BLUEPRINT_PREFIX)
    ]
    if not names:
        return ()
    blueprint_dir = blueprint_dir_for(target_dir)
    for name in names:
        (blueprint_dir / f"{Path(name).stem}_compact.md").unlink(missing_ok=True)
    resets = reset_blueprint_consumers(target_dir / "MANIFEST.md", blueprint_dir, names)
    return tuple(dict.fromkeys(block_id for reset in resets for block_id in reset.reset_ids))


def _commit_repairs(
    outcome: Outcome, target_dir: Path, out: Callable[[str], None], style: Style
) -> None:
    """Checkpoint applied repairs in the Target repository as their own commit."""
    if not outcome.applied:
        return
    from drydock.target_git import commit_target

    summary = "; ".join(amendment.summary for amendment in outcome.applied)
    commit = commit_target(target_dir, f"Apply drydock diagnose repairs: {summary}", quiet=True)
    if commit:
        out(
            f"{INDENT}{style.paint('✓', GREEN)} Committed repairs to the Target repository as {commit}."
        )


def _report_outcome(
    outcome: Outcome,
    target: str,
    target_dir: Path,
    report_path: Path,
    out: Callable[[str], None],
    rebuild: tuple[str, ...] = (),
    style: Style | None = None,
    *,
    unreviewed: bool = False,
) -> str:
    """Print what happened to each amendment; return the next command, or ``""`` for none."""
    style = style or Style()
    out("")
    out(style.rule("Outcome"))
    if outcome.applied:
        out(
            f"{INDENT}{style.paint('✓', GREEN)} Applied {len(outcome.applied)} amendment(s) to "
            f"{', '.join(outcome.changed_files)}."
        )
        if unreviewed:
            out(
                f"{INDENT}{style.paint('•', YELLOW)} Logged them for review in "
                f"{target_dir / 'DECISIONS.json'}."
            )
    if rebuild:
        out(
            f"{INDENT}{style.paint('✓', GREEN)} Reset {len(rebuild)} Manifest block(s) to pending "
            "for rebuild:"
        )
        for line in style.wrap(", ".join(rebuild) + ".", first=INDENT * 3):
            out(style.paint(line, DIM))
    for amendment, error in outcome.failed:
        out(f"{INDENT}{style.paint('✗', RED)} Could not apply '{amendment.summary}': {error}")
    if outcome.declined:
        out(
            f"{INDENT}{style.paint('•', YELLOW)} Recorded {len(outcome.declined)} declined "
            f"amendment(s) in {target_dir / 'DECISIONS.json'}."
        )
        return f"drydock diagnose {target} --apply"
    if rebuild:
        return f"drydock build {target}"
    if not outcome.applied:
        out(f"{INDENT}Nothing changed. The report stands at {report_path}.")
    return ""


def _next(out: Callable[[str], None], style: Style, command: str) -> None:
    """The closing line of every exit that leaves work to do."""
    out("")
    out(INDENT + style.paint(NEXT_STEP.format(command=command), BOLD))


def _unapplicable_line(diagnosis) -> str:
    count = len(diagnosis.unapplicable)
    return (
        f"No amendments could be offered: {count} proposal(s) did not verify against the "
        "current files. See the report's Not Offered section."
    )


def _interactive(confirm: Callable[[str], bool] | None) -> bool:
    """Whether this session can ask a human. An injected confirmer always can."""
    return confirm is not None or sys.stdin.isatty()


def _provider_unavailable(llm: str | None = None) -> str:
    """The reason no model call can be made, or ``""`` when one can.

    Drydock always resolves *a* provider — the config default stands in when none is set — so
    the failure worth catching here is the CLI agent not being installed. Discovering that
    after assembling a prompt would report it as a diagnosis failure rather than a setup one.
    """
    import shutil

    try:
        from drydock.config import get_llm_provider

        provider = get_llm_provider(llm)
    except Exception as error:  # noqa: BLE001 — a bad provider setting is a setup problem
        return str(error)
    if shutil.which(provider) is None:
        return f"The '{provider}' CLI agent is not installed or not on PATH."
    return ""


def _last_target(targets_root: Path) -> str:
    """The Target to diagnose when the operator named none.

    The last Target a command touched, falling back to the most recently modified Target
    directory. Resolution never guesses between equals: with no recorded activity and no
    Targets on disk, it returns nothing and the caller reports that.
    """
    from drydock.config import get_last_activity

    recorded = (get_last_activity().get("target") or "").strip()
    if recorded and (targets_root / recorded).is_dir():
        return recorded
    if not targets_root.is_dir():
        return ""
    candidates = [path for path in targets_root.iterdir() if path.is_dir()]
    if not candidates:
        return ""
    return max(candidates, key=lambda path: path.stat().st_mtime).name

"""Confirm and apply the amendments a diagnosis proposed.

Approval is per amendment. A diagnosis that proposes three corrections is three questions, not
one, because an operator who agrees with two of them should not have to refuse all three to
decline the third.

Declined amendments become recommended decisions. Important amendments applied under delegated
``--apply`` authority are disclosed for later review; routine repairs remain report annotations.
Neither kind of applied repair requires a Commander response before execution continues.

A non-interactive session declines everything. Guessing a human's answer to "may I edit your
Compass" is not a default this command gets to have.
"""

from __future__ import annotations

import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from drydock.decisions import Decision, DecisionOption, load_decisions, write_decisions
from drydock.diagnose_console import Style, render_amendment
from drydock.patch import Amendment

#: How a declined amendment is filed. ``recommended`` is the status Drydock already uses for a
#: proposal awaiting a Commander, so a diagnosis's leftovers appear beside every other one.
DECISION_ORIGIN = "diagnose"
DECISION_STATUS = "recommended"
DECISION_TYPE = "text"

Confirm = Callable[[str], bool]


@dataclass(frozen=True)
class Outcome:
    """What happened to the proposed amendments."""

    applied: tuple[Amendment, ...] = ()
    declined: tuple[Amendment, ...] = ()
    failed: tuple[tuple[Amendment, str], ...] = ()
    review_error: str = ""

    @property
    def changed_files(self) -> tuple[str, ...]:
        seen: list[str] = []
        for amendment in self.applied:
            if amendment.file not in seen:
                seen.append(amendment.file)
        return tuple(seen)


def resolve(
    amendments: Sequence[Amendment],
    target_dir: Path,
    *,
    mode: str = "confirm",
    confirm: Confirm | None = None,
    report_path: Path | None = None,
    style: Style | None = None,
) -> Outcome:
    """Apply, decline, or ask about each amendment, then record what was declined.

    ``mode`` is ``"confirm"`` (ask per amendment), ``"apply"`` (apply all), or ``"none"``
    (decline all). ``confirm`` is injected so tests never touch a terminal; it receives the
    rendered amendment card, which ends in the question.
    """
    if not amendments:
        return Outcome()

    ask = confirm if confirm is not None else _terminal_confirm
    style = style or Style.detect()
    applied: list[Amendment] = []
    declined: list[Amendment] = []
    failed: list[tuple[Amendment, str]] = []

    for index, amendment in enumerate(amendments, start=1):
        if mode == "none":
            declined.append(amendment)
            continue
        if mode == "confirm" and not ask(
            render_amendment(index, len(amendments), amendment, style)
        ):
            declined.append(amendment)
            continue
        error = apply_one(amendment, target_dir)
        if error:
            failed.append((amendment, error))
        else:
            applied.append(amendment)

    if declined or failed:
        record(
            [*declined, *(item for item, _ in failed)],
            target_dir,
            report_path=report_path,
        )
    review_error = ""
    if mode == "apply":
        review_error = record_unreviewed(
            [item for item in applied if item.importance == "important"],
            target_dir,
            report_path=report_path,
        )
    return Outcome(
        applied=tuple(applied),
        declined=tuple(declined),
        failed=tuple(failed),
        review_error=review_error,
    )


def apply_one(amendment: Amendment, target_dir: Path) -> str:
    """Apply one amendment to its file. Returns an error string, or ``""`` on success.

    The diff is re-verified against the file as it stands now, not as it stood when the
    diagnosis read it. An earlier amendment in the same run may have moved the lines this one
    expects, and a stale application would corrupt a file the operator owns.
    """
    path = target_dir / amendment.file
    try:
        current = path.read_text(encoding="utf-8")
    except OSError as error:
        return f"cannot read {amendment.file}: {error}"
    updated = amendment.apply_to(current)
    if updated is None:
        return f"the diff no longer applies to {amendment.file}"
    if amendment.file.startswith("blueprint/"):
        from drydock.diagnose_repair import validate_acceptance_repair

        error = validate_acceptance_repair(current, updated, path.name)
        if error:
            return f"acceptance repair did not validate: {error}"
    try:
        path.write_text(updated, encoding="utf-8", newline="\n")
    except OSError as error:
        return f"cannot write {amendment.file}: {error}"
    return ""


def record(
    amendments: Sequence[Amendment], target_dir: Path, *, report_path: Path | None = None
) -> None:
    """File declined amendments as recommended decisions, preserving what is already there.

    Recording is never a failure mode: a diagnosis that could not write its leftovers has still
    written its report, and losing the command's real output to a bookkeeping error helps nobody.
    """
    if not amendments:
        return
    path = target_dir / "DECISIONS.json"
    try:
        existing = load_decisions(path)
        known = {decision.id for decision in existing}
        fresh = [
            _as_decision(amendment, report_path)
            for amendment in amendments
            if _decision_id(amendment) not in known
        ]
        if fresh:
            write_decisions(path, (*existing, *fresh))
    except OSError:
        return


def record_unreviewed(
    amendments: Sequence[Amendment], target_dir: Path, *, report_path: Path | None = None
) -> str:
    """File amendments applied without review, replacing any earlier proposal of the same change.

    The record carries no Commander answer: an unreviewed change is not a Commander decision, so
    it must never reach a prompt as one.
    """
    if not amendments:
        return ""
    path = target_dir / "DECISIONS.json"
    try:
        fresh = {
            _decision_id(amendment): _as_applied_decision(amendment, report_path)
            for amendment in amendments
        }
        kept = tuple(decision for decision in load_decisions(path) if decision.id not in fresh)
        write_decisions(path, (*kept, *fresh.values()))
    except OSError as error:
        return str(error)
    return ""


def _as_applied_decision(amendment: Amendment, report_path: Path | None) -> Decision:
    report = f" Report: {report_path}" if report_path else ""
    return Decision(
        id=_decision_id(amendment),
        type=DECISION_TYPE,
        severity="material",
        origin=DECISION_ORIGIN,
        blueprint=amendment.file,
        story=None,
        status=DECISION_STATUS,
        archived=False,
        title=f"Applied without review: {amendment.summary}",
        description=f"drydock diagnose --apply changed {amendment.file}. {amendment.why.strip()}{report}",
        options=(),
        system_choice="apply",
    )


def _as_decision(amendment: Amendment, report_path: Path | None) -> Decision:
    source = f"\n\nProposed by drydock diagnose: {report_path}" if report_path else ""
    return Decision(
        id=_decision_id(amendment),
        type=DECISION_TYPE,
        severity="low",
        origin=DECISION_ORIGIN,
        blueprint=amendment.file,
        story=None,
        status=DECISION_STATUS,
        archived=False,
        title=amendment.summary,
        description=f"{amendment.why}{source}\n\n{amendment.diff.strip()}",
        options=(
            DecisionOption(value="apply", label=f"Apply the diff to {amendment.file}"),
            DecisionOption(value="decline", label="Leave the file unchanged"),
        ),
        system_choice="apply",
    )


def _decision_id(amendment: Amendment) -> str:
    """A stable id, so re-running a diagnosis does not file the same proposal twice."""
    slug = "".join(
        character if character.isalnum() else "-" for character in amendment.summary.lower()
    )
    return f"diagnose-{amendment.file.lower().removesuffix('.md')}-{slug.strip('-')[:60]}"


def _terminal_confirm(question: str) -> bool:
    """Ask at the terminal. A session with no terminal answers no.

    The card is written through ``sys.stdout`` and only its last line goes to ``input``: on a
    terminal ``input`` writes its prompt past the glyph-tier wrapper, so the prompt stays ASCII.
    An interrupted prompt is also no: the operator who hits Ctrl-C wants the command to stop
    changing their files, not to fall through to the next question.
    """
    if not sys.stdin.isatty():
        return False
    card, _, prompt = question.rpartition("\n")
    try:
        if card:
            sys.stdout.write(card + "\n")
            sys.stdout.flush()
        return input(prompt).strip().lower() in {"y", "yes"}
    except (EOFError, KeyboardInterrupt):
        return False

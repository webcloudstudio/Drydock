"""The deterministic half of ``drydock diagnose``: where the run stands, and what stopped it.

Everything here is computed from files Drydock already writes, so it runs before any model call
and costs nothing. It is also the part an operator reads first, which is why it prints before the
diagnosis rather than inside the report.

``PROJECT_STATUS.jsonl`` is the ladder. Its states are already the workflow's vocabulary and are
already three-valued: a state passed, failed, or was never established. There is no fourth
"unknown" state to render — an absent row means the stage was not run, which is a fact, not a
gap in the evidence.

The stop classification reuses the categories ``build_run._classify_failure`` writes into the
recorded failure detail. A run stopped by a provider rate limit says so deterministically; the
model is never asked to identify what Drydock already recorded.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from drydock.project_status import (
    LABEL_LADDER,
    StatusEntry,
    latest_per_label,
    read_status,
)

#: Rendered state markers. Fixed width so the ladder columns align without padding logic.
PASS_MARK = "[OK]  "
FAIL_MARK = "[FAIL]"
NOT_RUN_MARK = "[--]  "

#: Failure categories Drydock records itself, longest first so ``provider rate limit`` is not
#: shadowed by ``provider error``. Matched against the recorded detail of the stopping state.
KNOWN_CLASSIFICATIONS = (
    "dependency legitimacy gate failed",
    "execution environment unavailable",
    "programmatic acceptance failed",
    "context/token limit",
    "execution timed out",
    "provider rate limit",
    "LLM execution failed",
    "provider error",
)

#: A stage retried more than once and still failing is the shape an operator most often
#: misreads as a product defect. The report names it explicitly rather than leaving the
#: attempt count to be interpreted.
RETRY_NOTE = "retried {attempts} times"


@dataclass(frozen=True)
class LadderRow:
    """One workflow state as the console and the report render it."""

    label: str
    #: ``"pass"``, ``"fail"``, or ``"not run"``. Never anything else.
    state: str
    at: str = ""
    attempts: int = 0
    detail: str = ""
    #: Short deterministic annotation, e.g. ``"12 stories"``. Supplied by the evidence
    #: collector, which is the only part of diagnose that reads Target artifacts.
    note: str = ""

    @property
    def failed(self) -> bool:
        return self.state == "fail"

    @property
    def retried(self) -> bool:
        """Whether this state consumed more than one attempt before being recorded."""
        return self.attempts > 1


@dataclass(frozen=True)
class StopPoint:
    """Where the run stopped and, when Drydock recorded it, why.

    ``classification`` is empty when the recorded detail matches no category Drydock writes.
    That is not a defect in the evidence: an operator error or a product test failure has no
    provider-level category, and inventing one would be a guess.
    """

    label: str
    classification: str = ""
    detail: str = ""
    retried: bool = False
    attempts: int = 1

    @property
    def headline(self) -> str:
        """The one-line verdict printed under the copyright banner."""
        if not self.label:
            return "Drydock recorded no failure"
        if self.classification:
            return f"Drydock failed at {self.label} — {self.classification}"
        return f"Drydock failed at {self.label}"


def build_ladder(target_dir: Path, notes: Mapping[str, str] | None = None) -> tuple[LadderRow, ...]:
    """Render every workflow state, in ladder order, including the ones never reached.

    States absent from ``PROJECT_STATUS.jsonl`` are reported as ``not run`` rather than
    omitted: an operator diagnosing a stopped run needs to see how far the ladder should have
    gone, not only how far it got.
    """
    notes = notes or {}
    standing = latest_per_label(read_status(target_dir))
    rows: list[LadderRow] = []
    for label in LABEL_LADDER:
        entry = standing.get(label)
        if entry is None:
            rows.append(LadderRow(label=label, state="not run", note=notes.get(label, "")))
            continue
        rows.append(
            LadderRow(
                label=label,
                state="pass" if entry.passed else "fail",
                at=entry.at,
                attempts=entry.attempts,
                detail=entry.detail,
                note=notes.get(label, ""),
            )
        )
    return tuple(rows)


def stop_point(target_dir: Path) -> StopPoint | None:
    """The state the workflow stopped on, or ``None`` when nothing failed."""
    return stop_point_of(read_status(target_dir))


def stop_point_of(entries: Sequence[StatusEntry]) -> StopPoint | None:
    """The stop derived from status entries, split out so it is testable without a Target.

    The stop is the *highest* failed rung, not the lowest. A lower failure with a passing rung
    above it was already answered — ``PLAN CREATED`` failing and ``PLAN REPAIRED`` passing is
    the repair working, not two defects — so reporting it as the stop sends the operator to
    fix something that is no longer broken. :func:`superseded_failures` names those separately.
    """
    remaining = [entry for entry in entries if entry in _live_failures(entries)]
    if not remaining:
        return None
    failed = max(remaining, key=lambda entry: LABEL_LADDER.index(entry.label))
    return StopPoint(
        label=failed.label,
        classification=classify(failed.detail),
        detail=failed.detail,
        retried=failed.attempts > 1,
        attempts=failed.attempts,
    )


def superseded_failures(entries: Sequence[StatusEntry]) -> tuple[StatusEntry, ...]:
    """Failed states that a later passing state has already answered.

    These are the run's built-in false positives. An operator reading the ladder sees `[FAIL]`
    and reasonably concludes there is work to do; the report says plainly that there is not.
    """
    live = _live_failures(entries)
    return tuple(entry for entry in entries if not entry.passed and entry not in live)


def _live_failures(entries: Sequence[StatusEntry]) -> tuple[StatusEntry, ...]:
    """Failed states with no passing state above them on the ladder."""
    ranked = sorted(entries, key=lambda entry: LABEL_LADDER.index(entry.label))
    highest_pass = max(
        (LABEL_LADDER.index(entry.label) for entry in ranked if entry.passed),
        default=-1,
    )
    return tuple(
        entry
        for entry in ranked
        if not entry.passed and LABEL_LADDER.index(entry.label) > highest_pass
    )


def classify(detail: str) -> str:
    """The category Drydock recorded for a failure, or ``""`` when it recorded none."""
    haystack = (detail or "").lower()
    for category in KNOWN_CLASSIFICATIONS:
        if category.lower() in haystack:
            return category
    return ""


def render_ladder(rows: Sequence[LadderRow]) -> str:
    """The console ladder: one fixed-width line per workflow state."""
    width = max((len(row.label) for row in rows), default=0)
    lines: list[str] = []
    for row in rows:
        if row.state == "pass":
            mark = PASS_MARK
        elif row.state == "fail":
            mark = FAIL_MARK
        else:
            mark = NOT_RUN_MARK
        annotations = [part for part in (_clock(row.at), row.note) if part]
        if row.retried:
            annotations.append(RETRY_NOTE.format(attempts=row.attempts))
        if row.state == "not run":
            annotations = ["not run"]
        trailing = "   ".join(annotations)
        lines.append(f"  {mark} {row.label.ljust(width)}   {trailing}".rstrip())
    return "\n".join(lines)


def _clock(at: str) -> str:
    """``2026-08-21T18:44:02.113+00:00`` rendered as ``2026-08-21 18:44``.

    A malformed or absent instant renders as nothing rather than raising: the ladder's job is
    to show the state, and a state with an unreadable timestamp is still a state.
    """
    if not at or "T" not in at:
        return ""
    date, _, rest = at.partition("T")
    return f"{date} {rest[:5]}" if len(rest) >= 5 else date

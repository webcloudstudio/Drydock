"""The deterministic half of ``drydock diagnose``: where the run stands, and what stopped it.

Everything here is computed from files Drydock already writes, so it runs before any model call
and costs nothing. It is also the part an operator reads first, which is why it prints before the
diagnosis rather than inside the report.

The ladder is reported at milestone granularity — INIT, ANALYZE, PLAN, BUILD, SCORE — because
that is the lifecycle an operator thinks in, and because it is what makes supersession correct.
``PLAN CREATED`` failing and ``PLAN REPAIRED`` passing is one milestone that succeeded on the
second attempt, not a defect and a fix. :mod:`drydock.project_status` owns that rollup; this
module renders it and names what the rollup hid.

The stop classification reuses the categories ``build_run._classify_failure`` writes into the
recorded failure detail. A run stopped by a provider rate limit says so deterministically; the
model is never asked to identify what Drydock already recorded.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from drydock.project_status import (
    StatusEntry,
    answered,
    milestone_of,
    milestone_states,
    read_status,
    standing_state,
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
    """One milestone as the console and the report render it."""

    milestone: str
    #: ``"pass"``, ``"fail"``, or ``"not run"``. Never anything else.
    state: str
    #: The ladder state that speaks for this milestone, e.g. ``PLAN REPAIRED`` for ``PLAN``.
    label: str = ""
    at: str = ""
    attempts: int = 0
    detail: str = ""
    #: Short deterministic annotation, e.g. ``"12 stories"``. Supplied by the evidence
    #: collector, which is the only part of diagnose that reads Target artifacts.
    note: str = ""
    #: States inside this milestone that the authoritative one superseded.
    answered: tuple[StatusEntry, ...] = ()

    @property
    def failed(self) -> bool:
        return self.state == "fail"

    @property
    def retried(self) -> bool:
        """Whether this milestone consumed more than one attempt before being recorded."""
        return self.attempts > 1


@dataclass(frozen=True)
class StopPoint:
    """Where the run stopped and, when Drydock recorded it, why.

    ``classification`` is empty when the recorded detail matches no category Drydock writes.
    That is not a defect in the evidence: an operator error or a product test failure has no
    provider-level category, and inventing one would be a guess.
    """

    milestone: str
    label: str
    classification: str = ""
    detail: str = ""
    retried: bool = False
    attempts: int = 1

    @property
    def headline(self) -> str:
        """The one-line verdict printed under the copyright banner."""
        if not self.milestone:
            return "Drydock recorded no failure"
        if self.classification:
            return f"Drydock failed at {self.milestone} — {self.classification}"
        return f"Drydock failed at {self.milestone}"


def build_ladder(target_dir: Path, notes: Mapping[str, str] | None = None) -> tuple[LadderRow, ...]:
    """Render every milestone, in order, including the ones never reached.

    Milestones absent from ``PROJECT_STATUS.jsonl`` are reported as ``not run`` rather than
    omitted: an operator diagnosing a stopped run needs to see how far the lifecycle should
    have gone, not only how far it got.
    """
    return ladder_of(read_status(target_dir), notes)


def ladder_of(
    entries: Sequence[StatusEntry], notes: Mapping[str, str] | None = None
) -> tuple[LadderRow, ...]:
    """The milestone ladder for status entries, split out so it is testable without a Target."""
    notes = notes or {}
    retired = answered(entries)
    rows: list[LadderRow] = []
    for name, entry in milestone_states(entries):
        if entry is None:
            rows.append(LadderRow(milestone=name, state="not run", note=notes.get(name, "")))
            continue
        inside = tuple(
            other
            for other in entries
            if milestone_of(other.label) == name and other.label in retired
        )
        rows.append(
            LadderRow(
                milestone=name,
                state="pass" if entry.passed else "fail",
                label=entry.label,
                at=entry.at,
                attempts=entry.attempts,
                detail=entry.detail,
                note=notes.get(name, ""),
                answered=inside,
            )
        )
    return tuple(rows)


def stop_point(target_dir: Path) -> StopPoint | None:
    """The milestone the workflow stopped on, or ``None`` when it stands on a passing one."""
    return stop_point_of(read_status(target_dir))


def stop_point_of(entries: Sequence[StatusEntry]) -> StopPoint | None:
    """The stop derived from status entries.

    The stop is where the project *stands*, which is the milestone rollup's answer, not the
    lowest failed rung. A rung with a later rung above it in the same milestone was already
    answered; reporting it would send the operator to fix something that is no longer broken.
    """
    current = standing_state(tuple(entries))
    if current is None or current.passed:
        return None
    return StopPoint(
        milestone=milestone_of(current.label),
        label=current.label,
        classification=classify(current.detail),
        detail=current.detail,
        retried=current.attempts > 1,
        attempts=current.attempts,
    )


def superseded_failures(entries: Sequence[StatusEntry]) -> tuple[StatusEntry, ...]:
    """Failed states that a passing state has explicitly answered.

    These are the run's built-in false positives. An operator reading a raw ladder sees `FAIL`
    and reasonably concludes there is work to do; the report says plainly that there is not.
    Supersession is the named relation in ``project_status.SUPERSEDES``, never ladder position:
    a passing build report does not answer a failed acceptance gate.
    """
    retired = answered(entries)
    return tuple(entry for entry in entries if not entry.passed and entry.label in retired)


def classify(detail: str) -> str:
    """The category Drydock recorded for a failure, or ``""`` when it recorded none."""
    haystack = (detail or "").lower()
    for category in KNOWN_CLASSIFICATIONS:
        if category.lower() in haystack:
            return category
    return ""


def render_ladder(rows: Sequence[LadderRow]) -> str:
    """The console ladder: one fixed-width line per milestone."""
    width = max((len(row.milestone) for row in rows), default=0)
    lines: list[str] = []
    for row in rows:
        if row.state == "pass":
            mark = PASS_MARK
        elif row.state == "fail":
            mark = FAIL_MARK
        else:
            mark = NOT_RUN_MARK
        if row.state == "not run":
            annotations = ["not run"]
        else:
            annotations = [part for part in (_clock(row.at), row.note) if part]
            if row.retried:
                annotations.append(RETRY_NOTE.format(attempts=row.attempts))
            if row.failed and row.detail:
                annotations.append(row.detail)
        trailing = "   ".join(annotations)
        lines.append(f"  {mark} {row.milestone.ljust(width)}   {trailing}".rstrip())
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

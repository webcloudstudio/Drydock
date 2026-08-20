"""Project workflow state: the PROJECT_STATUS.jsonl state machine.

``PROJECT_STATUS.jsonl`` holds one row per workflow state the Target currently stands in, in
ladder order, followed by one summary row naming the state the project is in. It is a
snapshot, not a journal: recording a state rewrites the file, and there is no attempt history
to reduce. The states are not mutually exclusive — a failed rung can sit below passing ones.

Voiding is a property of the *command*, not of ladder position. A state is voided only when
the thing it verified has changed underneath it — a new plan or a new build in the same
space. Re-running a verification does not: the evidence is untouched, so every other state
still stands whatever the rerun reports. A verification that fails invalidates itself and
nothing else. A voided state is removed outright — absent means "not established", which is
the same thing it means for a state never attempted.

The summary row is derived, never authoritative, and names where the workflow stands: the
lowest failed state if there is one, otherwise the last good state. That is the rung the
workflow stopped on, so an external reader can ``tail -1`` the file for the answer.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

#: Workflow states, in ladder order. Position orders the workflow and nothing more; it is
#: not the transition rule. A state not listed here is not part of the machine.
LABEL_LADDER = (
    "INITIALIZED",
    "IMPORTED",
    "ANALYZED",
    "PLAN CREATED",
    "PLAN REPAIRED",
    "BUILDING",
    "BUILT",
    "LLM ACCEPTANCE CHECKS OK",
    "SCORE BUILD",
    "SCORE RELEASE",
    "FINALIZED",
)

_LADDER_INDEX = {label: index for index, label in enumerate(LABEL_LADDER)}

#: States whose command rewrites the artifact under test, so reaching one voids every state
#: above it. ``INITIALIZED`` and ``IMPORTED`` are not here: creating a Target and reading
#: sources into it change nothing a later state was established against. Everything from
#: analysis onward produces a new plan or a new build in the same space, which does.
#:
#: The verification states — the acceptance and score ladder — are absent by construction.
#: They read evidence; they never author it.
MUTATING_LABELS = frozenset({
    "ANALYZED",
    "PLAN CREATED",
    "PLAN REPAIRED",
    "BUILDING",
    "BUILT",
})

STATUS_FILENAME = "PROJECT_STATUS.jsonl"


@dataclass(frozen=True)
class StatusEntry:
    """One workflow state the Target currently stands in."""

    label: str
    passed: bool
    at: str  # ISO 8601 UTC instant (e.g. "2026-08-20T14:38:51.886+00:00")
    detail: str  # empty string if passed; one-line error message if failed
    command: str  # the drydock command that established this (e.g. "drydock build jq")
    attempts: int = 1  # consecutive attempts at this state since it was last voided


def record_status(
    target_dir: Path, label: str, *, passed: bool, detail: str = "", command: str = ""
) -> None:
    """Record an attempt at *label*, voiding states above it only if *label* is mutating.

    An attempt at a state in :data:`MUTATING_LABELS` re-authors the artifact everything above
    it was verified against, so those states are dropped. An attempt at any other state
    records itself and touches nothing else: a rerun of a verification changes no evidence,
    so a state established earlier still stands regardless of what the rerun reports.

    A failed verification is a claim about *this* state only and voids nothing. A failed
    *mutating* attempt still voids, because it ran: a build that got partway through and
    stopped has already rewritten the tree the scores above it were taken against.

    Recording is an observability side effect, never a failure mode: it is skipped when the
    Target directory does not exist (nothing was attempted against a Target that is not
    there), when *label* is not a ladder state, and filesystem errors are swallowed. The
    calling command's own exit-code contract is never altered by this write.

    Args:
        target_dir: the Target's directory ($DRYDOCK_WORKSPACE/targets/<Target>)
        label: one of LABEL_LADDER; anything else is ignored
        passed: whether the attempt succeeded
        detail: if passed=False, error message (collapsed to one line); if passed=True, empty
        command: the drydock command string (e.g. "drydock build jq")
    """
    if label not in _LADDER_INDEX or not target_dir.is_dir():
        return

    rank = _LADDER_INDEX[label]
    standing = read_status(target_dir)
    voids = label in MUTATING_LABELS
    kept = [
        entry
        for entry in standing
        if entry.label != label and (not voids or _LADDER_INDEX[entry.label] < rank)
    ]
    previous = next((entry for entry in standing if entry.label == label), None)
    kept.append(
        StatusEntry(
            label=label,
            passed=passed,
            at=datetime.now(UTC).isoformat(timespec="milliseconds"),
            detail="" if passed else _one_line(detail),
            command=_one_line(command),
            attempts=(previous.attempts + 1) if previous is not None else 1,
        )
    )
    _write(target_dir, kept)


def void_above(target_dir: Path, label: str) -> None:
    """Drop every state above *label* without claiming a state.

    For commands that re-author the artifact but occupy no rung of their own — ``drydock
    refit`` conforms a new specification into an existing build, so every verification above
    the plan was made against something that no longer exists. Same silent-side-effect
    contract as :func:`record_status`.
    """
    if label not in _LADDER_INDEX or not target_dir.is_dir():
        return
    rank = _LADDER_INDEX[label]
    standing = read_status(target_dir)
    kept = [entry for entry in standing if _LADDER_INDEX[entry.label] <= rank]
    if len(kept) != len(standing):
        _write(target_dir, kept)


def record_failure(target_dir: Path, label: str, exc: BaseException, *, command: str = "") -> None:
    """Record a failed attempt at *label*, unless the cause was a usage error.

    A malformed invocation never reached the state it names, so it is not an attempt: it
    must neither claim the state nor void the states below it.
    """
    from drydock.errors import UsageError

    if isinstance(exc, UsageError):
        return
    record_status(target_dir, label, passed=False, detail=str(exc)[:500], command=command)


def read_status(target_dir: Path) -> tuple[StatusEntry, ...]:
    """Return the states the Target currently stands in, in ladder order.

    Unparsable rows, unknown labels, and the derived summary row are skipped: the file is a
    snapshot the tool rewrites, so a corrupt row is dropped rather than failing a command
    whose real work already succeeded.
    """
    path = target_dir / STATUS_FILENAME
    try:
        content = path.read_text(encoding="utf-8")
    except OSError:
        return ()

    found: dict[str, StatusEntry] = {}
    for line in content.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except ValueError:
            continue
        label = row.get("label") if isinstance(row, dict) else None
        if not isinstance(label, str) or label not in _LADDER_INDEX:
            continue  # the summary row carries "state", not "label"
        found[label] = StatusEntry(
            label=label,
            passed=row.get("result") == "pass",
            at=str(row.get("at") or ""),
            detail=str(row.get("detail") or ""),
            command=str(row.get("command") or ""),
            attempts=row.get("attempts") if isinstance(row.get("attempts"), int) else 1,
        )
    return tuple(found[label] for label in LABEL_LADDER if label in found)


def current_state(target_dir: Path) -> StatusEntry | None:
    """The state the project is in, or None when it has established none.

    See :func:`standing_state`. States are no longer mutually exclusive — a verification that
    fails on rerun leaves the states it was built on in place — so "the highest row present"
    is no longer the answer.
    """
    return standing_state(read_status(target_dir))


def standing_state(entries: tuple[StatusEntry, ...]) -> StatusEntry | None:
    """Where the workflow stands: the rung blocking it, or the last good one.

    The workflow runs bottom-up and stops at its first failure, so a failed state is what an
    operator must act on and outranks any state above it. With nothing failed, this is the
    last good state — the furthest rung reached.
    """
    return blocking(entries) or last_good(entries)


def blocking(entries: tuple[StatusEntry, ...]) -> StatusEntry | None:
    """The lowest failed state, which is the one the workflow would have stopped on."""
    failures = [entry for entry in entries if not entry.passed]
    return min(failures, key=lambda entry: _LADDER_INDEX[entry.label], default=None)


def last_good(entries: tuple[StatusEntry, ...]) -> StatusEntry | None:
    """The highest passing entry ranked below the lowest failed one.

    Ranking rather than position handles the ladder's optional rungs: ``PLAN REPAIRED`` runs
    only after a failed verify and ``BUILDING`` only while work remains, so the passing states
    are not required to be contiguous.
    """
    failed = blocking(entries)
    ceiling = _LADDER_INDEX[failed.label] if failed is not None else len(LABEL_LADDER)
    good = [entry for entry in entries if entry.passed and _LADDER_INDEX[entry.label] < ceiling]
    return good[-1] if good else None


def latest_per_label(entries: tuple[StatusEntry, ...]) -> dict[str, StatusEntry]:
    """Index states by label, in ladder order.

    Retained for callers that render the ladder. With one row per state this is a
    re-indexing, not a reduction.
    """
    found = {entry.label: entry for entry in entries if entry.label in _LADDER_INDEX}
    return {label: found[label] for label in LABEL_LADDER if label in found}


def _write(target_dir: Path, entries: list[StatusEntry]) -> None:
    """Rewrite the snapshot: the state rows in ladder order, then the derived summary row."""
    entries = sorted(entries, key=lambda entry: _LADDER_INDEX[entry.label])
    lines = [
        json.dumps({
            "label": entry.label,
            "result": "pass" if entry.passed else "fail",
            "at": entry.at,
            "detail": entry.detail,
            "command": entry.command,
            "attempts": entry.attempts,
        })
        for entry in entries
    ]
    # The summary names where the workflow stands, not the last row written: a verification
    # that failed on rerun is recorded above states that still stand, and is not the answer.
    state = standing_state(tuple(entries))
    if state is not None:
        lines.append(
            json.dumps({
                "state": state.label,
                "result": "pass" if state.passed else "fail",
                "at": state.at,
                "attempts": state.attempts,
            })
        )
    try:
        (target_dir / STATUS_FILENAME).write_text("\n".join(lines) + "\n", encoding="utf-8")
    except OSError:
        return


def _one_line(text: str) -> str:
    """Collapse whitespace so one record field never spans lines."""
    return " ".join(text.split())

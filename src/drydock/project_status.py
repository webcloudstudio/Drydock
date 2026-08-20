"""Project workflow state: the PROJECT_STATUS.jsonl state machine.

A Target is in exactly one state. ``PROJECT_STATUS.jsonl`` holds one row per workflow state
the Target currently stands in, in ladder order, followed by one summary row naming the
state the project is in. It is a snapshot, not a journal: recording a state rewrites the
file, and there is no attempt history to reduce.

The ladder is linear, so the transition rule is linear too. Recording any state voids every
state below it: starting a build un-finalizes the project, re-running acceptance voids the
scores built on it, and re-importing voids everything downstream of the import. A voided
state is removed outright — absent means "not established", which is the same thing it
means for a state never attempted.

The summary row is derived, never authoritative. It is rewritten from the state rows on
every record so an external reader can ``tail -1`` the file for the answer.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

#: Workflow states, in ladder order. Position is the transition rule: recording a state
#: voids every state after it. A state not listed here is not part of the machine.
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

STATUS_FILENAME = "PROJECT_STATUS.jsonl"

#: The append-only markdown journal this file replaces. A Target still carrying one is
#: migrated on first read and the journal removed, so no Target keeps two status files.
_LEGACY_FILENAME = "PROJECT_STATUS.md"


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
    """Move the Target to *label*, voiding every state below it on the ladder.

    Recording is an observability side effect, never a failure mode: it is skipped when the
    Target directory does not exist (nothing was attempted against a Target that is not
    there), when *label* is not a ladder state, and filesystem errors are swallowed. The
    calling command's own exit-code contract is never altered by this write.

    Args:
        target_dir: the Target's directory ($DRYDOCK_WORKSPACE/targets/<Target>)
        label: one of LABEL_LADDER; anything else is ignored
        passed: whether the attempt succeeded. A failed attempt still voids downstream
            states — a build that failed invalidates the scores that ran before it.
        detail: if passed=False, error message (collapsed to one line); if passed=True, empty
        command: the drydock command string (e.g. "drydock build jq")
    """
    if label not in _LADDER_INDEX or not target_dir.is_dir():
        return

    rank = _LADDER_INDEX[label]
    standing = read_status(target_dir)
    kept = [entry for entry in standing if _LADDER_INDEX[entry.label] < rank]
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
    if not path.exists():
        _migrate_legacy(target_dir)
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
    """The one state the project is in, or None when it has established none.

    The highest ladder state present. Because every write voids what is below it, that is
    also always the most recently recorded state.
    """
    entries = read_status(target_dir)
    return entries[-1] if entries else None


def latest_per_label(entries: tuple[StatusEntry, ...]) -> dict[str, StatusEntry]:
    """Index states by label, in ladder order.

    Retained for callers that render the ladder. With one row per state this is a
    re-indexing, not a reduction.
    """
    found = {entry.label: entry for entry in entries if entry.label in _LADDER_INDEX}
    return {label: found[label] for label in LABEL_LADDER if label in found}


def _migrate_legacy(target_dir: Path) -> None:
    """Fold a legacy ``PROJECT_STATUS.md`` journal into the state machine, then remove it.

    The journal is replayed in recorded order under the same void rule live recording uses,
    which is the only reading of it that yields one state: its records are attempts, and an
    attempt at a state always invalidated whatever stood above it. A record with no parsable
    instant keeps its file position, because file order is the order the commands ran.
    """
    legacy = target_dir / _LEGACY_FILENAME
    try:
        content = legacy.read_text(encoding="utf-8")
    except OSError:
        return

    standing: list[StatusEntry] = []
    for record in _parse_legacy(content):
        if record.label not in _LADDER_INDEX:
            continue
        rank = _LADDER_INDEX[record.label]
        previous = next((entry for entry in standing if entry.label == record.label), None)
        standing = [entry for entry in standing if _LADDER_INDEX[entry.label] < rank]
        standing.append(
            StatusEntry(
                label=record.label,
                passed=record.passed,
                at=record.at,
                detail=record.detail,
                command=record.command,
                attempts=(previous.attempts + 1) if previous is not None else 1,
            )
        )

    _write(target_dir, standing)
    if not standing:
        # `_write` only unlinks the journal when it wrote something. A journal holding no
        # ladder state has nothing to carry forward, so it goes too.
        try:
            legacy.unlink(missing_ok=True)
        except OSError:
            return


def _parse_legacy(content: str) -> list[StatusEntry]:
    """Parse the legacy markdown journal into its records, in file order."""
    records: list[StatusEntry] = []
    fields: dict[str, str] = {}

    def flush() -> None:
        if "label" in fields:
            records.append(
                StatusEntry(
                    label=fields["label"],
                    passed=fields.get("result") == "pass",
                    at=fields.get("at", ""),
                    detail=fields.get("detail", ""),
                    command=fields.get("command", ""),
                )
            )

    for line in content.splitlines():
        line = line.rstrip()
        if line.startswith("## "):
            flush()
            fields = {"label": line[3:].strip()}
        else:
            for key in ("result", "at", "detail", "command"):
                prefix = f"{key}: "
                if line.startswith(prefix):
                    fields[key] = line[len(prefix) :].strip()
                    break
    flush()
    return records


def _write(target_dir: Path, entries: list[StatusEntry]) -> None:
    """Rewrite the snapshot: the state rows, then the derived summary row."""
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
    if entries:
        state = entries[-1]
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
        (target_dir / _LEGACY_FILENAME).unlink(missing_ok=True)
    except OSError:
        return


def _one_line(text: str) -> str:
    """Collapse whitespace so one record field never spans lines."""
    return " ".join(text.split())

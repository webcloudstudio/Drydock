"""Project workflow-state persistence: PROJECT_STATUS.md append-only ladder.

Each lifecycle command (init, analyze, plan, build, score ac/build/release, score report)
records its outcome in PROJECT_STATUS.md at the target directory. The file is append-only;
multiple attempts at the same state are preserved in full for audit, and the ladder
renders the *last* attempt per label. A state with a recorded attempt but no successful
completion carries a failure badge and optional detail; a state not yet attempted is
simply absent from the ladder.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

#: Workflow-state labels, in the order they appear in the ladder.
#: Not all are required; only attempted states are shown.
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

_STATUS_FILENAME = "PROJECT_STATUS.md"


@dataclass(frozen=True)
class StatusEntry:
    """One recorded lifecycle state attempt."""

    label: str
    passed: bool
    at: str  # ISO 8601 UTC instant (e.g. "2026-08-20T02:47:31.123Z")
    detail: str  # empty string if passed; error message if failed
    command: str  # the drydock command that recorded this (e.g. "drydock build jq")


def record_status(
    target_dir: Path, label: str, *, passed: bool, detail: str = "", command: str = ""
) -> None:
    """Append one state-attempt record to PROJECT_STATUS.md.

    Args:
        target_dir: the Target's directory ($DRYDOCK_WORKSPACE/targets/<Target>)
        label: one of LABEL_LADDER
        passed: whether the attempt succeeded
        detail: if passed=False, error message (one line); if passed=True, empty
        command: the drydock command string (e.g. "drydock build jq")
    """
    status_file = target_dir / _STATUS_FILENAME

    # Generate ISO 8601 UTC timestamp
    now = datetime.now(UTC)
    timestamp = now.isoformat(timespec="milliseconds")

    # Format the entry
    result = "pass" if passed else "fail"
    lines = [
        f"## {label}",
        f"result: {result}",
        f"at: {timestamp}",
        f"detail: {detail}",
        f"command: {command}",
        "",  # blank line between entries
    ]

    # Append to file (create if missing)
    if status_file.exists():
        content = status_file.read_text(encoding="utf-8")
        if not content.endswith("\n"):
            content += "\n"
        content += "\n".join(lines)
    else:
        content = "\n".join(lines)

    status_file.write_text(content, encoding="utf-8")


def read_status(target_dir: Path) -> tuple[StatusEntry, ...]:
    """Parse PROJECT_STATUS.md and return all recorded attempts in file order.

    Args:
        target_dir: the Target's directory

    Returns:
        Tuple of StatusEntry records, in the order they appear in the file.
        Empty tuple if the file doesn't exist or is empty.
    """
    status_file = target_dir / _STATUS_FILENAME

    if not status_file.exists():
        return ()

    content = status_file.read_text(encoding="utf-8")
    if not content.strip():
        return ()

    entries = []
    current_entry: dict[str, str] = {}

    for line in content.splitlines():
        line = line.rstrip()

        if line.startswith("## "):
            # Start of a new entry; save the previous one if complete
            if current_entry and "label" in current_entry:
                entries.append(
                    StatusEntry(
                        label=current_entry["label"],
                        passed=current_entry.get("result", "fail") == "pass",
                        at=current_entry.get("at", ""),
                        detail=current_entry.get("detail", ""),
                        command=current_entry.get("command", ""),
                    )
                )
            current_entry = {"label": line[3:].strip()}

        elif line.startswith("result: "):
            current_entry["result"] = line[8:].strip()

        elif line.startswith("at: "):
            current_entry["at"] = line[4:].strip()

        elif line.startswith("detail: "):
            current_entry["detail"] = line[8:].strip()

        elif line.startswith("command: "):
            current_entry["command"] = line[9:].strip()

    # Don't forget the last entry
    if current_entry and "label" in current_entry:
        entries.append(
            StatusEntry(
                label=current_entry["label"],
                passed=current_entry.get("result", "fail") == "pass",
                at=current_entry.get("at", ""),
                detail=current_entry.get("detail", ""),
                command=current_entry.get("command", ""),
            )
        )

    return tuple(entries)


def latest_per_label(entries: tuple[StatusEntry, ...]) -> dict[str, StatusEntry]:
    """Return the last recorded attempt per label, in fixed label order.

    Args:
        entries: all recorded attempts (from read_status)

    Returns:
        Dictionary mapping label -> StatusEntry (the last occurrence of each label),
        ordered by LABEL_LADDER so the ladder renders consistently.
    """
    # Build a dict of label -> last entry
    latest_map: dict[str, StatusEntry] = {}
    for entry in entries:
        latest_map[entry.label] = entry

    # Return entries in LABEL_LADDER order, filtering to only labels that have been attempted
    return {label: latest_map[label] for label in LABEL_LADDER if label in latest_map}

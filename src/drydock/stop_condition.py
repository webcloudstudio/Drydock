"""``STOP_NOW.md`` — the Target-level halt semaphore.

A lifecycle stage that reaches a terminal failure records why, at the Target root, in a file any
later stage can read before it spends anything. This is a stop *condition*, not a stop *flag*: the
halting stage does not have to know which stages follow it, and a later stage does not have to
reconstruct the earlier one's verdict from an exit code it did not observe.

The condition is checked, never inferred. A stage that runs while ``STOP_NOW.md`` exists is a
defect in the caller, because the reason a run stops is not "the last command exited non-zero" —
several commands exit non-zero as ordinary state signals — but "an earlier stage declared the run
over".

The file is Commander-readable on purpose. It is the first thing to open in a stopped run tree,
and it names the stage, the reason, and when the halt was declared.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

STOP_FILENAME = "STOP_NOW.md"


@dataclass(frozen=True)
class StopCondition:
    """A recorded halt: which stage declared it, why, and when."""

    stage: str
    reason: str
    declared_at: str = ""

    def line(self) -> str:
        return f"{self.stage}: {self.reason}"


def stop_path(target_dir: Path) -> Path:
    return target_dir / STOP_FILENAME


def write_stop(target_dir: Path, stage: str, reason: str) -> Path:
    """Declare the run over. The first declaration wins and is never overwritten.

    A later stage that also fails is describing a consequence of the halt, not a second cause,
    and rewriting the file would replace the first causal failure with the last incidental one —
    which is exactly the information a stopped run exists to preserve.
    """
    path = stop_path(target_dir)
    if path.is_file():
        return path
    declared_at = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "# STOP\n\n"
        f"- stage: {stage}\n"
        f"- declared: {declared_at}\n\n"
        "## Reason\n\n"
        f"{reason.strip()}\n\n"
        "## Clearing\n\n"
        "Fix the cause, then delete this file. Every lifecycle stage refuses to run while it\n"
        "exists, so a run that continues past a halt cannot be produced by accident.\n",
        encoding="utf-8",
        newline="\n",
    )
    return path


def read_stop(target_dir: Path) -> StopCondition | None:
    """Return the recorded halt, or ``None`` when the Target is not stopped."""
    path = stop_path(target_dir)
    if not path.is_file():
        return None
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        # An unreadable semaphore still means a halt was declared. Reporting "not stopped"
        # because the file would not open is the one answer that cannot be right.
        return StopCondition("unknown", f"{STOP_FILENAME} exists but could not be read")
    stage = ""
    declared_at = ""
    reason_lines: list[str] = []
    in_reason = False
    for line in text.splitlines():
        if line.startswith("- stage:"):
            stage = line.split(":", 1)[1].strip()
        elif line.startswith("- declared:"):
            declared_at = line.split(":", 1)[1].strip()
        elif line.startswith("## Reason"):
            in_reason = True
        elif line.startswith("## "):
            in_reason = False
        elif in_reason and line.strip():
            reason_lines.append(line.strip())
    return StopCondition(stage or "unknown", " ".join(reason_lines), declared_at)


def clear_stop(target_dir: Path) -> None:
    """Remove the halt so the Target can run again."""
    try:
        stop_path(target_dir).unlink()
    except FileNotFoundError:
        pass

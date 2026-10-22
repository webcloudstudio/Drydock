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
and it names the stage, the reason, when the halt was declared, and how to recover.

Two writers declare a halt. ``drydock uat`` declares one when a stage it drives cannot go on, and
every command declares one when its provider fails in a way another call cannot fix: a rate or
usage limit, an expired login, a timeout, or an outage (``llm.fatal_stop``). Every LLM-assisted
command checks for it before it spends anything (``cli._process_stop_gate``).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

STOP_FILENAME = "STOP_NOW.md"


@dataclass(frozen=True)
class StopCondition:
    """A recorded halt: which stage declared it, why, when, and how to recover."""

    stage: str
    reason: str
    declared_at: str = ""
    recovery: str = ""

    def line(self) -> str:
        return f"{self.stage}: {self.reason}"


def stop_path(target_dir: Path) -> Path:
    return target_dir / STOP_FILENAME


def write_stop(target_dir: Path, stage: str, reason: str, recovery: str = "") -> Path:
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
        + (f"## Recovery\n\n{recovery.strip()}\n\n" if recovery.strip() else "")
        + "## Clearing\n\n"
        "Fix the cause, then delete this file, or answer `y` when an interactive Drydock command\n"
        "offers to clear it. Every LLM-assisted command refuses to run while it exists, so a run\n"
        "that continues past a halt cannot be produced by accident.\n",
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
    sections: dict[str, list[str]] = {"Reason": [], "Recovery": []}
    section = ""
    for line in text.splitlines():
        if line.startswith("- stage:") and not section:
            stage = line.split(":", 1)[1].strip()
        elif line.startswith("- declared:") and not section:
            declared_at = line.split(":", 1)[1].strip()
        elif line.startswith("## "):
            section = line[3:].strip()
        elif section in sections and line.strip():
            sections[section].append(line.rstrip())
    return StopCondition(
        stage or "unknown",
        " ".join(line.strip() for line in sections["Reason"]),
        declared_at,
        "\n".join(sections["Recovery"]),
    )


def render_stop(stop: StopCondition, target: str = "") -> str:
    """The console banner for a recorded halt: what stopped, why, and the way back."""
    border = "=" * 72
    lines = [
        border,
        f"STOPPED{f': {target}' if target else ''}  ·  {stop.stage}"
        + (f"  ·  {stop.declared_at}" if stop.declared_at else ""),
        border,
        "",
        f"  {stop.reason}",
    ]
    if stop.recovery:
        lines += ["", "  Recovery", *(f"    {line.strip()}" for line in stop.recovery.splitlines())]
    lines += ["", f"  Clear: delete {STOP_FILENAME}, or answer y when a command offers to.", border]
    return "\n".join(lines)


def clear_stop(target_dir: Path) -> None:
    """Remove the halt so the Target can run again."""
    try:
        stop_path(target_dir).unlink()
    except FileNotFoundError:
        pass

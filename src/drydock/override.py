"""Override waivers: the record of every gate ``--override`` bypassed.

``--override`` waives the gates that are waiting on a human answer — unanswered Analyze
questionnaire decisions, blocking ``DECISIONS.json`` records that park a story, and acceptance
prerequisites awaiting Commander authorization. It deliberately does not waive a blocked
analysis (``BLOCKERS.md``, ``Quality: Blocked``), because on a Target whose sources the author
controls that verdict is a signal about the sources, not an interruption to route around.

Every waiver is recorded rather than merely skipped, so an override run reports what it ignored
and the Target is stamped as ungoverned.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

# Waiver kinds. Kept as constants so the summary groups stably and tests assert on a name
# rather than on prose.
PLAN_DECISION = "plan-decision"
STORY_QUESTION = "story-question"
ACCEPTANCE_AUTHORIZATION = "acceptance-authorization"


@dataclass(frozen=True)
class WaivedGate:
    """One gate that would have blocked, bypassed under ``--override``."""

    kind: str
    subject: str
    detail: str = ""

    def line(self) -> str:
        text = f"  {self.kind:<26} {self.subject}"
        return f"{text} — {self.detail}" if self.detail else text

    def warning(self) -> str:
        detail = f": {self.detail}" if self.detail else ""
        return f"WARNING: override waived {self.kind} for {self.subject}{detail}"


def dedupe_waivers(waivers: tuple[WaivedGate, ...] | list[WaivedGate]) -> tuple[WaivedGate, ...]:
    """Collapse repeats in Manifest order.

    A build re-synchronizes the question gates several times per run, so the same waived gate is
    observed repeatedly. The summary should count gates, not observations.
    """
    seen: set[tuple[str, str, str]] = set()
    unique: list[WaivedGate] = []
    for item in waivers:
        key = (item.kind, item.subject, item.detail)
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)
    return tuple(unique)


def format_override_summary(waivers: tuple[WaivedGate, ...] | list[WaivedGate]) -> str:
    """Render the end-of-run block naming every bypassed gate, or '' when none fired."""
    items = tuple(waivers)
    if not items:
        return ""
    plural = "" if len(items) == 1 else "s"
    lines = [f"---- OVERRIDE SUMMARY ({len(items)} gate{plural} bypassed) ----"]
    lines.extend(item.line() for item in items)
    lines.append("This run is not governed: the waived gates were never answered.")
    return "\n".join(lines)


def stamp_override(target_dir: Path, waivers: tuple[WaivedGate, ...] | list[WaivedGate]) -> None:
    """Mark the Target as override-built so a waived run is never mistaken for a governed one."""
    items = tuple(waivers)
    if not items:
        return
    from drydock.metadata import METADATA_NAME, set_field

    path = target_dir / METADATA_NAME
    set_field(path, "override", "true", overwrite=True)
    set_field(path, "override_waivers", str(len(items)), overwrite=True)

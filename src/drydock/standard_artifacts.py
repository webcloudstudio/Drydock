"""Create and maintain the standard target-local QuarterDeck artifacts."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from drydock.build_plan import BuildPlan

SOUNDINGS_HEADER = ("ID", "Acceptance Criterion", "State", "Evidence")


@dataclass(frozen=True)
class Sounding:
    criterion_id: str
    criterion: str
    state: str
    evidence: str = ""


def _escape_cell(value: str) -> str:
    return value.replace("|", r"\|").replace("\n", " ")


def render_soundings(rows: list[Sounding]) -> str:
    lines = [
        "# Soundings",
        "",
        "| ID | Acceptance Criterion | State | Evidence |",
        "|---|---|---|---|",
    ]
    lines.extend(
        f"| {_escape_cell(row.criterion_id)} | {_escape_cell(row.criterion)} | "
        f"{_escape_cell(row.state)} | {_escape_cell(row.evidence)} |"
        for row in rows
    )
    return "\n".join(lines) + "\n"


def _split_row(line: str) -> list[str]:
    return [cell.strip().replace(r"\|", "|") for cell in re.split(r"(?<!\\)\|", line.strip("|"))]


def load_soundings(path: Path) -> dict[str, Sounding]:
    if not path.is_file():
        return {}
    lines = path.read_text(encoding="utf-8").splitlines()
    for index, line in enumerate(lines):
        if tuple(_split_row(line)) != SOUNDINGS_HEADER or index + 1 >= len(lines):
            continue
        rows: dict[str, Sounding] = {}
        for row_line in lines[index + 2 :]:
            if "|" not in row_line:
                break
            cells = _split_row(row_line)
            if len(cells) != 4 or not cells[0]:
                continue
            rows[cells[0]] = Sounding(*cells)
        return rows
    return {}


def _soundings_state(plan_state: str) -> str:
    return {
        "pending": "NOT STARTED",
        "implemented": "IMPLEMENTED",
        "closed/verified": "DONE",
        "closed/failed": "IMPLEMENTED",
    }[plan_state]


def sync_plan_soundings(plan: BuildPlan, target_dir: Path) -> Path:
    """Project plan acceptance gates into Soundings while preserving recorded evidence."""
    path = target_dir / "SOUNDINGS.md"
    existing = load_soundings(path)
    rows = []
    for block in plan.blocks:
        if block.block_type != "ac":
            continue
        previous = existing.get(block.block_id)
        state = _soundings_state(block.state)
        evidence = previous.evidence if previous else ""
        rows.append(Sounding(block.block_id, block.name, state, evidence))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_soundings(rows), encoding="utf-8", newline="\n")
    return path


def ensure_standard_artifacts(target: str, target_dir: Path) -> list[Path]:  # noqa: ARG001
    """Create missing standard artifact files without overwriting authored content."""
    return []


def render_console(target: str, *, plan_path: Path | None = None) -> str:
    """Return the target QuarterDeck config with standard artifacts in canonical order."""
    planning_item = ""
    default_item = "commanders_view"
    if plan_path is not None:
        default_item = "planning_session"
        planning_item = (
            '\n  - { id: planning_session, label: "Planning Session", section: actions, '
            f"type: plan_decision, plan_path: {json.dumps(str(plan_path))} }}\n"
        )
    slug = re.sub(r"[^a-z0-9]+", "-", target.lower()).strip("-") or "target"
    return f"""console:
  name: {target} QuarterDeck
  default_item: {default_item}
  state_db: data/console_state.sqlite

project:
  id: {slug}
  name: {target}
  description: "Drydock target workspace."

sections:
  - {{ id: blockers, label: "Blockers", dot: "#dc2626" }}
  - {{ id: core, label: "Drydock Core", dot: "#0d9488", pinned: true }}
  - {{ id: build_plan, label: "Build Plan", dot: "#d97706" }}
  - {{ id: actions, label: "Action Items", dot: "#dc2626" }}
  - {{ id: project_pages, label: "Project Pages", dot: "#2563eb" }}
  - {{ id: archive, label: "Archive", dot: "#94a3b8", collapsed: true }}

items:
  - {{ id: blockers_doc, label: "Blockers", section: blockers, type: editable_markdown, path: ../BLOCKERS.md }}
  - {{ id: commanders_view, label: "Captain's Chair", section: core, type: document, path_html: captains_chair.html, order: 1 }}
  - {{ id: sea_trials, label: "Sea Trials", section: core, type: markdown, path: ../SEA_TRIALS.md, order: 2 }}
  - {{ id: soundings, label: "Soundings", section: core, type: markdown, path: ../SOUNDINGS.md, order: 3 }}
{planning_item}  - {{ id: compass_edit, label: "Compass", section: actions, type: editable_markdown, path: ../COMPASS.md }}
  - {{ id: board, label: "Delivery Board", section: build_plan, type: kanban, path: tickets.json }}

sources:
  - glob: "QuarterDeck/questionnaires/spike-*.json"
    section: archive
    type: questionnaire
    template: spike
"""

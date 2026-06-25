"""Create and maintain the standard target-local QuarterDeck artifacts."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from drydock.build_plan import BuildPlan
from drydock.prompt_headers import prompt_header_for_file, prompt_headers

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
    build_compass_item = ""
    if plan_path is not None:
        planning_item = (
            '\n  - { id: planning_session, label: "Planning Session", section: plan, '
            f"type: plan_decision, plan_path: {json.dumps(str(plan_path))} }}\n"
        )
        build_compass_item = (
            '\n  - { id: build_compass, label: "Build Compass", section: plan, '
            'type: compass, path: ../MANIFEST.md, order: 4 }\n'
        )
    slug = re.sub(r"[^a-z0-9]+", "-", target.lower()).strip("-") or "target"
    docs_by_item = {doc.item_id: doc for doc in prompt_headers()}
    blockers = docs_by_item["blockers_doc"]
    compass = docs_by_item["compass_edit"]
    analyze_compass = docs_by_item["analyze_compass"]
    plan_compass = docs_by_item["plan_compass"]
    exclude_files = docs_by_item["exclude_files"]
    analysis = prompt_header_for_file("ANALYSIS.md")
    soundings_doc = prompt_header_for_file("SOUNDINGS.md")
    commanders_chair_help = (
        "Live project overview and delivery snapshot for this target."
    )
    sea_trials_help = (
        "Verification record and trial results for the current target state."
    )
    return f"""console:
  name: {target} QuarterDeck
  default_item: compass_edit
  app_help_file_location: docs/index.html

project:
  id: {slug}
  name: {target}
  description: "Drydock target workspace."

sections:
  - {{ id: analyze, label: "Analysis", dot: "#0d9488", pinned: true }}
  - {{ id: plan, label: "Plan", dot: "#2563eb" }}
  - {{ id: build, label: "Build", dot: "#d97706" }}

items:
  - {{ id: blockers_doc, label: "Blockers", section: analyze, type: editable_markdown, path: ../BLOCKERS.md, order: 1, help_text: {json.dumps(blockers.help_text)}, prompt_text: {json.dumps(blockers.prompt_text)} }}
  - {{ id: commanders_chair, label: "Commanders Chair", section: analyze, type: document, path_html: commanders_chair.html, order: 2, help_text: {json.dumps(commanders_chair_help)} }}
  - {{ id: compass_edit, label: "Compass", section: analyze, type: editable_markdown, path: ../COMPASS.md, order: 3, help_text: {json.dumps(compass.help_text)}, prompt_text: {json.dumps(compass.prompt_text)} }}
  - {{ id: analysis, label: "Analysis", section: analyze, type: markdown, tabs: true, path: ../ANALYSIS.md, order: 4, help_text: {json.dumps(analysis.help_text if analysis else "")} }}
  - {{ id: analyze_compass, label: "Analyze Compass", section: analyze, type: editable_markdown, path: ../ANALYZE_COMPASS.md, order: 5, help_text: {json.dumps(analyze_compass.help_text)}, prompt_text: {json.dumps(analyze_compass.prompt_text)} }}
  - {{ id: sea_trials, label: "Sea Trials", section: analyze, type: markdown, path: ../SEA_TRIALS.md, order: 6, help_text: {json.dumps(sea_trials_help)} }}
  - {{ id: soundings, label: "Soundings", section: analyze, type: markdown, path: ../SOUNDINGS.md, order: 7, help_text: {json.dumps(soundings_doc.help_text if soundings_doc else "")} }}
  - {{ id: exclude_files, label: "Exclude Files", section: analyze, type: editable_markdown, path: ../EXCLUDE_FILES.md, order: 8, help_text: {json.dumps(exclude_files.help_text)}, prompt_text: {json.dumps(exclude_files.prompt_text)} }}
{planning_item}  - {{ id: board, label: "Delivery Board", section: plan, type: kanban, path: tickets.json, order: 1 }}
  - {{ id: plan_compass, label: "Plan Compass", section: plan, type: editable_markdown, path: ../PLAN_COMPASS.md, order: 2, help_text: {json.dumps(plan_compass.help_text)}, prompt_text: {json.dumps(plan_compass.prompt_text)} }}
{build_compass_item}

sources:
  - glob: "QuarterDeck/questionnaires/discovery-*.json"
    section: analyze
    type: questionnaire
    template: discovery
    order: 99
"""

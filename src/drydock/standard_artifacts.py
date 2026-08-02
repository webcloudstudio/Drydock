"""Create and maintain the standard target-local QuarterDeck artifacts."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from drydock.prompt_headers import prompt_header_for_file, prompt_headers

SOUNDINGS_HEADER = ("Status", "Blueprint", "AC Id", "Text", "Evidence", "Verified At")

# Trust-but-verify vocabulary. ``score ac`` sets these from deterministic proof results so the
# Commander can scan the board and see exactly which acceptance criteria are proven.
VERIFIED_PASS = "✓ PASS"
VERIFIED_FAIL = "✗ FAIL"
VERIFIED_UNVERIFIED = "— UNVERIFIED"


@dataclass(frozen=True)
class Sounding:
    criterion_id: str
    blueprint: str
    summary: str
    verified: str = VERIFIED_UNVERIFIED
    evidence: str = ""
    verified_at: str = ""


def _escape_cell(value: str) -> str:
    return value.replace("|", r"\|").replace("\n", " ")


def render_soundings(rows: list[Sounding]) -> str:
    lines = [
        "# Soundings",
        "",
        "Per-assertion acceptance board, one row per Blueprint Programmatic Acceptance check.",
        "`drydock plan` projects every assertion as `— UNVERIFIED`; `drydock score ac` sets the",
        "Status column from deterministic proof results. A rerun of `drydock plan` resets Status to",
        "`— UNVERIFIED`; rescore to refresh.",
        "",
        "| Status | Blueprint | AC Id | Text | Evidence | Verified At |",
        "|---|---|---|---|---|---|",
    ]
    lines.extend(
        f"| {_escape_cell(row.verified)} | {_escape_cell(row.blueprint)} | "
        f"{_escape_cell(row.criterion_id)} | {_escape_cell(row.summary)} | "
        f"{_escape_cell(row.evidence)} | {_escape_cell(row.verified_at)} |"
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
            if len(cells) != len(SOUNDINGS_HEADER) or not cells[2]:
                continue
            rows[cells[2]] = Sounding(
                criterion_id=cells[2],
                blueprint=cells[1],
                summary=cells[3],
                verified=cells[0],
                evidence=cells[4],
                verified_at=cells[5],
            )
        return rows
    return {}


def ensure_standard_artifacts(target: str, target_dir: Path) -> list[Path]:  # noqa: ARG001
    """Create missing standard artifact files without overwriting authored content."""
    return []


def render_console(target: str, *, plan_path: Path | None = None) -> str:
    """Return the target QuarterDeck config with standard artifacts in canonical order."""
    build_compass_item = ""
    if plan_path is not None:
        build_compass_help = (
            "MANIFEST is the live work graph: feature groups, "
            "story-point cost, per-step lifecycle state (buildable now, review, done, "
            "failed with reason), and constrained reorder/regroup/rename/split editing."
        )
        build_compass_item = (
            '\n  - { id: build_compass, label: "MANIFEST", section: implement, '
            f"type: compass, path: ../MANIFEST.md, order: 1, help_text: {json.dumps(build_compass_help)} }}\n"
        )
    slug = re.sub(r"[^a-z0-9]+", "-", target.lower()).strip("-") or "target"
    docs_by_item = {doc.item_id: doc for doc in prompt_headers()}
    blockers = docs_by_item["blockers_doc"]
    compass = docs_by_item["compass_edit"]
    analyze_compass = docs_by_item["analyze_compass"]
    plan_compass = docs_by_item["plan_compass"]
    exclude_files = docs_by_item["exclude_files"]
    tech_stack = docs_by_item["technology_stack"]
    analysis = prompt_header_for_file("ANALYSIS.md")
    soundings_doc = prompt_header_for_file("SOUNDINGS.md")
    commanders_chair_help = "Live project overview and delivery snapshot for this target."
    sea_trials_help = "Verification record and trial results for the current target state."
    scorecard_help = (
        "Technical quality and project acceptance completion gate for the current build identity."
    )
    specification_scorecard_help = (
        "Specification quality and coverage report. Run "
        f"`drydock score specification {target}` to refresh this artifact."
    )
    decisions_help = (
        "Significant design decisions Plan made where the Blueprint, guardrails, or stack "
        "declaration were silent. Plan never hard-blocks on these; review and redirect any of "
        "them here."
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
  - {{ id: setup, label: "Setup", dot: "#64748b", pinned: true }}
  - {{ id: analyze, label: "Analysis", dot: "#0d9488", pinned: true }}
  - {{ id: implement, label: "Build", dot: "#2CB67D" }}
  - {{ id: refit, label: "Refit", dot: "#d97706" }}

items:
  - {{ id: blockers_doc, label: "⛔ Blockers", section: setup, type: editable_markdown, path: ../BLOCKERS.md, order: 1, help_text: {json.dumps(blockers.help_text)}, prompt_text: {json.dumps(blockers.prompt_text)} }}
  - {{ id: commanders_chair, label: "Commanders Chair", section: setup, type: document, path_html: commanders_chair.html, order: 2, help_text: {json.dumps(commanders_chair_help)} }}
  - {{ id: big_errors, label: "⛔ BIG ERRORS — action required", section: setup, type: markdown, path: ../ERRORS.md, order: 3, help_text: "Current post-LLM recovery record. Resolve the prescribed action and rerun the command." }}
  - {{ id: compass_edit, label: "Compass", section: setup, type: editable_markdown, path: ../COMPASS.md, order: 4, help_text: {json.dumps(compass.help_text)}, prompt_text: {json.dumps(compass.prompt_text)} }}
  - {{ id: analyze_compass, label: "Analyze Compass", section: setup, type: editable_markdown, path: ../ANALYZE_COMPASS.md, order: 4, help_text: {json.dumps(analyze_compass.help_text)}, prompt_text: {json.dumps(analyze_compass.prompt_text)} }}
  - {{ id: exclude_files, label: "Exclude Files", section: setup, type: editable_markdown, path: ../EXCLUDE_FILES.md, order: 5, help_text: {json.dumps(exclude_files.help_text)}, prompt_text: {json.dumps(exclude_files.prompt_text)} }}
  - {{ id: analysis, label: "Analysis", section: analyze, type: markdown, tabs: true, path: ../ANALYSIS.md, order: 1, help_text: {json.dumps(analysis.help_text if analysis else "")} }}
  - {{ id: plan_compass, label: "Plan Compass", section: analyze, type: editable_markdown, path: ../PLAN_COMPASS.md, order: 2, help_text: {json.dumps(plan_compass.help_text)}, prompt_text: {json.dumps(plan_compass.prompt_text)} }}
  - {{ id: technology_stack, label: "Technology Stack", section: analyze, type: technology_stack, path: ../TECHNOLOGY_STACK.md, order: 3, help_text: {json.dumps(tech_stack.help_text)}, prompt_text: {json.dumps(tech_stack.prompt_text)} }}
  - {{ id: sea_trials, label: "Sea Trials", section: analyze, type: markdown, path: ../SEA_TRIALS.md, order: 4, help_text: {json.dumps(sea_trials_help)} }}
  - {{ id: soundings, label: "Soundings", section: analyze, type: markdown, path: ../SOUNDINGS.md, order: 5, help_text: {json.dumps(soundings_doc.help_text if soundings_doc else "")} }}
  - {{ id: specification_scorecard, label: "Specification Scorecard", section: analyze, type: markdown, path: ../SPECIFICATION_SCORECARD.md, order: 6, help_text: {json.dumps(specification_scorecard_help)} }}
  - {{ id: board, label: "Kanban Board", section: implement, type: kanban, path: ../MANIFEST.md, order: 2 }}
  - {{ id: decisions, label: "Decisions", section: implement, type: decisions, path: ../DECISIONS.json, order: 3, help_text: {json.dumps(decisions_help)} }}
  - {{ id: scorecard, label: "Build Score", section: implement, type: markdown, path: ../SCORECARD.md, order: 4, help_text: {json.dumps(scorecard_help)} }}
  - {{ id: refit_status, label: "Refit", section: refit, type: refit, order: 1, help_text: "Blueprints that changed since they were applied to the Manifest, plus waiting change tickets. Run drydock refit to fold them in. Never-built blueprints are build items, not refit items." }}
{build_compass_item}

sources:
  - glob: "QuarterDeck/questionnaires/discovery-*.json"
    section: analyze
    type: questionnaire
    template: discovery
    order: 99
"""

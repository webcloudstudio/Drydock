"""Tests for SCORECARD.md's full-rebuild regeneration."""

from __future__ import annotations

import json
from pathlib import Path

from drydock.decisions import DECISIONS_FILENAME
from drydock.project_status import record_status
from drydock.scorecard import render_scorecard, write_scorecard
from drydock.standard_artifacts import Sounding, render_soundings


def _target(tmp_path: Path) -> Path:
    target_dir = tmp_path / "targets" / "Demo"
    target_dir.mkdir(parents=True)
    return target_dir


def test_a_never_run_target_reports_every_command_as_not_yet_run(tmp_path):
    target_dir = _target(tmp_path)

    text = render_scorecard("Demo", target_dir)

    assert "# Scorecard: Demo" in text
    assert text.count("NOT YET RUN") == 4


def test_ac_section_reads_project_status_and_soundings(tmp_path):
    target_dir = _target(tmp_path)
    record_status(target_dir, "SCORE AC", passed=False, command="drydock score ac Demo")
    (target_dir / "SOUNDINGS.md").write_text(
        render_soundings([
            Sounding("ac-1", "FEATURES.md", "First", "✓ PASS", "", "2026-08-21T00:00:00Z"),
            Sounding("ac-2", "FEATURES.md", "Second", "✗ FAIL", "", "2026-08-21T00:00:00Z"),
        ]),
        encoding="utf-8",
    )

    text = render_scorecard("Demo", target_dir)

    assert "## Acceptance" in text
    assert "FAILED" in text
    assert "PASS 1   FAIL 1   UNVERIFIED 0   PREPASSED 0   (2 AC total)" in text
    assert "ac-2 — FEATURES.md" in text


def test_release_section_reads_evidence_and_keeps_legacy_markers_for_quarterdeck(tmp_path):
    """quarterdeck_state._scorecard_html parses "- Verdict:" and a "## Project acceptance"
    table by column name; both must survive the rebuild."""
    target_dir = _target(tmp_path)
    record_status(target_dir, "SCORE RELEASE", passed=True, command="drydock score release Demo")
    (target_dir / "SEA_TRIALS.md").write_text(
        """# Sea Trials: Demo

## st-proof: Built behavior
Type: behavioral
Required: yes
Criterion: The built artifact shall contain its marker.
Verification: proof
Pattern: ubiquitous
""",
        encoding="utf-8",
    )
    evidence_dir = target_dir / "evidence"
    evidence_dir.mkdir()
    (evidence_dir / "score-release.json").write_text(
        json.dumps({
            "verdict": "PASSED",
            "statement": "Demo: PASSED — 1 of 1",
            "criteria": [
                {
                    "criterion_id": "st-proof",
                    "verdict": "MET",
                    "rationale": "observed",
                    "evidence": ["pytest returned 0"],
                }
            ],
            "blockers": [],
            "attestations": [],
            "kit_faults": [],
            "warnings": [],
            "improvements": [],
        }),
        encoding="utf-8",
    )

    text = write_scorecard("Demo", target_dir).read_text(encoding="utf-8")

    assert "- Verdict: PASSED" in text
    assert "## Project acceptance" in text
    assert "| st-proof | behavioral | The built artifact shall contain its marker. | MET |" in text


def test_material_decisions_are_included_in_the_release_section(tmp_path):
    target_dir = _target(tmp_path)
    record_status(target_dir, "SCORE RELEASE", passed=True, command="drydock score release Demo")
    (target_dir / DECISIONS_FILENAME).write_text(
        json.dumps([
            {
                "id": "d-1",
                "type": "choice",
                "severity": "material",
                "origin": "plan",
                "blueprint": "ARCHITECTURE.md",
                "story": None,
                "status": "answered",
                "archived": False,
                "title": "Pick a queue",
                "description": "Which queue backend.",
                "options": [],
                "system_choice": "sqlite",
                "commander_direction": None,
                "override_text": None,
            }
        ]),
        encoding="utf-8",
    )

    text = render_scorecard("Demo", target_dir)

    assert "**Material decisions:**" in text
    assert "Pick a queue" in text


def test_a_rebuild_never_loses_another_commands_section(tmp_path):
    """Each command's evidence is independent input; a rebuild after only one command ran must
    still report every other command, not silently drop them."""
    target_dir = _target(tmp_path)
    record_status(target_dir, "SCORE AC", passed=True, command="drydock score ac Demo")

    text = render_scorecard("Demo", target_dir)

    assert "## Specification" in text
    assert "## Acceptance" in text
    assert "## Build" in text
    assert "## Release" in text
    assert text.count("NOT YET RUN") == 3

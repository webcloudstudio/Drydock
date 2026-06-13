"""Tests for the drydock analyze capability."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import pytest

from drydock.analyze import (
    _assemble_prompt,
    _collect_blueprint_files,
    _parse_output,
    analyze,
)
from drydock.errors import SpecificationError

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_VALID_ANALYSIS = """\
# Blueprint Analysis: TestProject
generated: 2026-06-13T00:00:00
blueprint: /some/path

## Project Summary
A test project.

## Project Type
type: web
Signals: SCREEN files present.

## Dependency Graph
| File | Type | Depends On | Provides | Phase |
|------|------|------------|----------|-------|
| COMPASS.md | COMPASS | — | — | — |

## Coverage Assessment
| Check | Status | Notes |
|-------|--------|-------|
| COMPASS.md | pass | present |

## Gaps
- None.

## Spike Candidates
- None.

## Stack Assessment
stack: python/flask
Stack declared and sufficient.

## Readiness Verdict
verdict: ready
All required files present and stack declared.

## Notes
None."""

_VALID_PLANNING_DATA = {
    "id": "planning",
    "title": "Planning Session — Blueprint Questions",
    "purpose": "Resolve unknowns required before plan creation.",
    "questions": [],
}

_VALID_PLANNING_JSON = json.dumps(_VALID_PLANNING_DATA, indent=2)

_VALID_LLM_OUTPUT = (
    f"=== ANALYSIS.md ===\n{_VALID_ANALYSIS}\n=== END ANALYSIS.md ===\n\n"
    f"=== planning.json ===\n{_VALID_PLANNING_JSON}\n=== END planning.json ==="
)

_VALID_LLM_OUTPUT_WITH_QUESTIONS = (
    "=== ANALYSIS.md ===\n"
    + _VALID_ANALYSIS.replace("verdict: ready", "verdict: ready_with_questions")
    + "\n=== END ANALYSIS.md ===\n\n"
    "=== planning.json ===\n"
    + json.dumps(
        {
            **_VALID_PLANNING_DATA,
            "questions": [
                {
                    "id": "stack_declaration",
                    "label": "Stack",
                    "prompt": "What stack?",
                    "input": "text",
                    "gate": "plan_create",
                }
            ],
        },
        indent=2,
    )
    + "\n=== END planning.json ==="
)


@dataclass
class FakeRun:
    ok: bool = True
    text: str = _VALID_LLM_OUTPUT
    execution_id: str = "exec-fake"


def _target(tmp_path: Path, **blueprint_files: str) -> Path:
    target_dir = tmp_path / "MyTarget"
    bp = target_dir / "blueprint"
    bp.mkdir(parents=True)
    for fname, body in blueprint_files.items():
        (bp / fname).write_text(body, encoding="utf-8")
    return target_dir


# ---------------------------------------------------------------------------
# _collect_blueprint_files
# ---------------------------------------------------------------------------


class TestCollectBlueprintFiles:
    def test_returns_spec_files(self, tmp_path):
        bp = tmp_path / "blueprint"
        bp.mkdir()
        (bp / "COMPASS.md").write_text("c", encoding="utf-8")
        (bp / "FEATURE-Auth.md").write_text("f", encoding="utf-8")
        names = [p.name for p in _collect_blueprint_files(bp)]
        assert "COMPASS.md" in names
        assert "FEATURE-Auth.md" in names

    def test_excludes_meta_files(self, tmp_path):
        bp = tmp_path / "blueprint"
        bp.mkdir()
        for name in ("METADATA.md", "README.md", "IDEAS.md"):
            (bp / name).write_text("x", encoding="utf-8")
        assert _collect_blueprint_files(bp) == []

    def test_excludes_build_prefix(self, tmp_path):
        bp = tmp_path / "blueprint"
        bp.mkdir()
        (bp / "BUILD_CONFIGURATION.md").write_text("x", encoding="utf-8")
        (bp / "BUILD_PLAN_COMPASS.md").write_text("x", encoding="utf-8")
        assert _collect_blueprint_files(bp) == []

    def test_returns_sorted(self, tmp_path):
        bp = tmp_path / "blueprint"
        bp.mkdir()
        for name in ("SCREEN-Home.md", "ARCHITECTURE.md", "COMPASS.md"):
            (bp / name).write_text("x", encoding="utf-8")
        names = [p.name for p in _collect_blueprint_files(bp)]
        assert names == sorted(names)


# ---------------------------------------------------------------------------
# _assemble_prompt
# ---------------------------------------------------------------------------


class TestAssemblePrompt:
    def test_contains_job_block(self, tmp_path):
        bp = tmp_path / "blueprint"
        bp.mkdir()
        (bp / "COMPASS.md").write_text("compass content", encoding="utf-8")
        body = "PROMPT BODY"
        result = _assemble_prompt(body, bp, "2026-06-13")
        assert "## Analysis job" in result
        assert "BLUEPRINT_PATH:" in result
        assert "DATE: 2026-06-13" in result

    def test_injects_spec_files_fenced(self, tmp_path):
        bp = tmp_path / "blueprint"
        bp.mkdir()
        (bp / "COMPASS.md").write_text("compass content", encoding="utf-8")
        (bp / "FEATURE-Auth.md").write_text("auth content", encoding="utf-8")
        result = _assemble_prompt("body", bp, "2026-06-13")
        assert "### COMPASS.md" in result
        assert "compass content" in result
        assert "### FEATURE-Auth.md" in result
        assert "auth content" in result

    def test_excludes_build_files(self, tmp_path):
        bp = tmp_path / "blueprint"
        bp.mkdir()
        (bp / "BUILD_CONFIGURATION.md").write_text("should not appear", encoding="utf-8")
        result = _assemble_prompt("body", bp, "2026-06-13")
        assert "should not appear" not in result
        assert "BUILD_CONFIGURATION.md" not in result

    def test_prompt_body_comes_first(self, tmp_path):
        bp = tmp_path / "blueprint"
        bp.mkdir()
        result = _assemble_prompt("MY BODY", bp, "2026-06-13")
        assert result.startswith("MY BODY")


# ---------------------------------------------------------------------------
# _parse_output
# ---------------------------------------------------------------------------


class TestParseOutput:
    def test_valid_output_extracts_correctly(self):
        analysis, data, verdict, count = _parse_output(_VALID_LLM_OUTPUT)
        assert "Blueprint Analysis" in analysis
        assert verdict == "ready"
        assert count == 0
        assert data["id"] == "planning"

    def test_extracts_question_count(self):
        _, _, verdict, count = _parse_output(_VALID_LLM_OUTPUT_WITH_QUESTIONS)
        assert verdict == "ready_with_questions"
        assert count == 1

    def test_missing_analysis_block_raises(self):
        with pytest.raises(ValueError, match="ANALYSIS.md"):
            _parse_output("=== planning.json ===\n{}\n=== END planning.json ===")

    def test_missing_planning_block_raises(self):
        with pytest.raises(ValueError, match="planning.json"):
            _parse_output("=== ANALYSIS.md ===\ncontent\n=== END ANALYSIS.md ===")

    def test_invalid_json_raises(self):
        bad = (
            "=== ANALYSIS.md ===\nverdict: ready\n=== END ANALYSIS.md ===\n"
            "=== planning.json ===\n{bad json\n=== END planning.json ==="
        )
        with pytest.raises(ValueError, match="not valid JSON"):
            _parse_output(bad)

    def test_unknown_verdict_when_absent(self):
        no_verdict = _VALID_LLM_OUTPUT.replace("verdict: ready", "")
        _, _, verdict, _ = _parse_output(no_verdict)
        assert verdict == "unknown"


# ---------------------------------------------------------------------------
# analyze()
# ---------------------------------------------------------------------------


class TestAnalyze:
    def test_writes_analysis_and_planning_files(self, tmp_path):
        target_dir = _target(tmp_path, **{"COMPASS.md": "compass"})
        result = analyze("MyTarget", target_dir, runner=lambda *a, **k: FakeRun())
        assert result.ok
        assert result.analysis_path.exists()
        assert result.planning_path.exists()

    def test_analysis_path_is_under_quarterdeck_planning(self, tmp_path):
        target_dir = _target(tmp_path, **{"COMPASS.md": "compass"})
        result = analyze("MyTarget", target_dir, runner=lambda *a, **k: FakeRun())
        assert "QuarterDeck/planning" in result.analysis_path.as_posix()

    def test_planning_path_is_under_quarterdeck_questionnaires(self, tmp_path):
        target_dir = _target(tmp_path, **{"COMPASS.md": "compass"})
        result = analyze("MyTarget", target_dir, runner=lambda *a, **k: FakeRun())
        assert "QuarterDeck/questionnaires" in result.planning_path.as_posix()

    def test_planning_json_is_valid_json(self, tmp_path):
        target_dir = _target(tmp_path, **{"COMPASS.md": "compass"})
        result = analyze("MyTarget", target_dir, runner=lambda *a, **k: FakeRun())
        data = json.loads(result.planning_path.read_text(encoding="utf-8"))
        assert "questions" in data

    def test_verdict_and_question_count_returned(self, tmp_path):
        target_dir = _target(tmp_path, **{"COMPASS.md": "compass"})
        result = analyze(
            "MyTarget",
            target_dir,
            runner=lambda *a, **k: FakeRun(text=_VALID_LLM_OUTPUT_WITH_QUESTIONS),
        )
        assert result.verdict == "ready_with_questions"
        assert result.question_count == 1

    def test_missing_blueprint_raises(self, tmp_path):
        target_dir = tmp_path / "NoBlueprint"
        target_dir.mkdir()
        with pytest.raises(SpecificationError, match="Blueprint directory not found"):
            analyze("NoBlueprint", target_dir, runner=lambda *a, **k: FakeRun())

    def test_llm_failure_returns_not_ok(self, tmp_path):
        target_dir = _target(tmp_path, **{"COMPASS.md": "compass"})
        result = analyze(
            "MyTarget", target_dir, runner=lambda *a, **k: FakeRun(ok=False, text="")
        )
        assert not result.ok
        assert result.error == "LLM execution failed"
        assert not result.analysis_path.exists()
        assert not result.planning_path.exists()

    def test_parse_failure_returns_not_ok(self, tmp_path):
        target_dir = _target(tmp_path, **{"COMPASS.md": "compass"})
        result = analyze(
            "MyTarget", target_dir, runner=lambda *a, **k: FakeRun(text="garbled output")
        )
        assert not result.ok
        assert result.error is not None
        assert not result.analysis_path.exists()

    def test_idempotent_rerun_overwrites(self, tmp_path):
        target_dir = _target(tmp_path, **{"COMPASS.md": "compass"})

        def runner(*a, **k):
            return FakeRun()

        analyze("MyTarget", target_dir, runner=runner)
        result = analyze("MyTarget", target_dir, runner=runner)
        assert result.ok

    def test_exit_code_zero_on_success(self, tmp_path):
        target_dir = _target(tmp_path, **{"COMPASS.md": "compass"})
        result = analyze("MyTarget", target_dir, runner=lambda *a, **k: FakeRun())
        assert result.exit_code() == 0

    def test_exit_code_one_on_failure(self, tmp_path):
        target_dir = _target(tmp_path, **{"COMPASS.md": "compass"})
        result = analyze(
            "MyTarget", target_dir, runner=lambda *a, **k: FakeRun(ok=False, text="")
        )
        assert result.exit_code() == 1


# ---------------------------------------------------------------------------
# CLI contract
# ---------------------------------------------------------------------------


class TestAnalyzeCli:
    def test_help_exits_zero_and_shows_target(self):
        import subprocess
        import sys

        r = subprocess.run(
            [sys.executable, "-m", "drydock", "analyze", "--help"],
            capture_output=True,
            text=True,
        )
        assert r.returncode == 0
        assert "Target" in r.stdout or "Target" in r.stderr

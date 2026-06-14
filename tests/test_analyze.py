"""Tests for the drydock analyze capability."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import pytest

from drydock.analyze import (
    _assemble_prompt,
    _collect_blueprint_files,
    _parse_blocks,
    _parse_output,
    analyze,
)
from drydock.errors import SpecificationError

# ---------------------------------------------------------------------------
# Minimal valid LLM output helpers
# ---------------------------------------------------------------------------

_ANALYSIS_CONTENT = """\
# Blueprint Analysis: TestProject
generated: 2026-06-14
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

## Open Questions
- None.

## Stack Assessment
stack: python/flask
Stack declared and sufficient.

## Readiness Verdict
verdict: ready
All required files present and stack declared.

## Notes
None."""

_SEA_TRIALS_CONTENT = """\
# Sea Trials: TestProject

| ID | Objective / Success Criterion | State | Evidence |
|---|---|---|---|
| st-001 | System is operational | NOT STARTED | |"""

_SOUNDINGS_CONTENT = """\
# Soundings

| ID | Acceptance Criterion | State | Evidence |
|---|---|---|---|
| ac-login-001 | User can log in | NOT STARTED | |"""

_COMPASS_CONTENT = """\
# COMPASS: TestProject

## Compass
A test project compass.

## Constraints
- None stated.

## Success Criteria
- System operational."""

_SPIKE_INTENT = json.dumps({
    "id": "spike-intent",
    "title": "Spike: Product Intent",
    "purpose": "Clarify intent.",
    "questions": [{"id": "primary_goal", "label": "Primary Goal", "prompt": "What?", "input": "textarea"}],
}, indent=2)

_SPIKE_STACK = json.dumps({
    "id": "spike-stack",
    "title": "Spike: Technology Stack",
    "purpose": "Confirm stack.",
    "questions": [{"id": "stack_confirmed", "label": "Stack", "prompt": "What stack?", "input": "textarea"}],
}, indent=2)

_SPIKE_GAPS_AC = json.dumps({
    "id": "spike-gaps-ac",
    "title": "Spike: Gaps and Acceptance Criteria",
    "purpose": "Identify gaps.",
    "questions": [{"id": "missing_specs", "label": "Missing Specs", "prompt": "What is missing?", "input": "textarea"}],
}, indent=2)

_SPIKE_GUARDRAILS = json.dumps({
    "id": "spike-guardrails",
    "title": "Spike: Guardrails",
    "purpose": "Surface constraints.",
    "questions": [{"id": "security_requirements", "label": "Security", "prompt": "What security?", "input": "textarea"}],
}, indent=2)


def _make_llm_output(*, include_compass: bool = True, extra_spike: bool = False) -> str:
    blocks = [
        f"=== ANALYSIS.md ===\n{_ANALYSIS_CONTENT}\n=== END ANALYSIS.md ===",
        f"=== SEA_TRIALS.md ===\n{_SEA_TRIALS_CONTENT}\n=== END SEA_TRIALS.md ===",
        f"=== SOUNDINGS.md ===\n{_SOUNDINGS_CONTENT}\n=== END SOUNDINGS.md ===",
        f"=== spike-intent.json ===\n{_SPIKE_INTENT}\n=== END spike-intent.json ===",
        f"=== spike-stack.json ===\n{_SPIKE_STACK}\n=== END spike-stack.json ===",
        f"=== spike-gaps-ac.json ===\n{_SPIKE_GAPS_AC}\n=== END spike-gaps-ac.json ===",
        f"=== spike-guardrails.json ===\n{_SPIKE_GUARDRAILS}\n=== END spike-guardrails.json ===",
    ]
    if include_compass:
        blocks.insert(3, f"=== COMPASS.md ===\n{_COMPASS_CONTENT}\n=== END COMPASS.md ===")
    if extra_spike:
        extra = json.dumps({"id": "spike-auth", "title": "Spike: Auth", "purpose": "Auth model.", "questions": []}, indent=2)
        blocks.append(f"=== spike-auth.json ===\n{extra}\n=== END spike-auth.json ===")
    return "\n\n".join(blocks)


_VALID_LLM_OUTPUT = _make_llm_output(include_compass=True)
_VALID_LLM_OUTPUT_NO_COMPASS = _make_llm_output(include_compass=False)


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
        assert "COMPASS.md" not in names  # COMPASS lives at target root, not blueprint
        assert "FEATURE-Auth.md" in names

    def test_excludes_meta_files(self, tmp_path):
        bp = tmp_path / "blueprint"
        bp.mkdir()
        for name in ("METADATA.md", "README.md", "IDEAS.md", "COMPASS.md", "ACCEPTANCE_CRITERIA.md"):
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
        for name in ("SCREEN-Home.md", "ARCHITECTURE.md", "FEATURE-Login.md"):
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
        result = _assemble_prompt("PROMPT BODY", bp, "2026-06-14", compass_exists=False)
        assert "## Analysis job" in result
        assert "BLUEPRINT_PATH:" in result
        assert "DATE: 2026-06-14" in result
        assert "COMPASS_EXISTS: false" in result

    def test_compass_exists_flag_true(self, tmp_path):
        bp = tmp_path / "blueprint"
        bp.mkdir()
        result = _assemble_prompt("body", bp, "2026-06-14", compass_exists=True)
        assert "COMPASS_EXISTS: true" in result

    def test_injects_spec_files_fenced(self, tmp_path):
        bp = tmp_path / "blueprint"
        bp.mkdir()
        (bp / "COMPASS.md").write_text("compass content", encoding="utf-8")
        (bp / "FEATURE-Auth.md").write_text("auth content", encoding="utf-8")
        result = _assemble_prompt("body", bp, "2026-06-14", compass_exists=False)
        assert "### COMPASS.md" not in result   # blueprint COMPASS.md is skipped
        assert "compass content" not in result
        assert "### FEATURE-Auth.md" in result
        assert "auth content" in result

    def test_excludes_build_files(self, tmp_path):
        bp = tmp_path / "blueprint"
        bp.mkdir()
        (bp / "BUILD_CONFIGURATION.md").write_text("should not appear", encoding="utf-8")
        result = _assemble_prompt("body", bp, "2026-06-14", compass_exists=False)
        assert "should not appear" not in result

    def test_prompt_body_comes_first(self, tmp_path):
        bp = tmp_path / "blueprint"
        bp.mkdir()
        result = _assemble_prompt("MY BODY", bp, "2026-06-14", compass_exists=False)
        assert result.startswith("MY BODY")


# ---------------------------------------------------------------------------
# _parse_blocks
# ---------------------------------------------------------------------------


class TestParseBlocks:
    def test_parses_single_block(self):
        text = "=== foo.md ===\ncontent here\n=== END foo.md ==="
        blocks = _parse_blocks(text)
        assert blocks == {"foo.md": "content here"}

    def test_parses_multiple_blocks(self):
        text = "=== A.md ===\nalpha\n=== END A.md ===\n\n=== B.json ===\nbeta\n=== END B.json ==="
        blocks = _parse_blocks(text)
        assert blocks["A.md"] == "alpha"
        assert blocks["B.json"] == "beta"

    def test_strips_whitespace(self):
        text = "=== x.md ===\n\n  content  \n\n=== END x.md ==="
        blocks = _parse_blocks(text)
        assert blocks["x.md"] == "content"


# ---------------------------------------------------------------------------
# _parse_output
# ---------------------------------------------------------------------------


class TestParseOutput:
    def test_valid_output_extracts_all_fields(self):
        analysis, sea_trials, soundings, compass, spikes, verdict = _parse_output(_VALID_LLM_OUTPUT)
        assert "Blueprint Analysis" in analysis
        assert "Sea Trials" in sea_trials
        assert "Soundings" in soundings
        assert compass is not None
        assert "COMPASS" in compass
        assert verdict == "ready"
        assert "spike-intent.json" in spikes
        assert "spike-stack.json" in spikes
        assert "spike-gaps-ac.json" in spikes
        assert "spike-guardrails.json" in spikes

    def test_no_compass_block_returns_none(self):
        _, _, _, compass, _, _ = _parse_output(_VALID_LLM_OUTPUT_NO_COMPASS)
        assert compass is None

    def test_missing_analysis_block_raises(self):
        truncated = _VALID_LLM_OUTPUT.replace("=== ANALYSIS.md ===", "").replace("=== END ANALYSIS.md ===", "")
        with pytest.raises(ValueError, match="ANALYSIS.md"):
            _parse_output(truncated)

    def test_missing_sea_trials_raises(self):
        truncated = _VALID_LLM_OUTPUT.replace("=== SEA_TRIALS.md ===", "").replace("=== END SEA_TRIALS.md ===", "")
        with pytest.raises(ValueError, match="SEA_TRIALS.md"):
            _parse_output(truncated)

    def test_missing_soundings_raises(self):
        truncated = _VALID_LLM_OUTPUT.replace("=== SOUNDINGS.md ===", "").replace("=== END SOUNDINGS.md ===", "")
        with pytest.raises(ValueError, match="SOUNDINGS.md"):
            _parse_output(truncated)

    def test_missing_fixed_spike_raises(self):
        truncated = _VALID_LLM_OUTPUT.replace("=== spike-intent.json ===", "").replace("=== END spike-intent.json ===", "")
        with pytest.raises(ValueError, match="spike-intent.json"):
            _parse_output(truncated)

    def test_invalid_spike_json_raises(self):
        bad = _VALID_LLM_OUTPUT.replace(_SPIKE_INTENT, "{bad json")
        with pytest.raises(ValueError, match="not valid JSON"):
            _parse_output(bad)

    def test_unknown_verdict_when_absent(self):
        no_verdict = _VALID_LLM_OUTPUT.replace("verdict: ready", "")
        _, _, _, _, _, verdict = _parse_output(no_verdict)
        assert verdict == "unknown"

    def test_variable_spikes_collected(self):
        output = _make_llm_output(extra_spike=True)
        _, _, _, _, spikes, _ = _parse_output(output)
        assert "spike-auth.json" in spikes


# ---------------------------------------------------------------------------
# analyze()
# ---------------------------------------------------------------------------


class TestAnalyze:
    def test_writes_all_core_artifacts(self, tmp_path):
        target_dir = _target(tmp_path, **{"COMPASS.md": "compass"})
        result = analyze("MyTarget", target_dir, runner=lambda *a, **k: FakeRun())
        assert result.ok
        assert result.analysis_path.exists()
        assert result.sea_trials_path.exists()
        assert result.soundings_path.exists()

    def test_analysis_path_is_under_quarterdeck_planning(self, tmp_path):
        target_dir = _target(tmp_path, **{"COMPASS.md": "compass"})
        result = analyze("MyTarget", target_dir, runner=lambda *a, **k: FakeRun())
        assert "QuarterDeck/planning" in result.analysis_path.as_posix()

    def test_sea_trials_at_target_root(self, tmp_path):
        target_dir = _target(tmp_path, **{"COMPASS.md": "compass"})
        result = analyze("MyTarget", target_dir, runner=lambda *a, **k: FakeRun())
        assert result.sea_trials_path == target_dir / "SEA_TRIALS.md"

    def test_soundings_at_target_root(self, tmp_path):
        target_dir = _target(tmp_path, **{"COMPASS.md": "compass"})
        result = analyze("MyTarget", target_dir, runner=lambda *a, **k: FakeRun())
        assert result.soundings_path == target_dir / "SOUNDINGS.md"

    def test_compass_written_when_absent(self, tmp_path):
        target_dir = _target(tmp_path, **{"FEATURE-Auth.md": "auth"})
        result = analyze("MyTarget", target_dir, runner=lambda *a, **k: FakeRun())
        assert result.ok
        assert result.compass_path == target_dir / "COMPASS.md"
        assert result.compass_path.exists()

    def test_compass_not_overwritten_when_present(self, tmp_path):
        target_dir = _target(tmp_path, **{"COMPASS.md": "existing"})
        (target_dir / "COMPASS.md").write_text("original content\n", encoding="utf-8")
        result = analyze("MyTarget", target_dir, runner=lambda *a, **k: FakeRun())
        assert result.ok
        assert result.compass_path is None
        assert (target_dir / "COMPASS.md").read_text(encoding="utf-8") == "original content\n"

    def test_four_fixed_spikes_written(self, tmp_path):
        target_dir = _target(tmp_path, **{"COMPASS.md": "compass"})
        analyze("MyTarget", target_dir, runner=lambda *a, **k: FakeRun())
        questionnaires = target_dir / "QuarterDeck" / "questionnaires"
        for name in ("spike-intent.json", "spike-stack.json", "spike-gaps-ac.json", "spike-guardrails.json"):
            assert (questionnaires / name).exists(), f"{name} not written"

    def test_spike_paths_in_result(self, tmp_path):
        target_dir = _target(tmp_path, **{"COMPASS.md": "compass"})
        result = analyze("MyTarget", target_dir, runner=lambda *a, **k: FakeRun())
        assert len(result.spike_paths) >= 4

    def test_spike_files_are_valid_json(self, tmp_path):
        target_dir = _target(tmp_path, **{"COMPASS.md": "compass"})
        result = analyze("MyTarget", target_dir, runner=lambda *a, **k: FakeRun())
        for path in result.spike_paths:
            data = json.loads(path.read_text(encoding="utf-8"))
            assert "questions" in data

    def test_variable_spike_written(self, tmp_path):
        target_dir = _target(tmp_path, **{"COMPASS.md": "compass"})
        output = _make_llm_output(extra_spike=True)
        analyze("MyTarget", target_dir, runner=lambda *a, **k: FakeRun(text=output))
        questionnaires = target_dir / "QuarterDeck" / "questionnaires"
        assert (questionnaires / "spike-auth.json").exists()

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

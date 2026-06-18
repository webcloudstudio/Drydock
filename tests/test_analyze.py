"""Tests for the drydock analyze capability."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import pytest

from drydock.analyze import (
    _assemble_prompt,
    _collect_blueprint_files,
    _fill_captains_chair,
    _is_compass_unpopulated,
    _parse_blocks,
    _parse_output,
    _remove_open_questions_section,
    _validate_blockers,
    analyze,
    ensure_feedback_file,
)
from drydock.errors import SpecificationError

# ---------------------------------------------------------------------------
# Minimal valid LLM output helpers
# ---------------------------------------------------------------------------


def test_default_feedback_heading_is_analysis_compass(tmp_path):
    assert ensure_feedback_file(tmp_path).startswith("# Analysis Compass\n\n")


def test_open_questions_section_is_removed_from_analysis_output():
    result = _remove_open_questions_section(_ANALYSIS_CONTENT)

    assert "## Open Questions" not in result
    assert "## Story List" in result
    assert "## Notes" in result


_ANALYSIS_CONTENT = """\
# Blueprint Analysis: TestProject
generated: 2026-06-14
blueprint: /some/path

Quality: Ready
  blockers: 0
  questions: 0
  stories: 5
  stack: python/flask
  screens: 2

## Open Questions

- None.

## Story List

| Area | Story |
|------|-------|
| Auth | User login |
| Auth | User registration |
| Dashboard | Dashboard view |
| API | REST endpoints |
| UI | Login screen |

### Tuning Options
- Option A: Decompose by feature (recommended)
- Option B: Decompose by layer

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

_SPIKE_INTENT = json.dumps(
    {
        "id": "spike-intent",
        "title": "Spike: Product Intent",
        "purpose": "Clarify intent.",
        "questions": [
            {"id": "primary_goal", "label": "Primary Goal", "prompt": "What?", "input": "textarea"}
        ],
    },
    indent=2,
)

_SPIKE_STACK = json.dumps(
    {
        "id": "spike-stack",
        "title": "Spike: Technology Stack",
        "purpose": "Confirm stack.",
        "questions": [
            {
                "id": "stack_confirmed",
                "label": "Stack",
                "prompt": "What stack?",
                "input": "textarea",
            }
        ],
    },
    indent=2,
)

_SPIKE_GAPS_AC = json.dumps(
    {
        "id": "spike-gaps-ac",
        "title": "Spike: Gaps and Acceptance Criteria",
        "purpose": "Identify gaps.",
        "questions": [
            {
                "id": "missing_specs",
                "label": "Missing Specs",
                "prompt": "What is missing?",
                "input": "textarea",
            }
        ],
    },
    indent=2,
)

_SPIKE_GUARDRAILS = json.dumps(
    {
        "id": "spike-guardrails",
        "title": "Spike: Guardrails",
        "purpose": "Surface constraints.",
        "questions": [
            {
                "id": "security_requirements",
                "label": "Security",
                "prompt": "What security?",
                "input": "textarea",
            }
        ],
    },
    indent=2,
)


_ANALYSIS_CONTENT_BLOCKED = """\
# Blueprint Analysis: TestProject
generated: 2026-06-14
blueprint: /some/path

Quality: Blocked
  blockers: 1
  questions: 0
  stories: 0
  stack: not declared
  screens: 0

## Open Questions

- None.

## Story List

No stories can be derived until blockers are resolved.

### Tuning Options
- N/A

## Notes

None."""


_BLOCKERS_CONTENT = """\
# Blockers: TestProject

## blocker-001: Missing project name
No project name is stated. The product cannot be built without a name.

**Answer:**"""


def _make_llm_output(
    *,
    include_compass: bool = True,
    include_spikes: bool = True,
    extra_spike: bool = False,
    quality: str = "Ready",
    analysis_override: str | None = None,
    blockers: str | None = None,
) -> str:
    if analysis_override is not None:
        analysis = analysis_override
    else:
        analysis = _ANALYSIS_CONTENT.replace("Quality: Ready", f"Quality: {quality}")
    blocks = [
        f"=== ANALYSIS.md ===\n{analysis}\n=== END ANALYSIS.md ===",
        f"=== SEA_TRIALS.md ===\n{_SEA_TRIALS_CONTENT}\n=== END SEA_TRIALS.md ===",
        f"=== SOUNDINGS.md ===\n{_SOUNDINGS_CONTENT}\n=== END SOUNDINGS.md ===",
    ]
    if include_spikes:
        blocks += [
            f"=== spike-intent.json ===\n{_SPIKE_INTENT}\n=== END spike-intent.json ===",
            f"=== spike-stack.json ===\n{_SPIKE_STACK}\n=== END spike-stack.json ===",
            f"=== spike-gaps-ac.json ===\n{_SPIKE_GAPS_AC}\n=== END spike-gaps-ac.json ===",
            f"=== spike-guardrails.json ===\n{_SPIKE_GUARDRAILS}\n=== END spike-guardrails.json ===",
        ]
    if include_compass:
        blocks.insert(3, f"=== COMPASS.md ===\n{_COMPASS_CONTENT}\n=== END COMPASS.md ===")
    if blockers is not None:
        blocks.append(f"=== BLOCKERS.md ===\n{blockers}\n=== END BLOCKERS.md ===")
    if extra_spike:
        extra = json.dumps(
            {"id": "spike-auth", "title": "Spike: Auth", "purpose": "Auth model.", "questions": []},
            indent=2,
        )
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
# _is_compass_unpopulated
# ---------------------------------------------------------------------------


class TestIsCompassUnpopulated:
    def test_nonexistent_file_returns_false(self, tmp_path):
        assert not _is_compass_unpopulated(tmp_path / "COMPASS.md")

    def test_html_comment_placeholder_returns_true(self, tmp_path):
        p = tmp_path / "COMPASS.md"
        p.write_text("# COMPASS\n\n## Compass\n<!-- fill me in -->\n", encoding="utf-8")
        assert _is_compass_unpopulated(p)

    def test_all_none_sections_returns_true(self, tmp_path):
        p = tmp_path / "COMPASS.md"
        p.write_text(
            "# COMPASS\n\n## Compass\n- None.\n\n## Constraints\n- None.\n", encoding="utf-8"
        )
        assert _is_compass_unpopulated(p)

    def test_populated_file_returns_false(self, tmp_path):
        p = tmp_path / "COMPASS.md"
        p.write_text("# COMPASS\n\n## Compass\nThis is a real project.\n", encoding="utf-8")
        assert not _is_compass_unpopulated(p)

    def test_mixed_content_returns_false(self, tmp_path):
        p = tmp_path / "COMPASS.md"
        p.write_text(
            "# COMPASS\n\n## Compass\nA real project.\n\n## Constraints\n- None.\n",
            encoding="utf-8",
        )
        assert not _is_compass_unpopulated(p)


# ---------------------------------------------------------------------------
# _collect_blueprint_files
# ---------------------------------------------------------------------------


class TestCollectBlueprintFiles:
    def test_returns_imported_sources(self, tmp_path):
        bp = tmp_path / "blueprint"
        sources = bp / "sources"
        sources.mkdir(parents=True)
        (sources / "spec.md").write_text("content", encoding="utf-8")
        names = [p.name for p in _collect_blueprint_files(bp)]
        assert names == ["spec.md"]

    def test_no_sources_dir_returns_empty(self, tmp_path):
        bp = tmp_path / "blueprint"
        bp.mkdir()
        (bp / "FEATURE-Auth.md").write_text("f", encoding="utf-8")
        assert _collect_blueprint_files(bp) == []

    def test_empty_sources_dir_returns_empty(self, tmp_path):
        bp = tmp_path / "blueprint"
        (bp / "sources").mkdir(parents=True)
        assert _collect_blueprint_files(bp) == []

    def test_returns_sorted_recursive(self, tmp_path):
        bp = tmp_path / "blueprint"
        sources = bp / "sources"
        sources.mkdir(parents=True)
        for name in ("zzz.md", "aaa.md", "mmm.md"):
            (sources / name).write_text("x", encoding="utf-8")
        paths = _collect_blueprint_files(bp)
        assert paths == sorted(paths)

    def test_returns_subdirectory_files(self, tmp_path):
        bp = tmp_path / "blueprint"
        sub = bp / "sources" / "sub"
        sub.mkdir(parents=True)
        (sub / "deep.md").write_text("d", encoding="utf-8")
        names = [p.name for p in _collect_blueprint_files(bp)]
        assert "deep.md" in names


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

    def test_injects_source_files_fenced(self, tmp_path):
        bp = tmp_path / "blueprint"
        sources = bp / "sources"
        sources.mkdir(parents=True)
        (sources / "spec.md").write_text("imported content", encoding="utf-8")
        result = _assemble_prompt("body", bp, "2026-06-14", compass_exists=False)
        assert "### spec.md" in result
        assert "imported content" in result

    def test_top_level_blueprint_files_not_injected(self, tmp_path):
        bp = tmp_path / "blueprint"
        bp.mkdir()
        (bp / "FEATURE-Auth.md").write_text("should not appear", encoding="utf-8")
        result = _assemble_prompt("body", bp, "2026-06-14", compass_exists=False)
        assert "### FEATURE-Auth.md" not in result
        assert "should not appear" not in result

    def test_injects_feedback_directive_when_provided(self, tmp_path):
        bp = tmp_path / "blueprint"
        bp.mkdir()
        result = _assemble_prompt(
            "body",
            bp,
            "2026-06-14",
            compass_exists=False,
            feedback_text="Decompose by module, not by route.",
        )
        assert "Analysis feedback (standing directive)" in result
        assert "Decompose by module, not by route." in result

    def test_no_feedback_section_when_absent(self, tmp_path):
        bp = tmp_path / "blueprint"
        bp.mkdir()
        result = _assemble_prompt("body", bp, "2026-06-14", compass_exists=False)
        assert "Analysis feedback (standing directive)" not in result

    def test_build_configuration_is_not_injected(self, tmp_path):
        bp = tmp_path / "blueprint"
        bp.mkdir()
        (bp / "BUILD_CONFIGURATION.md").write_text("stack: flask\n", encoding="utf-8")
        result = _assemble_prompt("body", bp, "2026-06-14", compass_exists=False)
        assert "BUILD_CONFIGURATION" not in result
        assert "Prior PO answers" not in result

    def test_prompt_body_comes_first(self, tmp_path):
        bp = tmp_path / "blueprint"
        bp.mkdir()
        result = _assemble_prompt("MY BODY", bp, "2026-06-14", compass_exists=False)
        assert result.startswith("MY BODY")

    def test_injects_blockers_text_when_provided(self, tmp_path):
        bp = tmp_path / "blueprint"
        bp.mkdir()
        result = _assemble_prompt(
            "body",
            bp,
            "2026-06-14",
            compass_exists=False,
            blockers_text="# Blockers\n\n- No name provided.",
        )
        assert "Prior blocker answers" in result
        assert "No name provided" in result

    def test_no_blockers_section_when_absent(self, tmp_path):
        bp = tmp_path / "blueprint"
        bp.mkdir()
        result = _assemble_prompt("body", bp, "2026-06-14", compass_exists=False)
        assert "Prior blocker answers" not in result

    def test_feedback_injected_before_blockers(self, tmp_path):
        bp = tmp_path / "blueprint"
        bp.mkdir()
        result = _assemble_prompt(
            "body",
            bp,
            "2026-06-14",
            compass_exists=False,
            feedback_text="Steer this way.",
            blockers_text="- No name.",
        )
        assert result.index("Analysis feedback (standing directive)") < result.index(
            "Prior blocker answers"
        )

    def test_injection_order_is_driven_by_input_tokens(self, tmp_path):
        bp = tmp_path / "blueprint"
        sources = bp / "sources"
        sources.mkdir(parents=True)
        (sources / "spec.md").write_text("imported content", encoding="utf-8")
        # Reverse the declared order: sources before the feedback directive.
        result = _assemble_prompt(
            "body",
            bp,
            "2026-06-14",
            compass_exists=False,
            feedback_text="Steer this way.",
            input_tokens=("TYPED_SPEC", "ANALYSIS_COMPASS.md"),
        )
        assert result.index("Imported source files") < result.index(
            "Analysis feedback (standing directive)"
        )

    def test_compass_token_injects_no_content_section(self, tmp_path):
        # COMPASS.md is the COMPASS_EXISTS flag for analyze, not a fenced content block.
        bp = tmp_path / "blueprint"
        bp.mkdir()
        result = _assemble_prompt(
            "body", bp, "2026-06-14", compass_exists=True, input_tokens=("COMPASS.md",)
        )
        assert "COMPASS_EXISTS: true" in result
        assert "## COMPASS.md" not in result


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
        analysis, sea_trials, soundings, compass, blockers, spikes, quality, summary = (
            _parse_output(_VALID_LLM_OUTPUT)
        )
        assert "Blueprint Analysis" in analysis
        assert "Sea Trials" in sea_trials
        assert "Soundings" in soundings
        assert compass is not None
        assert "COMPASS" in compass
        assert blockers is None
        assert quality == "Ready"
        assert "spike-intent.json" in spikes
        assert "spike-stack.json" in spikes
        assert "spike-gaps-ac.json" in spikes
        assert "spike-guardrails.json" in spikes

    def test_summary_fields_parsed(self):
        _, _, _, _, _, _, _, summary = _parse_output(_VALID_LLM_OUTPUT)
        assert summary.get("stories") == "5"
        assert summary.get("blockers") == "0"
        assert summary.get("questions") == "0"
        assert summary.get("stack") == "python/flask"
        assert summary.get("screens") == "2"

    def test_blocked_quality_parsed(self):
        output = _make_llm_output(quality="Blocked")
        _, _, _, _, _, _, quality, _ = _parse_output(output)
        assert quality == "Blocked"

    def test_questions_quality_parsed(self):
        output = _make_llm_output(quality="Questions")
        _, _, _, _, _, _, quality, _ = _parse_output(output)
        assert quality == "Questions"

    def test_no_compass_block_returns_none(self):
        _, _, _, compass, _, _, _, _ = _parse_output(_VALID_LLM_OUTPUT_NO_COMPASS)
        assert compass is None

    def test_blockers_block_returned_when_present(self):
        output = _make_llm_output(blockers=_BLOCKERS_CONTENT)
        _, _, _, _, blockers, _, _, _ = _parse_output(output)
        assert blockers is not None
        assert "Missing project name" in blockers

    def test_placeholder_blockers_block_returns_none(self):
        # Regression (FIX-10): the LLM emitted the block with placeholder text instead of
        # omitting it; the writer must treat it as "no blockers" so its existence stays a real flag.
        output = _make_llm_output(blockers="(omitted — no blockers)")
        _, _, _, _, blockers, _, _, _ = _parse_output(output)
        assert blockers is None

    def test_titleonly_blockers_block_returns_none(self):
        # Heading prose but no "## " blocker entry → not a genuine blocker list.
        output = _make_llm_output(blockers="# Blockers: TestProject\n\nNo blockers found.")
        _, _, _, _, blockers, _, _, _ = _parse_output(output)
        assert blockers is None

    def test_missing_analysis_block_raises(self):
        truncated = _VALID_LLM_OUTPUT.replace("=== ANALYSIS.md ===", "").replace(
            "=== END ANALYSIS.md ===", ""
        )
        with pytest.raises(ValueError, match="ANALYSIS.md"):
            _parse_output(truncated)

    def test_missing_sea_trials_raises(self):
        truncated = _VALID_LLM_OUTPUT.replace("=== SEA_TRIALS.md ===", "").replace(
            "=== END SEA_TRIALS.md ===", ""
        )
        with pytest.raises(ValueError, match="SEA_TRIALS.md"):
            _parse_output(truncated)

    def test_missing_soundings_raises(self):
        truncated = _VALID_LLM_OUTPUT.replace("=== SOUNDINGS.md ===", "").replace(
            "=== END SOUNDINGS.md ===", ""
        )
        with pytest.raises(ValueError, match="SOUNDINGS.md"):
            _parse_output(truncated)

    def test_no_spikes_is_tolerated(self):
        # Spikes are emitted dynamically; an analysis with nothing open is valid.
        output = _make_llm_output(include_spikes=False)
        _, _, _, _, _, spikes, _, _ = _parse_output(output)
        assert spikes == {}

    def test_invalid_spike_json_raises(self):
        bad = _VALID_LLM_OUTPUT.replace(_SPIKE_INTENT, "{bad json")
        with pytest.raises(ValueError, match="not valid JSON"):
            _parse_output(bad)

    def test_unknown_quality_when_absent(self):
        no_quality = _VALID_LLM_OUTPUT.replace("Quality: Ready", "")
        _, _, _, _, _, _, quality, _ = _parse_output(no_quality)
        assert quality == "unknown"

    def test_variable_spikes_collected(self):
        output = _make_llm_output(extra_spike=True)
        _, _, _, _, _, spikes, _, _ = _parse_output(output)
        assert "spike-auth.json" in spikes


# ---------------------------------------------------------------------------
# _validate_blockers  (FIX-10: existence is the only signal)
# ---------------------------------------------------------------------------


class TestValidateBlockers:
    def test_genuine_blocker_list_accepted(self):
        assert _validate_blockers(_BLOCKERS_CONTENT) == _BLOCKERS_CONTENT

    def test_none_returns_none(self):
        assert _validate_blockers(None) is None

    def test_empty_returns_none(self):
        assert _validate_blockers("") is None
        assert _validate_blockers("   \n  ") is None

    def test_placeholder_text_returns_none(self):
        assert _validate_blockers("(omitted — no blockers)") is None

    def test_heading_without_blocker_entry_returns_none(self):
        assert _validate_blockers("# Blockers: P\n\nNone found.") is None


# ---------------------------------------------------------------------------
# _fill_captains_chair
# ---------------------------------------------------------------------------


class TestFillCaptainsChair:
    _TEMPLATE = (
        "{{PROJECT_NAME}}|{{QUALITY}}|{{QUALITY_CSS}}|{{QUALITY_ICON}}|"
        "{{STORY_COUNT}}|{{QUESTION_COUNT}}|{{BLOCKER_COUNT}}|{{SCREEN_COUNT}}|"
        "{{STACK}}|{{NEXT_STEP}}|{{GENERATED_DATE}}"
    )

    def test_ready_fill(self):
        result = _fill_captains_chair(
            self._TEMPLATE,
            quality="Ready",
            story_count=10,
            question_count=0,
            blocker_count=0,
            screen_count=3,
            stack="python/flask",
            next_step="drydock plan create Foo",
            project_name="Foo",
            generated_date="2026-06-14",
        )
        assert "Foo" in result
        assert "Ready" in result
        assert "ready" in result
        assert "✓" in result
        assert "10" in result
        assert "python/flask" in result

    def test_blocked_css_class(self):
        result = _fill_captains_chair(
            "{{QUALITY_CSS}}|{{QUALITY_ICON}}",
            quality="Blocked",
            story_count=0,
            question_count=0,
            blocker_count=1,
            screen_count=0,
            stack="",
            next_step="",
            project_name="X",
            generated_date="",
        )
        assert "blocked" in result
        assert "✗" in result

    def test_questions_css_class(self):
        result = _fill_captains_chair(
            "{{QUALITY_CSS}}|{{QUALITY_ICON}}",
            quality="Questions",
            story_count=0,
            question_count=2,
            blocker_count=0,
            screen_count=0,
            stack="",
            next_step="",
            project_name="X",
            generated_date="",
        )
        assert "questions" in result
        assert "⚠" in result


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
        assert "## Open Questions" not in result.analysis_path.read_text(encoding="utf-8")

    def test_analysis_path_is_at_target_root(self, tmp_path):
        target_dir = _target(tmp_path, **{"COMPASS.md": "compass"})
        result = analyze("MyTarget", target_dir, runner=lambda *a, **k: FakeRun())
        assert result.analysis_path == target_dir / "ANALYSIS.md"

    def test_sea_trials_at_target_root(self, tmp_path):
        target_dir = _target(tmp_path, **{"COMPASS.md": "compass"})
        result = analyze("MyTarget", target_dir, runner=lambda *a, **k: FakeRun())
        assert result.sea_trials_path == target_dir / "SEA_TRIALS.md"

    def test_soundings_at_target_root(self, tmp_path):
        target_dir = _target(tmp_path, **{"COMPASS.md": "compass"})
        result = analyze("MyTarget", target_dir, runner=lambda *a, **k: FakeRun())
        assert result.soundings_path == target_dir / "SOUNDINGS.md"

    def test_quality_signal_in_result(self, tmp_path):
        target_dir = _target(tmp_path, **{"COMPASS.md": "compass"})
        result = analyze("MyTarget", target_dir, runner=lambda *a, **k: FakeRun())
        assert result.quality == "Ready"

    def test_summary_counts_in_result(self, tmp_path):
        target_dir = _target(tmp_path, **{"COMPASS.md": "compass"})
        result = analyze("MyTarget", target_dir, runner=lambda *a, **k: FakeRun())
        assert result.story_count == 5
        assert result.blocker_count == 0
        assert result.question_count == 0
        assert result.screen_count == 2
        assert result.stack == "python/flask"

    def test_compass_written_when_absent(self, tmp_path):
        target_dir = _target(tmp_path, **{"FEATURE-Auth.md": "auth"})
        result = analyze("MyTarget", target_dir, runner=lambda *a, **k: FakeRun())
        assert result.ok
        assert result.compass_path == target_dir / "COMPASS.md"
        assert result.compass_path.exists()

    def test_compass_written_when_unpopulated_template(self, tmp_path):
        target_dir = _target(tmp_path, **{"FEATURE-Auth.md": "auth"})
        compass = target_dir / "COMPASS.md"
        compass.write_text("# COMPASS\n\n## Compass\n<!-- fill me in -->\n", encoding="utf-8")
        result = analyze("MyTarget", target_dir, runner=lambda *a, **k: FakeRun())
        assert result.ok
        assert result.compass_path is not None

    def test_compass_not_overwritten_when_present(self, tmp_path):
        target_dir = _target(tmp_path, **{"FEATURE-Auth.md": "auth"})
        (target_dir / "COMPASS.md").write_text(
            "# COMPASS\n\n## Compass\nReal content.\n", encoding="utf-8"
        )
        result = analyze("MyTarget", target_dir, runner=lambda *a, **k: FakeRun())
        assert result.ok
        assert result.compass_path is None
        assert (target_dir / "COMPASS.md").read_text(encoding="utf-8").startswith("# COMPASS")

    def test_emitted_spikes_written(self, tmp_path):
        target_dir = _target(tmp_path, **{"COMPASS.md": "compass"})
        analyze("MyTarget", target_dir, runner=lambda *a, **k: FakeRun())
        questionnaires = target_dir / "QuarterDeck" / "questionnaires"
        for name in (
            "spike-intent.json",
            "spike-stack.json",
            "spike-gaps-ac.json",
            "spike-guardrails.json",
        ):
            assert (questionnaires / name).exists(), f"{name} not written"

    def test_no_spikes_emitted_is_ok(self, tmp_path):
        target_dir = _target(tmp_path, **{"COMPASS.md": "compass"})
        output = _make_llm_output(include_spikes=False)
        result = analyze("MyTarget", target_dir, runner=lambda *a, **k: FakeRun(text=output))
        assert result.ok
        assert result.spike_paths == ()

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

    def test_blockers_md_written_when_blocked(self, tmp_path):
        target_dir = _target(tmp_path, **{"COMPASS.md": "compass"})
        output = _make_llm_output(
            analysis_override=_ANALYSIS_CONTENT_BLOCKED, blockers=_BLOCKERS_CONTENT
        )
        result = analyze("MyTarget", target_dir, runner=lambda *a, **k: FakeRun(text=output))
        assert result.ok
        blockers_path = target_dir / "BLOCKERS.md"
        assert blockers_path.exists()
        assert result.blockers_path == blockers_path
        assert "No project name" in blockers_path.read_text(encoding="utf-8")

    def test_blockers_md_not_written_when_no_blockers(self, tmp_path):
        target_dir = _target(tmp_path, **{"COMPASS.md": "compass"})
        result = analyze("MyTarget", target_dir, runner=lambda *a, **k: FakeRun())
        assert result.ok
        assert result.blockers_path is None
        assert not (target_dir / "BLOCKERS.md").exists()

    def test_blockers_md_deleted_when_resolved(self, tmp_path):
        target_dir = _target(tmp_path, **{"COMPASS.md": "compass"})
        (target_dir / "BLOCKERS.md").write_text("# Blockers\n\n- Old blocker.\n", encoding="utf-8")
        result = analyze("MyTarget", target_dir, runner=lambda *a, **k: FakeRun())
        assert result.ok
        assert not (target_dir / "BLOCKERS.md").exists()

    def test_placeholder_blockers_block_not_written(self, tmp_path):
        # FIX-10: a placeholder block must not create a file (its existence would falsely halt
        # plan create) and must remove any stale file.
        target_dir = _target(tmp_path, **{"COMPASS.md": "compass"})
        (target_dir / "BLOCKERS.md").write_text("(omitted — no blockers)\n", encoding="utf-8")
        output = _make_llm_output(blockers="(omitted — no blockers)")
        result = analyze("MyTarget", target_dir, runner=lambda *a, **k: FakeRun(text=output))
        assert result.ok
        assert result.blockers_path is None
        assert not (target_dir / "BLOCKERS.md").exists()

    def test_blockers_md_injected_in_prompt(self, tmp_path):
        target_dir = _target(tmp_path, **{"COMPASS.md": "compass"})
        (target_dir / "BLOCKERS.md").write_text(
            "# Blockers\n\n- Name is missing.\n", encoding="utf-8"
        )
        received_prompts = []

        def runner(prompt, *a, **k):
            received_prompts.append(prompt)
            return FakeRun()

        analyze("MyTarget", target_dir, runner=runner)
        assert received_prompts
        assert "Prior blocker answers" in received_prompts[0]
        assert "Name is missing" in received_prompts[0]

    def test_missing_blueprint_raises(self, tmp_path):
        target_dir = tmp_path / "NoBlueprint"
        target_dir.mkdir()
        with pytest.raises(SpecificationError, match="Blueprint directory not found"):
            analyze("NoBlueprint", target_dir, runner=lambda *a, **k: FakeRun())

    def test_llm_failure_returns_not_ok(self, tmp_path):
        target_dir = _target(tmp_path, **{"COMPASS.md": "compass"})
        result = analyze("MyTarget", target_dir, runner=lambda *a, **k: FakeRun(ok=False, text=""))
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
        result = analyze("MyTarget", target_dir, runner=lambda *a, **k: FakeRun(ok=False, text=""))
        assert result.exit_code() == 1


# ---------------------------------------------------------------------------
# Lifecycle state
# ---------------------------------------------------------------------------


class TestLifecycleState:
    def test_state_advances_to_analyzed_on_first_run(self, tmp_path):
        from drydock.metadata import get_build_state, render_metadata

        target_dir = _target(tmp_path, **{"COMPASS.md": "compass"})
        (target_dir / "METADATA.md").write_text(render_metadata("MyTarget"), encoding="utf-8")
        assert get_build_state(target_dir) == "init"
        analyze("MyTarget", target_dir, runner=lambda *a, **k: FakeRun())
        assert get_build_state(target_dir) == "analyzed"

    def test_captains_chair_written_on_first_run(self, tmp_path):
        from drydock.metadata import render_metadata

        target_dir = _target(tmp_path, **{"COMPASS.md": "compass"})
        (target_dir / "METADATA.md").write_text(render_metadata("MyTarget"), encoding="utf-8")
        result = analyze("MyTarget", target_dir, runner=lambda *a, **k: FakeRun())
        assert result.captains_chair_path is not None
        assert result.captains_chair_path.exists()

    def test_captains_chair_not_overwritten_when_state_does_not_advance(self, tmp_path):
        from drydock.metadata import render_metadata, set_build_state

        target_dir = _target(tmp_path, **{"COMPASS.md": "compass"})
        (target_dir / "METADATA.md").write_text(render_metadata("MyTarget"), encoding="utf-8")
        set_build_state(target_dir, "analyzed")

        result = analyze("MyTarget", target_dir, runner=lambda *a, **k: FakeRun())
        assert result.captains_chair_path is None

    def test_captains_chair_not_written_when_no_metadata(self, tmp_path):
        target_dir = _target(tmp_path, **{"COMPASS.md": "compass"})
        result = analyze("MyTarget", target_dir, runner=lambda *a, **k: FakeRun())
        assert result.captains_chair_path is None

    def test_state_not_reversed_when_already_planned(self, tmp_path):
        from drydock.metadata import get_build_state, render_metadata, set_build_state

        target_dir = _target(tmp_path, **{"COMPASS.md": "compass"})
        (target_dir / "METADATA.md").write_text(render_metadata("MyTarget"), encoding="utf-8")
        set_build_state(target_dir, "analyzed")
        set_build_state(target_dir, "planned")
        analyze("MyTarget", target_dir, runner=lambda *a, **k: FakeRun())
        assert get_build_state(target_dir) == "planned"


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

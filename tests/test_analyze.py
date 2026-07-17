"""Tests for the drydock analyze capability."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import pytest

from drydock.analyze import (
    _assemble_prompt,
    _collect_blueprint_files,
    _feedback_body,
    _is_compass_unpopulated,
    _normalize_analysis_layout,
    _normalize_analysis_summary,
    _normalize_discovery,
    _parse_blocks,
    _parse_output,
    _remove_open_questions_section,
    _remove_tuning_options_section,
    _validate_blockers,
    analyze,
    ensure_feedback_file,
)
from drydock.errors import SpecificationError
from drydock.quarterdeck_state import (
    _blocker_items,
    _feature_items,
    _fill_chair,
    _render_story_breakdown_html,
    _screen_items,
    _story_breakdown,
    _story_items,
)

# ---------------------------------------------------------------------------
# Minimal valid LLM output helpers
# ---------------------------------------------------------------------------


def test_default_feedback_heading_is_analyze_compass(tmp_path):
    assert ensure_feedback_file(tmp_path) == "# Analyze Compass\n"


def test_open_questions_section_is_removed_from_analysis_output():
    result = _remove_open_questions_section(_ANALYSIS_CONTENT)

    assert "## Open Questions" not in result
    assert "## Story List" in result
    assert "## Notes" in result


def test_tuning_options_section_is_removed_from_analysis_output():
    result = _remove_tuning_options_section(_ANALYSIS_CONTENT)

    assert "### Tuning Options" not in result
    assert "## Notes" in result


def test_feedback_body_strips_heading_and_placeholder():
    assert _feedback_body("# Analyze Compass\n\nSteer by feature.\n") == "Steer by feature."
    assert _feedback_body("# Analyze Compass\n") == ""


def test_normalize_analysis_summary_rewrites_quality_and_counts():
    result = _normalize_analysis_summary(
        _ANALYSIS_CONTENT,
        quality="Questions",
        blockers=0,
        questions=1,
    )

    assert "Quality: Questions" in result
    assert "  blockers: 0" in result
    assert "  questions: 1" in result


def test_normalize_analysis_layout_moves_summary_into_analysis_notes():
    result = _normalize_analysis_layout(
        _remove_tuning_options_section(_remove_open_questions_section(_ANALYSIS_CONTENT))
    )

    assert result.startswith("# Blueprint Analysis: TestProject\n\n## Story List")
    assert "## Analysis Notes\n\ngenerated: 2026-06-14" in result
    assert "\nQuality: Ready\n  blockers: 0" in result
    assert "## Notes" not in result


_ANALYSIS_CONTENT = """\
# Blueprint Analysis: TestProject
generated: 2026-06-14
blueprint: /some/path

Quality: Ready
  blockers: 0
  questions: 0
  features: 4
  stories: 5
  stack: python/flask
  screens: 2
  display_name: Test Project
  short_description: A test project for automated analysis.

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

_GROUPED_ANALYSIS_CONTENT = """\
# Blueprint Analysis: TestProject
generated: 2026-06-14
blueprint: /some/path

Quality: Ready
  blockers: 0
  questions: 0
  features: 2
  stories: 5
  stack: python/flask
  screens: 2

## Story List

### Feature Area 1 — Foundation

| ID | Story | High-level AC |
|---|---|---|
| FND-001 | One | AC |
| FND-002 | Two | AC |

### Feature Area 2 — Setup Screen: AWS

| ID | Story | High-level AC |
|---|---|---|
| USA-001 | Three | AC |
| USA-002 | Four | AC |
| USA-003 | Five | AC |
"""

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

_DISCOVERY_IDENTITY = json.dumps(
    {
        "id": "discovery-identity",
        "title": "Discovery: Project Identity",
        "purpose": "Confirm the proposed display name and short description before planning.",
        "questions": [
            {
                "id": "display_name",
                "label": "Display Name",
                "prompt": "The display name Drydock will use for this project.",
                "input": "text",
                "proposed": "Test Project",
            },
            {
                "id": "short_description",
                "label": "Short Description",
                "prompt": "One-sentence description of what this project does.",
                "input": "textarea",
                "proposed": "A test project for automated analysis.",
            },
        ],
    },
    indent=2,
)

_DISCOVERY_INTENT = json.dumps(
    {
        "id": "discovery-intent",
        "title": "Discovery: Product Intent",
        "purpose": "Clarify intent.",
        "questions": [
            {"id": "primary_goal", "label": "Primary Goal", "prompt": "What?", "input": "textarea"}
        ],
    },
    indent=2,
)

_DISCOVERY_STACK = json.dumps(
    {
        "id": "discovery-stack",
        "title": "Discovery: Technology Stack",
        "purpose": "Confirm stack.",
        "questions": [
            {
                "id": "stack_confirmed",
                "label": "Stack",
                "prompt": "What stack?",
                "input": "textarea",
                "options": ["other", "flask.md", "python.md"],
            }
        ],
    },
    indent=2,
)

_DISCOVERY_GAPS_AC = json.dumps(
    {
        "id": "discovery-gaps-ac",
        "title": "Discovery: Gaps and Acceptance Criteria",
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

_DISCOVERY_GUARDRAILS = json.dumps(
    {
        "id": "discovery-guardrails",
        "title": "Discovery: Guardrails",
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
    include_spikes: bool = False,
    include_identity: bool = False,
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
    if include_identity:
        blocks.append(
            f"=== discovery-identity.json ===\n{_DISCOVERY_IDENTITY}\n=== END discovery-identity.json ==="
        )
    if include_spikes:
        blocks += [
            f"=== discovery-intent.json ===\n{_DISCOVERY_INTENT}\n=== END discovery-intent.json ===",
            f"=== discovery-stack.json ===\n{_DISCOVERY_STACK}\n=== END discovery-stack.json ===",
            f"=== discovery-gaps-ac.json ===\n{_DISCOVERY_GAPS_AC}\n=== END discovery-gaps-ac.json ===",
            f"=== discovery-guardrails.json ===\n{_DISCOVERY_GUARDRAILS}\n=== END discovery-guardrails.json ===",
        ]
    if include_compass:
        blocks.insert(3, f"=== COMPASS.md ===\n{_COMPASS_CONTENT}\n=== END COMPASS.md ===")
    if blockers is not None:
        blocks.append(f"=== BLOCKERS.md ===\n{blockers}\n=== END BLOCKERS.md ===")
    if extra_spike:
        extra = json.dumps(
            {
                "id": "discovery-auth",
                "title": "Discovery: Auth",
                "purpose": "Auth model.",
                "questions": [],
            },
            indent=2,
        )
        blocks.append(f"=== discovery-auth.json ===\n{extra}\n=== END discovery-auth.json ===")
    return "\n\n".join(blocks)


_VALID_LLM_OUTPUT = _make_llm_output(include_compass=True)
_VALID_LLM_OUTPUT_WITH_SPIKES = _make_llm_output(include_compass=True, include_spikes=True)
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

    def test_verbatim_intent_without_compass_sections_returns_false(self, tmp_path):
        p = tmp_path / "COMPASS.md"
        p.write_text("# Intent\n\nUse local first.\n", encoding="utf-8")
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
        assert 'filename="sources/spec.md"' in result
        assert "imported content" in result

    def test_excludes_listed_source_filenames(self, tmp_path):
        bp = tmp_path / "blueprint"
        sources = bp / "sources"
        sources.mkdir(parents=True)
        (sources / "spec.md").write_text("keep me", encoding="utf-8")
        (sources / "BUILD_PLAN.md").write_text("ignore me", encoding="utf-8")
        (bp.parent / "EXCLUDE_FILES.md").write_text(
            "# Exclude Files\n\n## Excluded files\n- BUILD_PLAN.md\n",
            encoding="utf-8",
        )
        result = _assemble_prompt("body", bp, "2026-06-14", compass_exists=False)
        assert 'filename="sources/spec.md"' in result
        assert 'filename="sources/BUILD_PLAN.md"' not in result
        assert "ignore me" not in result

    def test_top_level_blueprint_files_not_injected(self, tmp_path):
        bp = tmp_path / "blueprint"
        bp.mkdir()
        (bp / "FEATURE-Auth.md").write_text("should not appear", encoding="utf-8")
        result = _assemble_prompt("body", bp, "2026-06-14", compass_exists=False)
        assert 'filename="FEATURE-Auth.md"' not in result
        assert "should not appear" not in result

    def test_imported_source_uses_generic_source_category_even_for_known_filenames(self, tmp_path):
        bp = tmp_path / "blueprint"
        sources = bp / "sources"
        sources.mkdir(parents=True)
        (sources / "ARCHITECTURE.md").write_text("arch content", encoding="utf-8")
        result = _assemble_prompt("body", bp, "2026-06-14", compass_exists=False)
        assert 'filename="sources/ARCHITECTURE.md"' in result
        assert "## Imported source files" in result

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
        assert 'filename="ANALYZE_COMPASS.md"' in result
        assert "user steering" in result
        assert "Decompose by module, not by route." in result

    def test_no_feedback_section_when_absent(self, tmp_path):
        bp = tmp_path / "blueprint"
        bp.mkdir()
        result = _assemble_prompt("body", bp, "2026-06-14", compass_exists=False)
        assert "Analyze feedback (standing directive)" not in result

    def test_build_configuration_is_not_injected(self, tmp_path):
        bp = tmp_path / "blueprint"
        bp.mkdir()
        (bp / "BUILD_CONFIGURATION.md").write_text("stack: flask\n", encoding="utf-8")
        result = _assemble_prompt("body", bp, "2026-06-14", compass_exists=False)
        assert "BUILD_CONFIGURATION" not in result
        assert "Prior PO answers" not in result

    def test_prompt_body_comes_last(self, tmp_path):
        bp = tmp_path / "blueprint"
        bp.mkdir()
        result = _assemble_prompt("MY BODY", bp, "2026-06-14", compass_exists=False)
        assert result.endswith("MY BODY")
        assert result.index("## Analysis job") < result.index("MY BODY")

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
        assert 'filename="BLOCKERS.md"' in result
        assert "user responses" in result
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
        assert result.index("ANALYZE_COMPASS.md") < result.index("BLOCKERS.md")

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
            input_tokens=("TYPED_SPEC", "ANALYZE_COMPASS.md"),
        )
        assert result.index("Imported source files") < result.index("ANALYZE_COMPASS.md")

    def test_compass_token_injects_no_content_section(self, tmp_path):
        # COMPASS.md is the COMPASS_EXISTS flag for analyze, not a fenced content block.
        bp = tmp_path / "blueprint"
        bp.mkdir()
        result = _assemble_prompt(
            "body", bp, "2026-06-14", compass_exists=True, input_tokens=("COMPASS.md",)
        )
        assert "COMPASS_EXISTS: true" in result
        assert "COMPASS_PENDING_FORMAT: false" in result
        assert "## COMPASS.md" not in result

    def test_compass_token_injects_imported_compass_when_pending_format(self, tmp_path):
        bp = tmp_path / "blueprint"
        bp.mkdir()
        result = _assemble_prompt(
            "body",
            bp,
            "2026-06-14",
            compass_exists=True,
            compass_pending_format=True,
            compass_content="# Intent\n\nRaw intent.\n",
            input_tokens=("COMPASS.md",),
        )
        assert "COMPASS_EXISTS: true" in result
        assert "COMPASS_PENDING_FORMAT: true" in result
        assert 'filename="COMPASS.md"' in result
        assert "Raw intent." in result

    def test_identity_fields_in_job_block_when_provided(self, tmp_path):
        bp = tmp_path / "blueprint"
        bp.mkdir()
        result = _assemble_prompt(
            "body",
            bp,
            "2026-06-14",
            compass_exists=False,
            identity={"display_name": "MyApp", "short_description": "Does things."},
        )
        assert "DISPLAY_NAME: MyApp" in result
        assert "SHORT_DESCRIPTION: Does things." in result

    def test_identity_fields_blank_when_not_provided(self, tmp_path):
        bp = tmp_path / "blueprint"
        bp.mkdir()
        result = _assemble_prompt("body", bp, "2026-06-14", compass_exists=False)
        assert "DISPLAY_NAME: (blank)" in result
        assert "SHORT_DESCRIPTION: (blank)" in result


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

    def test_rejects_write_tool_transcript(self):
        text = """\
<function_calls>
<invoke name="Write">
<parameter name="path">/tmp/target/blueprint/ANALYSIS.md</parameter>
<parameter name="content">analysis body</parameter>
</invoke>
<invoke name="Write">
<parameter name="path">/tmp/target/COMPASS.md</parameter>
<parameter name="content">compass body</parameter>
</invoke>
</function_calls>"""
        blocks = _parse_blocks(text)
        assert blocks["ANALYSIS.md"] == "analysis body"
        assert blocks["COMPASS.md"] == "compass body"


# ---------------------------------------------------------------------------
# _parse_output
# ---------------------------------------------------------------------------


class TestParseOutput:
    def test_valid_output_extracts_all_fields(self):
        analysis, sea_trials, soundings, compass, blockers, spikes, quality, summary = (
            _parse_output(_VALID_LLM_OUTPUT_WITH_SPIKES)
        )
        assert "Blueprint Analysis" in analysis
        assert "Sea Trials" in sea_trials
        assert "Soundings" in soundings
        assert compass is not None
        assert "COMPASS" in compass
        assert blockers is None
        assert quality == "Ready"
        assert "discovery-intent.json" in spikes
        assert "discovery-stack.json" in spikes
        assert "discovery-gaps-ac.json" in spikes
        assert "discovery-guardrails.json" in spikes

    def test_summary_fields_parsed(self):
        _, _, _, _, _, _, _, summary = _parse_output(_VALID_LLM_OUTPUT_WITH_SPIKES)
        assert summary.get("stories") == "5"
        assert summary.get("features") == "4"
        assert summary.get("blockers") == "0"
        assert summary.get("questions") == "0"
        assert summary.get("stack") == "python/flask"
        assert summary.get("screens") == "2"
        assert summary.get("display_name") == "Test Project"
        assert summary.get("short_description") == "A test project for automated analysis."

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
        with pytest.raises(Exception, match="Text appeared outside"):
            _parse_output(truncated)

    def test_missing_sea_trials_raises(self):
        truncated = _VALID_LLM_OUTPUT.replace("=== SEA_TRIALS.md ===", "").replace(
            "=== END SEA_TRIALS.md ===", ""
        )
        with pytest.raises(Exception, match="Text appeared outside"):
            _parse_output(truncated)

    def test_malformed_sea_trials_raises(self):
        broken = _VALID_LLM_OUTPUT.replace(
            _SEA_TRIALS_CONTENT,
            """# Sea Trials: TestProject

## st-001: Operational
Type: technical
Required: yes
Criterion: The system is operational.
Verification: proof""",
        )
        with pytest.raises(SpecificationError, match="is missing Pattern"):
            _parse_output(broken)

    def test_model_owned_sea_trials_questionnaire_is_rejected(self):
        intruding = _VALID_LLM_OUTPUT.replace(
            "=== ANALYSIS.md ===",
            '=== discovery-sea-trials.json ===\n{"id": "discovery-sea-trials"}\n'
            "=== END discovery-sea-trials.json ===\n\n=== ANALYSIS.md ===",
            1,
        )
        with pytest.raises(ValueError, match="must not be emitted"):
            _parse_output(intruding)

    def test_documentation_is_injected_into_sea_trials(self):
        _, sea_trials_text, *_ = _parse_output(_VALID_LLM_OUTPUT)

        assert "### About Sea Trials" in sea_trials_text
        assert "### Notation — EARS" in sea_trials_text

    def test_missing_soundings_is_derived_from_analysis(self):
        analysis = """# Blueprint Analysis: TestProject

## Story List

| ID | Story | High-level AC |
|---|---|---|
| STORY-001 | Start | Start works |

## Analysis Notes

Quality: Ready
"""
        output = "\n".join([
            f"=== ANALYSIS.md ===\n{analysis}\n=== END ANALYSIS.md ===",
            f"=== SEA_TRIALS.md ===\n{_SEA_TRIALS_CONTENT}\n=== END SEA_TRIALS.md ===",
        ])
        _, _, soundings, _, _, _, _, _ = _parse_output(output)
        assert "| STORY-001 | Start works | NOT STARTED |  |" in soundings

    def test_no_spikes_is_tolerated(self):
        # Spikes are emitted dynamically; an analysis with nothing open is valid.
        output = _make_llm_output(include_spikes=False)
        _, _, _, _, _, spikes, _, _ = _parse_output(output)
        assert spikes == {}

    def test_invalid_spike_json_raises(self):
        bad = _VALID_LLM_OUTPUT_WITH_SPIKES.replace(_DISCOVERY_INTENT, "{bad json")
        with pytest.raises(ValueError, match="not valid JSON"):
            _parse_output(bad)

    def test_unknown_quality_when_absent(self):
        no_quality = _VALID_LLM_OUTPUT.replace("Quality: Ready", "")
        _, _, _, _, _, _, quality, _ = _parse_output(no_quality)
        assert quality == "unknown"

    def test_variable_spikes_collected(self):
        output = _make_llm_output(extra_spike=True)
        _, _, _, _, _, spikes, _, _ = _parse_output(output)
        assert "discovery-auth.json" in spikes

    def test_write_tool_transcript_is_recovered(self):
        text = """\
<function_calls>
<invoke name="Write">
<parameter name="path">/tmp/target/blueprint/ANALYSIS.md</parameter>
<parameter name="content"># Blueprint Analysis: TestProject
generated: 2026-06-14
blueprint: /tmp/target/blueprint

Quality: Ready
  blockers: 0
  questions: 0
  stories: 5
  stack: python/flask
  screens: 2

## Story List

- Story

### Tuning Options

- Option A

## Notes

None.</parameter>
</invoke>
<invoke name="Write">
<parameter name="path">/tmp/target/blueprint/SEA_TRIALS.md</parameter>
<parameter name="content"># Sea Trials: TestProject

| ID | Objective / Success Criterion | State | Evidence |
|---|---|---|---|
| st-001 | Objective | NOT STARTED | |</parameter>
</invoke>
<invoke name="Write">
<parameter name="path">/tmp/target/blueprint/SOUNDINGS.md</parameter>
<parameter name="content"># Soundings

| ID | Acceptance Criterion | State | Evidence |
|---|---|---|---|
| ac-001 | Criterion | NOT STARTED | |</parameter>
</invoke>
<invoke name="Write">
<parameter name="path">/tmp/target/COMPASS.md</parameter>
<parameter name="content"># COMPASS: TestProject

## Compass
Compass text.

## Constraints
- None stated.

## Guardrails
- None stated.</parameter>
</invoke>
</function_calls>"""
        analysis, sea_trials, soundings, compass, blockers, spikes, quality, _ = _parse_output(text)
        assert "Blueprint Analysis" in analysis
        assert "Sea Trials" in sea_trials
        assert "Soundings" in soundings
        assert compass is not None
        assert blockers is None
        assert spikes == {}
        assert quality == "Ready"


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
# _fill_chair
# ---------------------------------------------------------------------------

_CHAIR_TEMPLATE = (
    "{{PROJECT_NAME}}|{{PHASE_LABEL}}|{{QUALITY}}|{{QUALITY_CSS}}|{{QUALITY_ICON}}|"
    "{{STATS_HTML}}|{{NEXT_STEP}}|{{GENERATED_DATE}}|{{QUESTION_STATUS}}|"
    "{{QUESTION_LEAD_HTML}}|{{STORIES_HTML}}|{{QUESTIONS_HTML}}|{{BLOCKERS_HTML}}|"
    "{{SCREENS_HTML}}"
)


def _base_fill(**overrides):
    kwargs = dict(
        project_name="Foo",
        phase_label="Analyzed",
        generated_date="2026-06-14",
        quality="Ready",
        stats_html="<div>10 stories</div>",
        next_step="drydock plan Foo",
        question_count=0,
        stories_html="",
        questions_html="",
        blockers_html="",
        screens_html="",
    )
    kwargs.update(overrides)
    return _fill_chair(_CHAIR_TEMPLATE, **kwargs)


class TestFillCaptainsChair:
    def test_ready_fill(self):
        result = _base_fill()
        assert "Foo" in result
        assert "Ready" in result
        assert "ready" in result
        assert "✓" in result
        assert "Analyzed" in result
        assert "No open questionnaires" in result
        assert "<strong>Questionnaires:</strong> No open questionnaires" in result

    def test_blocked_css_class(self):
        result = _fill_chair(
            "{{QUALITY_CSS}}|{{QUALITY_ICON}}",
            quality="Blocked",
            project_name="X",
            phase_label="Analyzed",
            generated_date="",
            stats_html="",
            next_step="",
            question_count=0,
            stories_html="",
            questions_html="",
            blockers_html="",
            screens_html="",
        )
        assert "blocked" in result
        assert "✗" in result

    def test_questions_css_class(self):
        result = _fill_chair(
            "{{QUALITY_CSS}}|{{QUALITY_ICON}}",
            quality="Questions",
            project_name="X",
            phase_label="Analyzed",
            generated_date="",
            stats_html="",
            next_step="",
            question_count=2,
            stories_html="",
            questions_html="",
            blockers_html="",
            screens_html="",
        )
        assert "questions" in result
        assert "⚠" in result

    def test_open_questions_render_status_under_heading(self):
        result = _fill_chair(
            "{{QUESTION_LEAD_HTML}}",
            quality="Questions",
            project_name="X",
            phase_label="Analyzed",
            generated_date="",
            stats_html="",
            next_step="",
            question_count=2,
            stories_html="",
            questions_html="",
            blockers_html="",
            screens_html="",
        )
        assert "<h2>Questionnaires</h2>" in result
        assert "Open questionnaires remain" in result
        assert "<strong>Questionnaires:</strong>" not in result


def test_story_breakdown_extracts_feature_area_counts():
    breakdown = _story_breakdown(_GROUPED_ANALYSIS_CONTENT)

    assert breakdown == [("Foundation", 2), ("Setup Screen: AWS", 3)]


def test_render_story_breakdown_html_renders_rows():
    rendered = _render_story_breakdown_html(_GROUPED_ANALYSIS_CONTENT)

    assert "Story Shape" in rendered
    assert "Foundation" in rendered
    assert "Setup Screen: AWS" in rendered
    assert ">3<" in rendered


def test_commanders_chair_extracts_story_screen_and_blocker_items():
    assert _story_items(_GROUPED_ANALYSIS_CONTENT) == [
        "FND-001 - One",
        "FND-002 - Two",
        "USA-001 - Three",
        "USA-002 - Four",
        "USA-003 - Five",
    ]
    assert _screen_items(_GROUPED_ANALYSIS_CONTENT) == ["Setup Screen: AWS"]
    assert _feature_items(_GROUPED_ANALYSIS_CONTENT) == ["Foundation", "Setup Screen: AWS"]
    assert _blocker_items(_BLOCKERS_CONTENT) == ["blocker-001: Missing project name"]


def test_commanders_chair_story_items_stop_before_analysis_notes_and_skip_headers():
    analysis = """\
# Blueprint Analysis: TestProject

## Story List

### Feature: Inventory

| # | Story | High-level AC |
|---|---|---|
| 1 | HTTP server initialization | Server starts. |
| 2 | Root route `GET /` | Route responds. |

## Analysis Notes

- This note is not a story.
"""

    assert _story_items(analysis) == [
        "1 - HTTP server initialization",
        "2 - Root route `GET /`",
    ]


def test_normalize_discovery_prefills_identity_answers():
    normalized = _normalize_discovery(
        "discovery-identity.json",
        json.loads(_DISCOVERY_IDENTITY),
    )

    questions = {q["id"]: q for q in normalized["questions"]}
    assert questions["display_name"]["answer"] == "Test Project"
    assert questions["short_description"]["answer"] == "A test project for automated analysis."


_FAKE_CATALOG = [
    ("BRANDING_MAIN.md", "Branding"),
    ("aws-s3.md", "AWS"),
    ("flask.md", "Web Server"),
    ("python.md", "Technologies"),
    ("sqlite.md", "Persistence"),
]


def test_normalize_discovery_replaces_stack_options_with_full_catalog(monkeypatch):
    monkeypatch.setattr("drydock.analyze._rigging_catalog", lambda: _FAKE_CATALOG)
    normalized = _normalize_discovery("discovery-stack.json", json.loads(_DISCOVERY_STACK))

    question = normalized["questions"][0]
    assert question["input"] == "checkbox_grid"
    assert question["options"] == [
        "BRANDING_MAIN.md",
        "aws-s3.md",
        "flask.md",
        "python.md",
        "sqlite.md",
        "other",
    ]
    assert question["groups"] == [
        {"label": "Web Server", "options": ["flask.md"]},
        {"label": "Persistence", "options": ["sqlite.md"]},
        {"label": "AWS", "options": ["aws-s3.md"]},
        {"label": "Technologies", "options": ["python.md"]},
        {"label": "Branding", "options": ["BRANDING_MAIN.md"]},
        {"label": "Other", "options": ["other"]},
    ]
    assert question["answer"] == ""


def test_normalize_discovery_degrades_optionless_select_to_textarea():
    normalized = _normalize_discovery(
        "discovery-stack-guidance.json",
        {
            "id": "discovery-stack-guidance",
            "questions": [{"id": "gap", "label": "Gap", "prompt": "Proceed?", "input": "select"}],
        },
    )
    assert normalized["questions"][0]["input"] == "textarea"


def test_normalize_discovery_stack_falls_back_to_sorted_llm_options(monkeypatch):
    monkeypatch.setattr("drydock.analyze._rigging_catalog", lambda: [])
    normalized = _normalize_discovery("discovery-stack.json", json.loads(_DISCOVERY_STACK))

    question = normalized["questions"][0]
    assert question["input"] == "checkbox_grid"
    assert question["options"] == ["flask.md", "other", "python.md"]
    assert "groups" not in question
    assert question["answer"] == ""


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

    def test_malformed_sea_trials_writes_nothing_and_fails_the_run(self, tmp_path):
        """Validation precedes every target write, so a rejected contract leaves no artifacts."""
        target_dir = _target(tmp_path, **{"COMPASS.md": "compass"})
        broken = _VALID_LLM_OUTPUT.replace(
            _SEA_TRIALS_CONTENT,
            """# Sea Trials: TestProject

## st-001: Operational
Type: guardrail
Required: yes
Criterion: The system is operational.
Verification: llm
Pattern: ubiquitous""",
        )

        result = analyze("MyTarget", target_dir, runner=lambda *a, **k: FakeRun(text=broken))

        assert result.ok is False
        assert "must use Pattern: unwanted" in result.error
        assert not (target_dir / "SEA_TRIALS.md").exists()
        assert not (target_dir / "ANALYSIS.md").exists()
        assert not (target_dir / "SOUNDINGS.md").exists()

    def test_emitted_sea_trials_carry_the_reader_documentation(self, tmp_path):
        target_dir = _target(tmp_path, **{"COMPASS.md": "compass"})

        analyze("MyTarget", target_dir, runner=lambda *a, **k: FakeRun())

        sea_trials = (target_dir / "SEA_TRIALS.md").read_text(encoding="utf-8")
        assert sea_trials.startswith("# Sea Trials: TestProject")
        assert "### Guardrails" in sea_trials

    def test_sea_trial_questions_are_projected_to_quarterdeck(self, tmp_path):
        target_dir = _target(tmp_path, **{"COMPASS.md": "compass"})
        structured = """# Sea Trials: MyTarget

## st-speed: Faster workflow
Type: outcome
Required: yes
Criterion: The representative workflow is faster than its baseline.
Verification: measurement

QUESTIONS:
- q-speed-workload: Which representative workload defines the measurement?
"""
        output = _VALID_LLM_OUTPUT.replace(_SEA_TRIALS_CONTENT, structured)

        analyze("MyTarget", target_dir, runner=lambda *a, **k: FakeRun(text=output))

        questionnaire = json.loads(
            (target_dir / "QuarterDeck/questionnaires/discovery-sea-trials.json").read_text(
                encoding="utf-8"
            )
        )
        assert questionnaire["questions"][0]["id"] == "q-speed-workload"

    def test_soundings_at_target_root(self, tmp_path):
        target_dir = _target(tmp_path, **{"COMPASS.md": "compass"})
        result = analyze("MyTarget", target_dir, runner=lambda *a, **k: FakeRun())
        assert result.soundings_path == target_dir / "SOUNDINGS.md"

    def test_quality_signal_in_result(self, tmp_path):
        # The always-written stack questionnaire is an open question until answered.
        target_dir = _target(tmp_path, **{"COMPASS.md": "compass"})
        result = analyze("MyTarget", target_dir, runner=lambda *a, **k: FakeRun())
        assert result.quality == "Questions"

    def test_summary_counts_in_result(self, tmp_path):
        target_dir = _target(tmp_path, **{"COMPASS.md": "compass"})
        result = analyze("MyTarget", target_dir, runner=lambda *a, **k: FakeRun())
        assert result.story_count == 5
        assert result.feature_count == 4
        assert result.blocker_count == 0
        assert result.question_count == 1  # the always-written stack questionnaire
        assert result.screen_count == 4
        assert result.stack == "python/flask"

    def test_question_count_tracks_open_discovery_files_not_model_summary(self, tmp_path):
        target_dir = _target(tmp_path, **{"COMPASS.md": "compass"})
        output = _make_llm_output(include_spikes=True, quality="Ready")
        result = analyze("MyTarget", target_dir, runner=lambda *a, **k: FakeRun(text=output))

        assert result.question_count == 4
        assert result.quality == "Questions"
        analysis = result.analysis_path.read_text(encoding="utf-8")
        assert "Quality: Questions" in analysis
        assert "  questions: 4" in analysis

    def test_compass_written_when_absent(self, tmp_path):
        target_dir = _target(tmp_path, **{"FEATURE-Auth.md": "auth"})
        result = analyze("MyTarget", target_dir, runner=lambda *a, **k: FakeRun())
        assert result.ok
        assert result.compass_path == target_dir / "COMPASS.md"
        assert result.compass_path.exists()

    def test_imported_intent_seeds_compass_before_prompt(self, tmp_path):
        from drydock.compass_sources import compass_import_pending

        target_dir = _target(tmp_path)
        sources = target_dir / "blueprint" / "sources"
        sources.mkdir()
        (sources / "INTENT.md").write_text("# Intent\n\nUse local first.\n", encoding="utf-8")
        received_prompts = []

        def runner(prompt, *a, **k):
            received_prompts.append(prompt)
            return FakeRun()

        result = analyze("MyTarget", target_dir, runner=runner)

        assert result.ok
        assert (target_dir / "COMPASS.md").read_text(encoding="utf-8") == _COMPASS_CONTENT + "\n"
        assert result.compass_path == target_dir / "COMPASS.md"
        assert not compass_import_pending(target_dir)
        assert "COMPASS_EXISTS: true" in received_prompts[0]
        assert "COMPASS_PENDING_FORMAT: true" in received_prompts[0]
        assert "Use local first." in received_prompts[0]

    def test_pending_imported_compass_requires_normalized_output(self, tmp_path):
        from drydock.compass_sources import compass_import_pending, mark_compass_imported

        target_dir = _target(tmp_path, **{"FEATURE-Auth.md": "auth"})
        (target_dir / "COMPASS.md").write_text("# Intent\n\nUse local first.\n", encoding="utf-8")
        mark_compass_imported(target_dir, target_dir / "COMPASS.md")

        result = analyze(
            "MyTarget",
            target_dir,
            runner=lambda *a, **k: FakeRun(text=_VALID_LLM_OUTPUT_NO_COMPASS),
        )

        assert not result.ok
        assert result.error == "Imported COMPASS.md was not normalized by analyze output"
        assert (target_dir / "COMPASS.md").read_text(encoding="utf-8") == (
            "# Intent\n\nUse local first.\n"
        )
        assert compass_import_pending(target_dir)

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
        output = _make_llm_output(include_spikes=True)
        analyze("MyTarget", target_dir, runner=lambda *a, **k: FakeRun(text=output))
        questionnaires = target_dir / "QuarterDeck" / "questionnaires"
        for name in (
            "discovery-intent.json",
            "discovery-stack.json",
            "discovery-gaps-ac.json",
            "discovery-guardrails.json",
        ):
            assert (questionnaires / name).exists(), f"{name} not written"

    def test_no_spikes_emitted_still_writes_stack_questionnaire(self, tmp_path, monkeypatch):
        monkeypatch.setattr("drydock.analyze._rigging_catalog", lambda: _FAKE_CATALOG)
        target_dir = _target(tmp_path, **{"COMPASS.md": "compass"})
        output = _make_llm_output(include_spikes=False)
        result = analyze("MyTarget", target_dir, runner=lambda *a, **k: FakeRun(text=output))
        assert result.ok
        assert [p.name for p in result.discovery_paths] == ["discovery-stack.json"]
        data = json.loads(result.discovery_paths[0].read_text(encoding="utf-8"))
        question = data["questions"][0]
        assert question["input"] == "checkbox_grid"
        assert question["options"][-1] == "other"
        assert [g["label"] for g in question["groups"]][-1] == "Other"
        assert question["answer"] == ""

    def test_spike_paths_in_result(self, tmp_path):
        target_dir = _target(tmp_path, **{"COMPASS.md": "compass"})
        output = _make_llm_output(include_spikes=True)
        result = analyze("MyTarget", target_dir, runner=lambda *a, **k: FakeRun(text=output))
        assert len(result.discovery_paths) >= 4

    def test_spike_files_are_valid_json(self, tmp_path):
        target_dir = _target(tmp_path, **{"COMPASS.md": "compass"})
        output = _make_llm_output(include_spikes=True)
        result = analyze("MyTarget", target_dir, runner=lambda *a, **k: FakeRun(text=output))
        for path in result.discovery_paths:
            data = json.loads(path.read_text(encoding="utf-8"))
            assert "questions" in data

    def test_variable_spike_written(self, tmp_path):
        target_dir = _target(tmp_path, **{"COMPASS.md": "compass"})
        output = _make_llm_output(include_spikes=True, extra_spike=True)
        analyze("MyTarget", target_dir, runner=lambda *a, **k: FakeRun(text=output))
        questionnaires = target_dir / "QuarterDeck" / "questionnaires"
        assert (questionnaires / "discovery-auth.json").exists()

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

    def test_proposed_identity_written_to_metadata(self, tmp_path):
        from drydock.metadata import parse_metadata

        target_dir = _target(tmp_path, **{"COMPASS.md": "compass"})
        # Write METADATA.md with blank identity fields so the LLM proposal gets applied.
        (target_dir / "METADATA.md").write_text(
            "# AUTHORITATIVE PROJECT METADATA — FIELDS SHOULD BE CURRENT\n\n"
            "name: MyTarget\n"
            "display_name: \n"
            "short_description: \n"
            "stack: \n"
            "build_state: \n",
            encoding="utf-8",
        )
        result = analyze("MyTarget", target_dir, runner=lambda *a, **k: FakeRun())
        assert result.ok
        fields = parse_metadata(target_dir / "METADATA.md")
        assert fields.get("display_name") == "Test Project"
        assert fields.get("short_description") == "A test project for automated analysis."

    def test_proposed_identity_not_overwritten_when_already_set(self, tmp_path):
        from drydock.metadata import parse_metadata, render_metadata

        target_dir = _target(tmp_path, **{"COMPASS.md": "compass"})
        meta = render_metadata(
            "MyTarget", display_name="Existing Name", short_description="Existing desc."
        )
        (target_dir / "METADATA.md").write_text(meta, encoding="utf-8")
        result = analyze("MyTarget", target_dir, runner=lambda *a, **k: FakeRun())
        assert result.ok
        fields = parse_metadata(target_dir / "METADATA.md")
        assert fields.get("display_name") == "Existing Name"
        assert fields.get("short_description") == "Existing desc."

    def test_discovery_identity_questionnaire_written(self, tmp_path):
        target_dir = _target(tmp_path, **{"COMPASS.md": "compass"})
        output = _make_llm_output(include_identity=True)
        result = analyze("MyTarget", target_dir, runner=lambda *a, **k: FakeRun(text=output))
        assert result.ok
        identity_path = target_dir / "QuarterDeck" / "questionnaires" / "discovery-identity.json"
        assert identity_path.exists()
        data = json.loads(identity_path.read_text(encoding="utf-8"))
        assert data["id"] == "discovery-identity"
        questions = {q["id"]: q for q in data["questions"]}
        assert "display_name" in questions
        assert "short_description" in questions
        assert questions["display_name"]["proposed"] == "Test Project"
        assert questions["display_name"]["answer"] == "Test Project"
        assert questions["short_description"]["answer"] == "A test project for automated analysis."

    def test_discovery_stack_questionnaire_written_as_grouped_checkbox_grid(
        self, tmp_path, monkeypatch
    ):
        monkeypatch.setattr("drydock.analyze._rigging_catalog", lambda: _FAKE_CATALOG)
        target_dir = _target(tmp_path, **{"COMPASS.md": "compass"})
        output = _make_llm_output(include_spikes=True)
        result = analyze("MyTarget", target_dir, runner=lambda *a, **k: FakeRun(text=output))
        assert result.ok
        stack_path = target_dir / "QuarterDeck" / "questionnaires" / "discovery-stack.json"
        data = json.loads(stack_path.read_text(encoding="utf-8"))
        question = data["questions"][0]
        assert question["input"] == "checkbox_grid"
        assert question["options"] == [
            "BRANDING_MAIN.md",
            "aws-s3.md",
            "flask.md",
            "python.md",
            "sqlite.md",
            "other",
        ]
        assert [g["label"] for g in question["groups"]] == [
            "Web Server",
            "Persistence",
            "AWS",
            "Technologies",
            "Branding",
            "Other",
        ]
        assert question["answer"] == ""

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

    def test_cli_provider_override_is_passed_to_runner(self, tmp_path):
        target_dir = _target(tmp_path, **{"COMPASS.md": "compass"})
        calls = []

        def runner(*a, **k):
            calls.append(k)
            return FakeRun()

        result = analyze("MyTarget", target_dir, runner=runner, llm_provider="codex")

        assert result.ok
        assert calls[0]["llm"] == "codex"

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

    def test_commanders_chair_written_on_first_run(self, tmp_path):
        from drydock.metadata import render_metadata

        target_dir = _target(tmp_path, **{"COMPASS.md": "compass"})
        (target_dir / "METADATA.md").write_text(render_metadata("MyTarget"), encoding="utf-8")
        output = _make_llm_output(analysis_override=_GROUPED_ANALYSIS_CONTENT)
        result = analyze("MyTarget", target_dir, runner=lambda *a, **k: FakeRun(text=output))
        assert result.commanders_chair_path is not None
        assert result.commanders_chair_path.exists()
        html = result.commanders_chair_path.read_text(encoding="utf-8")
        assert '<span class="label">Target:</span> MyTarget' in html
        assert "Commanders Chair" in html
        assert "Build Directory:" not in html
        assert 'class="stat" href="#stories"' in html
        assert 'section id="stories"' in html
        # The always-written stack questionnaire keeps questionnaires open on first run.
        assert "Open questionnaires remain" in html
        assert "Next Step" in html
        assert "drydock plan MyTarget" in html
        assert "FND-001 - One" in html
        assert "Setup Screen: AWS" in html
        assert '<div class="stat-label">Features</div>' in html
        assert "Story Shape" not in html

    def test_commanders_chair_rewritten_when_state_does_not_advance(self, tmp_path):
        from drydock.metadata import render_metadata, set_build_state

        target_dir = _target(tmp_path, **{"COMPASS.md": "compass"})
        (target_dir / "METADATA.md").write_text(render_metadata("MyTarget"), encoding="utf-8")
        set_build_state(target_dir, "analyzed")

        result = analyze("MyTarget", target_dir, runner=lambda *a, **k: FakeRun())
        assert result.commanders_chair_path is not None
        assert result.commanders_chair_path.exists()

    def test_commanders_chair_written_on_first_analyze(self, tmp_path):
        target_dir = _target(tmp_path, **{"COMPASS.md": "compass"})
        result = analyze("MyTarget", target_dir, runner=lambda *a, **k: FakeRun())
        assert result.commanders_chair_path is not None
        assert result.commanders_chair_path.exists()

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

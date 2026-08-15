"""Tests for the prompt loader and the YAML frontmatter contract."""

from __future__ import annotations

import pytest

from drydock.errors import DrydockError
from drydock.prompts import REQUIRED_FIELDS, load_prompt, parse_frontmatter, render_inputs


class TestParseFrontmatter:
    def test_parses_scalars_and_body(self):
        meta, body = parse_frontmatter(
            "---\nname: x\ndescription: a thing\nversion: 2\n---\nhello body\n"
        )
        assert meta == {"name": "x", "description": "a thing", "version": "2"}
        assert body == "hello body"

    def test_strips_quotes_and_ignores_comments(self):
        meta, _ = parse_frontmatter("---\n# a comment\nname: 'quoted'\n---\nbody")
        assert meta["name"] == "quoted"

    def test_missing_block_raises(self):
        with pytest.raises(DrydockError, match="frontmatter"):
            parse_frontmatter("no frontmatter here")

    def test_non_key_value_line_raises(self):
        with pytest.raises(DrydockError, match="key: value"):
            parse_frontmatter("---\nname: x\njust a line\n---\nbody")


class TestLoadPrompt:
    @pytest.mark.parametrize(
        ("prompt_name", "expected_name"),
        (
            ("rigging_compact_contracts", "rigging_compact_contracts"),
            ("rigging_compact_architecture", "rigging_compact_architecture"),
            ("rigging_compact_database", "rigging_compact_database"),
        ),
    )
    def test_loads_role_based_rigging_compact_prompts_with_required_fields(
        self, prompt_name, expected_name
    ):
        prompt = load_prompt(prompt_name)
        assert prompt.name == expected_name
        for field in REQUIRED_FIELDS:
            assert prompt.meta.get(field), f"missing required field {field!r}"
        assert prompt.model == "sonnet"
        assert prompt.body  # non-empty body

    def test_unknown_prompt_raises(self):
        with pytest.raises(DrydockError, match="prompt not found"):
            load_prompt("does_not_exist")

    def test_uat_diagnostic_is_read_only_and_evidence_first(self):
        prompt = load_prompt("uat_diagnostic")

        assert prompt.name == "uat_diagnostic"
        assert "Do not edit code" in prompt.body
        assert "result.json" in prompt.body
        assert "evidence/llm.jsonl" in prompt.body
        assert "LINEAGE.json" in prompt.body
        assert "specification-contaminated" in prompt.body
        assert "exactly two sections" in prompt.body

    def test_missing_required_field_raises(self, tmp_path, monkeypatch):
        (tmp_path / "broken.md").write_text("---\nname: broken\n---\nbody", encoding="utf-8")
        monkeypatch.setattr("drydock.prompts.get_prompts_root", lambda: tmp_path)
        with pytest.raises(DrydockError, match="missing required frontmatter"):
            load_prompt("broken")


class TestInputTokens:
    def test_no_inputs_row_yields_empty_tuple(self):
        assert load_prompt("rigging_compact_contracts").input_tokens == ()

    def test_analyze_inputs_are_ordered_compass_first(self):
        tokens = load_prompt("analyze").input_tokens
        assert tokens == (
            "COMPASS.md",
            "ANALYZE_COMPASS.md",
            "BLOCKERS.md",
            "SEA_TRIALS.md",
            "EXISTING_SPIKES",
            "RIGGING_MANIFEST",
            "IMPORTED_SOURCES",
        )

    def test_analyze_prompt_keeps_questions_out_of_analysis_markdown(self):
        prompt = load_prompt("analyze")
        analysis_contract = prompt.body.split("=== BEGIN ARTIFACT ANALYSIS.md ===", 1)[1].split(
            "=== END ARTIFACT ===", 1
        )[0]

        assert "## Questions" not in analysis_contract
        assert "### Tuning Options" not in analysis_contract
        assert "questions live only in `discovery-*.json`" in prompt.body

    def test_analyze_sizes_stories_in_agile_points(self):
        body = load_prompt("analyze").body
        normalized = " ".join(body.split())

        assert "1 to 5 story points" in normalized
        assert "releasable on its own" in normalized
        assert "a story has no token dimension" in normalized

    def test_analyze_asks_about_high_story_counts_instead_of_capping(self):
        """A high count is a granularity signal for the Commander, never a refusal."""
        body = load_prompt("analyze").body
        normalized = " ".join(body.split())

        assert "discovery-story-count.json" in normalized
        assert "never drop, merge, or withhold stories" in normalized
        assert "never cap the list" in normalized

    def test_render_inputs_emits_in_token_order(self):
        renderers = {
            "A": lambda: ["a-section"],
            "B": lambda: ["b-section"],
            "C": lambda: ["c-section"],
        }
        assert render_inputs(["C", "A", "B"], renderers) == [
            "c-section",
            "a-section",
            "b-section",
        ]

    def test_render_inputs_skips_unknown_and_empty(self):
        renderers = {
            "PRESENT": lambda: ["here"],
            "ABSENT": lambda: [],  # conditional input that resolved to nothing
        }
        assert render_inputs(["UNKNOWN", "ABSENT", "PRESENT"], renderers) == ["here"]

    def test_plan_create_inputs_are_ordered_compass_first(self):
        tokens = load_prompt("plan_create").input_tokens
        assert tokens[0] == "COMPASS.md"
        assert tokens == (
            "COMPASS.md",
            "TECHNOLOGY_STACK.md",
            "PLAN_COMPASS.md",
            "ANALYSIS.md",
            "SEA_TRIALS.md",
            "ACCEPTANCE.json",
            "SOUNDINGS.md",
            "BLOCKERS.md",
            "QUESTIONNAIRES",
            "DECISIONS.json",
            "MANIFEST_CONTRACT.md",
            "BLUEPRINTS_CONTRACT.md",
            "TYPED_SPEC",
        )

    def test_plan_create_makes_each_acceptance_check_repeat_its_imports(self):
        body = load_prompt("plan_create").body

        assert "Every `=== AC <id> ===` block is a standalone Python script" in body
        assert (
            "every block that calls `subprocess.run` contains its own `import subprocess`" in body
        )

    def test_plan_create_preserves_commander_owned_governed_stage_ids(self):
        body = " ".join(load_prompt("plan_create").body.split())

        assert "Each key in `stages` is an exact story id" in body
        assert "Preserve those ids verbatim in `TOPOLOGY.md`" in body
        assert "Do not emit or amend `ACCEPTANCE.json`" in body

    def test_plan_create_declares_the_graph_and_leaves_ordering_to_drydock(self):
        body = load_prompt("plan_create").body

        # The Manifest is the single work graph; no separate ordering file is emitted.
        assert "BUILD_COMPASS" not in body
        assert "implemented by exactly one story." in body
        # Authorship versus verification: the model declares, Drydock orders, blocks, serializes.
        assert "Do not sort the stories." in body
        assert "Never emit `block:` or `stack_mode:`" in body
        assert "Drydock computes everything positional" in body

    def test_plan_create_declares_the_story_taxonomy(self):
        body = load_prompt("plan_create").body

        assert "`foundational`, `service`, or `feature`" in body
        assert "no `spike` or `ac` story type" in body
        assert "Story count is not capped" in body
        assert "`Phase` is never a Blueprint header field" in body

    def test_plan_create_sizes_stories_in_agile_points_not_tokens(self):
        """A story is sized by Agile judgement. Tokens are a property of its block."""
        body = load_prompt("plan_create").body
        normalized = " ".join(body.split())

        assert "**1 to 5 story points**" in normalized
        assert "releasable on its own" in normalized
        assert "A story has no token dimension" in normalized
        # The superseded framing invited a model to treat capacity as a decomposition boundary.
        assert "implement and verify in a single pass" not in normalized

    def test_plan_create_uses_analysis_decomposition_as_default_work_breakdown(self):
        body = load_prompt("plan_create").body
        normalized = " ".join(body.split())

        assert "completed planning decomposition and the default work breakdown" in normalized
        assert "Preserve their proposed story boundaries and mapped" in normalized
        assert "split, merge, move, replace, or reorder the affected scope" in normalized
        assert "source content is not authoritative" in normalized
        assert "planning seed, not as the final artifact" not in normalized

    def test_build_prompt_requires_dependency_verification_before_install(self):
        body = load_prompt("build").body

        assert "verify each package name" in body
        assert "fail explicitly" in body
        assert "instead of installing it" in body
        assert "`uv`" in body

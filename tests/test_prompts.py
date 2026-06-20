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
    def test_loads_rigging_compact_with_required_fields(self):
        prompt = load_prompt("rigging_compact")
        assert prompt.name == "rigging_compact"
        for field in REQUIRED_FIELDS:
            assert prompt.meta.get(field), f"missing required field {field!r}"
        assert prompt.model == "sonnet"
        assert prompt.body  # non-empty body

    def test_unknown_prompt_raises(self):
        with pytest.raises(DrydockError, match="prompt not found"):
            load_prompt("does_not_exist")

    def test_missing_required_field_raises(self, tmp_path, monkeypatch):
        (tmp_path / "broken.md").write_text("---\nname: broken\n---\nbody", encoding="utf-8")
        monkeypatch.setattr("drydock.prompts.get_prompts_root", lambda: tmp_path)
        with pytest.raises(DrydockError, match="missing required frontmatter"):
            load_prompt("broken")


class TestInputTokens:
    def test_no_inputs_row_yields_empty_tuple(self):
        assert load_prompt("rigging_compact").input_tokens == ()

    def test_analyze_inputs_are_ordered_compass_first(self):
        tokens = load_prompt("analyze").input_tokens
        assert tokens == (
            "COMPASS.md",
            "ANALYZE_COMPASS.md",
            "BLOCKERS.md",
            "EXISTING_SPIKES",
            "TYPED_SPEC",
        )

    def test_analyze_prompt_keeps_questions_out_of_analysis_markdown(self):
        prompt = load_prompt("analyze")
        analysis_contract = prompt.body.split("=== ANALYSIS.md ===", 1)[1].split(
            "=== END ANALYSIS.md ===", 1
        )[0]

        assert "## Open Questions" not in analysis_contract
        assert "questions live only in `discovery-*.json`" in prompt.body

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
            "PLAN_COMPASS.md",
            "ANALYSIS.md",
            "SOUNDINGS.md",
            "BLOCKERS.md",
            "QUESTIONNAIRES",
            "MANIFEST_CONTRACT.md",
            "BLUEPRINTS_CONTRACT.md",
            "TYPED_SPEC",
        )

    def test_plan_create_compass_requires_ordered_token_budgeted_build_steps(self):
        body = load_prompt("plan_create").body

        assert "## 1: Foundation" in body
        assert "stories: scaffold, persistence" in body
        assert "# Estimated prompt: ~42KB (~11k tokens)" in body
        assert "Each story appears in exactly one step." in body
        assert "Keep every estimated prompt at or below `PROMPT_WARN_KB`." in body

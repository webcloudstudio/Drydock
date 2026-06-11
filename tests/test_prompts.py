"""Tests for the prompt loader and the YAML frontmatter contract."""

from __future__ import annotations

import pytest

from drydock.errors import DrydockError
from drydock.prompts import REQUIRED_FIELDS, load_prompt, parse_frontmatter


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

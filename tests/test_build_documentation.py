"""Tests for Drydock documentation assembly."""

from __future__ import annotations

from pathlib import Path

import pytest

from drydock.build_documentation import (
    DEFAULT_SPECIFICATION,
    _default_source,
    build_documentation,
    main,
    parse_source,
    render_page,
)

SOURCE = """---
title: Example
eyebrow: Blueprint
subtitle: Example subtitle
author: Ed
studio: Studio
year: 2026
ideas_title: Adds
ideas:
  - title: First idea
    sub_list:
      - One
      - Two
---

## Product

Body with `code`.
"""


def test_parse_source_reads_frontmatter_and_body():
    metadata, body = parse_source(SOURCE)

    assert metadata["title"] == "Example"
    assert metadata["ideas"] == [
        {"title": "First idea", "sub_list": ["One", "Two"]},
    ]
    assert body.startswith("## Product")


def test_parse_source_requires_frontmatter():
    with pytest.raises(ValueError, match="frontmatter"):
        parse_source("# No frontmatter")


def test_render_page_embeds_metadata_and_markdown_safely():
    metadata, body = parse_source(SOURCE)

    page = render_page(metadata, body + "\n</script>")

    assert "<title>Example Documentation</title>" in page
    assert "<strong>First idea</strong>" in page
    assert r"<\/script>" in page
    assert "marked.parse(BODY)" in page
    assert "mermaid.run" in page


def test_build_documentation_writes_output(tmp_path: Path):
    source = tmp_path / "spec.md"
    output = tmp_path / "docs" / "index.html"
    source.write_text(SOURCE, encoding="utf-8")

    result = build_documentation(source, output)

    assert result == output
    assert output.exists()
    assert "<h1>Example</h1>" in output.read_text(encoding="utf-8")


def test_main_accepts_explicit_paths(tmp_path: Path, capsys: pytest.CaptureFixture[str]):
    source = tmp_path / "spec.md"
    output = tmp_path / "index.html"
    source.write_text(SOURCE, encoding="utf-8")

    assert main(["--source", str(source), "--output", str(output)]) == 0
    assert f"Built documentation: {output}" in capsys.readouterr().out


def test_default_source_prefers_authoritative_path(tmp_path: Path):
    authoritative = tmp_path / DEFAULT_SPECIFICATION
    authoritative.parent.mkdir(parents=True)
    authoritative.write_text(SOURCE, encoding="utf-8")

    assert _default_source(tmp_path) == authoritative


def test_canonical_specification_documents_current_command_surface():
    specification = _default_source(Path(__file__).parents[1]).read_text(encoding="utf-8")
    expected = (
        "drydock config show",
        "drydock config set <key> <value>",
        "drydock init <Target>",
        "drydock run quarterdeck [<Target>] [--host HOST] [--port PORT]",
        "drydock import <Blueprint> <Target> <Source> --format <auto|markdown|source|speckit>",
        "drydock status <Blueprint> [--verbose]",
        "drydock analyze <Blueprint> [<Target>]",
        "drydock plan create <Blueprint> <Target>",
        "drydock build <Blueprint> <Target>",
        "drydock build status <Blueprint> <Target>",
        "drydock build score <Blueprint> <Target>",
        "drydock iterate <Blueprint> <Target> <BOTH|BLUEPRINT|TGT> <Scope> <Change>",
        "drydock rigging compact <Blueprint> <Target> [--all] [--force]",
        "drydock rigging update <Target>",
        "drydock rigging verify <Target>",
        "drydock document <Blueprint> <Target>",
        "drydock document generate <Blueprint> <Target>",
        "drydock document assemble <Blueprint> <Target>",
    )

    for command in expected:
        assert f"```text\n{command}\n```" in specification

    for nonexistent in ("drydock conform", "drydock plan validate", "drydock plan approve"):
        assert nonexistent not in specification

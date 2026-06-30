"""Tests for Drydock documentation assembly."""

from __future__ import annotations

from pathlib import Path

import pytest

from drydock.build_documentation import (
    DEFAULT_SPECIFICATION,
    _default_source,
    build_documentation,
    default_pdf_path,
    main,
    parse_source,
    publish_document,
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
  - title: First **idea**
    sub_list:
      - One **signal**
      - Two
---

## Product

Body with `code`.
"""

SAIL_SOURCE = """---
title: Example
eyebrow: Blueprint
subtitle: Example subtitle
author: Ed
studio: Studio
year: 2026
ideas_title: The SAIL Method
ideas_layout: sail
sail_lead:
  - Your Compass (constitution/intent) guides your build
  - QuarterDeck keeps the product owner in command of plans, evidence, questions, and decisions
  - Your Ship's Log preserves material decisions and milestones
ideas:
  - title: **S** — Setup and Install Drydock
    sub_list:
      - pip install, drydock config, drydock init
  - title: **A** — Analyze and Arrange
    sub_list:
      - Import your projects into **Blueprints** - Typed Specifications
      - Plan creates your Manifest based on the analysis
---

## Product

Body with `code`.
"""


def test_parse_source_reads_frontmatter_and_body():
    metadata, body = parse_source(SOURCE)

    assert metadata["title"] == "Example"
    assert metadata["ideas"] == [
        {"title": "First **idea**", "sub_list": ["One **signal**", "Two"]},
    ]
    assert body.startswith("## Product")


def test_parse_source_reads_sail_lead_lines():
    metadata, _body = parse_source(SAIL_SOURCE)

    assert metadata["sail_lead"] == [
        "Your Compass (constitution/intent) guides your build",
        "QuarterDeck keeps the product owner in command of plans, evidence, questions, and decisions",
        "Your Ship's Log preserves material decisions and milestones",
    ]


def test_parse_source_requires_frontmatter():
    with pytest.raises(ValueError, match="frontmatter"):
        parse_source("# No frontmatter")


def test_render_page_embeds_metadata_and_markdown_safely():
    metadata, body = parse_source(SOURCE)

    page = render_page(metadata, body + "\n</script>")

    assert "<title>Example Documentation</title>" in page
    assert '<div class="idea-title">First <strong>idea</strong></div>' in page
    assert "<li>One <strong>signal</strong></li>" in page
    assert r"<\/script>" in page
    assert "marked.parse(BODY)" in page
    assert "mermaid.run" in page


def test_render_page_supports_sail_cover_layout():
    metadata, body = parse_source(SAIL_SOURCE)

    page = render_page(metadata, body)

    assert 'class="ideas ideas-sail"' in page
    assert 'class="sail-lead"' in page
    assert '<div class="sail-letter">S</div>' in page
    assert '<div class="sail-letter">A</div>' in page
    assert "<p>Your Compass (constitution/intent) guides your build</p>" in page
    assert "<p>Your Ship&#x27;s Log preserves material decisions and milestones</p>" in page
    assert '<div class="idea-title">Setup and Install Drydock</div>' in page
    assert "<li>pip install, drydock config, drydock init</li>" in page
    assert (
        "<li>Import your projects into <strong>Blueprints</strong> - Typed Specifications</li>"
        in page
    )


def test_build_documentation_writes_output(tmp_path: Path):
    source = tmp_path / "spec.md"
    output = tmp_path / "docs" / "index.html"
    source.write_text(SOURCE, encoding="utf-8")

    result = build_documentation(source, output)

    assert result == output
    assert output.exists()
    assert "<h1>Example</h1>" in output.read_text(encoding="utf-8")


def test_publish_document_writes_html_with_theme(tmp_path: Path):
    source = tmp_path / "spec.md"
    output = tmp_path / "site" / "index.html"
    source.write_text(SOURCE, encoding="utf-8")

    result = publish_document(source, output, theme="paper")

    assert result.html_path == output
    assert result.pdf_path is None
    assert result.theme == "paper"
    assert 'body class="theme-paper"' in output.read_text(encoding="utf-8")


def test_publish_document_writes_pdf_with_injected_renderer(tmp_path: Path):
    source = tmp_path / "spec.md"
    output = tmp_path / "index.html"
    pdf_output = tmp_path / "paper.pdf"
    source.write_text(SOURCE, encoding="utf-8")
    calls = []

    def fake_renderer(html_path: Path, pdf_path: Path) -> Path:
        calls.append((html_path, pdf_path))
        pdf_path.write_bytes(b"%PDF-1.4\n")
        return pdf_path

    result = publish_document(
        source,
        output,
        pdf=True,
        pdf_output=pdf_output,
        pdf_renderer=fake_renderer,
    )

    assert result.pdf_path == pdf_output
    assert pdf_output.read_bytes().startswith(b"%PDF")
    assert calls == [(output, pdf_output)]


def test_default_pdf_path_replaces_html_suffix():
    assert default_pdf_path(Path("dist/paper.html")) == Path("dist/paper.pdf")


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
        "drydock status [<Target>]",
        "drydock validate <Target> [--verbose]",
        "drydock run quarterdeck [<Target>] [--host HOST] [--port PORT]",
        "drydock import <Target> <Source> --format <auto|markdown|source|speckit|compass>",
        "drydock analyze <Target>",
        "drydock plan <Target>",
        "drydock build <Target>",
        "drydock build status <Target>",
        "drydock build score <Target>",
        "drydock refit <Target>",
        "drydock rigging compact <Target> [--all] [--force]",
        "drydock rigging update <Target>",
        "drydock rigging verify <Target>",
        "drydock document <Target>",
        "drydock document generate <Target>",
        "drydock document assemble <Target>",
        "drydock publish <Source.md>",
    )

    for command in expected:
        assert command in specification

    phase_headings = (
        "## SAIL Phase 1 — Set Up: Laying the Keel",
        "## SAIL Phase 2 — Analyze: Charting the Course",
        "## SAIL Phase 3 — Implement: Sailing the Frontier",
        "## SAIL Phase 4 — Loop: The Refit",
    )
    assert [specification.index(heading) for heading in phase_headings] == sorted(
        specification.index(heading) for heading in phase_headings
    )
    for phase in specification.split("## SAIL Phase ")[1:]:
        assert "### Commands" in phase

    for nonexistent in ("drydock conform", "drydock plan validate", "drydock plan approve"):
        assert nonexistent not in specification

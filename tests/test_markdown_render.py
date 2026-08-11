from __future__ import annotations

from drydock.markdown_render import render_markdown


def test_headings_paragraphs_and_rules() -> None:
    html = render_markdown("# Title\n\nA line\nand its continuation.\n\n---\n\n## Second\n")

    assert "<h1>Title</h1>" in html
    assert "<p>A line and its continuation.</p>" in html
    assert "<hr>" in html
    assert "<h2>Second</h2>" in html


def test_inline_emphasis_code_and_links() -> None:
    html = render_markdown("Run `drydock build` for **each** *Target*; see [spec](docs/spec.md).")

    assert "<code>drydock build</code>" in html
    assert "<strong>each</strong>" in html
    assert "<em>Target</em>" in html
    assert '<a href="docs/spec.md">spec</a>' in html


def test_markup_inside_a_code_span_stays_literal() -> None:
    html = render_markdown("Use `**not bold**` and `<script>`.")

    assert "<code>**not bold**</code>" in html
    assert "<code>&lt;script&gt;</code>" in html
    assert "<strong>" not in html


def test_html_in_prose_is_escaped_rather_than_emitted() -> None:
    html = render_markdown("A <script>alert(1)</script> tag.")

    assert "<script>" not in html
    assert "&lt;script&gt;" in html


def test_fenced_code_keeps_its_lines_and_escapes_its_content() -> None:
    html = render_markdown("```python\nif a < b:\n    run()\n```\n")

    assert "<pre><code>if a &lt; b:\n    run()</code></pre>" in html


def test_a_github_table_becomes_a_table() -> None:
    html = render_markdown("| ID | State |\n|---|---|\n| st-001 | PASS |\n| st-002 | FAIL |\n")

    assert "<th>ID</th>" in html
    assert "<td>st-001</td>" in html
    assert "<td>FAIL</td>" in html


def test_lists_nest_by_indentation_and_ordered_lists_are_distinguished() -> None:
    html = render_markdown("- one\n  - inner\n- two\n\n1. first\n2. second\n")

    assert "<ul><li>one<ul><li>inner</li></ul></li><li>two</li></ul>" in html
    assert "<ol><li>first</li><li>second</li></ol>" in html


def test_a_block_quote_renders_its_own_blocks() -> None:
    html = render_markdown("> **Note**\n> quoted text\n")

    assert "<blockquote><p><strong>Note</strong> quoted text</p></blockquote>" in html


def test_a_block_that_follows_a_paragraph_without_a_blank_line_still_renders() -> None:
    # Drydock's own artifacts are written this way, so a heading must not be swallowed
    # into the paragraph above it.
    html = render_markdown("Intro text\n## Heading\n- item\n")

    assert "<p>Intro text</p>" in html
    assert "<h2>Heading</h2>" in html
    assert "<li>item</li>" in html


def test_field_lines_keep_their_own_lines_while_prose_still_reflows() -> None:
    # Drydock writes typed records as consecutive "Field: value" lines. Folding them into one
    # paragraph, as CommonMark does, destroys the record.
    html = render_markdown(
        "Type: technical\nRequired: yes\nCriterion: The suite passes.\n\n"
        "Ordinary prose that the author\nwrapped at a column limit.\n"
    )

    assert "Type: technical<br>Required: yes<br>Criterion: The suite passes." in html
    assert "<p>Ordinary prose that the author wrapped at a column limit.</p>" in html


def test_rendering_is_deterministic_and_empty_input_is_empty_output() -> None:
    text = "# A\n\ntext `code` **bold**\n\n| a |\n|---|\n| b |\n"

    assert render_markdown(text) == render_markdown(text)
    assert render_markdown("") == ""
    assert render_markdown("\n\n   \n") == ""

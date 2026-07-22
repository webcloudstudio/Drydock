# FEATURE: Block Parsing

| Field       | Value |
|-------------|-------|
| Version     | 20260722 V4 |
| Description | Block parsing recognizes CommonMark leaf and container structures and document-wide link reference definitions. |
| Depends On  | ARCHITECTURE.md, FEATURE-Filter-Execution.md |
| Provides    | commonmark.blocks.parse_document, commonmark.blocks.collect_reference_definitions |
| Phase       | 3 |

## Purpose

This feature defines phase-one parsing for the CommonMark document tree, including leaf blocks,
container blocks, list tightness, and reference-definition collection.

## Trigger

`commonmark.api.convert()` receives a Markdown document and invokes the block parser before any
inline parsing occurs.

## Sequence

1. Classify each input line against the currently open block stack.
2. Open, continue, or close block quotes, list items, paragraphs, headings, code blocks, thematic
   breaks, HTML blocks, and other supported block types according to CommonMark precedence.
3. Preserve block raw text until the block structure is complete.
4. Extract link reference definitions with document-wide scope and first-definition precedence.
5. Produce a document tree plus a normalized reference-definition map for phase-two inline parsing.

## Reads

- Input document lines.
- Existing open block stack state.

## Writes

- Block syntax tree.
- Reference-definition map keyed by normalized labels.

## Operational Behavior

- Block structure takes precedence over inline markers.
- Setext heading precedence over thematic breaks is preserved.
- Lists handle nesting, laziness, and tight versus loose rendering semantics.
- HTML blocks preserve raw HTML according to the seven CommonMark HTML block forms.
- Link reference definitions can be declared within block containers and still apply document-wide.

## Programmatic Acceptance

### block-atx-and-thematic-break
Representative ATX heading and thematic break inputs render with the expected block structure.

```python
from commonmark.api import convert

html = convert("# Title\n\n***\n")
assert html == "<h1>Title</h1>\n<hr />\n"
```

### block-list-and-blockquote
Nested list and block quote structures preserve container boundaries and item nesting.

```python
from commonmark.api import convert

markdown = "> - one\n> - two\n"
html = convert(markdown)

assert html == "<blockquote>\n<ul>\n<li>one</li>\n<li>two</li>\n</ul>\n</blockquote>\n"
```

### block-fenced-code-literal
Fenced code blocks preserve literal content and do not parse Markdown inside the fence.

```python
from commonmark.api import convert

markdown = "```python\n*not emphasis*\n```\n"
html = convert(markdown)

assert html == '<pre><code class="language-python">*not emphasis*\\n</code></pre>\\n'
```

### block-reference-definition-precedence
Reference definitions are collected across the document and the first matching definition wins.

```python
from commonmark.api import convert

markdown = "[foo]\\n\\n[foo]: /first\\n[foo]: /second\\n"
html = convert(markdown)

assert html == '<p><a href="/first">foo</a></p>\\n'
```

## User Acceptance

- None.

## Guardrails

- Block parsing does not render HTML directly.
- Code blocks remain literal content and are not re-parsed as Markdown.
- Reference-definition extraction does not discard non-definition paragraph content incorrectly.

## Open Questions

- None.

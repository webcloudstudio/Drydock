# FEATURE: Block Parsing

| Field       | Value |
|-------------|-------|
| Version     | 20260722 V1 |
| Description | Defines CommonMark block structure, containers, lists, and reference-definition collection. |
| Depends On  | ARCHITECTURE.md, FEATURE-Filter-Execution.md |
| Provides    | block parsing, container parsing, link reference collection |
| Phase       | 3 |

## Purpose

The block parser builds document structure before inline parsing. It handles paragraphs, headings, thematic breaks, indented and fenced code, HTML blocks, block quotes, lists, nesting, laziness, tightness, and link reference definitions.

## Behavior

Block structure takes precedence over inline syntax. Code blocks and HTML blocks retain literal content according to CommonMark 0.31.2. Link reference definitions are collected across the document and containers, with the first matching normalized definition taking precedence.

## Programmatic Acceptance

### block-leaf-structures
Representative leaf blocks render with the expected structure.

```python
from mycommonmark import convert
html = convert("# Heading\n\n---\n\n    literal\n\n```\ncode\n```\n")
assert "<h1>Heading</h1>" in html
assert "<hr />" in html
assert "<pre><code>literal\n</code></pre>" in html
assert "<pre><code>code\n</code></pre>" in html
```

### block-container-structures
Nested block containers preserve list and block quote structure.

```python
from mycommonmark import convert
html = convert("> quote\n>\n> - one\n> - two\n")
assert "<blockquote>" in html
assert "<ul>" in html
assert "<li>one</li>" in html
assert "<li>two</li>" in html
assert "</blockquote>" in html
```

### block-code-literal
Fenced code content is not parsed as Markdown.

```python
from mycommonmark import convert
html = convert("```\n*literal*\n# literal\n```\n")
assert "<em>" not in html
assert "<h1>" not in html
assert "*literal*" in html
```

### block-reference-precedence
The first matching reference definition resolves a reference link.

```python
from mycommonmark import convert
html = convert("[foo]\n\n[foo]: /first\n[foo]: /second\n")
assert '<a href="/first">foo</a>' in html
assert "/second" not in html
```

## User Acceptance

- Nested lists and block quotes have visibly correct HTML structure.

## Guardrails

- Block parsing precedes inline parsing.
- Code blocks are never interpreted as Markdown.
- HTML blocks preserve required raw content.

## Open Questions

- None.

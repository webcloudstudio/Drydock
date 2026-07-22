# FEATURE: Inline Parsing

| Field       | Value |
|-------------|-------|
| Version     | 20260722 V1 |
| Description | Inline parsing resolves CommonMark text structure including escapes, emphasis, links, images, autolinks, raw HTML, and line breaks. |
| Depends On  | ARCHITECTURE.md, FEATURE-Block-Parsing.md |
| Provides    | commonmark.inlines.parse_inlines, commonmark.render.render_inlines |
| Phase       | 4 |

## Purpose

This feature defines phase-two inline parsing over completed block text using the document-wide
reference-definition map collected during block parsing.

## Trigger

The block parser closes a paragraph, heading, or other inline-bearing node and the conversion
pipeline dispatches its raw text to the inline parser.

## Sequence

1. Scan text left-to-right for code spans, raw HTML tags, autolinks, delimiter runs, brackets, and
   escaped punctuation.
2. Resolve entity and numeric character references outside code spans and code blocks.
3. Parse emphasis and strong emphasis using delimiter-run rules and the no-backtracking stack
   strategy from the CommonMark appendix.
4. Resolve inline, full-reference, collapsed-reference, and shortcut-reference links and images.
5. Render the resulting inline tree with correct escaping, alt text extraction, and line-break
   behavior.

## Reads

- Raw inline text from paragraphs, headings, and other inline-bearing blocks.
- Normalized reference-definition map from block parsing.

## Writes

- Inline syntax tree nodes.
- HTML inline fragments rendered into the final document output.

## Operational Behavior

- Backslash escapes apply to ASCII punctuation outside code spans, autolinks, and raw HTML.
- Entity and numeric character references decode outside code spans and code blocks.
- Links cannot contain links, but image descriptions may contain links for alt-text extraction.
- Hard and soft line breaks follow CommonMark rules for trailing spaces and backslashes.

## Programmatic Acceptance

### inline-code-span-and-emphasis
Code spans bind more tightly than emphasis and render literal content.

```python
from commonmark.api import convert

markdown = "*a `*`*\n"
html = convert(markdown)

assert html == "<p><em>a <code>*</code></em></p>\n"
```

### inline-reference-link
Reference links resolve against normalized labels collected during block parsing.

```python
from commonmark.api import convert

markdown = "[Foo][]\n\n[foo]: /url \"title\"\n"
html = convert(markdown)

assert html == '<p><a href="/url" title="title">Foo</a></p>\n'
```

### inline-autolink-and-raw-html
Autolinks and raw HTML are preserved according to CommonMark precedence and escaping rules.

```python
from commonmark.api import convert

markdown = "<https://example.com>\n\n<a href=\"/raw\">raw</a>\n"
html = convert(markdown)

assert html == '<p><a href="https://example.com">https://example.com</a></p>\n<p><a href="/raw">raw</a></p>\n'
```

### inline-image-alt-text
Image descriptions render plain-string alt text rather than nested Markdown syntax.

```python
from commonmark.api import convert

markdown = "![foo *bar*](train.jpg)\n"
html = convert(markdown)

assert html == '<p><img src="train.jpg" alt="foo bar" /></p>\n'
```

## User Acceptance

- None.

## Guardrails

- Inline parsing does not run until block structure and reference definitions are complete.
- Links do not nest inside other links.
- Raw HTML tags that satisfy CommonMark inline HTML grammar are not escaped.

## Open Questions

- None.

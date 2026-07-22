# FEATURE: Inline Parsing

| Field       | Value |
|-------------|-------|
| Version     | 20260722 V1 |
| Description | Defines CommonMark inline parsing and HTML rendering for inline constructs. |
| Depends On  | ARCHITECTURE.md, FEATURE-Block-Parsing.md |
| Provides    | inline parsing, link and image rendering, autolinks, raw HTML |
| Phase       | 4 |

## Purpose

The inline parser converts paragraph and heading content into CommonMark inline elements. It handles escapes, entities, code spans, emphasis, strong emphasis, links, images, reference links, autolinks, raw HTML, hard breaks, and soft breaks.

## Behavior

Inline parsing follows CommonMark delimiter and precedence rules. Code spans, links, images, HTML tags, and autolinks bind more tightly than emphasis. Destinations and titles are escaped and URL-encoded as required. Image `alt` text contains only the plain description text.

## Programmatic Acceptance

### inline-code-emphasis
Code spans remain literal while emphasis is rendered.

```python
from mycommonmark import convert
html = convert("`*code*` and *emphasis*\n")
assert "<code>*code*</code>" in html
assert "<em>emphasis</em>" in html
assert "<code><em>" not in html
```

### inline-reference-link
Reference links resolve normalized labels.

```python
from mycommonmark import convert
html = convert("[Display][FOO]\n\n[foo]: /target \"Title\"\n")
assert '<a href="/target" title="Title">Display</a>' in html
```

### inline-autolink-html
Autolinks render as links and raw HTML remains unescaped.

```python
from mycommonmark import convert
html = convert("<https://example.com> and <span>raw</span>\n")
assert '<a href="https://example.com">https://example.com</a>' in html
assert "<span>raw</span>" in html
```

### inline-image-alt
Image descriptions render plain-string alt text.

```python
from mycommonmark import convert
html = convert("![foo *bar*](image.png)\n")
assert '<img src="image.png" alt="foo bar" />' in html
```

### inline-hard-break
Two trailing spaces create a hard line break.

```python
from mycommonmark import convert
html = convert("first  \nsecond\n")
assert "<br />" in html
assert "first<br />" in html
```

## User Acceptance

- Inline formatting, links, images, autolinks, and raw HTML render according to the CommonMark examples.

## Guardrails

- Code spans are not parsed for inline syntax.
- Raw HTML is not escaped when CommonMark requires preservation.
- Link nesting restrictions are enforced.

## Open Questions

- None.

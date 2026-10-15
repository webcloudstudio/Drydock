# DESIGN: drydock publish

| Field | Value |
|---|---|
| Version | 2026-10-15 V1 |
| Route | publish |
| Modules | `build_documentation.py`, `markdown_render.py` |
| Prompts | — |
| Tests | `tests/test_build_documentation.py`, `tests/test_markdown_render.py` |
| Topics | — |
| Pending spec | 0 |
| Pending impl | 0 |

## Behavior

### Purpose

Render one front-matter Markdown document — white paper, specification, or guide — into
publishable HTML, and optionally PDF. Deterministic; no Target and no LLM.

### Syntax

```text
drydock publish <Source.md> --output <Output.html> [--theme <theme>] [--flatten]
                [--pdf] [--pdf-output <Output.pdf>]
```

### Rules

`2026-06-26` · **Front matter drives the page; the flag only overrides the theme.** Title,
author, studio, cover, and navigation come from the leading front-matter block. The theme resolves
`--theme`, then front matter `theme:`, then `slate`; supported themes are `sail`, `slate`,
`paper`. An unknown theme is a usage error. Cost when broken: a document rendered in a theme its
author did not choose.

`2026-06-26` · **`--flatten` splits by heading.** Each H1 and H2 section becomes its own page with
table-of-contents navigation. Cost when broken: a long specification published as one unreadable
page.

`2026-06-26` · **PDF uses the local browser.** `--pdf` or `--pdf-output` renders the HTML through
local Playwright/Chromium; `--pdf-output` implies `--pdf` and defaults beside the HTML. A renderer
failure is operational, not usage. Cost when broken: a PDF that differs from the HTML.

### Mechanism

1. Parse front matter and body. 2. Resolve the theme. 3. Render one page or a flattened set.
4. Render the PDF when requested. 5. Print the written paths.

### Exit codes

| Code | Condition |
|---|---|
| `0` | Published. |
| `1` | PDF renderer or I/O failure. |
| `2` | Usage error, including an unknown theme. |

### Spec divergence

- The specification lists no theme set for `publish`; its example uses `sail`. `harbor` is a
  `document` theme only.

## Decisions

-

## Open Questions

-

## Working Notes

-

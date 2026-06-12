# Branding — White Papers

**Version:** 20260609 V2
**Description:** Visual standard for Ed Barlow / Web Cloud Studio white papers — the single 860px
print column.

Inherits palette, typography, and the readability contract from `BRANDING_MAIN.md`; this file
covers only what is specific to white papers. Authoritative; not auto-distributed.
Reference implementation: `docs/oneshot.html` and `docs/white-paper.html` (Slate theme,
`styles/spec.css`).

A white paper is a single self-contained HTML page that links `styles/spec.css`, sets the Slate
`:root` variables, and renders process diagrams with `mermaid@10`. It must print cleanly to one
narrow column.

**Build path:** white papers are **generated from conformed markdown** — author
`docs/whitepapers/<slug>.md`, then run `drydock document assemble` to render the HTML. Do not
hand-edit the generated HTML.

---

## Layout

| Element | Rule |
|---------|------|
| Width | `.page-content` max-width **860px**, centered, padding `36px 36px 80px`. |
| Header | `.page-header.gem-header` — dark bar (`--c-topbar-bg`), logo + per-paper `header_title` + copyright notice (right-aligned). No navigation links — each paper is a self-contained object for embedding in an external frame. |
| Cover | `.cover` with `cover-eyebrow` (theme line), `h1` (title), `cover-sub` (one-paragraph abstract), `cover-meta` (author · studio · year). Bottom border `2px solid var(--c-accent)`. |
| Ideas | Optional `.wp-ideas` block of light-bulb cards (from frontmatter `ideas:`) between the cover and the body — the 3–5 ideas that frame the paper. All flush at one level. |
| Sections | `.wp-section`; each `h2` carries `border-bottom: 2px solid var(--c-accent)`. |
| Footer | author left, "Web Cloud Studio · YYYY" right; top border `1px solid var(--c-td-border)`. |

Keep sections tight: short problem statements, tables over prose, callouts for the one idea that
must not be missed. A white paper is meant to be printed — do not let any single element take a
whole page.

---

## Copyright

Every white paper must carry a strongly-worded copyright notice from Web Cloud Studio. Set it in
the frontmatter `copyright:` field; `build_whitepaper.py` renders it in the page header. If omitted,
the renderer auto-generates `© {year} {studio}. All rights reserved.` from the `year` and `studio`
frontmatter fields.

**Required wording:**

```
copyright: Copyright © {YYYY} Web Cloud Studio. All rights reserved. No part of this document may be reproduced or distributed without express written consent.
```

The notice appears right-aligned in the `.gem-header-copyright` span — the topmost visible element
on every rendered page and PDF print.

Colors come from the Slate `:root` variables in `styles/spec.css` — see `BRANDING_MAIN.md` for the
canonical palette. The mermaid `classDef` fills below are the one exception (mermaid cannot read CSS
variables).

---

## Process Diagrams (mermaid)

Process diagrams are **shape + color carry meaning, very few details.** Every diagram is
`flowchart LR` with **four to seven nodes** — never fewer, never more. A reader who has seen one
Drydock diagram can read them all: same colors, same shapes, same size on the page.

Paste the canonical `classDef` block verbatim into **every** diagram, even when a class is unused.
This keeps diagrams copy-paste consistent and stops per-diagram drift:

```
classDef dir    fill:#0a5c38,stroke:#2cb67d,color:#fff,font-weight:bold
classDef md     fill:#d4a017,stroke:#a07810,color:#111,font-weight:bold
classDef script fill:#1e40af,stroke:#3b5fc0,color:#fff,font-weight:bold
classDef prompt fill:#c2410c,stroke:#ea580c,color:#fff,font-weight:bold
classDef output fill:#6d28d9,stroke:#8b5cf6,color:#fff,font-weight:bold
classDef web    fill:#be123c,stroke:#fb7185,color:#fff,font-weight:bold
```

| Class | Color | Shape | Means |
|-------|-------|-------|-------|
| `dir` | green | stadium `(["…"])` | source: directory, Blueprint, or specification input |
| `md` | gold | hexagon `{{"…"}}` | generated markdown artifact (`BUILD_PLAN.md`, `*_compact.md`, `SCORECARD.md`, evidence) |
| `script` | blue | rect `["…"]` | a `drydock` verb or process step |
| `prompt` | orange | stadium `(["…"])` | AI prompt / spike run |
| `output` | purple | stadium `(["…"])` | delivered product (working software, published HTML) |
| `web` | crimson | rect `["…"]` | QuarterDeck / interactive web console |

Node labels:

- One or two words. Blue nodes carry the verb only (`import`, `plan create`, `rigging compact`) —
  never the full command line. Gold and green nodes carry the exact filename or a two-word noun.
- The same concept always gets the same label and class in every diagram. `BUILD_PLAN.md` is always
  a gold hexagon; the QuarterDeck is always a crimson rect; a Blueprint is always a green stadium.

Conventions:

- Solid arrows `-->` for the main flow; dashed `-.->` for feedback / decision write-back links.
- Initialize mermaid with `theme:'neutral', flowchart:{curve:'linear'}, themeVariables:{fontSize:'14px'}`.
  In Markdown source files, embed this as a per-diagram init directive on the first line of each block:
  `%%{init: {'theme': 'neutral', 'flowchart': {'curve': 'linear'}, 'themeVariables': {'fontSize': '14px'}}}%%`
- Wrap each diagram in `.wp-diagram` (panel `--c-pre-bg`, border `--c-td-border`); add a one-line
  italic `.wp-diagram-cap` beneath it.
- Include a small swatch legend when shapes/colors first appear.
- Never encode fine detail in a diagram — that belongs in a table or the prose. The four-to-seven
  node band is what keeps rendered diagrams a uniform size; if a flow needs more nodes, split it
  into two diagrams or cut it back to the decision the reader must understand.

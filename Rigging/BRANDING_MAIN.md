# Branding — Master

**Version:** 20260523 V1
**Category:** Branding
**Description:** Master brand standard for Ed Barlow / Web Cloud Studio — canonical palette,
typography, and philosophy. Per-medium rules inherit from this file.

Branding here **suggests** the colors, type, and feel — it is the canonical guidance fed into
builds. The CSS is per-application: each project implements the brand in its own stylesheet
(Prototyper's `docs/styles/themes/*.css` is one implementation), and a project may be *conformed*
to the brand. This file is the single source of the brand; CSS is downstream.

Authoritative; not auto-distributed.

---

## Identity

- **Person / studio:** Ed Barlow · Web Cloud Studio.
- **Feel:** dark chrome, light content; calm, technical, confident. No clutter, no AI-generic gloss.

---

## Canonical Palette — Slate (default theme)

The one place brand hex is defined. Themes are brand assets; Slate is the reference. To add a
theme, copy this block and replace values — keep the same variable contract.

| Token | Value | Role |
|-------|-------|------|
| `--c-topbar-bg` | `#1A1D23` | Darkest chrome — sidebar header / page header bar |
| `--c-side-bg` | `#22262E` | Sidebar body |
| `--c-side-border` | `#363B44` | Chrome/content divider, scrollbar |
| `--c-side-section` | `#8A8F9A` | Muted section label text |
| `--c-side-link` | `#FFFFFF` | Sidebar link text — always white |
| `--c-accent` | `#2CB67D` | Warm teal — accents, borders, active state |
| `--c-accent-text` | `#0E1012` | Text on accent-colored elements |
| `--c-h1` | `#1E2328` | Content h1 |
| `--c-h2` | `#2E3640` | Content h2 |
| `--c-h3` | `#505A68` | Content h3 / captions / meta |
| `--c-bg` | `#FAFAF8` | Warm off-white content background — never pure white |
| `--c-text` | `#2A2E35` | Near-black body text |
| `--c-th-bg` / `--c-td-border` / `--c-tr-alt` | `#2E3640` / `#D5D8DE` / `#F3F4F2` | Table head / borders / zebra |
| `--c-code-bg` / `--c-code-text` | `#EDEEE8` / `#2E3640` | Inline code |
| `--c-pre-bg` / `--c-pre-text` | `#1A1D23` / `#C0C4CC` | Code block / diagram panel |
| `--c-callout-bg` / `--c-callout-border` | `rgba(44,182,125,.06)` / `rgba(44,182,125,.2)` | Callout block |

Available themes (same contract, different values): `slate` *(default)*, `green`, `midnight`,
`purple`, `midnight-green`, `mughal`, `rainforest`, `ivory`, `clean`.

---

## Typography

No web fonts — OS system stack, renders natively everywhere.

```css
font-family: 'Segoe UI', 'Trebuchet MS', Arial, Helvetica, sans-serif;  /* all text */
font-family: 'Cascadia Code', Consolas, 'Courier New', monospace;        /* code/pre */
```

| Element | Size | Weight | Notes |
|---------|------|--------|-------|
| Body | 14px | 400 | `line-height: 1.65` |
| h1 | 22px | 700 | `--c-accent` + 2px underline |
| h2 | 17px | 700 | Light accent-tint bg, 4px accent left border — never a dark banner |
| h3 | 14px | 600 | `--c-h3`, no decoration |
| Inline code | 12.5px | 400 | Monospace, `--c-code-bg` |
| Code block | 12.5px | 400 | Monospace, `--c-pre-bg` |

---

## Readability Contract (hard rule)

**Light text on dark, dark text on light — always.**

- Content areas: light background (`--c-bg`), dark text (`--c-text`).
- Dark panels (sidebar, header bar): white or light-grey text only. Never `--c-text`/`--c-h1`/
  `--c-h3` or any value darker than `#999` on a dark background.
- Sub-pages set `body { background: var(--c-bg) }`; only the `<header>` element carries the dark
  background. Never put `body.gem-topbar` (dark) on a sub-page.
- Any text/background pair below WCAG AA (4.5:1) is a bug.

---

## The Branding Family

| File | Medium |
|------|--------|
| `BRANDING_MAIN.md` | This file — palette, type, philosophy, identity. |
| `BRANDING_DOCUMENTATION.md` | The documentation site (sidebar single-page app, themes, CSS assembly). |
| `BRANDING_WHITEPAPERS.md` | White papers (single 860px print column). Authoring format: `prompts/whitepaper.md`. |
| `BRANDING_WEBSITE.md` | Portfolio / homepage site. |
| `BRANDING_POSTS.md` | Social / blog posts. |

Each child inherits palette, typography, and philosophy from this file and covers only what is
specific to its medium. No child re-pastes the palette hex.

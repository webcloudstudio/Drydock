# Branding — Documentation Site

**Version:** 20260523 V1
**Description:** Visual standard for the documentation site — the dark-sidebar / light-content
single-page app, themes, and CSS assembly.

Inherits palette, typography, and the readability contract from `BRANDING_MAIN.md`; this file
covers only what is specific to the documentation site. Authoritative; not auto-distributed.

---

## Design Philosophy

Documentation uses a **dark chrome / light content** split:

- **Sidebar** (220px) — dark background, white text. Always dark.
- **Content area** — warm off-white background (`--c-bg`), dark text. Optimised for reading.
- **Sidebar header** — `--c-topbar-bg` (slightly darker than the sidebar body); reads as one
  continuous dark panel.
- **Navigation links** — no underline. Hover shows a 3px colored left border and subtle background lift.
- **Content hyperlinks** — standard blue `#1565C0`, always underlined. Web convention; not theme-overridden.

---

## Page Structure: Single-Page Sidebar Layout

The standard layout for all new projects.

```html
<body>                              <!-- bg: --c-bg, display:flex, height:100vh -->
  <nav class="sidebar">             <!-- width:220px, bg:--c-side-bg, overflow-y:auto -->
    <div class="sidebar-header">    <!-- bg:--c-topbar-bg, logo image + project name -->
    </div>
    <div class="nav-section">WORKFLOW</div>
    <a class="sn" onclick="...">Step 1 — Setup</a>
    <a class="sn-sub" onclick="...">setup.sh</a>
    <div class="nav-sep"></div>
    <div class="nav-section">CURRENT PROJECTS</div>
    <a class="sn" onclick="...">GAME</a>
  </nav>
  <main>                            <!-- flex:1, overflow-y:auto, padding:28px 36px 48px -->
    <!-- content sections, shown/hidden via JS -->
  </main>
</body>
```

Sidebar header uses `--c-topbar-bg` (darker than sidebar body) so it reads as a unified dark panel.
Logo is an `<img>` (100px wide), not a text badge.

---

## Logo / Sidebar Header

Two supported formats — choose based on available assets:

**Full image header** (preferred when a project image exists):
```html
<div class="sidebar-header" onclick="show('workflow')">
  <img src="images/prototyper.webp" alt="Prototyper" style="width:100px;height:75px;">
  <h1>Project<br>Prototyper</h1>
</div>
```
Logo image: `docs/images/<project>.webp`, 100×75px display, `object-fit:contain`.

**Compact icon header** (for smaller projects or when a full image is unavailable):
```html
<div class="sidebar-header" onclick="show('workflow')">
  <span class="sidebar-icon">⚔️</span>
  <h1>Conquer<br>2026</h1>
</div>
```
```css
.sidebar-icon { font-size: 28px; line-height: 1; flex-shrink: 0; }
.sidebar-header h1 { font-size: 14px; font-weight: 700; color: #fff; line-height: 1.25; }
```
Emoji icons render crisply at sidebar scale. Use the compact format when a project image has not
been generated yet — it is not a lesser choice.

---

## Workflow Diagram (Process-Based Projects)

For projects without a web server, the primary content is a workflow pipeline diagram. CSS classes
(all in the inline `<style>` block of the generated page):

```css
.wf-diagram  — flex column, gap 2px, margin-bottom 20px
.wf-row      — flex row, left-aligned, no wrap
.wf-box      — dark sidebar-bg box: padding 5px 10px, border-radius 4px, centered
.wf-terminal — green terminal box: border-color --c-accent, background #0a5c38
.wf-label    — 12px bold white text
.wf-script   — 10px white monospace (script name)
.wf-path     — 9.5px white monospace (path)
.wf-arr      — right arrow (→), 22px bold, --c-accent color, padding 0 6px
```

Two independent rows, both left-aligned, no connecting arrows between rows.

---

## Build Process

Every documented project has `bin/build_documentation.sh`. Running it:

1. **Assembles CSS** — concatenates `docs/styles/themes/<theme>.css` + `docs/styles/spec-base.css`
   → `docs/styles/spec.css`.
2. **Generates the page** — runs a project-specific builder (Python or bash) and writes `docs/index.html`.

```bash
./bin/build_documentation.sh                   # rebuild with current theme (default: slate)
./bin/build_documentation.sh --theme=midnight  # switch theme then rebuild
```

**Output always lands in `docs/`.** The default theme is `slate`.

---

## CSS File Assembly

```bash
# Built at documentation build time — do not edit docs/styles/spec.css directly
cat docs/styles/themes/slate.css docs/styles/spec-base.css > docs/styles/spec.css
```

| File | Location | Edit? |
|------|----------|-------|
| `spec.css` | `docs/styles/spec.css` | Never — generated |
| `<theme>.css` (e.g. `slate.css`) | `docs/styles/themes/` | Yes — theme colors only (see `BRANDING_MAIN.md`) |
| `spec-base.css` | `docs/styles/` | Rarely — structural CSS, no colors |

Change colors by editing the theme file and rebuilding — never touch `spec.css`. One command
re-styles all documentation:
```bash
bin/build_documentation.sh --theme=midnight
```

All themes enforce the two-zone rule from `BRANDING_MAIN.md`: content is always light; the sidebar
is always dark but never pure black (minimum `#22262E`). `--c-bg` lives in `spec-base.css`, not in
themes, so no theme can put dark text on a dark content background.

---

## Link Rules

| Context | Style |
|---------|-------|
| Content body `<a>` | `color: #1565C0; text-decoration: underline` |
| Content visited | Same blue `#1565C0` — no purple |
| Sidebar nav | White, no underline; hover: subtle bg + 3px `--c-accent` left border |

---

## Callout Blocks

Callouts use the accent color for a left border and a faint tinted background; a monospace **label**
adds technical clarity.

```html
<div class="callout">
  <span class="callout-label">NOTE</span>
  This is an important callout with a distinct label.
</div>
```
```css
.callout { border-left: 3px solid var(--c-accent); padding: 8px 14px;
  margin: 10px 0; background: var(--c-callout-bg); border-radius: 0 4px 4px 0; }
.callout-label { font-family: 'Cascadia Code', Consolas, monospace;
  font-size: 11px; font-weight: 700; color: var(--c-accent);
  text-transform: uppercase; letter-spacing: .5px; display: block; margin-bottom: 3px; }
```

Variants: `callout--warn` (amber) or `callout--danger` (red) for urgency.

---

## Multi-Page Documentation

For projects with many pages (e.g. a game with separate guides per topic):

- Each page links `<link rel="stylesheet" href="styles/spec.css">`.
- Sidebar nav uses `<a href="page.html">` standard links (not JS `show()`).
- All pages share the same sidebar markup; active page adds `class="active"` to the current link.
- A single shared `spec.css` means one theme change re-styles the entire multi-page set.

---

## What Not to Do

| Don't | Do instead |
|-------|------------|
| Dark content area (`--c-bg` dark) | Content is always light — `#FAFAF8` |
| Pure black sidebar (`#000` / `#0d1117`) | Minimum charcoal — `#22262E` |
| Dark text on any dark background | White (`#FFFFFF`) or light grey (`#C0C0C0`+) — never `--c-text`/`--c-h1`/`--c-h3` |
| `body.gem-topbar` on sub-pages | Sub-pages set `body { background: var(--c-bg) }`; only the header gets the dark background |
| Purple visited links | Keep `a:visited` the same blue as `a:link` |
| Arrows connecting separate workflow rows | Two independent left-to-right rows, no DOWN arrow |
| Expand/collapse toggles for script details | Always show details inline |
| Edit `spec.css` directly | Edit the theme file (`docs/styles/themes/<name>.css`) and rebuild |
| Dark h2 banner | h2 uses a light accent tint, not the dark sidebar color |

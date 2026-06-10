# Branding — Website

**Version:** 20260523 V1
**Description:** Visual standard for the portfolio / homepage site. First pass — refine the
medium-specific rules below.

Inherits palette, typography, and the readability contract from `BRANDING_MAIN.md`; this file
covers only what is specific to the public website. Authoritative; not auto-distributed.
Related specification surface: `HOMEPAGE.md` / `HOMEPAGE-PUBLISHER.md`.

---

## Purpose

The public face of Ed Barlow / Web Cloud Studio — a portfolio homepage that presents the person,
the studio, and the project cards. Marketing-grade and confident, but in the same calm Slate brand
as the docs and white papers (not a louder, separate look).

## Layout (first pass)

| Region | Rule |
|--------|------|
| Header / nav | Dark `--c-topbar-bg` bar: studio logo left, section links right. Same `gem-header` family as the white papers. |
| Hero | Name + one-line positioning + short bio paragraph. Light `--c-bg` surface. Accent rule under the headline (`2px solid var(--c-accent)`). |
| Project cards | Grid of cards, each: title, one-line description, status badge, link. Card uses light surface, `--c-td-border` edge, accent on hover. |
| Contact / bio | Short bio, links (GitHub, email). |
| Footer | "Ed Barlow · Web Cloud Studio · YYYY". |

## Tone

Confident and concrete — what the work does and why it matters, not buzzwords. One strong sentence
beats a paragraph. Formal English (see `BRANDING_EDSVOICE.md`).

## To define (Ed)

- Exact section order and which projects are featured.
- Hero headline / positioning line.
- Card image style (reuse the per-project `images/<project>.webp` assets?).

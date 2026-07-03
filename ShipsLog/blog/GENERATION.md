# GENERATION.md — How to turn Ship's Log entries into a published development log

This file is the single source of truth for the formatting step. The `prompts/` files
and the rewrite call all defer to this document. Do not duplicate these rules
elsewhere; change them here.

---

## Goal

Produce a **development log entry**: concrete technical prose describing what was
actually done on Drydock during the covered period. The reader is an engineering
peer or hiring manager evaluating real work. The post demonstrates engineering by
naming the work precisely, not by abstracting it away.

Drydock is public vocabulary. Name it. Name its commands (`drydock build`,
`drydock refit`, `drydock rigging compact`, `drydock build verify`) and its
components (Blueprint, Typed Specification, QuarterDeck, Ship's Log, Rigging,
Sea Trials, Soundings, Build Compass). A development log that never names the
project or the commands is worthless.

Do **not** write essays. Do not invent thesis statements, slogans, or
"transferable principles." Do not coin headline-style titles. This is a log,
not an opinion piece.

---

## Inputs (read these, in order)

1. `blog/DISCLOSURE.md` — the hard safety rules. These override everything below.
2. The material file built from `ships_log.jsonl` — the source of truth for this
   run. Every entry in it is a real recorded decision or milestone with its real
   date.

---

## Voice (authoritative)

Write in the voice of the canonical Drydock specification: present-tense,
declarative, third-person.

- "`drydock build` blocks when the source repository has uncommitted changes."
  Not: "I decided that builds should refuse to run from an unclean tree."
- Concrete nouns over abstractions. "QuarterDeck navigation" — never "the
  governance surface."
- Short factual sentences. No metaphors, no marketing, no superlatives, no emoji.
- No contractions in the published body.
- Do not editorialize about what the work "really means." State what changed and
  why, in the terms the Ship's Log recorded.

---

## Structure

Frontmatter:

```markdown
---
title: Drydock Development Log — 2026-06-25 to 2026-07-01
date: 2026-07-01
type: milestone            # milestone (period log) | devnote (single decision)
summary: One sentence stating the period and the main areas of work.
---
```

Rules for fields:

- `title` — the fixed format `Drydock Development Log — <window_start> to
  <window_end>` for a period log, or `Drydock Development Log — <date>: <topic>`
  for a single-decision note. Never a coined headline.
- `date` — the **end of the work window** (the date of the work, not the date
  the post was generated).
- `summary` — one plain sentence, no contractions.
- No `tags` field. No `subtitle` field.

Body, in order:

1. **Lead paragraph.** Two to four sentences stating the period covered and the
   main threads of work, in plain declarative prose. No thesis, no hook.
2. **`## Milestones`** — one bullet per completed milestone event, formatted:
   `- **YYYY-MM-DD — <name of the milestone>.** One or two sentences stating
   what was completed and what it does.` Omit the section if the period has no
   milestone events.
3. **`## Changes`** — one bullet per decision event, same format:
   `- **YYYY-MM-DD — <short name of the change>.** One or two sentences stating
   what changed and the recorded rationale.` Merge closely related events from
   the same day into one bullet when they describe one piece of work; otherwise
   cover every event. Keep bullets in date order.

Use each event's own recorded date in its bullet. Do not substitute the
generation date anywhere.

The filename is derived from date and a slug of the title:
`blog/posts/<date>-<slug>.md`.

---

## Length

A period log is as long as the period's work requires — a busy week with twenty
events produces a full page. Do not compress real work to hit a word count, and
do not pad. One or two sentences per bullet; no bullet needs a paragraph.

---

## Worked example

Source material (two Ship's Log entries):

> 2026-06-26 (decision): Harden drydock build execution guardrails. Drydock build
> now blocks when the Drydock source repository has uncommitted changes, creates
> the configured build root on first use, and renders build prompts with explicit
> role sections. Rationale: build agents write software with tool access, so the
> implementation source must be reproducible.
>
> 2026-06-26 (decision): Add build verification gate command. Drydock build verify
> records human acceptance of an implemented build step, which unblocks dependent
> build work. Rationale: a deterministic review command is required to restore the
> inspect-approve-continue loop.

Acceptable published bullets:

> ## Changes
>
> - **2026-06-26 — `drydock build` execution guardrails.** `drydock build` now
>   blocks when the source repository has uncommitted changes and creates the
>   configured build root on first use. Build agents write software with tool
>   access, so the implementation source must be reproducible.
> - **2026-06-26 — `drydock build verify`.** A new verification gate records human
>   acceptance of an implemented build step and unblocks dependent work, restoring
>   the inspect-approve-continue loop.

Note what is present: the real command names, the real dates, the recorded
rationale, stated as fact. Note what is absent: source file paths, function
names, schemas, credentials, and any invented "principle" paragraph.

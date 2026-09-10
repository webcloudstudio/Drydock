# Branding — Posts

**Version:** 20260910 V3
**Category:** Branding
**Description:** Standard for development-log posts Ed publishes on his site.

Inherits the brand feel from `BRANDING_MAIN.md`; this file covers only what is specific to
published development-log posts. Authoritative; not auto-distributed.

---

## Purpose

Published development logs covering what shipped and what it does.
The reader is a working developer. The post earns their attention by saying plainly what each
piece of work does and why it exists, not by proving how much of it there was. Same calm,
technical, confident brand as everything else; written to be read in one sitting.

## Voice

The voice is the voice of the canonical project specification: present-tense, declarative,
third-person, concrete.

| Aspect | Rule |
|--------|------|
| Register | Specification prose. "`drydock build` blocks when the source repository has uncommitted changes." Never first-person narrative, never marketing. |
| Nouns | Real ones. The project name, its command surface, and its component names appear in the post. A log that names nothing proves nothing. |
| Sentences | Short and factual. No metaphors, no slogans, no coined "principles," no superlatives, no emoji, no contractions in the body. |
| Titles | The post is `Drydock Development Log`. A milestone title is the thing itself — `drydock diagnose`, `DATABASE.md persistence layer` — never a coined headline. |
| Dates | One date: the publication date, in the form `September 9, 2026`. Milestones are not dated and the post does not state a work period. |
| Subject | Every paragraph answers what the work does. Rationale earns its place only where the reader would otherwise ask why. |

## Structure

1. `## Milestones` — the post opens here. One undated bullet per milestone, each a single
   sentence saying what it does.
2. One `## <milestone>` section per bullet, in the same order, under the same title.

Bullet format: `- **<milestone>** — one sentence.`

A section is two or three short paragraphs and stops. Lead with what the thing does; a command
gets its invocation in a `text` block first. State a limitation where one exists.

## Length

One screen per milestone at most. Cut every sentence that does not tell the reader something
they can act on or repeat. A post that lists more than it explains is too long whatever its size.

## Anti-patterns

- Essay or think-piece framing of any kind.
- Headline-style titles written for social media.
- Abstract paraphrase where the concrete name exists ("the governance surface" for QuarterDeck).
- Inventories: lists of file names, log names, module paths, function names, or artifact names
  the reader has no reason to hold. Name a file when the reader opens or edits it.
- Invented vocabulary for an ordinary idea. Say what the code does instead.
- A change list in date order. The changelog is the change list.
- Tags, hashtags, or subtitle lines.
- Explaining the writing itself.

## Rendering

Posts live in `docs/posts/` and render with `drydock publish --theme slate`. Rendered pages
implement the Slate brand from `BRANDING_MAIN.md`: dark chrome header carrying the Drydock logo,
light content column, system font stack, teal accent on headings. No decorative hero cards, no
pill tags, no serif display type.

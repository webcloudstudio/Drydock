# Branding — Posts

**Type:** guidance
**Version:** 20260910 V4
**Category:** Branding
**Description:** Standard for development-log posts Ed publishes on his site.

Inherits the brand feel from `BRANDING_MAIN.md`; this file covers only what is specific to
published development-log posts. Authoritative; not auto-distributed.

**Reference example:** `docs/posts/devlog_2026-09-09.md`. That post is the standard. Where this
document and that post disagree, the post is right.

---

## Purpose

Published development logs covering what shipped and what it does. The reader is a working
developer who wants the interface: the command, the flags, the file, the section, the identifier.
A post is field notes tightened, not an article about the work.

## Voice

| Aspect | Rule |
|--------|------|
| Register | Terse technical note. Short declarative sentences; fragments are acceptable. Second person for the operator's own artifacts ("your last run"). No marketing, no narrative. |
| Nouns | Every real name, always: command, flag, file, section heading, package, identifier. `BLOCKERS.md`, `SQLAlchemy`, `## Access Patterns`, `FEATURE-ORDER-001`. The names are the content. |
| Lists | Content belongs in lists. What a report contains, what sections were added, what each one defines. Use prose only where a list cannot hold it. |
| Examples | Anything structural gets a worked example using real identifiers, not placeholders. |
| Rationale | One clause where the reader would otherwise ask why. Never a paragraph, never a thesis, never an aphorism. |
| Sentences | Factual. No metaphor, slogan, coined principle, superlative, emoji, or contraction in the body. |
| Titles | The post is `Drydock Development Log`. A milestone title is the thing itself — `drydock diagnose`, `DATABASE Encapsulation` — never a coined headline. |
| Dates | One date: the publication date, as `September 9, 2026`. Milestones are not dated; no work period is stated. |

## Structure

1. `## Milestones` — the post opens here. One undated bullet per milestone, one sentence saying
   what it does.
2. One `## <milestone>` section per bullet, in the same order, under the same title.

Bullet format: `- **<milestone>** — one sentence.`

A section leads with what the thing does. A command gets every invocation form in a `text` block
first. Then the list of what it produces or what changed, then the example, then the limitation.
State a limitation where one exists.

## Length

A section is a lead line, a list, and at most two short paragraphs. The whole post reads in one
sitting. Cut every sentence that does not tell the reader something they can act on or repeat.

## Anti-patterns

- Thesis and aphorism. "A stopped run is an opportunity, not a failure." "The persistence layer
  exists to keep application change out of the database." Delete the sentence; nothing is lost.
- Three paragraphs of prose where four bullets carry the same facts.
- Restating one fact in successive paragraphs at different altitudes.
- Paraphrase where the name exists — "a structured report" without naming the sections in it,
  "the governance surface" for QuarterDeck.
- Placeholder examples. Use the identifiers the code uses.
- Essay or think-piece framing; headline titles written for social media.
- Invented vocabulary for an ordinary idea. Say what the code does.
- A change list in date order. The changelog is the change list.
- Tags, hashtags, subtitle lines, or explaining the writing itself.

## Collaboration

Ed writes the post. The assistant edits it. Authoring is not delegated, and a post rewritten by
hand after an assistant draft cost more time than it saved.

- The supplied draft is the source text. Preserve his words, order, and headings. Edit around his
  sentences; complete only what he left unfinished.
- A question is a question. Answer it in chat. Never answer a question by rewriting the draft.
- Make only the requested edit. Never silently redraft, shorten, consolidate, reorder, or improve
  anything that was not asked about.
- When asked for the copy, return the complete current text of the file or section. Never a
  fragment, never a diff in place of the whole.
- Apply a terminology direction across the entire draft and hold it. Do not drift between naming
  schemes between replies.
- Read the code before writing about it. Never invent a class, file, command, or identifier the
  repository does not contain.

## Rendering

Posts live in `docs/posts/` and render with `drydock publish --theme slate`. Rendered pages
implement the Slate brand from `BRANDING_MAIN.md`: dark chrome header carrying the Drydock logo,
light content column, system font stack, teal accent on headings. No decorative hero cards, no
pill tags, no serif display type.

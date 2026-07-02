# Branding — Posts

**Version:** 20260702 V2
**Description:** Standard for development-log posts Ed publishes on his site.

Inherits the brand feel from `BRANDING_MAIN.md`; this file covers only what is specific to
published development-log posts. Authoritative; not auto-distributed.

---

## Purpose

Published development logs assembled from real project decision history (the Ship's Log).
The reader is an engineering peer or hiring manager. The post proves real, serious,
well-governed engineering work by naming it precisely. Same calm, technical, confident
brand as everything else; written to be skimmed quickly.

## Voice

The voice is the voice of the canonical project specification: present-tense, declarative,
third-person, concrete.

| Aspect | Rule |
|--------|------|
| Register | Specification prose. "`drydock build` blocks when the source repository has uncommitted changes." Never first-person narrative, never marketing. |
| Nouns | Real ones. The project name, its command surface, and its component names appear in the post. A log that names nothing proves nothing. |
| Sentences | Short and factual. No metaphors, no slogans, no coined "principles," no superlatives, no emoji, no contractions in the body. |
| Titles | Fixed format: `Drydock Development Log — <start> to <end>` (period) or `— <date>: <topic>` (single decision). Never a coined headline. |
| Dates | Every entry carries the date the work was recorded. The post date is the end of the work window, never the generation date. |

## Structure

1. Lead paragraph — two to four sentences stating the period and the main threads of work.
2. `## Milestones` — dated bullets for completed milestones (omit when none).
3. `## Changes` — dated bullets for decisions, in date order, each with the recorded rationale.

Bullet format: `- **YYYY-MM-DD — <name>.** One or two sentences.`

## Length

As long as the period's work requires. Do not compress real work to hit a word count;
do not pad. One or two sentences per bullet.

## Anti-patterns

- Essay or think-piece framing of any kind.
- Headline-style titles written for social media.
- Abstract paraphrase where the concrete name exists ("the governance surface" for QuarterDeck).
- Tags, hashtags, or subtitle lines.
- Explaining the writing itself.

## Rendering

Rendered pages implement the Slate brand from `BRANDING_MAIN.md`: dark chrome header
carrying the Drydock logo, light content column, system font stack, teal accent on
headings. No decorative hero cards, no pill tags, no serif display type.

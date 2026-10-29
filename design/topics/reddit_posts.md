# MEMORY: Reddit posts

| Field | Value |
|---|---|
| Version | 2026-10-29 |
| Description | Provider-specific Reddit drafts preserving Ed's source and brevity. |
| Modules | `docs/posts/real.md`, `docs/posts/codex.md`, `docs/posts/claudecode.md`, `docs/posts/claudeworkflows.md` |

## Intent

Preserve Ed's concise wording while adapting Drydock posts to each community's rules.

## Guardrails

- `2026-10-29` · Ed requires the style and format of `real.md`, no invented boilerplate or project claims, and questions where his wording or details are needed. Breaking this produces unusable copy.
- `2026-10-29` · The specification is read-only. Posts do not establish product behavior or authorize publication.

## Details

### Current contract

`real.md` supplies project facts and the reported release test matrix. The three drafts target r/codex, r/ClaudeCode, and r/ClaudeWorkflows; Ed confirmed the third destination. Only the drafts and editorial records are changed. No tests, reports, UAT inspection, or publication are run to establish new claims. Preserve the source; check draft claims against it and syntax-check the embedded shell without execution.

Public rules checked 2026-10-29: r/codex requires direct Codex relevance and appropriate flair; Showcase is applicable. r/ClaudeCode routes simple project sharing to its weekly showcase; standalone posts require how Claude Code was used and lessons learned. r/ClaudeWorkflows permits public posting but prohibits excessive promotion and advertising; most visible posts are curated summaries. Posting guidance is an HTML comment outside the rendered draft. Acceptance by moderation is unverified.

## Decisions

- None.

## Questions

- `2026-10-29` · Draft review: Ed's exact acceptance-criteria repair wording and its relationship to requirement intent remain pending; close with his supplied wording.
- `2026-10-29` · `real.md` describes 0.8; confirm whether newer changes belong in these posts.
- `2026-10-29` · ClaudeCode standalone eligibility: confirm how Claude Code was used and the lesson Ed wants to state. Current draft targets the weekly showcase.
- `2026-10-29` · Prior moderation removals: requested any removal message to identify restrictions beyond public rules; close with a supplied message or confirmation none is available.

## Actions

- `2026-10-29` · Review the three drafts with Ed and apply his supplied wording before treating them as final copy. No Reddit publication has occurred.

## Working Notes

- None.

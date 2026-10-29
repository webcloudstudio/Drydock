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

Ed confirmed the same 0.8 release scope, use of Claude Code and Codex both to build Drydock and to build software, and no previous group rejection. His acceptance-test wording describes iterative pretesting to reveal accuracy, quality, and existing behavior; malformed tests, including imports from another step, are judged and repaired. This wording is used without inventing a stronger test-intent guarantee.

## Decisions

- None.

## Questions

- None.

## Actions

- `2026-10-29` · Review the three drafts with Ed and refine any remaining wording he flags. No Reddit publication has occurred.

## Working Notes

- None.

# MEMORY: Reddit posts

| Field | Value |
|---|---|
| Version | 2026-10-29 |
| Description | Provider-specific Reddit drafts preserving Ed's source and brevity. |
| Modules | `docs/posts/20261029.specdrivendevelopment.md`, `docs/posts/codex.md`, `docs/posts/claudecode.md`, `docs/posts/claudeworkflows.md` |

## Intent

Preserve Ed's concise wording while adapting Drydock posts to each community's rules.

## Guardrails

- `2026-10-29` · Ed requires the style and format of the original `real.md` (now `20261029.specdrivendevelopment.md`), no invented boilerplate or project claims, and questions where his wording or details are needed. Breaking this produces unusable copy.
- `2026-10-29` · The specification is read-only. Posts do not establish product behavior or authorize publication.

## Details

### Current contract

`docs/posts/20261029.specdrivendevelopment.md` supplies project facts and the reported release test matrix. The three drafts target r/codex, r/ClaudeCode, and r/ClaudeWorkflows; Ed confirmed the third destination. Only the drafts and editorial records are changed. No tests, reports, UAT inspection, or publication are run to establish new claims. Preserve the source; check draft claims against it and syntax-check the embedded shell without execution.

Public rules checked 2026-10-29: r/codex requires direct Codex relevance and appropriate flair; Showcase is applicable. r/ClaudeCode routes simple project sharing to its weekly showcase; standalone posts require how Claude Code was used and lessons learned. r/ClaudeWorkflows permits public posting but prohibits excessive promotion and advertising; most visible posts are curated summaries. The documents contain only a title and post body; posting guidance stays in this memory. Codex uses Showcase, ClaudeCode uses the applicable Built with Claude showcase flair, and ClaudeWorkflows is a workflow submission. No group is treated as requiring the same release-announcement format. Acceptance by moderation is unverified.

Ed confirmed the same 0.8 release scope, use of Claude Code and Codex both to build Drydock and to build software, and initially reported no previous group rejection. He subsequently reported an automatic rejection in "ClaudeCodeWorkflows"; the precise subreddit and rejection text are not yet confirmed. His acceptance-test wording describes iterative pretesting to reveal accuracy, quality, and existing behavior; malformed tests, including imports from another step, are judged and repaired. This wording is used without inventing a stronger test-intent guarantee.

The 2026-10-29 rewrite uses the renamed source directly, with `docs/Drydock_Specification.md` only for workflow elaboration: block context, blockers, bounded repair, graph invalidation, and acceptance versus project-intent checks. All three posts lead with the workflow and omit version announcements, feature-launch labels, installation pitches, and star requests. Codex emphasizes context and completion; ClaudeCode explains use and observed lessons; ClaudeWorkflows gives five procedural stages. Test results remain the author's reported source claims, not newly inspected evidence. Embedded shell is syntax-checked without execution.

## Decisions

- None.

## Questions

- `2026-10-29` · Ed reports an automatic rejection in "ClaudeCodeWorkflows". Requested the exact subreddit and rejection text; close with the supplied notice so any additional restriction can be addressed. The cause is not established by the public rules.

## Actions

- `2026-10-29` · Reconcile the reported automatic rejection with its exact notice when supplied. The workflow rewrites address public content rules; moderation acceptance is unverified. No Reddit publication has occurred.

## Working Notes

- None.

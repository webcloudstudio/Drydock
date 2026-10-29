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

The posts lead with Ed's agreed product opening: software built from specifications and designs using Agile and Test Driven Development, low-end models, and a full locally hosted web experience, from vibe coding to enterprise tooling. The objective is buzz, repository discovery, and stars. Shared rules explain consistent branding and behavior. **Do not introduce SAIL terminology or make acceptance-test work the product's purpose.**

The workflow's point is multi-level self-correction to deliver working software: `plan verify / plan repair` corrects acceptance criteria; `build` repairs failed code; `diagnose --apply` identifies and repairs recoverable AC defects, partial blocks/agent-output failures, and environmental failures; `status --check / score release` measures completion and project objectives. The source command workflow retains its three-attempt build loop. Reported UAT passes are evidence for the workflow, not a promise that retries always succeed. `refit` supports ongoing change in one short closing paragraph.

All three documents contain **What I learned** with the four lessons Ed approved: a failed test may reject correct code (the archived Marina adjacent-move assertion); diagnosis of recoverable AC, agent-output, and environmental failures (corrected by Ed; the earlier specification-error framing was rejected); planning and building can need different models (two Haiku planning overrides); database encapsulation limits downstream rebuilds. Sources are `docs/posts/archive/devlog_2026-09-09.md.unposted`, the October archived drafts, the renamed source, and Ed's supplied wording. The archived SQLAlchemy/Alembic implementation is historical and is not asserted as current. Test results remain reported source claims; no UAT evidence is inspected or commands executed.

Ed rejected both the invented five-stage summary and the later SAIL-led rewrite. Condense his corpus and agreed wording; do not replace the product story with a methodology or acceptance-testing tutorial. Discuss substantive framing changes before implementation; the current edit is explicitly authorized. No release-announcement labels, installation pitch, star request, or invented workflow taxonomy appears in the posts. Syntax-check embedded shell without execution.

ClaudeCode and ClaudeWorkflows use **Drydock — Building Software from Specifications**. Ed shortened the Codex title to **Drydock — Build Software from Specifications**; preserve it. The shared drafts introduced a short rationale before the code: specifications define the software, acceptance criteria measure correctness, and changes return to the specifications as the source of truth. The general workflow definitions in `../patents/patent_acceptance.md` and `../patents/patent_refit.md` inform this explanation only; their claimed mechanisms are not implementation evidence. Patent files remain read-only.

The purpose is to demonstrate a useful specification-driven software-building workflow, not document every SDD command. Codex demonstrates building with Luna; ClaudeCode demonstrates use of Claude Code/Haiku plus observed lessons; ClaudeWorkflows presents a reproducible workflow. UAT is supporting evidence, not the topic: omit the UAT Testing heading and keep one provider-relevant sentence reporting the source matrix's passes. Omit Gemini trial counts where they do not support the destination's topic.

The Codex post is now edited independently around Ed's current introduction and goal. Before the command example, short `drydock analyze`, `drydock plan`, `drydock build`, and `drydock diagnose --apply` paragraphs explain the workflow. Analyze owns stories, questions, and blockers; Plan owns Blueprints, ordering/context, and acceptance-criteria repair; Build owns step execution and measured code repair, followed immediately by diagnosis when build repair is insufficient. The Luna rationale is manageable build steps, relevant context, and measured progress for a large specification; do not invent a model context limit or imply a measured universal inability. Preserve Ed's introduction, correct only its duplicated words/punctuation, and retain the lessons. Other group drafts are outside this edit.

Ed's current Codex draft owns the wording, including his environmental-failure observation and cheap prompt-stacking iteration. The latest pass is a copy edit/evaluation, not authorization to invent replacement lessons. Corrected grammar, headings, command case, the incomplete diagnosis description, and the distinction between Blueprint files and the graph build plan. Replaced claims that criteria/pretesting "guarantee" quality or coverage with verify/assess wording. The shell workflow stays unchanged. Archived October drafts label the material New Features, not What I learned: measured criteria, self-improving builds, persistence encapsulation. September adds root-cause diagnosis and the incorrect adjacent-move assertion.

Ed clarified Applications differ: jq/CommonMark have huge test-case suites, while other applications are database-oriented. The fragment is resolved. He treats the archived new features as lessons 1:1; do not replace his outer-loop explanation with "code repair alone is insufficient" or add an obvious generic retries lesson. Added brief lessons on memory files limiting code drift across varied projects and dependency-selected context/XML prompt blocks. Keeping the Cache Warm is a short separate section: preserve the step base prompt and append feedback; Claude resumes its block session, while Codex reuses the base plus only the latest feedback. Evidence: `prompt_assembly.py` renders `<pblock>` role/file metadata, `build.py` assembles declared roles, and `build_run.py` distinguishes Claude session appends from fresh-provider feedback. This is prompt-prefix reuse, not a separate keep-alive service or guaranteed cache hit.

The Codex shell loop uses `while ...; do` and a one-line `if ...; then echo ...; exit 1; fi`, preserving the pre-build attempt-limit check. Ed requested compact syntax. Other posts are unchanged.

Ed corrected the diagnosis framing explicitly: the lesson is not that specifications are wrong or need improving. AC may be wrong and repairable on reflection, LLM output may contain partial blocks, or recoverable environmental failures may halt the build. The Codex step, shell comment, and lesson now consistently describe that purpose. Removed "Some build failures require better specifications" from this post. The source document remains unchanged; this correction governs editorial framing, not a product implementation change.

Ed requires general lessons, not named-project examples. Applications differ now describes large test suites and database-oriented applications without naming kits. His latest prose is authoritative for voice; edits are limited to grammar, capitalization, and the requested correction. Preserve his concise memory-file and prompt-stacking lessons; do not restore a separate cache section he removed or reintroduce provider-specific mechanics without need.

## Decisions

- None.

## Questions

- `2026-10-29` · Ed reports an automatic rejection in "ClaudeCodeWorkflows". Requested the exact subreddit and rejection text; close with the supplied notice so any additional restriction can be addressed. The cause is not established by the public rules.

## Actions

- `2026-10-29` · Reconcile the reported automatic rejection with its exact notice when supplied. The workflow rewrites address public content rules; moderation acceptance is unverified. No Reddit publication has occurred.

## Working Notes

Ed rejected generic retries and code-repair-insufficiency wording. Keep his existing build/diagnose explanation. The Haiku/Sonnet planning observation remains available but is secondary in the Codex post.

# Proposed Specification Changes

Pending reconciliation of `spec:approved` items from `docs/notes_analyze.md` into
`docs/Drydock_Specification.md`. 16 items.

| # | Source | Change |
|---|--------|--------|
| A | FIX-1 | Quality gate is blockers-only — spec still says "no open questions" for Ready; correct to blockers-only gating; both Questions and Ready permit `plan create`. |
| B | FIX-2 | spike-stack.json example must be valid JSON — prompt showed unparseable options placeholder; spec should require valid JSON in all `spike-*.json` blocks. |
| C | FIX-3 | SOUNDINGS precedence — use stated AC from sources where present; otherwise synthesize per feature/screen/persistence area. Remove "from spec files" wording. |
| D | FIX-4 | "Do not invent gaps" clarification — fabricating requirements is forbidden; genuinely absent decisions (no auth model) are real gaps, not invented requirements. |
| E | FIX-5 | spike-stack options = Rigging catalog filenames filtered to project type; `analyze` never opens per-technology stack files. |
| F | FIX-6 | Checklist and project-type detection operate on imported source content only — no typed spec files exist at analyze time; remove `DATABASE.md`/`SCREEN-*.md` file-presence checks. |
| G | BUG-7 | `blueprint/` must contain only `sources/` after import+analyze — typed-spec template stubs are `plan create` outputs, not import outputs; `METADATA.md` lives at target root, not `blueprint/`. |
| H | FIX-8 | `analyze` prints artifact filenames it created — CLI output contract requires a list of written files on success. |
| I | FIX-9 | Analyze prompt structured as ordered steps with per-step consumes/emits contracts — sequential pipeline: sources→roles→blockers/questions→story list→SOUNDINGS→SEA_TRIALS→quality→questionnaires. |
| J | FIX-10 | BLOCKERS.md writer rejects empty/placeholder content — structural enforcement: ≥1 `##` heading required; absence of real blockers must not write/retain the file. |
| K | Feedback | Standing-directive methodology — each generative step exports a persistent feedback file (never overwritten by the command) re-injected at top of its prompt every run. |
| L | Feedback | ANALYSIS_COMPASS.md — target root, injection stack position 3 (after job block, before BLOCKERS.md); QuarterDeck shows it under ANALYSIS, editable, submit saves to file. |
| M | Feedback | BUILD_CONFIGURATION.md retired — no defined format, writer, or value; its two roles now split between feedback files (free-text) and answered `spike-*.json` (structured decisions). |
| N | Feedback | Rigging catalog = filename list only — inject `BRA*.md` + `stack/*.md` names, exclude `README.md`; no file content injected; names are the spike-stack options source. |
| O | Feedback | Final injection stack — (1) prompt body (2) job block (3) `ANALYSIS_COMPASS.md` (4) `BLOCKERS.md` (5) Rigging catalog filenames (6) `blueprint/sources/*.md`; COMPASS not injected. |
| P | Session | ANALYSIS.md tab structure — Overview/Story List/Open Questions/Notes; no `## Analysis Summary` heading; no `## Blockers` section; Open Questions items cite their `spike-*.json` file. |

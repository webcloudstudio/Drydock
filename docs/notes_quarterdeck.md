# NOTES: QuarterDeck

| Field | Value |
|-------|-------|
| Version | 2026-06-17 V15 |
| Route | quarterdeck |
| Status | Working notes — not canonical specification |
| Description | QuarterDeck nav, section routing, icon model, page header, blocker artifact, tabbed-render type, the Artifact Feed Matrix, and the buttonless questionnaire model. |
| Pending spec | 0 | 0 || Pending impl | 1 partial item (config-driven-agents: inputs: declared; runner wiring outstanding) | 0 |
## Goal

Build QuarterDeck the correct way: screens are shown based on where the project is in the
delivery workflow, not unconditionally. Build analyze to produce the correct set of artifacts.

## Decisions

### Config Driven Agents
`2026-06-17` · `spec:na` · `impl:partial`

The Artifact Feed Matrix is the *contract*; an agent's consumed inputs must be **declared
configuration, not hardcoded** assembly logic. The declared home is the **prompt frontmatter
`inputs:` row** — an ordered, comma-delimited list of logical tokens that is the agent's source of
truth AND its injection (stack) order. (The earlier `agents_config.json` idea is superseded — the
prompt header is the right place, symmetric with the existing `output:` row.)

**Rules.** COMPASS.md is always first. Single files are named by on-disk filename; globbed groups use
a suffix-less token (`QUESTIONNAIRES` = answered `spike-*.json`; `TYPED_SPEC` = Typed Spec / blueprint
source files). Rows are derived from the matrix: every cell with `I`, `O/I`, `O*/I`, or the `X` gate.
Absent inputs are skipped at assembly; per-token semantics (content injection vs `BLOCKERS` gate for
plan create) resolve in the Python assembler; computed job metadata (date, target, paths, quality) is
not a file and is not listed.

Per-command `inputs:` (matrix-derived):

| Command | `inputs:` (ordered, COMPASS first) |
|---|---|
| analyze | `COMPASS.md, ANALYSIS_FEEDBACK.md, BLOCKERS.md, TYPED_SPEC` |
| plan create | `COMPASS.md, ANALYSIS.md, SOUNDINGS.md, BLOCKERS.md, QUESTIONNAIRES, MANIFEST_FEEDBACK.md, MANIFEST_CONTRACT.md, BLUEPRINTS_CONTRACT.md, TYPED_SPEC` |
| build | `COMPASS.md, QUESTIONNAIRES, TYPED_SPEC, MANIFEST.md, tickets.json, BUILD_PLAN_COMPASS.md` |
| build score | `COMPASS.md, SOUNDINGS.md, TYPED_SPEC, MANIFEST.md, tickets.json` |
| refit | `COMPASS.md, TYPED_SPEC, MANIFEST.md, tickets.json` |

**Done (`impl:partial`).** The `inputs:` row is added to the two existing prompts (`analyze.md`,
`plan_create.md`), faithfully mirroring today's hardcoded injection order; `prompts/README.md`
documents the contract and token vocabulary; `Prompt.input_tokens` (`src/drydock/prompts.py`) parses
the row. **Outstanding (wiring):** refactor `analyze.py` and `planning_session.py` `_assemble_prompt()`
to resolve `inputs:` tokens and drive injection order from them (with glob expansion + parity tests),
so the row actually drives assembly rather than mirroring it. `build`/`build score`/`refit` rows
above are recorded for when those prompts are authored.


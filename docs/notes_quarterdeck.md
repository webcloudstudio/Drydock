# NOTES: QuarterDeck

| Field | Value |
|-------|-------|
| Version | 2026-06-17 V16 |
| Route | quarterdeck |
| Status | Working notes — not canonical specification |
| Description | QuarterDeck nav, section routing, icon model, page header, blocker artifact, tabbed-render type, the Artifact Feed Matrix, and the buttonless questionnaire model. |
| Pending spec | 0 |
| Pending impl | 0 |

## Goal

Build QuarterDeck the correct way: screens are shown based on where the project is in the
delivery workflow, not unconditionally. Build analyze to produce the correct set of artifacts.

## Decisions

### Config Driven Agents
`2026-06-17` · `spec:na` · `impl:implemented`

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
| analyze | `COMPASS.md, ANALYZE_COMPASS.md, BLOCKERS.md, TYPED_SPEC` |
| plan create | `COMPASS.md, ANALYSIS.md, SOUNDINGS.md, BLOCKERS.md, QUESTIONNAIRES, PLAN_COMPASS.md, MANIFEST_CONTRACT.md, BLUEPRINTS_CONTRACT.md, TYPED_SPEC` |
| build | `COMPASS.md, QUESTIONNAIRES, TYPED_SPEC, MANIFEST.md, tickets.json, BUILD_COMPASS.md` |
| build score | `COMPASS.md, SOUNDINGS.md, TYPED_SPEC, MANIFEST.md, tickets.json` |
| refit | `COMPASS.md, TYPED_SPEC, MANIFEST.md, tickets.json` |

**Done (`impl:implemented`).** The `inputs:` row drives prompt assembly end-to-end:

- `prompts/analyze.md` + `plan_create.md` carry the ordered `inputs:` rows; `prompts/README.md`
  documents the contract and token vocabulary.
- `Prompt.input_tokens` parses the row; `render_inputs(tokens, renderers)` (`src/drydock/prompts.py`)
  emits sections in token order — the shared dispatch both commands use.
- `analyze.py` and `planning_session.py` `_assemble_prompt()` build a per-command token→renderer map
  and inject by `prompt.input_tokens`. Order is now config-driven, COMPASS.md first; reordering the
  row reorders the prompt. Tokens without a renderer are intentionally skipped: `COMPASS.md` is the
  `COMPASS_EXISTS` flag for analyze; `BLOCKERS.md` is the refuse-if-present gate for plan create and
  never reaches assembly.
- Per-command rendering (analyze's Rigging-catalog scaffolding, fenced-vs-flag COMPASS, the answered-
  spike filter, contract injection) stays in each module; only ordering/inclusion is config-driven.
- Tests: `test_prompts.py::TestInputTokens` (incl. `render_inputs` order/skip), `test_analyze.py`
  (`test_injection_order_is_driven_by_input_tokens`, `test_compass_token_injects_no_content_section`),
  `test_planning_session.py` (`test_assemble_prompt_orders_sections_by_input_tokens`,
  `test_assemble_prompt_reorders_when_tokens_reordered`).

`build`/`build score`/`refit` rows above are recorded for when those prompts are authored; their
assemblers adopt the same `render_inputs` pattern.


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

## Build Compass — cost semantics and 2026-07-02 visualization pass

**Story Points = assembled build-prompt tokens.** `story_points_for(bytes) = ceil(bytes / 4)`
(`src/drydock/build.py`). A step's SP is the token estimate of its *full* assembled build prompt:
`COMPASS.md` + every `implements`/`context` spec + the stack files. It is not the size of the
story text alone.

**"over 50K SP" is a per-step ceiling, not a group sum.** `PROMPT_WARN_TOKENS = 50_000`;
`over_warn = total_story_points > 50_000`. A single step whose assembled prompt exceeds
50,000 tokens (story points) is flagged. So a feature like Report Ingest shows "over 50K SP"
because one of its stories individually stacks more than 50K tokens of context — adding the
group's stories together is not how the flag is computed.

**Unit-bug fix (2026-07-03).** The ceiling was originally `PROMPT_WARN_KB = 50` compared as
`total_bytes > 50 * 1024` — a *byte* threshold (≈ 12,800 tokens) while every displayed cost is
Story Points = tokens. A 12,634-SP step therefore tripped a gate labelled "over 50K," which
reads as false (12,634 < 50,000), and the tiny real ceiling over-flagged work. The threshold is
now token-based end to end: config key `prompt_warn_tokens` / env `PROMPT_WARN_TOKENS`, default
50,000; `build.StepAssembly.warn_tokens`; labels rendered by `_fmt_sp` as "over 50K SP".

**Why the group figure is not the arithmetic sum of its stories.** Every step re-injects the
shared context it needs (COMPASS, sibling FEATURE files, ARCHITECTURE/DATABASE), so the same
bytes are counted in multiple stories; you cannot add two stories' SP to get a group cost.
`assemble_steps` already compacts stack files after their first appearance in build order
(`compact_stack=frozenset(files_seen)`), so the per-step costs are partially de-duplicated in
sequence. The group header is therefore labelled **"Combined Story Points"** (was "Story Points")
to stop implying addition. `group.total_story_points` remains `sum(step costs)`; a genuinely
de-duplicated single-build estimate (shared context injected once for the whole group) is a
`group_steps` change deferred pending Ed's decision.

**Visualization changes applied (`render_compass`, `render_build_plan`, CSS).**
- Per-story ▲▼ reorder removed. Order within a group is meaningless (the group builds as a unit),
  so a story keeps only its change-group `<select>`. Group ▲▼ (`move_feature`) is retained.
- Group rollup relabelled "Combined Story Points".
- `Missing` / `over NNK` render as bordered uppercase tags (`.cmp-miss`, `.cmp-warn`,
  `.cmp-warn-bar`) — larger and clearer; original colours kept.
- Completed items are loud: a solid green check badge (`.bp-check`) sits before verified steps and
  fully-verified groups, with a green left-rail on the step (`.bp-step-done`) and group
  (`.cmp-group-done`).

**Structure editing implemented (2026-07-03).** `manifest_edit.apply_edit(path, kind, ...)` plus the
`POST /api/compass/{item}/edit` endpoint mutate MANIFEST.md for three edits, each unit-tested and
topology-validated before write:
- **Rename** a feature or story — rewrites only the `## <type> <ordinal>: <name>` header label. The
  block `id:` is untouched, so every `parent:`/`depends:` reference and the work graph stay intact.
  Renaming a feature/story is a display-label change only; it does not touch `FEATURE-*.md` files or
  `implements`/`context` (those name blueprint files, not manifest block labels). The earlier
  deferral over-estimated the coupling.
- **New group** — the top-right "+ New group" button appends an empty feature; it appears in the
  compass and the regroup dropdown at once, and stories are moved into it with the existing regroup
  control. (No net-new story blocks are fabricated — a story needs `instructions`/`implements` to be
  buildable, which is a planning act, not a compass edit.)
- **Split group** — a multi-story feature becomes one feature per story; the original is reused
  (renamed) for its first story, each other story gets a new adjacent feature. New features are
  inserted immediately after the original so a depended-on story is not pushed behind its consumer.

Story per-order up/down stays removed; group up/down (`move_feature`) stays. Rename/split controls
render in `render_compass`; the endpoint accepts both `compass` and `build_plan` item types.

**Build Compass moved to the BUILD section.** The durable fix is in the console.yaml generator:
`standard_artifacts.render_console` now emits `build_compass` with `section: build, order: 1` (was
`section: plan, order: 4`).

## `drydock build` console streaming — 2026-07-02

The provider streams model output as many small `text_delta` events; `llm.py` calls
`on_text(delta)` once per event. `cli.py` passed `on_text=print`, and `print` appends a newline to
every delta, shredding words across lines (`test su` / `ite`, `I` / `'ll wait`). Fixed by
`cli._stream_stdout`, which writes each delta verbatim and flushes — preserving the model's own line
breaks and the explicit content-block boundary the runner injects (`llm.py` `content_block_start`).
Applied to `build`, `refit`, and `document`/Ship's Log streaming.

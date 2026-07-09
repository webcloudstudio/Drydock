# NOTES: QuarterDeck

| Field | Value |
|-------|-------|
| Version | 2026-07-03 V17 |
| Route | quarterdeck |
| Status | Working notes — not canonical specification |
| Description | QuarterDeck nav, section routing, icon model, page header, blocker artifact, tabbed-render type, the Artifact Feed Matrix, the buttonless questionnaire model, and the Build Compass ordering/acceptance model. |
| Pending spec | 1 approved item |
| Pending impl | 0 unimplemented sections |

## Goal

Build QuarterDeck the correct way: screens are shown based on where the project is in the
delivery workflow, not unconditionally. Build analyze to produce the correct set of artifacts.

## Decisions

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

## Unified Build Compass — plan_decision and build_plan retired — 2026-07-03

Three renderers over one `MANIFEST.md` had accreted: `plan_decision` (state marks + `buildable
now`, read-only), `compass` (cost + full editing, no state), and an orphan `build_plan` (cost +
state, partial editing, wired to no console). Each surfaced a different subset of the same work
graph; none was a superset. The Planning Session's only unique *function* — plan approval — was
already gone (`api_plan_decision` returned read-only), leaving it a dead twin of the compass.

**Decision: one renderer.** `render_compass` is now the single Build Compass: the live work graph
with (a) a rollup header (project, plan state, verified/review/pending/failed counts, total SP,
buildable-now summary), (b) a per-step lifecycle chip — `buildable now` (green, wins over plain
`pending`), `review`, `✓ done`, `failed` — (c) the failure reason inline under a failed step and in
the chip tooltip, (d) done tint + group verified counts + a loud group-complete check, and (e) the
existing editing controls plus click-to-rename on the group title. `render_plan_decision`,
`render_build_plan`, the `plan_decision`/`build_plan` TYPES, the `/api/plan/{id}/decision` endpoint,
the `PlanDecision` model, and the `bp-stats-sentinel` header path were deleted.
`standard_artifacts.render_console` no longer emits `planning_session`; the Build Compass carries a
help_text describing the unified view.

**Group rename discoverability.** The `✎` group-rename button existed (added 2026-07-03 am) but was
easy to miss; the group title is now itself click-to-rename (`.cmp-gname-edit`), resolving the "no
way to rename a group" report. The bare `✎` stays as a secondary affordance.

## Build-outcome trusts observed reality, not report formatting — 2026-07-03

A build step was marked `closed/failed` unless the agent's final text contained the exact
`RESULT:`/`FILES CHANGED:` contract at line starts. Streaming concatenates deltas, so a successful
step whose `RESULT: SUCCESS` landed mid-line (`…temp DB file.RESULT: SUCCESS`) was falsely failed —
and because a failed frontier blocks all dependents, two such false negatives dammed the entire
Marina graph while tests passed and files were written.

**Decision:** the filesystem delta (already snapshotted before/after each step) and programmatic
acceptance are the authority. `_build_outcome` now fails only on a non-zero provider exit, empty
output, an explicit `RESULT: FAILURE`, or a run that wrote no files. `RESULT` is matched anywhere in
the text, not only at a line start. A missing/unparsable report no longer fails a step.

**Failure reasons persist.** On `closed/failed`, `build_run` writes a single-line `finding:` to the
block: the concise cause plus a trailing detail (first failing acceptance check, or the provider
stderr tail for an execution failure). Stories clear a stale `finding:` on success; a spike's
`finding:` (its research output) is never cleared here. The Build Compass reads `finding:` for the
failed-step reason line and tooltip, so *why* a step failed is visible without opening evidence.

## Move validation — layer bands, not linear dependency — 2026-07-03
`2026-07-03` · `spec:approved` · `impl:implemented`

**Symptom (Marina2).** Moving the Infrastructure feature up was rejected with "would break build
topology: ac-marlib-1 before its dependency infra; voice-capture before its dependency s3-share."
The message named blocks that are not drawn on the compass, so the reason was invisible.

**Diagnosis.** `infra` (Terraform Layers) is in the *right* spot — it depends on catalog, report,
access-control, queue, and s3-share, so it correctly sits last among the features. The manifest's
only forward-reaching edges are two *acceptance* blocks: `ac-marlib-1` (under marlib, feature 2)
and `ac-ui-terraform-1` (under Screen — Terraform), both `depends: infra`. Every *story* already
sits after its dependencies. So the file is linearly valid except for acceptance blocks pointing
forward.

**Root cause.** The move validator enforces a strict "every block after all its deps" invariant.
But file order does not determine build correctness — the engine picks work at run time via
`next_buildable_step()` walking `depends:`. Manifest order is display/priority only. The validator
guards an invariant the engine never needs.

**Decision.**
- Ordering constrains **layer bands only**: Foundation < Data/Persistence < Features ≈ Screens.
  Features and Screens are one band — no "all features before any screen" rule. Movement is free
  within a band.
- `ac` blocks leave the ordered stream entirely — never positioned, never move-checked.
- The validator lists only the violations a move actually causes, not the full pre-existing set.
- **Auto-normalize** = topo-sort the manifest into a canonical valid order (a real capability, not
  a rescue for an invalid file). Offered when a manifest is out of band order.

**Open rendering gap.** The compass draws stories but not their `ac` blocks and prints no
dependency names, which is why the rejection cited items the Commander cannot see. Rendering `ac`
as each story's Definition of Done (below) closes this.

## Acceptance — deterministic Python tests, self-contained, out of ordering — 2026-07-03
`2026-07-03` · `spec:applied` · `impl:implemented`

**What an `ac` is.** A small, self-contained test that the just-built story works — a few port
pings, a guard grep, or a scripted checkout of a page. Deterministic, independently runnable.

- **Deterministic, never agentic.** An `ac`'s `check:` is a Python test invocation (e.g.
  `pytest tests/test_marlib.py`) run as a **post hook** after the story builds. No model in the
  verify loop — verification costs zero context and cannot self-report. This is the context-tight
  design: the LLM spends tokens building; the tests just run.
- **Two kinds.** *Smoke* — shallow "does it run" check (`service starts, answers /health`).
  *Assertion / guard* — a precise invariant (`no DynamoDB Scan`, `idempotent write uses SK not PK`).
  Distinguished by `kind:`.
- **Self-only-depends (hard guard).** An `ac` may depend on its own parent story only. The planner
  and compass must never emit or accept an `ac`→other-story edge. `ac-marlib-1: depends infra` is
  the defect that started this; drop it and Marina2 is cleanly ordered.
- **Programmatic vs User Acceptance.** Programmatic Acceptance (the Python `check:`) runs
  automatically and gates the build. User Acceptance is a Commander eyeball signal and does not
  block downstream build.

**Guard against out-of-order generation.** Whatever emits `ac` blocks (plan create) must enforce
self-only-depends at generation time, so an invalid edge can never enter the manifest.

## Story and its tests built in one step; blueprint owns "done" — 2026-07-03
`2026-07-03` · `spec:applied` · `impl:implemented`

**One act.** The story and its deterministic Python tests are written in the **same LLM build
step** — the model wears the TDD-master hat and writes the tests as it builds ("if you were a TDD
master, what tests would you write"). Not a separate phase; simultaneous, no extra context. All
best practices applied at once inside one generation.

**Ownership: the blueprint owns "done"; the build authors the test that proves it.** Each `ac` in
the blueprint states the intent in human terms (the contract for what must be true). The build step
writes the concrete Python test that satisfies that contract and may add finer tests for coverage,
but it **cannot remove or weaken a declared `ac`**. "Done" is defined before the build, human-owned
and stable, so the model cannot move the goalposts by inventing softer criteria. Blueprint = the
assertion; build = its executable realization plus extra.

## Build Compass display refinements — 2026-07-03
`2026-07-03` · `spec:na` · `impl:implemented`

Rendering-only changes to the unified Build Compass:

- **State labels.** Per-block chips read **"Built"** and **"Ready To Build"** (today's `✓ done` /
  `buildable now`), sitting at the top of the block like the removed planning session's labels.
- **Loud completion.** A large, distinct green check beside a completed block — bigger and more
  clearly differentiated than the current badge.
- **Story Points format.** A story/sub-block shows `Story Points = XXXX (overhead XXXX)`, where
  total is the block's full assembled cost and overhead is the shared/injected context (COMPASS +
  stack + sibling specs) that is not the block's own spec text; own = total − overhead.
- **Definition of Done.** A story's `ac` blocks render in a per-block **Definition Of Done**
  section (with readable names and their checks) rather than inline in the ordered list. This also
  makes dependency/acceptance items visible, closing the "invisible cited block" gap.
- **Confirmed sufficient, no change:** rename/move blocks, rename/build stories.

# NOTES: Plan Create

| Field | Value |
|-------|-------|
| Version | 2026-06-22 V6 |
| Route | plan |
| Status | Working notes — not canonical specification |
| Description | Implementation detail for drydock plan: decomposition pipeline, guardrails, ordering, the Compass, and compact substitution for stack files. V6 adds compact/applied registry design and cost estimator forward-pass. |
| Pending spec | 14 items (6 recommended, 8 approved) |
| Pending impl | 2 unimplemented sections |
Read `notes_analyze.md` §Shared Model before this file — the work graph, source-of-truth model,
roles, and node header format are authoritative there and not reproduced here.

## Goal

From the approved Blueprint + `BUILD_CONFIGURATION.md` + `ANALYSIS.md`, produce a validated,
ordered, atomically-decomposed work graph and the executable Manifest, with ROOT seeded green.

## Decisions

### Plan Create CLI / Inputs / Outputs
`2026-06-13` · `spec:recommended` · `impl:implemented`

*Built, with the precondition divergence noted in As-Built (ANALYSIS.md + not-Blocked rather than
ROOT-green).*

**CLI:** `drydock plan create <Target>`

**Precondition:** `drydock approve <tgt>` must have been called. Exits with error if ROOT node
does not exist or is not green.

**Inputs:**
- `<Target>/blueprint/` Typed Specification (Intent: guardrails, AC, spec files)
- `<Target>/blueprint/BUILD_CONFIGURATION.md` (Decisions: approved route, `MANUAL_BUILD_ORDER`, PO answers)
- `<Target>/ANALYSIS.md` (approved top-level shape and recommendation)
- `<Target>/blueprint/BUILD_PLAN_COMPASS.md` *(on re-run, when `MANUAL_BUILD_ORDER = true` and the PO
  has edited it)* — PO manual ordering; read-only input when present

**Outputs (derived):**
- `<Target>/blueprint/BUILD_PLAN_COMPASS.md` — the ordering file, **always written** and always the
  input `build` consumes (spec files `#`-delimited into batches at no-cross-stack boundaries).
  `MANUAL_BUILD_ORDER = false` (default): Drydock auto-computes the order and `build` uses it as-is.
  `MANUAL_BUILD_ORDER = true`: written in a default order for the PO to reorder by hand.
- `<Target>/MANIFEST.md` — the single executable build plan: work graph in header format
  (nodes + `depends-on` edges + state), ROOT seeded green.

`plan create` is the expensive, full agile decomposition, run only against an approved, de-risked
top-level shape. Writes derived artifacts only. `blueprint/` specs + `BUILD_CONFIGURATION.md`
remain the source of truth and must regenerate the graph.

### Decomposition Pipeline
`2026-06-13` · `spec:recommended` · `impl:implemented`

LLM expands the approved route into features → atomic stories → spikes → AC gates, assigning
`depends-on` edges throughout. Edges are inferred proposals; the approved Manifest is the persisted,
ratified home.

Each story maps to **one spec file** (`spec:` field). Hard constraint, not a guideline. This is
the lever that makes the no-cross-stack guardrail enforceable: typed spec filenames
(`FEATURE-*` vs `SCREEN-*`) prevent cross-stack mixing within one story.

### Scrum Guardrails
`2026-06-16` · `spec:recommended` · `impl:unimplemented`

- **Story too big → split.** A story exceeding the atomicity threshold must be split until atomic.
  Threshold configured in `.env`. Standard scrum guardrail.
- **Stories are atomic.** One spec file; one bounded unit of work.
- **Every story has ≥1 AC gate.** A story without a `depends-on` AC node is a defect; `plan create`
  must not emit it.

**As-built (2026-06-16, item A):** the ≥1-AC gate is now a **fatal** `_integrity_check` finding
(was a warning), and the ~100-story cap is enforced (`_STORY_CAP`, fatal). **Blocked / not built:**
the story-too-big split has no defined atomicity threshold — the `.env` value has no agreed default
(see Open Questions #1), so deterministic split enforcement is deferred. The prompt still instructs
the LLM to keep stories atomic.

### Integrity / Validation Check
`2026-06-13` · `spec:recommended` · `impl:implemented`

Runs in `_integrity_check` after the Manifest is parsed.

- Acyclic: no dependency cycles. **(fatal — built)**
- All `depends-on` values resolve to existing node IDs. **(fatal — built)**
- Every story's `implements` names a real emitted spec file. **(fatal — built)**
- Every story has ≥1 AC. **(fatal — built 2026-06-16; was a warning)**
- Reachable / no orphans. **(warning — built)**
- Story count ≤ ~100. **(fatal — built 2026-06-16, `_STORY_CAP`)**

Fatal findings raise `SpecificationError` (exit 1). Note: spec files are written before the gate
runs, so a fatal failure currently leaves authored specs but no console update — make atomic later.

### Order and Batch
`2026-06-16` · `spec:recommended` · `impl:unimplemented`

**Blocked / not built (item B, 2026-06-16):** the automatic batching algorithm depends on the
`MANUAL_BUILD_ORDER` flag, which lived in the now-retired `BUILD_CONFIGURATION.md`. With that file
gone, the manual/auto toggle has no persistence home, so the auto-batcher cannot be wired as
specified. Decide a new home for the flag (e.g. `PLAN_COMPASS.md` directive, `METADATA.md`
field, or always-auto with no toggle) before building this. Until then `plan create` keeps the
LLM-seeded Compass ordering.


**Hard guardrail — no cross-stack batches.** Never put different stacks / component types in one
batch. V1 evidence: batching a feature with a screen produced materially worse results than two
batches. Applies to both grouping strategies.

**Order authorship** is a PO Decision, set in console review, persisted in `BUILD_CONFIGURATION.md`
via `MANUAL_BUILD_ORDER`. *(Renamed 2026-06-16 from `USE_COMPASS`: the Compass is always written and
always consumed by `build`, so "use compass" was a misnomer — the flag toggles who authors the order,
not whether the Compass exists.)* The Compass is seeded either way; the flag only decides who orders it.

**`MANUAL_BUILD_ORDER = true` — manual:**
`plan create` seeds `BUILD_PLAN_COMPASS.md` in a default order; the PO reorders it by hand; `build`
consumes the edited file.

**`MANUAL_BUILD_ORDER = false` (default) — automatic:**
`plan create` seeds the Compass from a Python batching algorithm: topological sort by `depends-on`
order, then secondary sort by build-cost similarity — group nodes sharing stack / build rules to
amortize fixed per-run token cost (UI changes batch together; feature builds batch separately).
`build` consumes it as-is. Not yet implemented; fully specified here so it can be built.

Both strategies must respect the no-cross-stack guardrail.

### The Compass — Manual Build-Ordering Methodology
`2026-06-13` · `spec:recommended` · `impl:implemented`

*This is now the single definition of `BUILD_PLAN_COMPASS.md` (ordered spec-file list, `#`-delimited
into no-cross-stack batches, consumed by `build`). As-built it is **LLM-seeded** in the plan create
call rather than Python-seeded; the `MANUAL_BUILD_ORDER` gate and automatic alternative are not yet
built.*

One file, always seeded by `plan create`, then (when `MANUAL_BUILD_ORDER = true`) edited directly
by the PO.

- **Gate:** `MANUAL_BUILD_ORDER` in `BUILD_CONFIGURATION.md`. The Compass is always written and always
  consumed by `build`. When `true`, the PO hand-authors the order; when `false` (default), the order
  is auto-computed and used as-is.
- **File:** `<Target>/blueprint/BUILD_PLAN_COMPASS.md`.
- **Format:** ordered list of spec files (one per story via the story→spec mapping), `#`-delimited
  into build steps/batches. One file = one step + its related stack. Never cross-stack within a step.

  ```
  FEATURE-Authentication.md
  FEATURE-UserManagement.md
  #
  SCREEN-Login.md
  SCREEN-Dashboard.md
  #
  DATABASE.md
  ```

- **Lifecycle:**
  1. **Seed (`plan create`):** writes every spec file in default topological order with `#`
     delimiters at no-cross-stack boundaries.
  2. **Edit (PO):** PO reorders entries and adjusts `#` delimiters directly in the file. The edited
     Compass is the authoritative manual ordering (a Decision once edited).
  3. **Consume (`build`):** reads `BUILD_PLAN_COMPASS.md` as its ordering input instead of
     computing order.

### Build-Time Context (Downstream — Noted Here, Not Owned Here)
`2026-06-13` · `spec:na` · `impl:unimplemented`

These belong to `build`; the graph must support them:

- **No long-term memory.** Each build iteration assembles a complete, clean instruction set from
  scratch: full builder view of the stack + compacted user/contract view. No reliance on what the
  model remembers.
- **Verification.** After each build, tool calls check success. AC expressed as executable Python
  runnables where possible; some non-executable AC is unavoidable.
- **Drift oracle.** Graph node state tracks what is built and verified; green propagates along
  `depends-on` edges. Propagation model not yet fully elaborated.

## Feedback Loop & Injection Stack (2026-06-16)

Companion to notes_analyze.md §Feedback Loop & Injection Stack. Applies the standing-directive
methodology to `plan create` and finalizes its prompt injection stack.

### PLAN_COMPASS.md (standing directive)
`2026-06-16` · `spec:approved` · `impl:implemented`

`plan create` exports a persistent `<target>/PLAN_COMPASS.md`, re-injected into the
plan-create prompt on every run. Same contract as ANALYZE_COMPASS.md: created if absent with
default body `Enter Direction for the Manifest Run`, never overwritten by the command, top-of-file
note that it is used on every `plan create` run, edited/submitted via QuarterDeck, injected near
the top (after the job block). See notes_analyze.md §Standing-Directive Feedback File.

### BUILD_CONFIGURATION.md retired (plan create)
`2026-06-16` · `spec:approved` · `impl:implemented`

Drop `BUILD_CONFIGURATION.md` injection from `planning_session.py` and scrub `prompts/plan_create.md`.
**Supersedes** the BUILD_CONFIGURATION.md inputs in §Plan Create CLI / Inputs / Outputs and the
`MANUAL_BUILD_ORDER` persistence in §Order and Batch (if that feature is later built, its flag
needs a new home; out of scope here). PO direction now comes from PLAN_COMPASS.md and answered
spikes.

### Single-directional regenerate — no state merge
`2026-06-16` · `spec:approved` · `impl:implemented`

`plan create` is a one-directional clean regenerate. Do **not** inject the existing `MANIFEST.md`,
and **remove** the module-side `_merge_states`. Every run re-authors the plan fresh; prior block
states are **not** preserved. Rationale (Ed): a new plan is a new plan; LLMs are non-deterministic,
so attempting state/id consistency across re-plans is not worth it. **Supersedes** §As-Built
"state-merge on re-run" and any AC/guardrail language implying preserved states across re-plans.

### Final plan create injection stack
`2026-06-16` · `spec:approved` · `impl:implemented`

1. `prompts/plan_create.md` — prompt body
2. job block (inline) — `TARGET`, `BLUEPRINT_PATH`, `DATE`, `SYSTEM_SHAPE`, `ANALYSIS_QUALITY`
3. `<target>/PLAN_COMPASS.md` — standing directive, if present
4. `<target>/ANALYSIS.md`
5. `<target>/SEA_TRIALS.md`, `SOUNDINGS.md`, `COMPASS.md` (if present)
6. answered `QuarterDeck/questionnaires/spike-*.json`
7. contract files — `MANIFEST_CONTRACT.md`, `BLUEPRINTS_CONTRACT.md`
8. `<target>/blueprint/sources/*.md` — imported sources

Removed vs current: `BUILD_CONFIGURATION.md` and the existing `MANIFEST.md` (prior plan).

---

## Acceptance Criteria

1. Does not run without ROOT green (approval precondition enforced; exits with error otherwise).
2. Emits a graph that is atomic-story (one spec per story), fully AC-gated, acyclic, reachable,
   ≤ ~100 stories.
3. Story-too-big guardrail applied; oversized stories split before emission.
4. Integrity check passes before `MANIFEST.md` is written; failure surfaces actionable findings.
5. Always writes `BUILD_PLAN_COMPASS.md` (auto-ordered, or default-ordered for PO edit when
   `MANUAL_BUILD_ORDER = true`) + `MANIFEST.md` with ROOT seeded green.
6. Deterministic given the same Intent + Decisions.
7. All `depends-on` edges use the single direction (dependent node declares); no `gates` syntax.
8. Multiple `parent` values allowed and parsed correctly.

## Guardrails

- **Precondition: ROOT green.** Must not run unless `drydock approve <tgt>` has been called.
- **No cross-stack batches.** Hard rule; applies to both manual and automatic ordering.
- **One spec per story.** `spec:` field required; blank is a defect.
- **Every story has ≥1 AC gate.** A story without a `depends-on` AC node must not be emitted.
- **Story-too-big → split.** Must split before `MANIFEST.md` is written.
- **~100-story cap.** Over threshold: refuse to emit.
- **Integrity check gates emission.** `MANIFEST.md` not written until the graph passes fully.
- **Derived artifacts only.** Never writes to `blueprint/` Typed Specification files or
  `BUILD_CONFIGURATION.md`.
- **`depends-on` is the only edge syntax.** No `gates`, no other direction. Parser enforces this.

### Compact substitution rule — stack files
`2026-06-22` · `spec:approved` · `impl:implemented`

The first use of a stack file across the full build uses the full file. Every subsequent use
substitutes the compact derivative (`*_compact.md`) if it exists. The rule is build-order-global —
not per-story, not phase-based.

The manifest always stores canonical names (`common.md`, `fastapi.md`). Compact substitution is
derived, never authored.

### Applied registry in the manifest
`2026-06-22` · `spec:approved` · `impl:implemented`

`build` writes one field to the manifest: a per-file applied registry. Each entry records the git
commit ID at the time the file was applied to a build step.

Substitution logic at build time:
- No applied record, or recorded commit differs from HEAD → use **full** file; record commit on
  successful build completion
- Recorded commit matches HEAD → use **compact**
- Uncommitted working tree → **build blocked** (no clean commit ID available)

The manifest is not human-editable (managed via QuarterDeck). No human override of applied flag.

### Uncommitted files guard
`2026-06-22` · `spec:approved` · `impl:implemented`

A build step cannot execute if the working tree contains uncommitted changes. The applied registry
records commit IDs; a dirty tree yields no reliable ID to record or compare.

### Cost estimator forward pass
`2026-06-22` · `spec:approved` · `impl:implemented`

The cost estimator (QuarterDeck compass / `assemble_steps`) cannot read the applied registry — it
is empty before any story has run. It simulates the forward pass independently:

1. Walk stories in manifest order.
2. Maintain a local "seen" set for this calculation pass.
3. First occurrence of a stack file → cost using the full file.
4. Subsequent occurrence → cost using compact sibling (if it exists); fall through to full if not.

The cost estimator groups stories and emits a derived view of the manifest showing compact file
names in downstream stories (e.g., `fastapi_compact.md` instead of `fastapi.md`). The user sees
the substitution and the resulting token cost before anything runs. This makes the token cost
honest and the substitution auditable before build executes.

The build runner performs the same substitution at execution time and writes results to the applied
registry — two passes, same substitution decisions.

## Open Questions

1. **Compact scope** — does the applied registry and compact substitution rule cover only `stack:`
   files, or also `rules:` and `context:` files?
2. **Story-too-big threshold** — atomicity heuristic (token/context budget? AC count? touched-files
   estimate?). Configured in `.env`; specific default value TBD.
2. **Integrity failure UX** — block `MANIFEST.md` write only, surface as QuarterDeck questions, or
   both? (Lean: block + surface findings; PO decides whether to re-analyze or fix the spec.)
3. **Drift propagation model** — how green/stale propagates when an upstream node changes post-build.
4. **Compass setup verb** — command name TBD; no command needed until implemented.

## Not in scope yet

Editing the canonical specification. Full `build`-time execution design. (The command itself is
now built — see As-Built.) Remaining work: story-too-big split, ~100-story cap, hard AC gate,
deterministic no-cross-stack enforcement, and the `MANUAL_BUILD_ORDER = false` automatic batching
algorithm.

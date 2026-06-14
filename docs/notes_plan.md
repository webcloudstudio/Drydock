# NOTES: Plan Create

| Field | Value |
|-------|-------|
| Version | 2026-06-14 V2 |
| Route | plan create |
| Status | Working notes — not canonical specification |
| Description | Implementation detail for drydock plan create: decomposition pipeline, guardrails, ordering, and the Compass. Shared model lives in notes_analyze.md. |
| Pending spec | 6 recommended items |
| Pending impl | 6 unimplemented sections |

Read `notes_analyze.md` §Shared Model before this file — the work graph, source-of-truth model,
roles, and node header format are authoritative there and not reproduced here.

## Goal

From the approved Blueprint + `BUILD_CONFIGURATION.md` + `ANALYSIS.md`, produce a validated,
ordered, atomically-decomposed work graph and the executable Manifest, with ROOT seeded green.

## Decisions

### Plan Create CLI / Inputs / Outputs
`2026-06-13` · `spec:recommended` · `impl:unimplemented`

**CLI:** `drydock plan create <Target>`

**Precondition:** `drydock approve <tgt>` must have been called. Exits with error if ROOT node
does not exist or is not green.

**Inputs:**
- `<Target>/blueprint/` Typed Specification (Intent: guardrails, AC, spec files)
- `<Target>/blueprint/BUILD_CONFIGURATION.md` (Decisions: approved route, `USE_COMPASS`, PO answers)
- `<Target>/ANALYSIS.md` (approved top-level shape and recommendation)
- `<Target>/blueprint/BUILD_PLAN_COMPASS.md` *(if `USE_COMPASS` = true and file exists)* — PO manual
  ordering; read-only input when present

**Outputs (derived):**
- `<Target>/blueprint/BUILD_PLAN_COMPASS.md` — seeded ordering file (spec files in default order,
  `#`-delimited into batches at no-cross-stack boundaries). Written on first run when `USE_COMPASS`
  = true; the PO then edits it directly.
- `<Target>/MANIFEST.md` — the single executable build plan: work graph in header format
  (nodes + `depends-on` edges + state), ROOT seeded green.

`plan create` is the expensive, full agile decomposition, run only against an approved, de-risked
top-level shape. Writes derived artifacts only. `blueprint/` specs + `BUILD_CONFIGURATION.md`
remain the source of truth and must regenerate the graph.

### Decomposition Pipeline
`2026-06-13` · `spec:recommended` · `impl:unimplemented`

LLM expands the approved route into features → atomic stories → spikes → AC gates, assigning
`depends-on` edges throughout. Edges are inferred proposals; the approved Manifest is the persisted,
ratified home.

Each story maps to **one spec file** (`spec:` field). Hard constraint, not a guideline. This is
the lever that makes the no-cross-stack guardrail enforceable: typed spec filenames
(`FEATURE-*` vs `SCREEN-*`) prevent cross-stack mixing within one story.

### Scrum Guardrails
`2026-06-13` · `spec:recommended` · `impl:unimplemented`

- **Story too big → split.** A story exceeding the atomicity threshold must be split until atomic.
  Threshold configured in `.env`. Standard scrum guardrail.
- **Stories are atomic.** One spec file; one bounded unit of work.
- **Every story has ≥1 AC gate.** A story without a `depends-on` AC node is a defect; `plan create`
  must not emit it.

### Integrity / Validation Check
`2026-06-13` · `spec:recommended` · `impl:unimplemented`

Runs on the fully assembled graph before writing `MANIFEST.md`.

- Acyclic: no dependency cycles.
- Reachable: no orphan / unreachable nodes.
- Every story has ≥1 AC gate in its depended-on set.
- All `depends-on` values resolve to existing node IDs.
- Story count ≤ ~100 (`.env` threshold).

Failure: block `MANIFEST.md` write and surface findings. (UX detail TBD — see open items.)

### Order and Batch
`2026-06-13` · `spec:recommended` · `impl:unimplemented`

**Hard guardrail — no cross-stack batches.** Never put different stacks / component types in one
batch. V1 evidence: batching a feature with a screen produced materially worse results than two
batches. Applies to both grouping strategies.

**Grouping strategy** is a PO Decision, set in console review, persisted in `BUILD_CONFIGURATION.md`
via `USE_COMPASS`:

**`USE_COMPASS = true` — manual (the Compass):**
`plan create` seeds `BUILD_PLAN_COMPASS.md`; the PO edits it; `build` consumes it as the ordering
input.

**`USE_COMPASS = false` — automatic:**
Python batching algorithm: topological sort by `depends-on` order, then secondary sort by
build-cost similarity — group nodes sharing stack / build rules to amortize fixed per-run token
cost (UI changes batch together; feature builds batch separately). Not yet implemented; fully
specified here so it can be built.

Both strategies must respect the no-cross-stack guardrail.

### The Compass — Manual Build-Ordering Methodology
`2026-06-13` · `spec:recommended` · `impl:unimplemented`

One file, seeded by `plan create`, then edited directly by the PO.

- **Gate:** `USE_COMPASS` in `BUILD_CONFIGURATION.md`. When false: no Compass, no setup step,
  ordering is automatic.
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

## Acceptance Criteria

1. Does not run without ROOT green (approval precondition enforced; exits with error otherwise).
2. Emits a graph that is atomic-story (one spec per story), fully AC-gated, acyclic, reachable,
   ≤ ~100 stories.
3. Story-too-big guardrail applied; oversized stories split before emission.
4. Integrity check passes before `MANIFEST.md` is written; failure surfaces actionable findings.
5. Writes `BUILD_PLAN_COMPASS.md` (if `USE_COMPASS`) + `MANIFEST.md` with ROOT seeded green.
6. Deterministic given the same Intent + Decisions.
7. All `depends-on` edges use the single direction (dependent node declares); no `gates` syntax.
8. Multiple `parent` values allowed and parsed correctly.

## Guardrails

- **Precondition: ROOT green.** Must not run unless `drydock approve <tgt>` has been called.
- **No cross-stack batches.** Hard rule; applies to both `USE_COMPASS` and automatic ordering.
- **One spec per story.** `spec:` field required; blank is a defect.
- **Every story has ≥1 AC gate.** A story without a `depends-on` AC node must not be emitted.
- **Story-too-big → split.** Must split before `MANIFEST.md` is written.
- **~100-story cap.** Over threshold: refuse to emit.
- **Integrity check gates emission.** `MANIFEST.md` not written until the graph passes fully.
- **Derived artifacts only.** Never writes to `blueprint/` Typed Specification files or
  `BUILD_CONFIGURATION.md`.
- **`depends-on` is the only edge syntax.** No `gates`, no other direction. Parser enforces this.

## Open Questions

1. **Story-too-big threshold** — atomicity heuristic (token/context budget? AC count? touched-files
   estimate?). Configured in `.env`; specific default value TBD.
2. **Integrity failure UX** — block `MANIFEST.md` write only, surface as QuarterDeck questions, or
   both? (Lean: block + surface findings; PO decides whether to re-analyze or fix the spec.)
3. **Drift propagation model** — how green/stale propagates when an upstream node changes post-build.
4. **Compass setup verb** — command name TBD; no command needed until implemented.

## Not in scope yet

Building the command. Editing the canonical specification. Full `build`-time execution design.

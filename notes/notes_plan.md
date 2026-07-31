# NOTES: Plan Create

| Field | Value |
|-------|-------|
| Version | 2026-07-31 V7 |
| Route | plan |
| Status | Working notes — not canonical specification |
| Description | Plan team authority, source-to-Blueprint translation, decomposition, Commander-decision preservation, ordering, and downstream build handoff. |
| Pending spec | 16 approved items |
| Pending impl | 10 unimplemented sections |
Read `notes_analyze.md` §Shared Model before this file — the work graph, source-of-truth model,
roles, and node header format are authoritative there and not reproduced here.

## Goal

From the Commander-reviewed epic, all immutable source material, and the Team Lead's complete
Analyze handoff, author the governed Blueprint and a validated, ordered, atomically decomposed
Manifest that the Shipyard Crew can build without synchronous access to the Commander.

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

The Analyze story list is the Team Lead's proposed map, not an immutable decomposition. The Plan
team reviews it after Commander questionnaires are answered and may retain, split, rename,
replace, or reorder its candidate stories.

### Scrum Guardrails
`2026-06-16` · `spec:recommended` · `impl:unimplemented`

- **Story too big → split.** A story exceeding the atomicity threshold must be split until atomic.
  Threshold configured in `.env`. Standard scrum guardrail.
- **Stories are atomic.** One spec file; one bounded unit of work.
- **Independent actions remain independent stories.** A screen and its route are separate stories;
  a story does not combine actions merely because they participate in one workflow.
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
8. `<target>/blueprint/sources/**` — all readable imported source material

Removed vs current: `BUILD_CONFIGURATION.md` and the existing `MANIFEST.md` (prior plan).

### Analyze Team Lead and Product Owner handoff
`2026-07-31` · `spec:approved` · `impl:unimplemented`

Analyze is the Team Lead conducting the Product Owner feedback session. It evaluates completeness
of the epic and surfaces Commander expectations as product-level assertions, such as "Commander
wants a web server." Its acceptance criterion is that the Commander is satisfied that intent,
goals, constraints, contradictions, and required decisions have been captured.

Analyze is deliberately "secretly waterfall": it works iteratively with the Commander, but its
handoff must be complete and capable of becoming a buildable Plan. It authors `ANALYSIS.md` and
`COMPASS.md`; required questionnaires are answered before Plan. The story list is an expert
proposal for Plan to review, not a binding work breakdown.

### Cross-functional Plan team authority
`2026-07-31` · `spec:approved` · `impl:unimplemented`

Plan is a room containing the Scrum Master, test-driven development, UI, data, architecture, and
delivery disciplines. The team reviews the whole epic, determines atomic stories, authors governed
specifications, computes dependencies, and orders the work in `MANIFEST.md`.

Plan does not return to the Commander for synchronous clarification. It has full authority to
replace Plan-owned top-level Blueprint files and the Manifest as needed to implement Commander
intent. It may revise Analyze's proposed story list. A source Markdown file already organized as
one candidate story is strong evidence for retaining that file and boundary, but it is not
authority: Plan splits non-atomic files according to normal Agile rules and does not combine
independent actions.

### Immutable sources and Blueprint projection
`2026-07-31` · `spec:approved` · `impl:unimplemented`

`blueprint/sources/**` is immutable, unconstrained Commander input. Source filenames, nesting,
headings, formatting, and completeness are never validated as governed Blueprint syntax. Analyze
and Plan receive all readable source content; Analyze guides interpretation and decomposition but
does not restrict Plan's visibility to cited files.

Markdown sources are interpreted into governed top-level Blueprint specifications. Non-Markdown
sources are copied to the corresponding path one level above `sources/`, byte for byte. The copy
preserves every existing byte, including line-ending convention and final-newline state. Imported
Markdown is never copied over an authored governed specification.

### Persistent Commander input across replans
`2026-07-31` · `spec:approved` · `impl:unimplemented`

Commander input is preserved before Plan overwrites any Plan-owned artifact. It includes every
stage Compass, persistent questionnaire answers, and Commander edits or answers in Blueprint
`## Questions` sections. A deterministic scanner appends newly observed Commander information to
persistent replan memory. Replan consumes that accumulated memory so regenerated files cannot erase
human decisions or corrections.

### Plan decisions, severity, and implied approval
`2026-07-31` · `spec:approved` · `impl:unimplemented`

Plan normally resolves contradictions and incomplete detail by making its best decision, encoding
that decision consistently, and exposing it in the relevant Blueprint's `## Questions` section.
A useful record states the available options, the option selected and why, and asks whether the
Commander wants to redirect and replan. This enables override; it is not a request for permission.

Severity is plain English: `Low`, `Material`, or `Blocking`. Blocking decisions are extremely rare
and mean the team cannot responsibly endorse even its best available interpretation. Low and
Material records do not gate execution. Approval is implied by running the next command; there is
no mandatory review ceremony. The next stage fails only when a material blocker actually prevents
that stage.

### Shipyard Crew build handoff and decision records
`2026-07-31` · `spec:approved` · `impl:unimplemented`

Build is performed by the outsourced **Shipyard Crew**, which has no synchronous feedback channel
to the Commander. It cannot generate questionnaires or create a new question workflow. When a
story requires an interpretation, the builder proceeds with the best bounded choice and may append
a decision record to that story's owning Blueprint `## Questions` section. The record states what
was done and enables later override; it does not ask for approval or block the completed build.

A decision appears only in the specification that owns it. The same conflict is not duplicated
across related stories. Commander edits to these records become persistent input to a later replan.

### Crew presentation and terminal compatibility
`2026-07-31` · `spec:approved` · `impl:unimplemented`

Analyze presents the handoff using a stable crew roster: Commander, Team Lead, Planning Crew, and
Shipyard Crew. Descriptions may adapt to the project while role names and authority remain stable.
The presentation is concise, nautical, cute, and fun without obscuring status or responsibility.

CLI output is ASCII-safe on MSYS and other terminals whose Unicode rendering is not controlled.
Decorative emoji may appear in QuarterDeck HTML, where Drydock controls presentation, but terminal
meaning never depends on emoji or other ambiguous-width Unicode glyphs.

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
9. Analyze hands Plan a Commander-reviewed, expectation-complete epic and a proposed story map.
10. Plan receives all readable immutable sources and may revise the proposed decomposition.
11. Markdown becomes governed specifications; non-Markdown assets are projected byte-for-byte.
12. Commander questionnaires and Blueprint question edits survive every replan.
13. Plan and Build decisions remain story-local, visible, non-duplicated, and non-blocking unless
    explicitly classified `Blocking`.
14. Running the next command implies approval when no blocker prevents that stage.

## Guardrails

- **Precondition: ROOT green.** Must not run unless `drydock approve <tgt>` has been called.
- **No cross-stack batches.** Hard rule; applies to both manual and automatic ordering.
- **One spec per story.** `spec:` field required; blank is a defect.
- **Every story has ≥1 AC gate.** A story without a `depends-on` AC node must not be emitted.
- **Story-too-big → split.** Must split before `MANIFEST.md` is written.
- **~100-story cap.** Over threshold: refuse to emit.
- **Integrity check gates emission.** `MANIFEST.md` not written until the graph passes fully.
- **Immutable source provenance.** Never modifies `blueprint/sources/**`.
- **Plan owns governed outputs.** Plan may replace top-level Blueprint specifications and
  `MANIFEST.md` only after persistent Commander input has been harvested.
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

### Applied Blueprint Specification provenance
`2026-06-26` · `spec:approved` · `impl:implemented`

`build` writes `applied_specs` in the Manifest preamble for Blueprint files applied by successful
stories and spikes. This registry is separate from the older compact-substitution `applied:`
field. It covers only Blueprint-resolved `implements:` files and Blueprint-resolved `context:`
files.

Each record stores path, SHA-256 content hash, latest file-level git commit when available,
applying step id, and application timestamp. SHA-256 is authoritative; commit is diagnostic.

Before executing any agent, `build` compares every previously applied spec record against current
Blueprint content. Changed or missing files block build with a stale-spec report. New unapplied
Blueprint files do not block build.

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

Editing the canonical specification. Detailed Shipyard Crew execution mechanics beyond the
story-local decision-record contract. Remaining implementation work includes the approved
source-to-Blueprint handoff, persistent Commander-input harvesting, question severity, ASCII-safe
crew presentation, story-too-big splitting, and deterministic no-cross-stack enforcement.

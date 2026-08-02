# NOTES: Plan Create

| Field | Value |
|-------|-------|
| Version | 2026-08-02 V18 |
| Route | plan |
| Status | Working notes — not canonical specification |
| Description | Plan team authority, source-to-Blueprint translation, decomposition, Commander-decision preservation, ordering, and downstream build handoff. |
| Pending spec | 4 approved items |
| Pending impl | 2 unimplemented sections |
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
- `<Target>/blueprint/BUILD_CONFIGURATION.md` (Decisions: approved route, PO answers)
- `<Target>/ANALYSIS.md` (approved top-level shape and recommendation)

**Outputs (derived):**
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
`2026-07-31` · `spec:recommended` · `impl:implemented`

- **Story too big → split.** A story exceeding the atomicity threshold must be split until atomic.
  Threshold configured in `.env`. Standard scrum guardrail.
- **Stories are atomic.** One spec file; one bounded unit of work.
- **Independent actions remain independent stories.** A screen and its route are separate stories;
  a story does not combine actions merely because they participate in one workflow.
- **Every story has ≥1 AC gate.** A story without a `depends-on` AC node is a defect; `plan create`
  must not emit it.

**As-built:** semantic splitting is owned by the frontier Planning Crew; deterministic validation
enforces exactly one governed specification per story, exactly one owning story per specification,
required acceptance, and valid dependency structure. The Plan prompt requires
independent actions and screen/provider work to remain separate specifications.

### Integrity / Validation Check
`2026-06-13` · `spec:recommended` · `impl:implemented`

Runs in `_integrity_check` after the Manifest is parsed.

- Acyclic: no dependency cycles. **(fatal — built)**
- All `depends-on` values resolve to existing node IDs. **(fatal — built)**
- Every story's `implements` names a real emitted spec file. **(fatal — built)**
- Every story has ≥1 AC. **(fatal — built 2026-06-16; was a warning)**
- Reachable / no orphans. **(warning — built)**
- ~~Story count ≤ ~100~~ — **retired**; see §Story count is not capped.

Fatal findings raise `SpecificationError` (exit 1). Note: spec files are written before the gate
runs, so a fatal failure currently leaves authored specs but no console update — make atomic later.

## Feedback Loop & Injection Stack (2026-06-16)

Companion to notes_analyze.md §Feedback Loop & Injection Stack. Applies the standing-directive
methodology to `plan create` and finalizes its prompt injection stack.

## Plan Restructure (2026-08-01)

Session goal: build `plan` the correct way. The driver was three consecutive Marina plan failures.
The diagnostic is recorded below; the restructure is the design response.

### Significant decisions surface as DECISIONS.json
`2026-08-01` · `spec:approved` · `impl:implemented`

**Built 2026-08-01.** `src/drydock/decisions.py` (parse Plan's `=== DECISIONS.json ===` block,
validate blueprint attachment against the run's emitted specs plus `ARCHITECTURE.md`, load/write
the persisted file, `reconcile_decisions` retains only Commander-directed prior items). Wired into
`planning_session.create_plan`: `DECISIONS.json` added to `_RESERVED_BLOCKS`, parsed and merged
after Blueprint specs are authored, written to `<Target>/DECISIONS.json`. `plan_create.md` V31
carries the exact prompt language (new `## Significant Design Decisions` section) and no longer
directs Plan to record decisions in a Blueprint `## Questions` section — Precedence input #2 now
reads Commander-directed `DECISIONS.json` items instead of Blueprint `## Questions` answers.
`console.yaml` gains a `decisions`-type item (order 3, implement section); `QuarterDeck/app.py`
gains the `decisions` renderer (severity-ranked cards, radio buttons for `choice`, textarea for
`text`, archive toggle, severity filter bar) and `POST /api/decisions/direct` to persist
`commander_direction` / `override_text` / `archived`. Tests: `tests/test_decisions.py` (module),
`tests/test_planning_session.py` (three `create_plan` integration tests covering disclosure,
empty-disclosure, and Commander-directed retention across a replan).

**Deliberately not touched (residual):** the structural `## Questions` section requirement in
`BLUEPRINTS_CONTRACT.md` / typed spec format is unchanged — `build_decisions.py` (Shipyard Crew
decision reporting, AC13's other half) still appends there via `questions.py`, and retiring that
machinery repo-wide was out of this item's scope. `DECISIONS.json` is Plan's disclosure surface
only; Build's decisions are a separate, unstarted migration. §Significant decisions surface as
DECISIONS.json's DOC item (spec:approved) is still open — reconciling this into
`Drydock_Specification.md` was not selected.

Replaces the prior "questions" design in full. The `## Questions` Markdown section embedded in
Blueprint files, and the `questions.py` `QUESTIONS_HEADING` / `QUESTIONS:` parsing contract, are
**retired for Plan — never emitted again.** `questions.py`'s vocabulary
(`QUESTION_ORIGINS = {plan, build, analyze-questionnaire}`, `QUESTION_SEVERITIES = {low, material,
blocking}`) carries forward as JSON enum values only; its Markdown parsing machinery does not.

**Scope widened.** Not just error-threshold overflows — every significant design decision Plan
makes where the Blueprint, guardrails, or stack declaration are silent (e.g. Commander selected
Flask/Django/FastAPI all three in the stack and Plan must pick one for a given service) is
recorded. Plan never hard-blocks on an unresolved choice regardless of severity; it decides,
proceeds as if chosen, and discloses.

**New artifact: `DECISIONS.json`**, Target-root, same tier as `MANIFEST.md` / `ANALYSIS.md`. Single
format, JSON only. Written by the Plan module from LLM-emitted JSON (per the LLM-Assisted Command
Pattern — the model emits delimited text, the module parses and writes the file). Read back by
QuarterDeck via a new `decisions`-type `console.yaml` item, following the same
generic-index-plus-purpose-built-renderer pattern already used for `compass` and `kanban`: severity
icon = worst severity present, archive/hide toggle, top filters, choice items rendered as radio
buttons for instant Commander select. QuarterDeck's core stays domain-blind — all Decisions
intelligence lives in that one renderer, per its existing "index only, renderer per type" design.

**Item schema** (shared with Analyze's questionnaire via `origin`; physical location of the shared
fragment TBD — open item):
```
id, type (choice|text), severity (low|material|blocking), origin (plan|build|analyze-questionnaire),
blueprint (owning Blueprint file: the service or screen it governs; else ARCHITECTURE.md), story,
status (open|recommended|answered), archived,
title, description, options ([{value,label}], choice only), system_choice,
commander_direction (choice, Commander-set), override_text (text answer, or annotation on choice)
```
`commander_direction` / `override_text` are QuarterDeck/Commander-owned; Plan never emits them.

**Persistence and re-decision contract.** `DECISIONS.json` is the sole persistence target — Plan
never writes a decision back into a Blueprint file; `blueprint` is attribution only. On each run,
Plan adds `DECISIONS.json` (if present) to its inputs and keeps **only human-authored items**
(`commander_direction` or `override_text` set) as fixed constraints, not reconsidered. Every other
item — LLM-only `system_choice`, never Commander-touched — is **discarded outright**, not carried
forward stale; Plan re-decides it fresh if the underlying gap still exists. Plan emits the full set
(retained human items + freshly decided ones) each run; the module writes it wholesale.

**Blueprint attachment rule.** Local to a service or screen/UI → that file. Everything else →
`ARCHITECTURE.md`. Two buckets only.

**Prompt language** (Plan prompt; uses the codebase's real, existing delimiter convention, verified
in `prompts/plan_create.md`):

> Significant Design Decisions not specified by the Blueprint. Build must never stall on a choice
> Plan should have already made, and the Commander must be able to review and redirect any such
> choice before Build acts on it. Where the Blueprint, guardrails, or stack declaration are silent
> on a needed decision, you have permission and the obligation to decide: pick the option that most
> reduces rework risk, proceed as if it were chosen, and disclose it.
>
> Ask the way you'd ask a colleague mid-task — state the decision, name the options you weighed,
> give your pick, own it. Not an exhaustive survey.
>
> Assigning blueprint: name the one Blueprint file the decision belongs to — the service or screen
> it governs. If it belongs to neither, name ARCHITECTURE.md.
>
> Emit every decision as DECISIONS.json, using the standard file delimiters. Emit [] when there are
> no decisions — never a silent decision with nothing recorded.
>
> ```
> === DECISIONS.json ===
> [
>   {
>     "id":            "string, e.g. Q-001",
>     "type":          "choice | text",
>     "severity":      "low | material | blocking",
>     "blueprint":     "string — the Blueprint filename this decision belongs to",
>     "story":         "string | null",
>     "title":         "string",
>     "description":   "string",
>     "options":       [ { "value": "string", "label": "string" } ],
>     "system_choice": "string"
>   }
> ]
> === END DECISIONS.json ===
> ```
>
> type: "text" decisions set options to [] and put the resolution in system_choice. Do not include
> commander_direction, override_text, status, or archived — those are Commander/QuarterDeck-owned
> and never emitted by Plan.

**Open items:**
- Stable `id` guarantee for undirected items across re-decision runs, so QuarterDeck references
  don't rot.
- Physical location of the shared `Item` schema fragment, so Plan's prompt and Analyze's
  questionnaire prompt don't duplicate/diverge it.

### Continuation — resume, never discard
`2026-08-02` · `spec:approved` · `impl:implemented`

**Built 2026-08-02.** `src/drydock/plan_score.py` (`PlanScore`, `score_plan`, `artifact_defect`;
deterministic, no I/O). `plan_topology.merge_declaration` enforces the accepted-story-frozen
invariant. `planning_session._continue_short_plan` runs the loop, with
`_unpaired_artifact_names`, `_render_ledger`, and `_continuation_assembly` (appends to the
unchanged `PromptAssembly`, mirroring `_conflict_challenge_assembly`). `prompts/plan_continue.md`
V1. `plan_shape.has_typed_heading` made public. `create_plan(continue_attempts=3)`, exposed as
`drydock plan --continue-attempts`. Tests: `tests/test_plan_score.py` (14) and 10 continuation
integration tests in `tests/test_planning_session.py`, including a byte-identical-prefix assertion.

**Divergence from the approved plan:** the typed-heading check does **not** gate acceptance
(`require_typed_heading=False` by default). It is repairable by `conform_specs` and advisory in
`PLAN_SHAPE_ADVISORY`, and it is a poor truncation detector — the heading is a specification's
first line, so a cut tail never removes it. Gating on it would spend a continuation pass
re-authoring complete work. Truncation is detected by delimiter evidence instead.

**Also as-built:** the stall record's `detail` is whitespace-normalized by `write_error_record`, so
the rendered score arrives as one line rather than the three-line block. The numbers survive.

**Design settled 2026-08-02.** The failure mode is **output-token exhaustion** (provider default
64K output, 128K max, inclusive of reasoning) — not process death. Everything stays in memory
within one `plan create` invocation and the all-or-nothing write contract is unchanged.

Two of the three mechanisms already exist: the ruler (`prompts/plan_create.md:624` makes leading
`TOPOLOGY.md` a hard requirement; `PLAN_SHAPE_ADVISORY` states leading placement exists precisely
to make a short run resumable) and truncation detection (`_artifact_delimiters_are_complete`).
Only the score and the loop are missing.

Refinements over the original 8-step plan below:

- **The score is a value object.** Deterministic, LLM-free: `(topology_parsed, len(accepted),
  manifest_serialized)`, plus `missing` and `invalid` detail. It has three consumers, all
  renderings of the same object — console progress, the appended continuation block (the score's
  inverse), and the failure message. Failure text stops being hand-written prose ("No Blueprint or
  Manifest artifacts were written") and becomes `score.render()`, so a stall reports `8/10` and
  names the two missing stories.
- **Progress is measured on `accepted`, never on `remaining`.** A ratio against `expected` breaks
  when a split moves the denominator; strictly increasing `accepted` is immune and needs no
  special case for splits.
- **Topology invariants replace "frozen topology."** (1) An accepted story is frozen — never
  renamed, re-scoped, or removed. (2) A pending story may be refined into children covering it.
  (3) Total declared scope never shrinks.
- **Lazy amendment.** Continuation omits `TOPOLOGY.md` by default; the model re-emits it only to
  split a pending story. Python diffs against the merged declaration and rejects any delta
  touching an accepted story. An amendment must carry complete child declarations (full
  `_PASSTHROUGH_FIELDS` plus `depends`/`provides`/`consumes`) — Python cannot synthesize edges.
- **No final re-emission.** `TOPOLOGY.md` is transient; its only consumer is
  `_manifest_from_declaration` at the end. Python already holds the merged declaration, so it *is*
  the final topology. A closing re-emit would spend front-of-budget output, risk truncating the one
  artifact everything depends on at the point of least slack, and re-open frozen declarations.
- **Acceptance is shape-level, not delimiter-level.** `planning_session.py:2404` already warns a
  cut landing after a prior closing delimiter can leave a truncated story parsing clean. Since
  acceptance freezes irreversibly, an artifact is accepted only on declared-story match, paired
  delimiters, typed-spec shape, and no conflict with an accepted artifact.
- **Two stop conditions, mirroring the build repair loop** (`build_run.py`: `stalled` plus
  `repair_attempts: int = 3`): no progress, and an attempt cap of 3 continuations (4 total passes),
  exposed as `--continue-attempts`.
- **Step 0 — measure first.** The `cached 305,407 (100% hit)` was observed *within* one
  invocation. Whether the adapter preserves the prefix and the cache stays warm across a second
  `run_prompt` call is unverified. Confirm before building; if it misses, the loop still works but
  costs full input per pass.
- **Known residual:** continuation makes failure cheaper and its diagnostic numeric; it does not
  make failure partial. A stall at 8/10 still writes nothing, because a target holding 8 specs, no
  manifest, and a stale prior blueprint is neither runnable by Build nor cleanly reconcilable by
  the next `plan create`. Accepted deliberately.
- **Unexamined:** Zone D (`conform_specs`) may rewrite authored content and could mutate artifacts
  the loop has frozen. Remains Open Question 4, out of scope.

A run that stops one artifact short must not throw away twelve minutes and $2.70 of valid work.
Model the existing build loop, which succeeds by exactly this method: append a bounded instruction
to the same prompt and continue while progress is measurable ("5/10 accepted stories" → "8/10
accepted stories" → done).

- **Progress metric:** accepted story artifacts against story artifacts declared in `TOPOLOGY.md`.
  The declaration supplies both the expected story count and the exact story ID → `implements`
  filename mapping. A parsed block is not progress until it is individually valid and accepted.
- Continue while the accepted count strictly increases. Stop on no progress, not on an iteration
  count. There is no retry limit and no size limit; strict increase bounds successful continuation
  passes by the number of declared stories.
- Assemble as the **byte-identical base prompt prefix** plus an appended block. The failed run
  logged `cached 305,407 (100% hit)`; an identical prefix re-hits it.
- Never discard already-valid artifacts.

**Depends on the declaration.** Progress is unmeasurable without a count of what should exist, which
is what §Zone B topology declaration cutover produces. That cutover landed on 2026-08-01, so this
section is now unblocked.

**Implementation.**

1. **Prompt.** New `prompts/plan_continue.md` per the Prompt Contract Standard (`AGENTS.md`):
   frontmatter `name`, `description`, `version`, `intent`. Its body is the bounded continuation
   instruction appended to the original assembly; it is not a replacement prompt. It states one
   job — emit only the named missing or replacement artifacts, in the same delimited block format,
   nothing else.
2. **Assembly.** Reuse the original `PromptAssembly` and append one part, the way
   `_conflict_challenge_assembly` already does (`planning_session.py`, near the Zone C helpers).
   Copy that shape: it appends a bounded instruction to the complete original planning context and
   is the proven pattern for a second pass. The **prefix must stay byte-identical** or the cache
   hit is lost.
3. **Ledger.** Python derives `expected`, `accepted`, `missing`, and `invalid` from the declaration
   and returned artifacts. An accepted artifact corresponds to exactly one declared story and
   filename, has a complete structural boundary, satisfies the applicable Typed Specification
   shape needed for accumulation, and does not conflict with an already accepted artifact. Invalid
   artifacts never enter the accumulator and remain eligible for replacement. A conflicting second
   version of an already-valid artifact is an error.
4. **Appended block carries:** accepted story/artifact metadata; remaining story IDs and required
   filenames; invalid artifact names and concise validation defects when applicable; and the
   instruction to emit only missing or replacement artifacts. Do **not** resend accepted artifact
   bodies.
5. **Loop.** After each pass, recompute `expected - accepted`. Continue only when
   `len(accepted)` strictly increases. Complete when every declared story has one accepted artifact.
   Stop on no increase. No iteration cap, no token cap.
6. **Execution.** Make another invocation through the injected `runner` (default
   `llm.run_prompt`) using the same `llm`/`model`/`effort`, target context, and byte-identical base
   prefix. Give every pass its own `execution_id` and use `command_name="plan"`. This is a runner
   invocation, not an agent file-write tool call: Plan keeps provider tools disabled and the module
   owns filesystem writes. Console: one line per pass showing the accepted and missing counts.
7. **Merge.** Accumulate only accepted artifacts across passes. Validate each pass's contribution
   before admission, permit a later pass to replace an invalid earlier attempt, and run the existing
   whole-plan validation over the merged set before writing. Keep `blocks_text` correct by
   validating each contribution against its own source response before accumulation.
8. **Failure.** When progress stalls, raise the existing error with the pass count and every
   `execution_id` appended. Already-valid artifacts are still never written on failure; that is
   the current all-or-nothing contract and this section does not change it.

**Tests** (fake runner, `tests/test_planning_session.py`): missing specs → continues and completes;
accepted count increases then stalls → stops with all execution IDs reported; nothing missing →
never fires; a pass returning junk → does not corrupt accumulated artifacts; invalid artifact →
remains replaceable; conflicting valid artifact → fails; no accepted artifact discarded; no files
written until the merged set passes whole-plan validation.

### Computed blocks are executable build units
`2026-08-02` · `spec:approved` · `impl:unimplemented`

The topology cutover correctly made `TOPOLOGY.md` a flat LLM-authored declaration and made Drydock
compute ordering, type-safe block grouping, and numeric `block:` membership mechanically. The
Build consumer was not cut over with it: Build still recognizes a group only through the legacy
`feature` node plus child `parent:` relationship, ignores numeric `block:`, labels every new-
taxonomy story `Ungrouped`, and executes one story at a time.

Numeric `block:` is the sole normal Build batching relationship for a Plan- or replan-generated
Manifest. `depends:` remains the LLM-authored prerequisite relationship. `parent:` is not added to
the new taxonomy; legacy feature/parent Manifests remain a compatibility path only.

Every Plan/replan story belongs to exactly one valid computed block. A block containing one story
is still a group. `Ungrouped` in a new-taxonomy Manifest is a fatal Manifest defect: the computed
execution tree is absent or damaged, not an executable fallback category. Validation requires a
positive block number on every story, consistent membership, and a preamble `blocks:` count that
matches the distinct computed blocks.

Build forms one executable unit from all stories sharing the selected block number. Pending
members execute together in Manifest order. Verified members are supplied as regression context.
Dependencies within the block are internal sequencing and do not split or block the unit. Every
dependency outside the block must be `closed/verified`, otherwise the entire block is blocked.
`--story` remains the explicit single-story override.

Build status, QuarterDeck presentation, grouped prompt assembly, block selection, and readiness
checks consume this same block contract. No new-taxonomy story is rendered as `Ungrouped`.

### Replan preserves built work across topology-only changes
`2026-08-02` · `spec:approved` · `impl:unimplemented`

Replanning may freely change dependency relationships, type-safe block membership, and block
numbers without resetting otherwise unchanged built work. State preservation keys on stable story
identity plus build-relevant specification content; block-number changes never affect state.

Whole-file byte equality is too broad as the only preservation test. Relationship-only metadata
changes introduced by Plan/refit — specifically `Depends On` / `Is Dependent On` refactoring — do
not dirty an otherwise unchanged built story or force a rebuild. The preservation decision uses a
normalized build-relevant fingerprint that excludes those relationship-only fields while retaining
the existing full-file applied-spec provenance.

A materially changed story may reset to `pending`. Its previously verified dependents do not
automatically reset in this implementation. Contract-sensitive downstream invalidation remains an
open design item.

---

## Acceptance Criteria

1. Does not run without ROOT green (approval precondition enforced; exits with error otherwise).
2. Emits a graph that is atomic-story (one spec per story), fully AC-gated, acyclic, reachable,
   with no story-count ceiling.
3. Story-too-big guardrail applied; oversized stories split before emission.
4. Integrity check passes before `MANIFEST.md` is written; failure surfaces actionable findings.
5. Writes `MANIFEST.md` with ROOT seeded green. No separate ordering file is produced.
6. Deterministic given the same Intent + Decisions.
7. All `depends-on` edges use the single direction (dependent node declares); no `gates` syntax.
8. Multiple `parent` values allowed and parsed correctly.
9. Analyze hands Plan a Commander-reviewed, expectation-complete epic and a proposed story map.
10. Plan receives all readable immutable sources and may revise the proposed decomposition.
11. Markdown becomes governed specifications; non-Markdown assets are projected byte-for-byte.
12. Commander questionnaires and human-authored `DECISIONS.json` items survive every replan.
13. Plan and Build decisions surface via `DECISIONS.json`, visible, non-duplicated, and never
    hard-block regardless of severity.
14. Running the next command implies approval when no blocker prevents that stage.
15. Every generated story belongs to one valid numeric block; a one-story block is grouped and a
    new-taxonomy `Ungrouped` story is a fatal Manifest defect.
16. Build executes all pending stories in the selected numeric block together, permits internal
    dependency sequencing, and blocks the unit on any unverified external dependency.
17. Replan preserves unchanged built stories across block renumbering and relationship-only
    metadata changes.

## Guardrails

- **Precondition: ROOT green.** Must not run unless `drydock approve <tgt>` has been called.
- **No cross-stack batches.** Hard rule; applies to both manual and automatic ordering.
- **One spec per story.** `spec:` field required; blank is a defect.
- **Every story has ≥1 AC gate.** A story without a `depends-on` AC node must not be emitted.
- **Integrity check gates emission.** `MANIFEST.md` not written until the graph passes fully.
- **Immutable source provenance.** Never modifies `blueprint/sources/**`.
- **Plan owns governed outputs.** Plan may replace top-level Blueprint specifications and
  `MANIFEST.md` only after persistent Commander input has been harvested.
- **`depends-on` is the only edge syntax.** No `gates`, no other direction. Parser enforces this.

## Open Questions

1. **Compact scope** — does the applied registry and compact substitution rule cover only `stack:`
   files, or also `rules:` and `context:` files?
2. **Integrity failure UX** — block `MANIFEST.md` write only, surface as QuarterDeck questions, or
   both? (Lean: block + surface findings; PO decides whether to re-analyze or fix the spec.)
3. **Drift propagation model** — how green/stale propagates when an upstream node changes post-build.
4. **Zone D review** — dependent and deferred. `conform_specs` is unreviewed and may rewrite
   authored content. Determine whether it stays, and what its firing rate says about Zone B, only
   after its dependency and actual behavior are understood. No implementation decision is made.
5. **Contract-sensitive downstream invalidation** — determine whether a dependent story becomes
   dirty from a change to the upstream surface it actually consumes. Do not propagate dirty state
   merely because any upstream specification byte or story changed. The likely discriminator is a
   changed consumed contract or compact projection. Until this is designed, replanning resets the
   changed story only and leaves previously verified dependents unchanged.

*Closed 2026-08-01:* `ac` as node or field (§Programmatic Acceptance is not a node); deterministic
and model phase grouping (§Plan command workflow); TDD phase placement (§Content and acceptance are
authored together). *Dropped:* the Marina stopping condition — it was a property of the plan
boundary being rewritten. *Removed:* the Compass setup verb — `BUILD_PLAN_COMPASS.md` does not
exist.

## Not in scope yet

Editing the canonical specification. Detailed Shipyard Crew execution mechanics beyond the
story-local decision-record contract. Story-too-big splitting is retired by §Story sizing; the
story count cap is retired by §Story count is not capped and removed from the code.

Remaining implementation work: §Computed blocks are executable build units and §Replan preserves
built work across topology-only changes. Zone D and contract-sensitive downstream invalidation
remain deferred reviews in Open Questions 4 and 5, not implementation items.

`BUILD_PLAN_COMPASS.md`, `MANUAL_BUILD_ORDER`, and PO hand-authored build ordering are prototype
artifacts that never existed in implementation. They are removed from these notes and from
`notes/archive/archive_plan.md`, which carries a deprecation banner. `CHANGELOG.md` retains its
historical mention as a release record.

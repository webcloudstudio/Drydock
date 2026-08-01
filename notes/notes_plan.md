# NOTES: Plan Create

| Field | Value |
|-------|-------|
| Version | 2026-08-01 V15 |
| Route | plan |
| Status | Working notes — not canonical specification |
| Description | Plan team authority, source-to-Blueprint translation, decomposition, Commander-decision preservation, ordering, and downstream build handoff. |
| Pending spec | 2 approved items |
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

### Diagnostic — the Marina plan failure was not a capacity limit
`2026-08-01` · `spec:na` · `impl:n/a`

Recorded so the analysis is not repeated.

| Run | Prompt | Output tokens | Text | Files | MANIFEST |
|---|---|---|---|---|---|
| CommonMark 07-27 | 313 KB | 132,692 | 107 KB | 30 | yes |
| CommonMark 07-27 | 314 KB | 134,592 | 106 KB | 31 | yes |
| Marina 08-01 | 373 KB | 69,657 | 65 KB | 13 | no |
| Marina 08-01 | 374 KB | 69,052 | 35 KB | 8 | no |
| Marina 08-01 | 374 KB | 70,077 | 35 KB | 8 | no |

All five runs used `claude-sonnet-5` on the same code path and ended with `stop_reason: end_turn`.
Sonnet emitted 132,692 output tokens and a complete thirty-file plan five days before the failures,
so there is no ceiling near 70,000.

`drydock plan CommonMark` passes under the current prompt, so `plan_create.md` V26 and the
accumulated guardrails are exonerated. The three Marina runs terminating within 1.5% of each other
indicates a consistent stopping condition rather than model variance.

**Amended `2026-08-01` after a fourth Marina run (41 files).** The headline holds and is now proven
rather than inferred: **capacity is not the discriminator.** The premise "the runs were not
truncated" does not hold, and the per-message evidence identifies the real signal.

Every `claude` run — failures *and* successes — carries a `max_tokens` message end. Crossing the
64,000-token per-message output cap is routine and `claude -p` transparently continues past it.

| Run | msg 1 | msg 2 | msg 3 | Files | MANIFEST |
|---|---|---|---|---|---|
| CommonMark 07-27 | cap 64k (63,999 thinking) | cap 64k (25,955 thinking) | end_turn 4,692 | 30 | yes |
| CommonMark 07-27 | cap 64k (64,000 thinking) | cap 64k (27,886 thinking) | end_turn 6,592 | 31 | yes |
| Marina 08-01 a/b/c | cap 64k | end_turn 5–6k | — | 8–13 | no |
| Marina 08-01 d | cap 64k (39,249 thinking) | end_turn 18,420 | — | 41 | no |

**The successes truncate more than the failures.** The discriminator is message count: CommonMark
continues into a third message and lands the Manifest there; Marina's second message ends
voluntarily, one artifact short. The model is not being cut off at the end — it is stopping.

Why it stops is still unidentified: thinking text is not persisted, only token counts. One untested
observation — CommonMark spent its entire first message thinking (63,999 of 64,000) and then wrote
cleanly, while Marina interleaves, so its cap lands mid-artifact and the resumption must recover
from a broken tail.

Two corrections to the record:

- **Granularity was never the problem.** `targets/Marina/ANALYSIS.md` holds 63 stories and 43 Story
  Realization Map entries against 46 source files — close to the one-story-per-source expectation,
  at defensible Agile granularity (`HARNESS-001 Typed settings model and resolution order`). A
  "99 candidate stories" figure reported by a second agent is not in the file. Verify counts before
  acting on them.
- **Some output was damaged, and silently.** Marina run *d* was cut inside
  `FEATURE-Reconciliation.md` and the continuation restarted that artifact, leaving the truncated
  attempt and its retry fused into one block that still pairs 1:1. Run *b* has the same shape
  (`DATABASE.md (continued)` inside `DATABASE.md`). A CommonMark codex run lost
  `FEATURE-Autolinks.md` entirely to an opener with no `END`. All three now fail loudly — see
  §Artifact delimiter guardrail.

The trajectory across the four Marina runs is 8 → 8 → 13 → 41 files. The restructure is converging;
run *d* authored a near-complete Blueprint and failed only on its final artifact.

### Constraints surface as questions
`2026-08-01` · `spec:approved` · `impl:unimplemented`

Red and yellow lights are raised as **questions, not refusals**, through machinery that already
exists — `questions.py` defines `QUESTION_ORIGINS = {plan, build, analyze-questionnaire}`,
`QUESTION_SEVERITIES`, and the `## Questions` / `QUESTIONS:` contract.

- **Analyze — story count.** Above 80 stories, emit one `discovery-story-count.json` asking the
  Commander to confirm granularity, quoting the real count and offering to take a target NUMBER for
  a replan. `required_before_plan: false` — the plan is usable either way. Never drop, merge, or
  withhold stories to get under the number, and never cap the list. *(Prompt-side: implemented.)*
- **Plan — error threshold.** Raised as a `QUESTION:` block in a Blueprint rather than a hard
  failure. The question belongs to the block; it does not require a foundational specification or
  architecture context. Its deterministic carrier is the specification implemented by the first
  story in computed block order. *(Unimplemented.)*

**Implementation of the plan side.** After `compute_plan` returns, compare each block's measured
cost against `build.resolve_error_tokens()` (default 120,000; `resolve_warn_tokens()` stays the
advisory marker already written as `size:` / `budget: over-target`). For each block over the error
threshold, append a question through the existing `questions.py` contract — `origin: plan`,
`severity: material`, `status: open`, id `Q-BLOCK-<n>` — to the specification implemented by the
first story in computed block order, naming the block, its measured cost, the threshold, and its
complete member-story list. Do not inject an
architecture specification or `architecture_compact.md`, change block membership, invalidate the
block, or change its execution eligibility merely to carry the question. Emit the plan; do not
refuse it. `normalize_questions_first` already runs over emitted specs in `_validate_plan_output`,
so the section lands in the right place. Test with a fake runner and a deliberately huge spec.

### Continuation — resume, never discard
`2026-08-01` · `spec:approved` · `impl:unimplemented`

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
12. Commander questionnaires and Blueprint question edits survive every replan.
13. Plan and Build decisions remain story-local, visible, non-duplicated, and non-blocking unless
    explicitly classified `Blocking`.
14. Running the next command implies approval when no blocker prevents that stage.

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

*Closed 2026-08-01:* `ac` as node or field (§Programmatic Acceptance is not a node); deterministic
and model phase grouping (§Plan command workflow); TDD phase placement (§Content and acceptance are
authored together). *Dropped:* the Marina stopping condition — it was a property of the plan
boundary being rewritten. *Removed:* the Compass setup verb — `BUILD_PLAN_COMPASS.md` does not
exist.

## Not in scope yet

Editing the canonical specification. Detailed Shipyard Crew execution mechanics beyond the
story-local decision-record contract. Story-too-big splitting is retired by §Story sizing; the
story count cap is retired by §Story count is not capped and removed from the code.

Remaining implementation work: §Constraints surface as questions (plan side) and §Continuation —
resume, never discard. Zone D remains a dependent, deferred review in Open Question 4, not an
implementation item.

`BUILD_PLAN_COMPASS.md`, `MANUAL_BUILD_ORDER`, and PO hand-authored build ordering are prototype
artifacts that never existed in implementation. They are removed from these notes and from
`notes/archive/archive_plan.md`, which carries a deprecation banner. `CHANGELOG.md` retains its
historical mention as a release record.

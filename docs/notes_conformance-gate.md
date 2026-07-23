# NOTES: Conformance Gate

| Field | Value |
|-------|-------|
| Version | 2026-07-23 V2 |
| Route | build / plan (acceptance-criteria gating) |
| Status | Working notes — not canonical specification |
| Description | Acceptance criteria are the definition of done; deterministic ACs are never sampled, tested at story/block build and mirrored into Sea Trials. |
| Pending spec | 7 approved items |
| Pending impl | 4 unimplemented sections |

## Implementation status (2026-07-23)
- **Done:** Block → Story → AC failure chain (`build_run._render_ac_failure_chain`, commit
  732875e). Opaque build failures routed through the LLM standoff diagnosis into ERRORS.md and
  the evidence file (commit 464da26). Generation guidance in the Blueprint authoring contract and
  build prompt: acceptance is the complete definition of done, never sampled; a full deterministic
  suite belongs on the completing block (`Corpus: full`) and mirrored into Sea Trials; stub/absent
  is a defect (commit 05149c9).
- **Pending:** a deterministic Plan-time gate that rejects a *dishonest* `Corpus: full` (declares
  full but samples via `--pattern`/`--number`/slice) and a *missing* gate when an authoritative
  suite is imported. Deferred because reliable "suite is present" detection and per-check honesty
  scoping risk false positives; generation guidance carries the intent for now.

## Goal
Build conformance gating the correct way: acceptance criteria are the definition of done, at
story/block level and at project (Sea Trials) level, and a deterministic definition of done is
never a sample — it is the complete test suite. Strong gates that stop a mis-built step early
rather than diagnosing a large finished project later.

## Decisions

### Programmatic acceptance criteria are never sampled
`2026-07-23` · `spec:approved` · `impl:unimplemented`

A story/block's programmatic (deterministic) acceptance criteria are the **complete** test
suite, never a hand-picked subset. Sampling is only ever a cost-saving move and it saves
nothing here: Drydock builds one-shot with no iterate loop, so there is no loop to justify a
sample; a deterministic suite simply runs longer, and the LLM build is a single pass regardless
of AC count. "100%" is not an exotic bar — it is just what "definition of done" means: a story
with failing ACs is not done.

### Two acceptance levels, both tested
`2026-07-23` · `spec:approved` · `impl:implemented`

Story/block acceptance criteria (in the Blueprint) and project acceptance criteria (Sea Trials)
are both real and both tested — not either/or. Sea Trials are the LLM-judged project layer and
are naturally small (a reasonable project is not 100 LLM-evaluated criteria). The "never sample"
rule therefore bites on the programmatic ACs, not on Sea Trials.

### The block is the test unit; failures report a Block → Story → AC chain
`2026-07-23` · `spec:applied` · `impl:implemented`

Multiple stories build together in one step (the block). After the block builds, the block's
entire AC set runs once. Because every AC maps to its story, a failure is attributed per story
and reported as a chain: **"Block failed → Story X failed → AC abc failed"**, naming the story,
its stated intent, and the concrete assertion (e.g. "must add two numbers, but a+b≠c"). No
per-story execution; per-story attribution.

### Strong gates, fail fast; `score ac` stays manual
`2026-07-23` · `spec:approved` · `impl:implemented`

The gate's job is to stop a wrong story from propagating: halting and redoing a mis-built step
is cheaper than diagnosing a large finished project. The story/block-stage AC test during build
is the **automatic gate**. `drydock score ac` is **manual re-verification, not a gate** — if the
stories built honestly, it is already green.

### A whole-project deterministic AC lives in both the completing block AC and Sea Trials
`2026-07-23` · `spec:approved` · `impl:unimplemented`

The same deterministic criterion (e.g. "parse the spec suite 100%") belongs in **both** the
acceptance of the block that completes the runnable capability **and** Sea Trials. It is a Sea
Trial and a block AC at once — no competition between the two homes.

### Placement is by judgment; existence is mandatory
`2026-07-23` · `spec:approved` · `impl:unimplemented`

A whole-project deterministic AC can only run once the code that makes it runnable exists, so it
must sit on the story/block that **completes** the capability — never on a foundation step that
cannot yet run it (it would fail vacuously). Placement uses whatever the author provides:
explicit project ACs, or feature-level statements ("feature X must do A, B, C"). The hard
invariant is existence — the definition of done **must be somewhere**. Absent is the one
unacceptable state; a missing definition of done is exactly how the sampled build slipped
through.

### The planning integrity gate inverts
`2026-07-23` · `spec:approved` · `impl:unimplemented`

Today `planning_session._invokes_unbounded_corpus` makes "a story's acceptance runs the full
deterministic suite" a **fatal** Plan error and tells the author to defer it to Sea Trials.
Under these decisions that inverts: a complete deterministic suite as a story/block AC is
**required**, not a violation. What the gate rejects instead is the **sampled, stubbed, or
missing** definition of done when a complete authoritative suite is available.

## Acceptance Criteria
- Plan integrity fails when a Blueprint imports an authoritative deterministic test suite but a
  story/block acceptance criterion samples or stubs it, or when no story carries it at all.
- A build block failure names the failing story and its failing AC (Block → Story → AC) with the
  concrete assertion.
- Running the complete deterministic suite as a story/block AC does not raise the "unbounded
  corpus" Plan error.

## Guardrails
- Terminology: speak in "acceptance criteria" / "test suite" / "definition of done," not
  "corpus" (the CommonMark project's own name for `spec.txt`). The internal `corpus.py` sense
  (imported source files) is a different, unrelated meaning.
- Sea Trials remain the LLM-judged project-acceptance layer; do not overload them with the
  programmatic suite mechanics — mirror the criterion, keep the concepts distinct.

## Open Questions
- Exact detection of "sampled/stubbed" deterministic ACs (slices `[:N]`, `--pattern`,
  `--number`, hardcoded subset lists, files-exist stubs) versus a genuine full run — heuristic
  boundary to set in `proof_integrity` / the planning gate.

## Not in scope yet
- Rebuilding the `commonmark_2` Blueprint by hand (regenerate via the fixed generation path).
- Any project-AC threshold below 100% for a deterministic suite (rejected).

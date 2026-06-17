# ARCHIVE: plan
Archived from notes_plan.md

### As-Built (wired 2026-06-16)
`2026-06-16` · `spec:na` · `impl:implemented`

`drydock plan create <Target>` is wired as LLM-driven Blueprint authoring
(`src/drydock/planning_session.py`, `prompts/plan_create.md`, commit `aea9eb9`). One LLM call
authors the typed Blueprint spec files (rewriting `blueprint/sources/**` per the analyze story
map), emits the single `BUILD_PLAN_COMPASS.md`, and a draft `MANIFEST.md`. The module parses the
delimited blocks, merges prior block states by id, runs a deterministic integrity gate, and writes
the QuarterDeck projection. Tests: `tests/test_planning_session.py` (fake runner).

**Built:** spec authoring; single `BUILD_PLAN_COMPASS.md` definition; single-directional clean
regenerate (no state merge — superseded the earlier re-run merge on 2026-06-16); integrity gate
(depends resolve, acyclic, `implements` names real files, ≥1 AC per story, ~100-story cap — all
fatal); precondition gate (ANALYSIS.md exists, not Blocked, no `BLOCKERS.md`).

**Diverged / not yet built (open items):**
- **Precondition is `ANALYSIS.md` + not-Blocked, not an `approve`/ROOT-green gate.** No `drydock
  approve` verb exists; the original ROOT-green precondition was not implemented.
- **Story-too-big split** and the **~100-story cap** are not enforced.
- **≥1 AC per story** is a *warning*, not a hard emission gate.
- **No-cross-stack batching** is instructed to the LLM in the prompt but not deterministically
  enforced; the **automatic batching algorithm** (the `MANUAL_BUILD_ORDER = false` auto-seed) is
  not built.
- The Compass is **LLM-seeded** in the same call (not a separate Python seeding step).

### Contract files (clarification)
`2026-06-16` · `spec:na` · `impl:implemented`

The injected "contract files" are `prompts/MANIFEST_CONTRACT.md` (MANIFEST block format) and
`prompts/BLUEPRINTS_CONTRACT.md` (typed-spec file format) — output-format authoring contracts.
`docs/Drydock_Specification.md` (the product spec) is **not** injected into plan create.


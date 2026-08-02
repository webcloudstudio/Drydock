# ARCHIVE: plan
Archived from notes_plan.md

> **Deprecated 2026-08-01.** `BUILD_PLAN_COMPASS.md`, `MANUAL_BUILD_ORDER`, and PO hand-authored
> build ordering were prototype artifacts and never existed in implementation. They are removed
> from this archive. `MANIFEST.md` is the ordering. See `notes_plan.md` §Order and Batch.

### As-Built (wired 2026-06-16)
`2026-06-16` · `spec:na` · `impl:implemented`

`drydock plan create <Target>` is wired as LLM-driven Blueprint authoring
(`src/drydock/planning_session.py`, `prompts/plan_create.md`, commit `aea9eb9`). One LLM call
authors the typed Blueprint spec files (rewriting `blueprint/sources/**` per the analyze story
map) and a draft `MANIFEST.md`. The module parses the
delimited blocks, merges prior block states by id, runs a deterministic integrity gate, and writes
the QuarterDeck projection. Tests: `tests/test_planning_session.py` (fake runner).

**Built:** spec authoring; single-directional clean regenerate (no state merge — superseded the earlier re-run merge on 2026-06-16); integrity gate
(depends resolve, acyclic, `implements` names real files, ≥1 AC per story, ~100-story cap — all
fatal); precondition gate (ANALYSIS.md exists, not Blocked, no `BLOCKERS.md`).

**Diverged / not yet built (open items):**
- **Precondition is `ANALYSIS.md` + not-Blocked, not an `approve`/ROOT-green gate.** No `drydock
  approve` verb exists; the original ROOT-green precondition was not implemented.
- **Story-too-big split** and the **~100-story cap** are not enforced.
- **≥1 AC per story** is a *warning*, not a hard emission gate.
- **No-cross-stack batching** is instructed to the LLM in the prompt but not deterministically
  enforced; the automatic batching algorithm is not built.

### Contract files (clarification)
`2026-06-16` · `spec:na` · `impl:implemented`

The injected "contract files" are `prompts/MANIFEST_CONTRACT.md` (MANIFEST block format) and
`prompts/BLUEPRINTS_CONTRACT.md` (typed-spec file format) — output-format authoring contracts.
`docs/Drydock_Specification.md` (the product spec) is **not** injected into plan create.

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

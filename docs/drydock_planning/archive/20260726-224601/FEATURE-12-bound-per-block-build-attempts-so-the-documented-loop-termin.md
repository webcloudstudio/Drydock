---
id: DDF-013
title: Bound per-block build attempts so the documented loop terminates
area: drydock build
impact: 7
complexity: 3
rank: 12
generated_at: 2026-07-26T20:31:43-04:00
review_model: claude-opus-5
source: drydock score drydock
---

# FEATURE DDF-013: Bound per-block build attempts so the documented loop terminates

| Field | Value |
|---|---|
| Area | drydock build |
| Impact | 7/10 |
| Complexity | 3/10 |
| Rank | 12 |
| Project Types | All |

## Problem

The Specification prints `while drydock status <Target> --ready; do drydock build <Target>; done` as the normal operating loop, and `--continue` resumes a failed block in place by default. A block that fails for an environmental reason — a missing tool, an unreachable service, a context overflow — stays runnable, so the loop reissues the same expensive LLM call indefinitely with no durable record of how many times it has been tried and no Commander-visible stop.

## Intent

Specification `drydock status` — `--ready is the build-loop guard` with the printed loop; `drydock build` — `A block that fails resumes in place on the next build`.

## Evidence

Specification `drydock status` build-loop snippet; `--repair-attempts <n>` is per-invocation and defaults to 1; `MANIFEST_CONTRACT.md` Block States has no attempt counter and no terminal condition other than a state a failing block need not reach.

## Recommendation

Each block carries durable `attempts:` and `last_failure:` fields. A configurable `max_block_attempts` (default 3) is enforced across invocations: on exhaustion the decision writer transitions the block to `closed/failed` carrying the recorded `FAILURE_SUMMARY`, so `drydock status --ready` reports blocked and the documented loop terminates. Two consecutive identical `FAILURE_SUMMARY` values escalate to `--escalate-model` once, then halt.

## Stories

### Story 1: Durable attempt accounting

As the Commander, I want the plan to remember how many times a block has been tried, so that failure budgets survive across invocations.

**Acceptance Criteria**

- A failed block's `attempts:` increments by one per `drydock build` invocation and persists in `MANIFEST.md`.
- A successful block resets `attempts:` to zero.
- `last_failure:` records the single-line `FAILURE_SUMMARY` from `build.md`'s failure contract.
- A Manifest without `attempts:` parses and is treated as zero.

**Tests (RED first)**

- tests/test_build_run.py::test_attempts_increment_persists_across_invocations
- tests/test_build_run.py::test_success_resets_attempts
- tests/test_build_run.py::test_last_failure_records_failure_summary
- tests/test_build_plan.py::test_manifest_without_attempts_defaults_to_zero

### Story 2: Budget exhaustion terminates the loop

As the Commander, I want a hopeless block to stop the build loop, so that a subscription is not consumed by a repeating failure.

**Acceptance Criteria**

- A block reaching `max_block_attempts` is transitioned to `closed/failed` with `finding:` set to the recorded failure summary.
- With that block failed and no other executable work, `drydock status <Target> --ready` exits 1 and `--check` exits 2, terminating the documented loop.
- `max_block_attempts` is readable and settable through `drydock config`.

**Tests (RED first)**

- tests/test_build_run.py::test_exhausted_budget_marks_block_failed
- tests/test_status.py::test_ready_exits_one_when_only_failed_work_remains
- tests/test_config.py::test_max_block_attempts_is_configurable

### Story 3: Repeat-failure escalation

As the Commander, I want an identical repeated failure escalated once rather than retried blindly, so that the remaining budget is spent usefully.

**Acceptance Criteria**

- Two consecutive attempts producing the same `FAILURE_SUMMARY` cause the next attempt to use the configured escalate model.
- A third identical failure halts immediately regardless of remaining budget, with reason `no-progress`.
- A changed `FAILURE_SUMMARY` between attempts counts as progress and does not trigger the halt.

**Tests (RED first)**

- tests/test_build_run.py::test_repeated_identical_failure_escalates_model
- tests/test_build_run.py::test_third_identical_failure_halts_with_no_progress
- tests/test_build_run.py::test_changed_failure_summary_continues

## Definition of Done

- The loop printed in the Specification provably terminates for a block that always fails.
- Attempt state is visible in `drydock build status` and in the QuarterDeck Build Compass failure badge the Specification already describes.
- A Commander can reopen an exhausted block from the QuarterDeck, which resets `attempts:` through the decision writer.

## Implementation Plan

1. Add `attempts:` and `last_failure:` to the story/spike/feature field lists in `prompts/MANIFEST_CONTRACT.md` and to the block serializer in `build_plan.py`.
2. Add `max_block_attempts` to `config.py` with default 3 and document it in the `drydock config` variable table.
3. In `build_run.py`, read and increment attempts before the invocation, compare the new `FAILURE_SUMMARY` against `last_failure:`, and apply escalation and halt rules.
4. Route every state change through the decision writer; add the reopen path that resets `attempts:` from `build_review.py`.
5. Surface attempts and last failure in `build_status.py` and the QuarterDeck compass page.
6. Add tests in `tests/test_build_run.py`, `tests/test_status.py`, and `tests/test_config.py`, including a fake LLM that always fails identically.

## Specification Impact

The `Block States` table and the story/spike block field lists would need the author's approval to document `attempts:` and `last_failure:`; the `drydock config` table gains `max_block_attempts`.

## Risks

- A legitimately hard block that would have succeeded on attempt four is now failed and requires a Commander reopen — the default must be tunable and the halt message must name the reopen path.
- Comparing `FAILURE_SUMMARY` strings for progress is brittle if the agent varies wording for the same cause; treat near-identical summaries conservatively as progress rather than halting early.

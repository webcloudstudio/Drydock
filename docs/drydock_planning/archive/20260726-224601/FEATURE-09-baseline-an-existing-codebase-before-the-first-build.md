---
id: DDF-012
title: Baseline an existing codebase before the first build
area: drydock build
impact: 8
complexity: 5
rank: 9
generated_at: 2026-07-26T20:31:43-04:00
review_model: claude-opus-5
source: drydock score drydock
---

# FEATURE DDF-012: Baseline an existing codebase before the first build

| Field | Value |
|---|---|
| Area | drydock build |
| Impact | 8/10 |
| Complexity | 5/10 |
| Rank | 9 |
| Project Types | Legacy brownfield modernization, Multi-service system, Library / SDK |

## Problem

Planning always emits every block `pending` with an empty `applied_specs`, so pointing Drydock at an existing product makes the documented build loop re-derive working software from scratch. Whether existing code survives is left to the build agent's reading of `Preserve existing application files unless this step's specifications require a change`. Brownfield modernization — the most common real engagement — has no truthful starting frontier.

## Intent

Specification `SAIL Phase 4 — Loop` — `A Refit lets the Commander update the application while keeping the Blueprint and built software aligned`; `drydock import <Target> <Source> --format source` exists to bring existing code under control.

## Evidence

`prompts/plan_create.md`: `All blocks start state: pending`; Specification Plan Header: `applied_specs records one line per Blueprint Specification file that has been applied by a successful story or spike`; `prompts/build.md` step 2 leaves preservation to model judgment.

## Recommendation

Add `drydock build <Target> --baseline`: a no-LLM pass that runs every story's declared Programmatic Acceptance against the existing build directory, marks a story `closed/verified` only when all its proofs pass and none is demoted, records `applied_by=baseline` plus the current sha256 and commit into `applied_specs`, and leaves every other story `pending`. The result is a truthful frontier and a QuarterDeck report of exactly what the existing code already satisfies.

## Stories

### Story 1: Baseline verification pass

As the Commander, I want Drydock to test what already works before it builds anything, so that adopting an existing codebase does not mean rewriting it.

**Acceptance Criteria**

- `drydock build <Target> --baseline` makes zero LLM invocations and writes no application files.
- A story whose implemented spec's proofs all pass non-vacuously becomes `closed/verified` with `applied_by=baseline` recorded in `applied_specs`.
- A story with any failing or demoted proof remains `pending` and is listed in the baseline report with the failing check ids.
- Running `--baseline` twice is idempotent: the second run changes no block state.

**Tests (RED first)**

- tests/test_build_run.py::test_baseline_makes_no_llm_calls
- tests/test_build_run.py::test_baseline_verifies_passing_story
- tests/test_build_run.py::test_baseline_leaves_failing_story_pending
- tests/test_build_run.py::test_baseline_is_idempotent

### Story 2: Baseline provenance and drift continuity

As the Commander, I want baselined specs tracked like built ones, so that refit drift detection works from day one on an adopted project.

**Acceptance Criteria**

- `applied_specs` after a baseline run contains one line per verified story's spec with the correct sha256 and commit.
- Editing a baselined spec and running `drydock refit` marks the affected work for rebuild exactly as it would for a Drydock-built spec.
- `drydock status <Target> --check` reflects the baselined completion state.

**Tests (RED first)**

- tests/test_build_run.py::test_baseline_writes_applied_specs_provenance
- tests/test_refit.py::test_refit_detects_drift_on_baselined_spec
- tests/test_status.py::test_status_reflects_baselined_completion

### Story 3: Baseline report for the Commander

As the Commander, I want a reviewable account of what the existing code proves, so that I can decide what to modernize.

**Acceptance Criteria**

- A `BASELINE.md` artifact at the Target root lists every story with verified/pending status and, for pending stories, the failing or demoted check ids with reasons.
- The QuarterDeck renders `BASELINE.md` as a markdown page.
- The report distinguishes `pending — proof failed` from `pending — proof demoted` from `pending — no proof declared`.

**Tests (RED first)**

- tests/test_build_run.py::test_baseline_report_lists_story_outcomes
- tests/test_build_run.py::test_baseline_report_distinguishes_pending_reasons
- tests/test_quarterdeck_state.py::test_baseline_page_is_registered

## Definition of Done

- An imported existing codebase can be planned, baselined, and then built only where it genuinely falls short.
- Baseline verification uses the same acceptance runner and integrity detectors as `drydock score ac`, with no separate code path.
- The DDF-003 prepass gate does not fire spuriously on a baselined Target, because baselined stories are already closed.

## Implementation Plan

1. Add the `--baseline` flag to the `drydock build` parser in `cli.py` alongside the existing `--reset`/`--dry-run` selectors.
2. Implement the pass in `build_run.py` by iterating executable blocks and delegating to `score.py`'s per-story verification path so results are identical to `drydock score ac --step`.
3. Write state transitions exclusively through the decision writer named in `MANIFEST_CONTRACT.md`; record `applied_by=baseline` in `applied_specs`.
4. Add `BASELINE.md` generation through `standard_artifacts.py` and register the page in `QuarterDeck/console.yaml` defaults.
5. Document the flag in `prompts/build.md` only insofar as the build agent must not be invoked for it (it is a no-LLM path).
6. Add tests across `tests/test_build_run.py`, `tests/test_refit.py`, and `tests/test_status.py`.

## Specification Impact

The `drydock build` flag list and the `Plan Header` `applied_by` description would need the author's approval to add the `--baseline` flag and the `baseline` applier value.

## Risks

- A baselined story is closed on the strength of proofs the plan authored against code it did not write; weak proofs will over-credit the existing codebase, so DDF-004's detectors are a prerequisite.
- Running arbitrary acceptance proofs against an unfamiliar existing tree executes that project's code; the Specification's containment guidance applies with full force here and should be restated at the flag.

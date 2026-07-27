---
id: DDF-007
title: Compute and enforce per-block context cost at plan time
area: cross-cutting
impact: 8
complexity: 5
rank: 8
generated_at: 2026-07-26T20:31:43-04:00
review_model: claude-opus-5
source: drydock score drydock
---

# FEATURE DDF-007: Compute and enforce per-block context cost at plan time

| Field | Value |
|---|---|
| Area | cross-cutting |
| Impact | 8/10 |
| Complexity | 5/10 |
| Rank | 8 |
| Project Types | All, Large enterprise product, Multi-service system |

## Problem

Drydock claims story points are token costs and that each build step displays its estimated counts, but nothing computes a block's assembled prompt size until the build runs. `plan_create.md` bounds feature grouping by a `context ceiling` that is never given a value, and story size is defined as `the token and context size of the build step` — a quantity the planning model cannot see, since it does not know the size of the stack files, compact derivatives, or staged assets that will be injected. Oversized blocks are discovered as truncation or degraded output on the low-end models the process is designed for.

## Intent

Specification `Agile Methodology` — `Agile story points are token costs`; `Context Optimization` — `Build sets of stories together to optimize context`; `Agile Build Planning` — `Each step will display its estimated counts`.

## Evidence

`prompts/plan_create.md` Story and Task Criteria (`A story whose build step would not fit comfortably in one build prompt is too large`) and Manifest Construction Rules (`Keep a group's combined size within the context ceiling`); `config.py` exposes `prompt_warn_tokens` but only as a warning threshold at invocation time.

## Recommendation

After admission, `planning_session.py` invokes the deterministic assembly path in `build.py` for every executable block and writes `est_tokens:` onto each story, spike, and feature block plus `context_ceiling:` in the Manifest header. A block over the ceiling is a plan defect routed through the repair pass with the per-role byte breakdown. The QuarterDeck Build Compass renders per-block estimates and group totals so regrouping is a numeric decision.

## Stories

### Story 1: Deterministic per-block cost estimation

As the Commander, I want each block's assembled prompt cost computed without an LLM call, so that plan cost is knowable before I spend anything.

**Acceptance Criteria**

- For a fixture Manifest, `estimate_block_cost(block)` returns a token count that matches the count `drydock build --dry-run --show-prompt` reports for the same block within one percent.
- A feature block's estimate reflects stack deduplication across its child stories, not the sum of child estimates.
- Estimation performs no network call and writes no files.

**Tests (RED first)**

- tests/test_build.py::test_block_estimate_matches_dry_run_prompt_size
- tests/test_build.py::test_feature_estimate_dedupes_shared_stack
- tests/test_build.py::test_estimation_is_side_effect_free

### Story 2: Estimates persisted in the Manifest

As the Commander, I want token estimates recorded in the plan, so that the QuarterDeck and status output show real numbers.

**Acceptance Criteria**

- Every executable block in a generated `MANIFEST.md` carries an `est_tokens:` field with an integer value.
- The header carries `context_ceiling:` resolved from configuration with a documented default.
- `build_plan.py` parses `est_tokens:` and ignores it for execution ordering; a Manifest without the field still parses.
- `drydock build status` prints per-block estimates and the per-feature total.

**Tests (RED first)**

- tests/test_build_plan.py::test_est_tokens_field_round_trips
- tests/test_build_plan.py::test_manifest_without_est_tokens_still_parses
- tests/test_build_status.py::test_status_prints_block_estimates

### Story 3: Ceiling enforcement and regroup guidance

As the Commander, I want an oversized block rejected with a breakdown, so that the planner splits it instead of me discovering it at build time.

**Acceptance Criteria**

- A block whose estimate exceeds `context_ceiling` yields admission defect `block-over-ceiling` including the per-role byte breakdown (compass, implements, context, stack, rules).
- The repair pass receives the breakdown and a directive to split the spec file or regroup the feature.
- A block within the ceiling produces no defect.

**Tests (RED first)**

- tests/test_plan_admission.py::test_oversized_block_is_defect_with_role_breakdown
- tests/test_plan_admission.py::test_block_within_ceiling_passes
- tests/test_planning_session.py::test_repair_prompt_contains_role_breakdown

## Definition of Done

- No plan is written containing a block whose assembled prompt exceeds the configured ceiling.
- `MANIFEST.md`, `drydock build status`, and the QuarterDeck Build Compass all show the same estimate for a block.
- The ceiling default is documented alongside `prompt_warn_tokens` in `drydock config`.

## Implementation Plan

1. Expose the assembly and cost path in `build.py` as a pure function taking a parsed block and returning `(rendered_prompt, token_estimate, per_role_bytes)`; `prompt_assembly.py` already owns the estimator.
2. Add `context_ceiling` to `config.py` with a conservative default sized for the lowest-end model the process targets.
3. In `planning_session.py`, after admission, estimate every block, write `est_tokens:` through the Manifest writer, and raise `block-over-ceiling` defects.
4. Extend `build_plan.py` block parsing and the Manifest serializer to carry `est_tokens:` and header `context_ceiling:`.
5. Render estimates in `build_status.py` and in the QuarterDeck `compass` page type described in the Specification's page-type table.
6. Add tests across `tests/test_build.py`, `tests/test_build_plan.py`, `tests/test_build_status.py`, and `tests/test_plan_admission.py`.

## Specification Impact

None required; the Specification already promises estimated counts on each step. The `MANIFEST.md` block field lists and the Plan Header description would be extended to document `est_tokens:` and `context_ceiling:`.

## Risks

- Token estimation is approximate and provider-dependent; the ceiling must carry headroom or legitimate blocks will be rejected.
- Estimating every block adds plan-time work proportional to block count on large plans; assembly must reuse cached file reads.

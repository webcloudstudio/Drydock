---
id: DDF-006
title: Compute and enforce a per-block context budget at plan time
area: drydock plan
impact: 8
complexity: 5
rank: 6
generated_at: 2026-07-26T22:46:01-04:00
review_model: claude-opus-5
source: drydock score drydock
---

# FEATURE DDF-006: Compute and enforce a per-block context budget at plan time

| Field | Value |
|---|---|
| Area | drydock plan |
| Impact | 8/10 |
| Complexity | 5/10 |
| Rank | 6 |
| Project Types | All, Decisive for web applications and multi-service systems where feature groups accumulate stack files |

## Problem

`plan_create.md` instructs the model to 'Keep a group's combined size within the context ceiling' and defines story size as 'the token and context size of the build step' — quantities the planning model cannot compute and is never given. Drydock can compute them: `build.py` is the deterministic prompt and cost subroutine, `prompt_assembly.py` provides cost estimation, and `--dry-run --show-prompt` already assembles a step. Nothing runs that estimate across the whole plan at plan time, so an oversize block is discovered one at a time, mid-build, at full cost — undermining the declared feature of building large projects with low-end models. `prompt_warn_tokens` is a warning only.

## Intent

`Drydock_Specification.md` § Drydock Features ('Build large projects with low-end models', 'Context optimization at every stage') and § Agile Build Planning ('Each step will display its estimated counts').

## Evidence

`prompts/plan_create.md` § Manifest Construction Rules > Story blocks: 'Keep a group's combined size within the context ceiling' with no ceiling supplied; `Drydock_Specification.md` § drydock config lists `prompt_warn_tokens` as a 'Prompt-size warning threshold'; module inventory `build.py: Build-step assembly — the single deterministic prompt/cost subroutine`.

## Recommendation

After planning, assemble every block's prompt deterministically and write `cost_tokens:` into each Manifest block. `drydock plan` fails, listing every block over a configured `build_context_budget`, and `--split-oversize` emits split proposals the Commander can accept in the QuarterDeck. `drydock build status` and the Compass show per-block cost. `drydock build` refuses a block over the hard ceiling with the named remedy rather than issuing a call that will truncate.

## Stories

### Story 1: Write per-block assembled cost into the Manifest

As the Commander, I want each block's real assembled prompt size recorded, so that I can see cost before I spend it.

**Acceptance Criteria**

- Every executable Manifest block carries a `cost_tokens:` integer written by `drydock plan`.
- The recorded value equals the estimate `drydock build --dry-run --show-prompt` reports for the same block, within a documented tolerance.
- A feature group's cost reflects stack deduplication across its child stories, not the sum of per-story stacks.
- Re-running plan updates costs without altering block state.

**Tests (RED first)**

- test_every_executable_block_has_cost_tokens
- test_recorded_cost_matches_dry_run_estimate
- test_feature_group_cost_reflects_stack_dedup
- test_replan_updates_cost_preserving_state

### Story 2: Fail planning on oversize blocks

As the Commander, I want planning to refuse a plan containing a block that cannot fit, so that I do not discover it forty steps in.

**Acceptance Criteria**

- `drydock plan` exits non-zero listing every block whose `cost_tokens` exceeds `build_context_budget`, with each block's id and cost.
- `build_context_budget` is a `drydock config` key with a documented default and is overridable per run.
- A plan with no oversize block exits 0 and writes no warning.

**Tests (RED first)**

- test_plan_fails_listing_oversize_blocks_with_costs
- test_build_context_budget_config_key_and_default
- test_plan_within_budget_exits_clean

### Story 3: Propose splits for oversize blocks

As the Commander, I want a concrete split proposal for a block that is too large, so that I can fix the plan without hand-editing the Manifest.

**Acceptance Criteria**

- `drydock plan --split-oversize` writes a proposal naming the block, the suggested child stories, and the spec files each would implement.
- Accepting a proposal produces a Manifest in which every block is within budget and the dependency graph remains acyclic.
- The proposal never merges two blocks or reorders unrelated work.

**Tests (RED first)**

- test_split_oversize_writes_proposal_with_child_specs
- test_accepted_split_yields_all_blocks_within_budget
- test_accepted_split_preserves_acyclic_graph
- test_split_proposal_does_not_reorder_unrelated_blocks

### Story 4: Refuse to build an over-ceiling block

As the Commander, I want the build to refuse a step it cannot fit rather than truncate it, so that a wasted call becomes an actionable error.

**Acceptance Criteria**

- `drydock build` exits non-zero without issuing an LLM call when the assembled prompt exceeds the hard ceiling.
- The error names the block id, the assembled size, the ceiling, and the remedy command.
- `drydock build status` marks over-ceiling blocks distinctly from blocked and pending blocks.

**Tests (RED first)**

- test_build_refuses_over_ceiling_block_without_llm_call
- test_over_ceiling_error_names_block_size_ceiling_remedy
- test_build_status_marks_over_ceiling_distinctly

## Definition of Done

- A fixture plan with one deliberately oversize feature group fails planning and yields an accepted split that passes.
- Per-block cost is visible in `drydock build status` and on the QuarterDeck Compass.
- No LLM call is ever issued for a block known in advance to exceed the ceiling.
- `plan_create.md` no longer asks the model to judge a ceiling it is not given.

## Implementation Plan

1. Expose a whole-plan cost pass in `build.py` that assembles every block using the same code path as `--dry-run`.
2. Add `cost_tokens:` to the story, spike, and feature block field tables in `prompts/MANIFEST_CONTRACT.md`, marked as tool-written and never hand-edited.
3. Add `build_context_budget` to `config.py` and to the `drydock config` key table.
4. Add the oversize gate and `--split-oversize` to `planning_session.py` and the `plan` subparser in `cli.py`.
5. Add the pre-call ceiling check to `build_run.py` and the status marker to `build_status.py`.
6. Remove the unquantified ceiling instruction from `prompts/plan_create.md` and replace it with the deterministic contract.
7. Add fixtures: an oversize feature group, a plan at exactly the budget, and a plan well within it.

## Specification Impact

§ drydock config (new key), § The Manifest Graph Database (new block field), and § drydock build status (new state presentation). Requires the author's approval.

## Risks

- Token estimation differs across providers; a single budget may be wrong for `codex` versus `claude`.
- A hard failure at plan time will block Commanders who previously shipped oversize blocks that happened to work.
- Split proposals interact with the one-story-per-Blueprint-file rule and may force emitting new spec files mid-plan.

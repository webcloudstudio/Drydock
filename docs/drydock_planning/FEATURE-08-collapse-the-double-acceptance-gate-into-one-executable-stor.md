---
id: DDF-001
title: Collapse the double acceptance gate into one executable story gate
area: drydock plan
impact: 7
complexity: 4
rank: 8
generated_at: 2026-07-26T22:46:01-04:00
review_model: claude-opus-5
source: drydock score drydock
---

# FEATURE DDF-001: Collapse the double acceptance gate into one executable story gate

| Field | Value |
|---|---|
| Area | drydock plan |
| Impact | 7/10 |
| Complexity | 4/10 |
| Rank | 8 |
| Project Types | All, Especially CLI tools and libraries where a whole-suite smoke gate is the only gate emitted |

## Problem

A story's gate is defined twice and inconsistently. The specification calls `ac` a legacy block type and states a story closes when the build succeeds and Blueprint `Programmatic Acceptance` passes; `MANIFEST_CONTRACT.md` states acceptance is mandatory at both levels and that a plan missing either gate is rejected; `plan_create.md` then defines the mandatory child `ac` as 'a smoke check that runs the project test suite'. Every new plan is forced to emit a legacy construct whose canonical content is the same command for every story — a gate that cannot distinguish a story that delivered from one that did not, and that reruns the whole suite once per story.

## Intent

`Drydock_Specification.md` § Acceptance Check Blocks ('`ac` blocks are supported for legacy Manifests and exceptional orchestration checks. Blueprint `Programmatic Acceptance` is the normal source of durable acceptance.') and § Execution Rules ('A `story` or `spike` becomes `closed/verified` after the build agent succeeds, files are written, and Blueprint `Programmatic Acceptance` passes after the build.').

## Evidence

`prompts/MANIFEST_CONTRACT.md` § Story: 'Acceptance is mandatory at both levels ... A plan that emits a story missing either gate is rejected.' `prompts/plan_create.md` § Acceptance check blocks: 'The child `ac` block is the build gate: a smoke check that runs the project test suite'. `prompts/plan_reuse.md`: 'A story without a child `ac` block is rejected.'

## Recommendation

One gate per story: the `Programmatic Acceptance` of the single Blueprint file the story implements. `ac` becomes optional and reserved for orchestration checks that cannot be expressed as a Blueprint proof (process starts, port binds, cross-story smoke). The plan validator rejects a story that has neither non-vacuous proofs nor an orchestration `ac`, and rejects duplicate whole-suite `ac` checks.

## Stories

### Story 1: Make the child `ac` optional in the Manifest contract

As the Commander, I want a story to be gated by its Blueprint proofs alone, so that the gate discriminates between stories instead of running the same suite command for each.

**Acceptance Criteria**

- The plan validator accepts a story with zero child `ac` blocks when its implemented spec carries at least one `Programmatic Acceptance` check that `proof_integrity` does not classify as vacuous.
- The plan validator rejects a story whose implemented spec's `Programmatic Acceptance` is `- None.` and which has no child `ac` block.
- The plan validator rejects a story whose implemented spec's `Programmatic Acceptance` is `- None.` without an inline reason on the same line.
- `prompts/MANIFEST_CONTRACT.md` contains no sentence requiring a child `ac` block for every story.

**Tests (RED first)**

- test_validate_accepts_story_without_ac_when_nonvacuous_proofs_present
- test_validate_rejects_story_with_none_acceptance_and_no_ac
- test_validate_rejects_bare_none_acceptance_without_inline_reason
- test_manifest_contract_text_has_no_mandatory_ac_clause

### Story 2: Reject non-discriminating and duplicated `ac` checks

As the Commander, I want the plan validator to refuse gates that cannot fail differently per story, so that a passing block means that block worked.

**Acceptance Criteria**

- Validation fails when two or more `ac` blocks in one Manifest carry byte-identical normalized `check:` commands.
- Validation fails when an `ac` `check:` invokes an unfiltered full-suite run while a `Suite: full` proof exists elsewhere in the Blueprint.
- The failure message names each offending `ac` id and its parent story id.

**Tests (RED first)**

- test_validate_rejects_identical_ac_checks_across_stories
- test_validate_rejects_full_suite_ac_when_suite_full_proof_exists
- test_validate_error_names_offending_ac_ids

### Story 3: Align the planning prompts with the single-gate rule

As the Commander, I want the planning prompts to stop instructing the model to emit legacy blocks, so that generated plans match the specification.

**Acceptance Criteria**

- `plan_create.md`, `plan_reuse.md`, and `plan_create_speckit.md` contain no instruction requiring a child `ac` per story.
- A golden fixture plan containing zero `ac` blocks passes validation end to end.
- A golden fixture legacy Manifest containing `ac` blocks still parses and executes unchanged.

**Tests (RED first)**

- test_plan_prompts_have_no_mandatory_ac_instruction
- test_golden_plan_without_ac_blocks_validates
- test_legacy_manifest_with_ac_blocks_still_parses_and_orders

## Definition of Done

- `MANIFEST_CONTRACT.md`, `plan_create.md`, `plan_reuse.md`, and `plan_create_speckit.md` agree with `Drydock_Specification.md` on the legacy status of `ac`.
- Exactly one gate path is enforced per story by a named validator.
- Existing Manifests containing `ac` blocks parse, order, and close unchanged.
- QuarterDeck kanban and Compass render a story with no child `ac` without an empty column or a null badge.

## Implementation Plan

1. Rewrite `prompts/MANIFEST_CONTRACT.md` § Story acceptance paragraph and § Execution Rules to state that Blueprint `Programmatic Acceptance` is the story gate and `ac` is optional orchestration.
2. Rewrite `prompts/plan_create.md` § Manifest Construction Rules > Acceptance check blocks and its matching Hard Rules bullet; do the same in `prompts/plan_reuse.md` § Manifest Rules and `prompts/plan_create_speckit.md`.
3. Add a `story_gate` check to the plan validator in `validate_specification.py`, reading proofs through `acceptance.py` and vacuity verdicts through `proof_integrity.py`.
4. Add duplicate/full-suite `ac` detection to the same validator, normalizing `check:` by whitespace collapse before comparison.
5. Add fixtures: `tests/fixtures/plan_no_ac_valid/`, `tests/fixtures/plan_none_acceptance_no_ac_invalid/`, `tests/fixtures/plan_duplicate_ac_invalid/`, `tests/fixtures/manifest_legacy_ac/`.
6. Update `build_review.py` and `quarterdeck_state.py` closure logic so a story with no child `ac` closes on post-build proof pass alone.

## Specification Impact

none — this brings the two contracts into line with § Acceptance Check Blocks and § Execution Rules as already written.

## Risks

- Plans whose only real gate was the suite smoke now have no gate if their Blueprint proofs are weak; DDF-005 is the compensating control and should land in the same release.
- QuarterDeck views or reconciliation code keyed on the existence of a child `ac` per story may assume a non-empty set.
- Feature-level `ac` semantics ('runnable after all executable child stories are closed/verified') must be preserved while story-level `ac` becomes optional.

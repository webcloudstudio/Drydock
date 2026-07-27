---
id: DDF-005
title: Resolve the ac-block contradiction and stop full-suite reruns per story
area: drydock plan
impact: 8
complexity: 4
rank: 6
generated_at: 2026-07-26T20:31:43-04:00
review_model: claude-opus-5
source: drydock score drydock
---

# FEATURE DDF-005: Resolve the ac-block contradiction and stop full-suite reruns per story

| Field | Value |
|---|---|
| Area | drydock plan |
| Impact | 8/10 |
| Complexity | 4/10 |
| Rank | 6 |
| Project Types | All, Large enterprise product |

## Problem

The Specification calls `ac` a legacy block type whose durable acceptance lives in the Blueprint, while `MANIFEST_CONTRACT.md` and both planning prompts reject any story without a child `ac` block. `plan_create.md` then defines that mandatory gate as `a smoke check that runs the project test suite` while the same file rejects `An unbounded run of the suite from any non-terminal story`. Planners must therefore emit a block that the plan's own rules forbid, and the common resolution — running the full suite once per story — is both the slowest possible build and a gate that passes for reasons unrelated to the story.

## Intent

Specification `The Manifest Graph Database` — ``ac` is a legacy block type retained for existing Manifests. Durable acceptance lives in the Blueprint.` and `Blueprint Programmatic Acceptance is the normal source of durable acceptance.`

## Evidence

`prompts/MANIFEST_CONTRACT.md`: `every story is gated by at least one child ac block`; `prompts/plan_create.md`: `The child ac block is the build gate: a smoke check that runs the project test suite` versus `An unbounded run of the suite from any non-terminal story, without Suite: full, is rejected`; `prompts/plan_reuse.md`: `A story without a child ac block is rejected`.

## Recommendation

The per-story gate is the story's Blueprint Programmatic Acceptance, which is already the declared Definition of Done. `ac` blocks become optional orchestration checks only — process starts, port listens, container builds, artifact publishes — and an `ac` whose `check:` invokes a test runner without a selector is a plan defect unless its parent is the terminal `Suite: full` story. All three planning prompts and `MANIFEST_CONTRACT.md` are corrected to one rule.

## Stories

### Story 1: Single acceptance rule across the contracts

As the Commander, I want one stated rule for what gates a story, so that the planner is not asked to satisfy two incompatible ones.

**Acceptance Criteria**

- `MANIFEST_CONTRACT.md` states that a story is gated by concrete Programmatic Acceptance in the spec it implements, and that `ac` blocks are optional orchestration gates.
- `plan_create.md`, `plan_reuse.md`, and `plan_create_speckit.md` contain no rule requiring a child `ac` block.
- A repository test asserts that no prompt file contains the phrase `at least one child ac block`.

**Tests (RED first)**

- tests/test_prompt_contracts.py::test_no_prompt_requires_child_ac_block
- tests/test_prompt_contracts.py::test_manifest_contract_states_blueprint_gate

### Story 2: Story gate enforced from the Blueprint

As the Commander, I want a story with no real acceptance to be rejected at plan time, so that removing the ac requirement does not remove the gate.

**Acceptance Criteria**

- A story whose implemented spec has a bare `- None.` Programmatic Acceptance and any `Provides` entry yields admission defect `story-ungated`.
- A story whose implemented spec carries at least one non-demoted proof passes the gate with no `ac` block present.
- An `ac` block remains legal and continues to gate its parent when present.

**Tests (RED first)**

- tests/test_plan_admission.py::test_story_without_blueprint_acceptance_is_defect
- tests/test_plan_admission.py::test_story_with_blueprint_acceptance_needs_no_ac
- tests/test_build_plan.py::test_existing_ac_block_still_gates_parent

### Story 3: Reject unbounded suite runs in ac checks

As the Commander, I want an orchestration check that secretly runs the whole suite to be rejected, so that build time is not multiplied by story count.

**Acceptance Criteria**

- An `ac` whose `check:` invokes a known runner form without a selector, on a parent that is not the terminal `Suite: full` story, yields defect `ac-unbounded-suite`.
- The same `check:` on the terminal story is accepted.
- A selector-bounded runner invocation is accepted on any parent.

**Tests (RED first)**

- tests/test_plan_admission.py::test_unbounded_suite_ac_on_nonterminal_story_is_defect
- tests/test_plan_admission.py::test_unbounded_suite_ac_on_terminal_story_is_allowed
- tests/test_plan_admission.py::test_bounded_suite_ac_is_allowed

## Definition of Done

- Exactly one acceptance-gate rule exists across the Specification, `MANIFEST_CONTRACT.md`, and all planning prompts.
- Legacy Manifests with `ac` blocks continue to parse, execute, and gate unchanged.
- A newly generated plan for a five-story project runs the full test suite exactly once.

## Implementation Plan

1. Edit `prompts/MANIFEST_CONTRACT.md` Story section: replace the mandatory-ac paragraph with the Blueprint-gate rule; keep the `ac` block type documented as an orchestration gate.
2. Edit `prompts/plan_create.md` `Acceptance check blocks` section and Hard Rules; edit `prompts/plan_reuse.md` Manifest Rules; edit `prompts/plan_create_speckit.md` by reference.
3. Add admission checks `story-ungated` and `ac-unbounded-suite` in `drydock/plan_admission.py` (DDF-001).
4. Add a known-runner argv catalogue (pytest, unittest, node --test, go test, and the generic `run_suite` shape) with the selector flags that bound them, kept in one module constant.
5. Add `tests/test_prompt_contracts.py` asserting the prompt corpus no longer states the retired rule.

## Specification Impact

None — the Specification already declares `ac` legacy and Blueprint acceptance normative. This aligns the prompt contracts to it. The `Execution Rules` sentence `A story or spike cannot become closed/verified until its child ac blocks are closed/verified` remains true because it is conditional.

## Risks

- Existing Manifests that rely on the per-story ac smoke as their only real gate lose it when the spec's Programmatic Acceptance is weak — DDF-004's detectors must land first or coverage silently drops.
- The known-runner catalogue will not recognize custom runners; the check must fail open with a warning rather than block an unknown command.

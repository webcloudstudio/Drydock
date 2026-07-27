---
id: DDF-001
title: Enforce the plan contract deterministically with one bounded repair pass
area: drydock plan
impact: 10
complexity: 6
rank: 1
generated_at: 2026-07-26T20:31:43-04:00
review_model: claude-opus-5
source: drydock score drydock
---

# FEATURE DDF-001: Enforce the plan contract deterministically with one bounded repair pass

| Field | Value |
|---|---|
| Area | drydock plan |
| Impact | 10/10 |
| Complexity | 6/10 |
| Rank | 1 |
| Project Types | All, Web application, API service, CLI tool, Library |

## Problem

Every plan-integrity rule is prose addressed to the model that writes the plan. `plan_create.md` says a missing Sea Trial ID `rejects the plan`, a SCREEN acceptance that skips a route `is rejected`, an unbounded suite run from a non-terminal story `is rejected`, and a `parent:` naming an unemitted feature means `the plan is rejected` — but the emitting model is the only arbiter. Violations therefore surface as build-time failures or, worse, as a plan that builds successfully while proving nothing.

## Intent

Specification `Governance` — `drydock plan creates typed specifications with prescribed roles`, `Sealed foundational specifications require a change ticket`, and `Unknown references and missing required coverage invalidate a generated plan`.

## Evidence

`prompts/plan_create.md` Hard Rules and Manifest Construction Rules; `prompts/plan_reuse.md` (`A story without a child ac block is rejected`); `prompts/MANIFEST_CONTRACT.md` (`A plan that emits a story missing either gate is rejected`). None of these name an enforcing component; `planning_session.py` is described only as LLM-driven authoring.

## Recommendation

After parsing the emitted artifact blocks, `planning_session.py` runs a machine admission gate over the Blueprint plus Manifest. Each rule is a named check returning structured defects (rule id, block id, offending value, required correction). On failure the defect list is re-injected into exactly one bounded repair invocation; a second failure writes `PLAN_REJECTED.md` to the Target root, leaves the previous `MANIFEST.md` untouched, and exits non-zero. No plan reaches `drydock build` without passing the gate.

## Stories

### Story 1: Manifest graph admission checks

As the Commander, I want structural Manifest defects caught before the plan is written, so that a build never fails for a reason planning could have proven.

**Acceptance Criteria**

- A Manifest whose story `parent:` names an id with no emitted `feature` block yields defect `parent-unresolved` naming that story id.
- A Manifest with a `depends:` id that appears below the block naming it yields defect `depends-forward-reference`.
- A Manifest with no `story` or `spike` having an empty `depends:` yields defect `frontier-empty`.
- A Manifest where a `depends:` entry names an `ac` id yields defect `depends-on-ac` and the rewritten value is reported.
- A Manifest containing a `depends:` cycle yields defect `depends-cycle` listing the cycle members.
- A conformant Manifest yields zero defects.

**Tests (RED first)**

- tests/test_plan_admission.py::test_parent_unresolved_is_defect
- tests/test_plan_admission.py::test_forward_dependency_is_defect
- tests/test_plan_admission.py::test_empty_initial_frontier_is_defect
- tests/test_plan_admission.py::test_ac_id_in_depends_is_defect
- tests/test_plan_admission.py::test_dependency_cycle_is_defect
- tests/test_plan_admission.py::test_conformant_manifest_has_no_defects

### Story 2: Blueprint-to-Manifest correspondence checks

As the Commander, I want the story set and the Blueprint file set proven consistent, so that failure attribution and incremental rebuild remain intact.

**Acceptance Criteria**

- A story whose `implements:` names a file that is neither emitted nor already present in `blueprint/` yields defect `implements-missing`.
- An emitted Blueprint spec file implemented by zero stories yields defect `spec-unimplemented`.
- A spec file named by two stories' `implements:` yields defect `spec-double-implemented` listing both story ids.
- An `ANALYSIS.md` Story ID present in no story `covers:` yields defect `analysis-story-uncovered`; an ID present in two yields `analysis-story-double-covered`.
- A story whose `implements:` is `DATABASE.md` and whose `stack:` omits `persistence.md` or any backend stack file yields defect `persistence-stack-missing`.

**Tests (RED first)**

- tests/test_plan_admission.py::test_implements_missing_file_is_defect
- tests/test_plan_admission.py::test_unimplemented_spec_is_defect
- tests/test_plan_admission.py::test_double_implemented_spec_is_defect
- tests/test_plan_admission.py::test_uncovered_analysis_story_is_defect
- tests/test_plan_admission.py::test_database_story_requires_persistence_stack

### Story 3: Acceptance coverage checks

As the Commander, I want the plan's own acceptance rules mechanically checked, so that a plan cannot ship specs whose proofs skip what they declare.

**Acceptance Criteria**

- A SCREEN spec whose Programmatic Acceptance fences do not contain the literal path of every entry in its `Provides` and `Consumes` yields defect `screen-route-uncovered` naming each missing route.
- A FEATURE spec whose fences omit a literal route in its `Provides` yields defect `feature-route-uncovered`.
- A spec declaring any `Provides` entry whose Programmatic Acceptance is a bare `- None.` with no inline reason yields defect `acceptance-unjustified-none`.
- More than one proof in the Blueprint declaring `Suite: full` yields defect `suite-full-not-unique`.
- A `Suite: full` story that does not `depends:` on every other implementation story yields defect `terminal-story-incomplete-depends`.
- Every required `technical` or `behavioral` Sea Trial id absent from all `accepts:` fields and all `Sea Trials:` proof lines yields defect `sea-trial-untraced` naming the ids.

**Tests (RED first)**

- tests/test_plan_admission.py::test_screen_route_not_called_is_defect
- tests/test_plan_admission.py::test_feature_route_not_exercised_is_defect
- tests/test_plan_admission.py::test_bare_none_acceptance_with_provides_is_defect
- tests/test_plan_admission.py::test_multiple_suite_full_is_defect
- tests/test_plan_admission.py::test_terminal_story_missing_depends_is_defect
- tests/test_plan_admission.py::test_untraced_required_sea_trial_is_defect

### Story 4: Bounded structured repair round-trip

As the Commander, I want one automatic repair attempt with the exact defect list, so that a near-miss plan is fixed without a full re-plan and a hopeless plan stops instead of looping.

**Acceptance Criteria**

- A first-pass plan with defects triggers exactly one additional LLM invocation whose prompt contains every defect id and message.
- A repair pass that clears all defects writes `MANIFEST.md` and the Blueprint normally.
- A repair pass that still has defects writes `PLAN_REJECTED.md` containing the residual defect list, leaves any pre-existing `MANIFEST.md` byte-identical, and exits 1.
- Total LLM invocations for one `drydock plan` run never exceed two regardless of defect count.

**Tests (RED first)**

- tests/test_planning_session.py::test_repair_pass_invoked_once_with_defects
- tests/test_planning_session.py::test_repaired_plan_is_written
- tests/test_planning_session.py::test_second_failure_writes_plan_rejected_and_preserves_manifest
- tests/test_planning_session.py::test_invocation_count_capped_at_two

## Definition of Done

- Every `is rejected` sentence in `plan_create.md`, `plan_reuse.md`, `plan_create_speckit.md`, and `MANIFEST_CONTRACT.md` maps to a named check id in the admission gate, or is deleted from the prompt as unenforceable.
- `drydock plan` cannot write a Manifest that fails any admission check.
- The defect catalogue is documented in `prompts/MANIFEST_CONTRACT.md` with the check ids the prompts must satisfy.
- All admission tests pass and each was demonstrated failing against the pre-change code path.

## Implementation Plan

1. Create `drydock/plan_admission.py` exposing `check_plan(blueprint_files, manifest, analysis, sea_trials) -> list[Defect]` with `Defect(rule, block_id, detail, correction)`.
2. Port the rule catalogue from `prompts/plan_create.md` Hard Rules, Manifest Construction Rules, and `prompts/MANIFEST_CONTRACT.md` Field reference into named checks; reuse `build_plan.py` for Manifest parsing and `sea_trials.py` for criterion structure.
3. Implement route-literal coverage by scanning each spec's fenced `python` blocks for each declared route string; reuse the fence extraction already used by `acceptance.py`.
4. Wire the gate into `planning_session.py` between artifact-block parsing and file write; on defects, re-invoke the prompt with a rendered `## Plan Defects` section appended after the job block.
5. Add `PLAN_REJECTED.md` rendering and a QuarterDeck `markdown` page entry so the Commander sees the residual defects.
6. Add `tests/test_plan_admission.py` and `tests/test_planning_session.py` fixtures: one conformant plan and one deliberately defective plan per rule.

## Specification Impact

None required. The Specification already states that `Unknown references and missing required coverage invalidate a generated plan`; this makes that statement true. Optionally the `drydock plan` section gains a sentence naming the admission gate and the `PLAN_REJECTED.md` artifact.

## Risks

- Over-strict checks could reject usable plans on projects whose shape the rule authors did not anticipate — every check must name the block and the correction so the repair pass can act, and route-coverage checks must tolerate parameterized route templates.
- A plan that repeatedly fails now blocks the pipeline where it previously proceeded; this is intended but changes the operational experience and must be visible in `drydock status`.

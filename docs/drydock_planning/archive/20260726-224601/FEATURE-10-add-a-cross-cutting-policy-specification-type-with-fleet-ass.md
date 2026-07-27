---
id: DDF-010
title: Add a cross-cutting POLICY specification type with fleet assertions
area: drydock plan
impact: 8
complexity: 6
rank: 10
generated_at: 2026-07-26T20:31:43-04:00
review_model: claude-opus-5
source: drydock score drydock
---

# FEATURE DDF-010: Add a cross-cutting POLICY specification type with fleet assertions

| Field | Value |
|---|---|
| Area | drydock plan |
| Impact | 8/10 |
| Complexity | 6/10 |
| Rank | 10 |
| Project Types | Web application with authentication and sessions, REST / GraphQL API service, Multi-service system, Regulated products |

## Problem

Nothing owns an invariant that spans files. Authentication, authorization, tenancy isolation, PII handling, rate limiting, and audit logging are decomposed away by the per-route/per-screen rules, so the assertion `every protected route refuses an unauthenticated request` has no spec file, no story, and no story-level proof. Analyze surfaces the missing auth model as a questionnaire or a Sea Trial; a Sea Trial is judged at release, long after the code that would have satisfied it was written.

## Intent

Specification `Governance` — `drydock plan creates typed specifications with prescribed roles`; `analyze.md` Gap Checklist Security section (`Auth/authz model is named for any protected resource`).

## Evidence

`prompts/BLUEPRINTS_CONTRACT.md` Specification File Types table contains no cross-cutting policy type and its FileType values are `COMPASS, SCREEN, FEATURE, DATABASE, UI-GENERAL, ARCHITECTURE, HOMEPAGE, CHANGE`; `prompts/plan_create.md` decomposition table for `web` and `api` names no policy file.

## Recommendation

Introduce `POLICY-{Name}.md` (FileType `POLICY`) carrying the standard typed header plus an `Applies To` field holding selectors — route globs, module globs, or interface-point patterns. Its Programmatic Acceptance is a fleet assertion that enumerates the selected set from the Blueprint and asserts the invariant over every member, so adding a route automatically widens the proof. One story implements each policy file, consistent with the story/spec mapping. When analyze detects auth, tenancy, PII, or audit signals, plan must emit a matching POLICY file or the admission gate rejects the plan.

## Stories

### Story 1: POLICY file type in the contracts

As the Commander, I want a durable home for cross-cutting rules, so that security behavior is specified rather than assumed.

**Acceptance Criteria**

- `drydock validate` accepts a `# POLICY: {Name}` file with `Applies To` and the four terminal sections, and rejects one missing `Applies To`.
- `POLICY` appears in the FileType vocabulary in `BLUEPRINTS_CONTRACT.md` and in `plan_create.md`'s allowed list.
- A POLICY file participates in `Depends On` computation and may be named in a story's `implements:`.

**Tests (RED first)**

- tests/test_validate_specification.py::test_policy_file_validates
- tests/test_validate_specification.py::test_policy_without_applies_to_is_rejected
- tests/test_build_plan.py::test_story_can_implement_policy_file

### Story 2: Fleet assertion over a selector

As the Commander, I want a policy proof to cover every current member of its scope, so that a new route cannot silently escape the rule.

**Acceptance Criteria**

- A POLICY proof that resolves `Applies To: route:/admin/*` enumerates every matching route declared in the Blueprint's FEATURE `Provides` fields at run time.
- Adding a matching route to a FEATURE spec without changing the POLICY proof causes the proof to test the new route.
- A selector that matches zero members causes the proof to fail with `selector-empty` rather than pass vacuously.

**Tests (RED first)**

- tests/test_acceptance.py::test_policy_proof_enumerates_matching_routes
- tests/test_acceptance.py::test_new_route_is_covered_without_editing_policy
- tests/test_proof_integrity.py::test_empty_selector_policy_proof_fails

### Story 3: Policy requirement driven by analysis signals

As the Commander, I want a plan that ignores a detected security requirement to be rejected, so that the gap cannot be deferred to release scoring.

**Acceptance Criteria**

- `analyze.md` emits a `security_signals:` list in `ANALYSIS.md` Analysis Notes naming detected auth, tenancy, PII, or audit requirements.
- A plan whose analysis carries a security signal and emits no POLICY file yields admission defect `policy-missing` naming the signal.
- A plan with the matching POLICY file passes.

**Tests (RED first)**

- tests/test_analyze.py::test_security_signals_are_emitted
- tests/test_plan_admission.py::test_missing_policy_for_security_signal_is_defect
- tests/test_plan_admission.py::test_policy_present_passes_admission

## Definition of Done

- A web project with authentication produces a `POLICY-Authentication.md`, one implementing story, and a fleet proof over its protected routes.
- The Artifact I/O matrix and the Directory Layout include the POLICY type.
- The QuarterDeck renders POLICY files alongside other Typed Specifications.

## Implementation Plan

1. Add `POLICY` to the FileType vocabulary and the file-type table in `prompts/BLUEPRINTS_CONTRACT.md`, including the `Applies To` field definition and selector grammar (`route:`, `module:`, `symbol:`, `dataset:`, `topic:`).
2. Extend `validate_specification.py` with POLICY header rules.
3. Add a selector resolver in `drydock/policy_scope.py` that reads Blueprint `Provides` fields and returns the matching interface points; expose it to proofs as an importable helper staged like the Rigging templates.
4. Add the POLICY row to the `web`, `api`, and `event-driven` rows of the decomposition table in `prompts/plan_create.md` step 2 and to the Spec Kit prompt's decomposition reference.
5. Extend `prompts/analyze.md` Gap Checklist Security routing: a detected protected resource routes to a POLICY requirement recorded in `ANALYSIS.md`, not only to a questionnaire.
6. Add the `policy-missing` and `selector-empty` checks to `plan_admission.py` and `proof_integrity.py` respectively.

## Specification Impact

`SAIL Phase 2 — drydock plan` output table, the Directory Layout tree, the Artifact I/O Matrix, and the `Specification File Format` FileType list would need the author's approval to add POLICY.

## Risks

- A new file type expands the surface every prompt must understand; the three planning prompts, `plan_conform.md`, `document_generate.md`, and the QuarterDeck all need consistent handling or POLICY files become invisible.
- Fleet assertions couple a proof to the Blueprint at run time, which makes the proof sensitive to Blueprint parsing; the helper must fail loudly rather than silently returning an empty set.

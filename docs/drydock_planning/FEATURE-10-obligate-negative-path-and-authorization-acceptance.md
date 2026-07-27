---
id: DDF-011
title: Obligate negative-path and authorization acceptance
area: drydock plan
impact: 7
complexity: 5
rank: 10
generated_at: 2026-07-26T22:46:01-04:00
review_model: claude-opus-5
source: drydock score drydock
---

# FEATURE DDF-011: Obligate negative-path and authorization acceptance

| Field | Value |
|---|---|
| Area | drydock plan |
| Impact | 7/10 |
| Complexity | 5/10 |
| Rank | 10 |
| Project Types | Web application with authentication and sessions, REST and GraphQL API services, Multi-service systems, Mobile and desktop clients |

## Problem

The Gap Checklist asks whether an auth model is named, then has nowhere to put the answer: there is no typed file for an authorization matrix or session model, no header field declaring the auth state or roles an interface point requires, and no coverage obligation for the negative case. The strongest coverage rule Drydock has — SCREEN assertions must literally call every route and assert it 'returns the expected status' — is fully satisfied by one authenticated happy-path call. A product with sessions therefore ships with proofs that never exercise unauthenticated rejection, role denial, expired session, or invalid input, and `score release` has no signal that this is so.

## Intent

`Drydock_Specification.md` § Drydock Features > Governance ('Story Guardrails/AC are absolute prohibitions with a hard gate') and `prompts/analyze.md` Gap Checklist § Security ('Auth/authz model is named for any protected resource') and § Edge Cases ('Negative paths are addressed (invalid input, auth failure, not-found)').

## Evidence

`prompts/plan_create.md` step 5: 'assert a route responds ... for a route, that it is reachable and returns the expected status'; Hard Rules: 'A SCREEN spec's Programmatic Acceptance must literally call every route in its `Provides` and `Consumes`' — no negative obligation anywhere. `prompts/BLUEPRINTS_CONTRACT.md` § Specification File Types has no security file kind, and the SCREEN optional-field table has no `Auth` or `Roles` field.

## Recommendation

Add `Auth:` and `Roles:` declarations to interface points in FEATURE and SCREEN headers, and a `SECURITY.md` typed file holding the authorization matrix, session model, and secret-handling boundary — playing the role for authorization that `DATABASE.md` plays for persistence. The plan validator then requires, for every interface point declaring `Auth: required`, at least one assertion proving unauthenticated rejection and one per denied role; and for every point accepting input, at least one invalid-input rejection assertion. `score release` reports negative-path coverage as a named component of `acceptance_criteria_coverage`.

## Stories

### Story 1: Declare auth on interface points

As the Commander, I want each route or capability to declare whether it is protected and by which roles, so that protection is part of the specification rather than an implementation accident.

**Acceptance Criteria**

- A FEATURE or SCREEN header may declare `Auth: required | optional | none` and `Roles: <comma list>`.
- An interface point declaring `Roles` without `Auth: required` is a validation error.
- A project whose `SECURITY.md` names a role not referenced by any interface point is reported as unused-role spec debt.
- Blueprints declaring no `Auth` field validate unchanged.

**Tests (RED first)**

- test_auth_and_roles_fields_parse
- test_roles_without_auth_required_is_error
- test_unused_role_reported_as_spec_debt
- test_blueprint_without_auth_field_validates_unchanged

### Story 2: Add the SECURITY typed specification

As the Commander, I want an authorization matrix and session model in one typed file, so that security decisions are reviewable in one place.

**Acceptance Criteria**

- `SECURITY` is accepted as a FileType with required sections for the authorization matrix, session and token model, and the secret-handling boundary.
- `analyze.md`'s Security Gap Checklist rows route to `SECURITY.md` when the product has any protected resource.
- `plan_create.md`'s decomposition table names `SECURITY.md` for `web` and `api` shapes when the analysis reports any protected resource.
- `SECURITY.md` receives a compact derivative and is injected as context into stories implementing protected interface points.

**Tests (RED first)**

- test_security_filetype_accepted_with_required_sections
- test_analyze_routes_security_gaps_to_security_file
- test_decomposition_table_names_security_for_protected_products
- test_security_compact_injected_into_protected_stories

### Story 3: Enforce negative-path coverage

As the Commander, I want a protected route to be unbuildable without a proof that it rejects the wrong caller, so that authorization is proven, not assumed.

**Acceptance Criteria**

- A spec declaring `Auth: required` on a point is rejected unless an assertion calls that point without credentials and asserts a rejection status or exception.
- A spec declaring `Roles:` is rejected unless an assertion per denied role asserts rejection.
- A spec declaring any input-accepting point is rejected unless one assertion supplies invalid input and asserts a rejection.
- The rejection message names the interface point and the missing negative case.

**Tests (RED first)**

- test_protected_point_without_unauthenticated_proof_rejected
- test_roles_without_denial_proof_rejected
- test_input_point_without_invalid_input_proof_rejected
- test_rejection_message_names_point_and_missing_case

### Story 4: Score negative-path coverage

As the Commander, I want the release scorecard to show how much of the negative surface is proven, so that a green score cannot hide an untested authorization boundary.

**Acceptance Criteria**

- `score release` evidence facts include counts of protected points, points with unauthenticated proofs, and points with per-role denial proofs.
- `SCORECARD.md` reports negative-path coverage as a named line under `acceptance_criteria_coverage`.
- A project with zero protected points reports the component as not applicable rather than as zero.

**Tests (RED first)**

- test_release_facts_include_negative_path_counts
- test_scorecard_reports_negative_path_coverage
- test_no_protected_points_reports_not_applicable

## Definition of Done

- A web fixture with one protected route cannot pass planning without an unauthenticated-rejection assertion.
- `SECURITY.md` is generated for a fixture whose sources describe login, and its roles tie to interface points.
- `SCORECARD.md` shows negative-path coverage for that fixture.
- Unprotected projects are unaffected.

## Implementation Plan

1. Add `Auth` and `Roles` to the SCREEN and FEATURE header field tables in `prompts/BLUEPRINTS_CONTRACT.md` and to the parser in `validate_specification.py`.
2. Add the `SECURITY` FileType and its required sections to `BLUEPRINTS_CONTRACT.md` § Specification File Types and to `init_specification.py` templates and Rigging `spec_template/`.
3. Add Security routing rules to `prompts/analyze.md` § Gap Checklist and the decomposition rows in `prompts/plan_create.md` step 2.
4. Implement negative-path coverage checks in `acceptance.py`, surfaced through `validate_specification.py`.
5. Add the counts to the release evidence facts in `score.py` and the line to `SCORECARD.md` rendering.
6. Add fixtures: protected route with and without negative proofs, role-denial matrix, input-validation point.

## Specification Impact

§ SAIL Phase 2 output-file table and § Directory Layout (adds `SECURITY.md`), § Specification File Format (new header fields), and § drydock score (new scorecard component). Requires the author's approval.

## Risks

- Over-obligation will make simple internal tools expensive to plan; the rules must trigger only on declared protection.
- Negative proofs need the runtime contract from DDF-004 to exercise sessions and tokens reliably.
- A new typed file kind touches documentation generation, compaction, and QuarterDeck rendering.

# SURVEY-SPEC: drydock plan create

| Field       | Value |
|-------------|-------|
| Version     | 20260613 V1 |
| Description | Acceptance authority for `drydock plan create` — agile decomposition into MANIFEST.md. |
| Command     | drydock plan create |
| Scored In   | Survey/scores.jsonl |
| Source      | src/drydock/planning_session.py · prompts/plan_create.md · docs/SPEC_PLAN_CREATE.md |

## Goal

A user turns a ready Blueprint into an **executable, reviewable plan**: a `MANIFEST.md` of features,
stories, spikes, and acceptance checks, correctly ordered by dependency, prioritized for build,
sized for sprint planning, and gated so nothing runs until the product owner approves. The plan is
generated from the Blueprint — never a second product definition.

## Acceptance Criteria — Code

| ID | Criterion | Dim | Check | Weight | Verify |
|----|-----------|-----|-------|--------|--------|
| PLN-C1 | Hard gate: missing COMPASS.md or METADATA.md → exit 1, no MANIFEST written | D1 | A | 2 | remove file, assert |
| PLN-C2 | Writes `BUILD_PLAN_COMPASS.md` listing the ordered inputs | D1 | A | 2 | file exists + lists files |
| PLN-C3 | Writes `MANIFEST.md` with `state: draft` and a plan_hash | D1 | A | 2 | parse plan header |
| PLN-C4 | Each FEATURE-*.md yields ≥1 story; each story has ≥1 child `ac` | D1 | A | 3 | parse blocks |
| PLN-C5 | Each story carries `size:` ∈ {XS,S,M,L,XL} | D1 | A | 2 | parse blocks |
| PLN-C6 | DATABASE.md → Phase 1 foundation story (no parent, no depends) | D1 | A | 1 | block ordering |
| PLN-C7 | Each Open Question → a spike, ordered before dependent stories | D1 | A | 2 | spike count vs questions |

## Acceptance Criteria — Specification

| ID | Criterion | Dim | Check | Weight | Verify |
|----|-----------|-----|-------|--------|--------|
| PLN-D1 | All `id:` unique; all `depends:`/`parent:` resolve; all `state: pending` | D2 | A | 3 | graph validation |
| PLN-D2 | `implements:` files all exist in the Blueprint | D2 | A | 2 | path existence |
| PLN-D3 | AC mix per story: ≥1 `smoke` + ≥1 `assertion` (TDD up front) | D2 | A | 2 | parse ac kinds |
| PLN-D4 | Model emits block text; module writes the file (no model file-write) | D3 | A | 2 | write path is in module |
| PLN-D5 | Decomposition is sound: granularity, ordering, priority, no XL left unsplit | D2 | J | 3 | Scrum Master review (reviews/) |
| PLN-D6 | `plan_hash` matches injected spec content | D4 | A | 1 | recompute hash |

## Guardrails

- Plan create must not modify any Blueprint spec file.
- Re-running on an approved/partially-built plan must warn (re-approval required).
- Stack files come from Rigging injection, not hard-coded in the prompt.
- No API-key-backed provider; subscription CLI adapter only.
- An Open Question must surface as a spike — never be silently resolved by the planner.

## Open Questions

- If `ANALYSIS.md` is absent, does plan create proceed on deterministic defaults, or refuse until
  analyze has run? (Spec says warn-and-proceed; confirm that is the desired quality bar.)
- How are questionnaire answers in `BUILD_CONFIGURATION.md` validated before they steer the plan?

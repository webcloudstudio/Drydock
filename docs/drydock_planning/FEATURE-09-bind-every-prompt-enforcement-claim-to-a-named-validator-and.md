---
id: DDF-008
title: Bind every prompt enforcement claim to a named validator and a failing fixture
area: cross-cutting
impact: 7
complexity: 5
rank: 9
generated_at: 2026-07-26T22:46:01-04:00
review_model: claude-opus-5
source: drydock score drydock
---

# FEATURE DDF-008: Bind every prompt enforcement claim to a named validator and a failing fixture

| Field | Value |
|---|---|
| Area | cross-cutting |
| Impact | 7/10 |
| Complexity | 5/10 |
| Rank | 9 |
| Project Types | All |

## Problem

Prompts repeatedly promise deterministic rejection: raw-string control-character defects and unbound names are 'rejected at `drydock validate`', a SCREEN plan that skips a route 'is rejected', a missing Sea Trial ID 'rejects the plan', an unbounded suite run without `Suite: full` 'is rejected', a stack question in the Sea Trials QUESTIONS block is 'dropped', analysis with non-conforming EARS wording is 'rejected'. Nothing ties any of these sentences to a check. Where a claim is unbacked, the prompt teaches the model that a rule is policed when it is not — the precise condition under which models relax a rule — and the Commander has no way to tell a live guardrail from a decorative one.

## Intent

`Drydock_Specification.md` § Governance ('Story Guardrails/AC are absolute prohibitions with a hard gate') and § What is Drydock ('Trust But Verify').

## Evidence

`prompts/BLUEPRINTS_CONTRACT.md`: 'Drydock rejects this defect at `drydock validate` and blocks the build before the step runs' and 'Drydock rejects an unparseable snippet, and a snippet reading an unbound name'. `prompts/plan_create.md`: 'a plan whose SCREEN acceptance skips a route is rejected', 'A missing ID rejects the plan', 'An unbounded run of the suite from any non-terminal story, without `Suite: full`, is rejected'. `prompts/analyze.md`: 'Drydock rejects the analysis when the wording does not match' and 'Drydock drops any stack/Rigging question found in the Sea Trials QUESTIONS block'. The module inventory shows `validate_specification.py` and `proof_integrity.py` but nothing mapping claims to checks.

## Recommendation

An invariant registry. Each enforcement sentence in a prompt carries an id (`... is rejected (INV-014).`). `prompts/INVARIANTS.md` maps each id to the module and function that enforces it and to a fixture the validator must reject. A test asserts that every id referenced in any prompt exists in the registry, has a resolvable validator, and rejects its fixture — and that every registry entry is referenced by at least one prompt. Unbacked claims are then either implemented or deleted from the prompt.

## Stories

### Story 1: Create the invariant registry

As the Commander, I want every enforcement claim to name its enforcer, so that I know which guardrails are real.

**Acceptance Criteria**

- `prompts/INVARIANTS.md` lists id, claim text, enforcing module and function, fixture path, and status for every invariant.
- Each registry id resolves to an importable callable.
- Each registry entry names a fixture path that exists.

**Tests (RED first)**

- test_invariant_registry_rows_wellformed
- test_every_invariant_id_resolves_to_callable
- test_every_invariant_fixture_path_exists

### Story 2: Prove each invariant with a negative fixture

As the Commander, I want each guardrail proven against an artifact it must refuse, so that a claim cannot pass by asserting itself.

**Acceptance Criteria**

- For every registry entry, the named validator rejects the named fixture with a non-zero result and a message naming the invariant id.
- For every registry entry, the validator accepts a matching positive fixture.
- A registry entry with status `unenforced` fails the test suite unless the prompt sentence has been rewritten to drop the enforcement claim.

**Tests (RED first)**

- test_each_invariant_rejects_its_negative_fixture
- test_each_invariant_accepts_its_positive_fixture
- test_unenforced_invariant_fails_unless_claim_removed

### Story 3: Require ids on enforcement sentences

As the Commander, I want a new prompt sentence claiming rejection to fail CI unless it names an invariant, so that the registry cannot rot.

**Acceptance Criteria**

- A prompt sentence containing `rejects`, `is rejected`, `blocks the build`, or `drops` without a parenthesized invariant id fails validation, naming the prompt and the line.
- A registry id referenced by no prompt fails validation as dead.
- The check runs as part of `drydock prompt validate`.

**Tests (RED first)**

- test_unlabelled_enforcement_sentence_fails_validation
- test_orphan_registry_entry_fails_as_dead
- test_invariant_check_runs_under_prompt_validate

## Definition of Done

- Every enforcement sentence currently in the shipped prompts is either backed by a proven validator or rewritten to drop the claim.
- The registry, the fixtures, and the tests run in CI.
- A newly added unbacked claim fails CI.

## Implementation Plan

1. Audit `BLUEPRINTS_CONTRACT.md`, `MANIFEST_CONTRACT.md`, `plan_create.md`, `plan_reuse.md`, `plan_create_speckit.md`, `analyze.md`, and `build.md` for enforcement sentences and enumerate them.
2. Create `prompts/INVARIANTS.md` with the enumerated ids and current status.
3. Implement or locate each validator in `validate_specification.py`, `proof_integrity.py`, `acceptance.py`, `sea_trials.py`, and `planning_session.py`; ensure each raises with its invariant id in the message.
4. Add positive and negative fixtures per invariant under `tests/fixtures/invariants/INV-XXX/`.
5. Extend the `drydock prompt validate` gate from DDF-007 with the id-labelling and registry checks.
6. Delete or rewrite prompt sentences whose claims cannot be backed.

## Specification Impact

none — this is internal governance of prompt text and validators.

## Risks

- The audit will find claims that are genuinely unenforced, and removing them weakens the prompts before the validators land; sequence removal after implementation.
- Invariant ids inside prompt prose add noise to text that is already dense.
- A naive sentence-matching rule will fire on prose that discusses rejection without claiming it.

---
id: DDF-006
title: Bind every required guardrail Sea Trial to a deterministic negative check
area: drydock score
impact: 8
complexity: 4
rank: 7
generated_at: 2026-07-26T20:31:43-04:00
review_model: claude-opus-5
source: drydock score drydock
---

# FEATURE DDF-006: Bind every required guardrail Sea Trial to a deterministic negative check

| Field | Value |
|---|---|
| Area | drydock score |
| Impact | 8/10 |
| Complexity | 4/10 |
| Rank | 7 |
| Project Types | Web application with authentication, Infrastructure as code, Regulated / compliance-bound products, Library |

## Problem

Guardrail Sea Trials are explicitly exempted from planning coverage — `Guardrails require no story or proof reference` — while `score_release.md` returns INCONCLUSIVE for any guardrail with no positive evidence, which Drydock reports as UNPROVEN and which `fails the gate exactly as a breach does`. A plan that follows the contract exactly therefore cannot pass release scoring, and the strongest governance construct in the system is the one guaranteed to be unproven.

## Intent

Specification `Verification` — `Story Guardrails/AC are absolute prohibitions with a hard gate` and `Project Guardrails/AC validated using drydock score release`.

## Evidence

Specification `Story Blocks`: `Guardrails require no story or proof reference.` versus `prompts/score_release.md`: `Return PASS only when the supplied evidence positively shows the prohibition held; absent evidence is INCONCLUSIVE, which Drydock reports as UNPROVEN and which fails the gate exactly as a breach does.`

## Recommendation

Every `Required: yes` guardrail Sea Trial must be bound at plan time to at least one deterministic negative check — a Blueprint proof carrying `Sea Trials: st-XXX` that asserts the prohibited condition does not occur, or a repository-scan check with a declared scope. The admission gate rejects an unbound required guardrail. Rigging ships reusable scan proof templates so binding is cheap. `Required: no` guardrails remain advisory and report UNPROVEN without failing the gate.

## Stories

### Story 1: Guardrail binding requirement

As the Commander, I want a required prohibition to be provable before the build starts, so that release scoring is not decided by absence of evidence.

**Acceptance Criteria**

- A `SEA_TRIALS.md` guardrail with `Required: yes` and no proof carrying its id in a `Sea Trials:` line, and no `ac` bound to it, yields admission defect `guardrail-unbound`.
- The same guardrail bound to one Blueprint proof passes admission.
- A `Required: no` guardrail with no binding does not produce a defect.

**Tests (RED first)**

- tests/test_plan_admission.py::test_unbound_required_guardrail_is_defect
- tests/test_plan_admission.py::test_bound_guardrail_passes_admission
- tests/test_plan_admission.py::test_optional_guardrail_needs_no_binding

### Story 2: Reusable guardrail scan templates in Rigging

As the Commander, I want a standard way to prove a prohibition, so that guardrail binding does not require bespoke test authoring each time.

**Acceptance Criteria**

- `Rigging/templates/guardrail_scan.py` scans a declared root for a declared pattern, honors the exclusion scope stated in `build.md` (`.venv/`, `site-packages`, vendored and generated code), and exits non-zero on a match.
- A guardrail proof built from the template on a clean tree exits zero; on a tree with a planted violation it exits non-zero and prints the offending path and line.
- The template is registered in `Rigging/MANIFEST.md` and is not compacted away.

**Tests (RED first)**

- tests/test_rigging_templates.py::test_guardrail_scan_clean_tree_exits_zero
- tests/test_rigging_templates.py::test_guardrail_scan_reports_violation_path
- tests/test_rigging_templates.py::test_guardrail_scan_excludes_vendored_paths

### Story 3: Guardrail verdicts computed deterministically

As the Commander, I want a guardrail's verdict to come from its bound check, not from model judgment, so that HELD means something.

**Acceptance Criteria**

- A guardrail whose bound proof passed is reported HELD without consulting the release model's verdict for that id.
- A guardrail whose bound proof failed is reported BREACHED and the release gate fails.
- A guardrail whose bound proof was demoted to UNVERIFIED is reported UNPROVEN with the demotion reason code.
- `SCORECARD.md` names the bound check id next to every guardrail verdict.

**Tests (RED first)**

- tests/test_score.py::test_guardrail_verdict_from_bound_proof_held
- tests/test_score.py::test_guardrail_verdict_from_bound_proof_breached
- tests/test_score.py::test_demoted_guardrail_proof_reports_unproven
- tests/test_score.py::test_scorecard_names_bound_check_id

## Definition of Done

- No Target can reach `drydock score release` with an unbound required guardrail.
- Guardrail verdicts are deterministic where a binding exists, and the release prompt's guardrail paragraph is narrowed to unbindable qualitative prohibitions only.
- `analyze.md` guardrail authoring guidance names the binding requirement so guardrails are proposed in provable form.

## Implementation Plan

1. Extend `sea_trials.py` to expose bindings: for each criterion id, the proofs and `ac` blocks that reference it.
2. Add the `guardrail-unbound` check to `drydock/plan_admission.py`.
3. Add `Rigging/templates/guardrail_scan.py` and register it in `Rigging/MANIFEST.md`; reference it from `prompts/plan_create.md` step 5 as the default guardrail proof shape.
4. In `score.py`, compute guardrail verdicts from bound-check results before assembling the release fact bundle, and pass only unbindable guardrails to the model.
5. Update `prompts/score_release.md` and `prompts/build_score.md` guardrail paragraphs to cover only criteria Drydock did not settle deterministically.
6. Update `prompts/analyze.md` guardrail rules to require a prohibition stated in a form a scan or proof can test.

## Specification Impact

The `Story Blocks` sentence `Guardrails require no story or proof reference` would need the author's approval to become `required guardrails must be bound to a deterministic negative check`. The `drydock score release` section gains the deterministic guardrail path.

## Risks

- Some genuine prohibitions are not statically scannable (`never store PII in logs` across a running system); the rule must accept a runtime proof or allow `Required: no` rather than forcing a fake scan.
- Scan-based guardrails create false positives on test doubles and fixtures; the template's exclusion scope must match the rule already stated in `build.md` step 5.

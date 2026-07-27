---
id: DDF-004
title: Detect the vacuous proofs that actually occur
area: drydock score
impact: 9
complexity: 5
rank: 3
generated_at: 2026-07-26T20:31:43-04:00
review_model: claude-opus-5
source: drydock score drydock
---

# FEATURE DDF-004: Detect the vacuous proofs that actually occur

| Field | Value |
|---|---|
| Area | drydock score |
| Impact | 9/10 |
| Complexity | 5/10 |
| Rank | 3 |
| Project Types | All |

## Problem

Proof integrity demotes only an empty body, a constant assertion, or a self-comparison. The forms a build agent actually produces under pressure — asserting a file exists, importing a module and asserting nothing, running a subprocess and discarding its result, grepping the source file for its own string literal — all score PASS and lift the release verdict. `BLUEPRINTS_CONTRACT.md` warns against exactly these in prose and nothing checks them.

## Intent

Specification glossary `Proof integrity` — `Static analysis that demotes a vacuous or tautological acceptance proof to UNVERIFIED, so a passing test cannot lift the score without actually proving behavior`.

## Evidence

Specification `drydock score`: `Criteria with vacuous proof — an empty body, a constant assertion, or a self-comparison — is demoted`. `prompts/BLUEPRINTS_CONTRACT.md`: `Naming the suite file or asserting it is staged (Path(...).is_file()) is staging, not testing` — a rule with no enforcing analyzer.

## Recommendation

Extend `proof_integrity.py` with named semantic detectors, each producing a reason code recorded in `SOUNDINGS.md`: `existence-only`, `import-only`, `unasserted-subprocess`, `source-text-tautology`, `no-call-expression`, `bounded-suite-claiming-full`. A proof matching any detector is UNVERIFIED regardless of exit status, and `build_quality` facts carry the per-code counts.

## Stories

### Story 1: Existence-only and import-only detectors

As the Commander, I want a proof that only checks a file or import to be UNVERIFIED, so that staging cannot masquerade as testing.

**Acceptance Criteria**

- A proof whose every assertion operand derives from `Path(...).is_file`, `Path(...).exists`, `os.path.exists`, `os.listdir`, or `glob` is demoted with reason `existence-only`.
- A proof containing only import statements and assertions on module truthiness is demoted with reason `import-only`.
- A proof that asserts a file exists AND asserts a behavior on its contents is not demoted.

**Tests (RED first)**

- tests/test_proof_integrity.py::test_path_is_file_only_is_existence_only
- tests/test_proof_integrity.py::test_import_without_exercise_is_import_only
- tests/test_proof_integrity.py::test_existence_plus_behavior_is_not_demoted

### Story 2: Subprocess and tautology detectors

As the Commander, I want proofs that run a command without judging it, or that assert the source says what it says, to be UNVERIFIED.

**Acceptance Criteria**

- A proof calling `subprocess.run`/`check_output` with no assertion referencing `returncode`, `stdout`, or `stderr` is demoted with reason `unasserted-subprocess`.
- A proof whose assertion tests a string literal membership in text read from a path under the project's own source tree is demoted with reason `source-text-tautology`.
- A proof with no call expression other than imports is demoted with reason `no-call-expression`.
- A proof declaring `Suite: full` whose runner argv contains a `--pattern`, `--number`, `--sections`, or `-k` selector is demoted with reason `bounded-suite-claiming-full`.

**Tests (RED first)**

- tests/test_proof_integrity.py::test_subprocess_without_result_assertion_is_demoted
- tests/test_proof_integrity.py::test_source_grep_tautology_is_demoted
- tests/test_proof_integrity.py::test_no_call_expression_is_demoted
- tests/test_proof_integrity.py::test_selector_bounded_suite_full_is_demoted

### Story 3: Reason codes surfaced to the Commander and the scorer

As the Commander, I want to see why a proof was demoted, so that I can fix the acceptance rather than guess.

**Acceptance Criteria**

- `SOUNDINGS.md` records `— UNVERIFIED (<reason-code>)` for each demoted criterion.
- The score fact bundle includes a count per reason code and the demoted check ids.
- `drydock validate` reports the same demotions at authoring time, before the plan is built.

**Tests (RED first)**

- tests/test_score.py::test_soundings_records_demotion_reason_code
- tests/test_score.py::test_score_facts_include_reason_code_counts
- tests/test_validate_specification.py::test_validate_reports_vacuous_proof_reasons

## Definition of Done

- Each detector has a positive and a negative fixture and neither fires on the Drydock corpus's legitimate proofs.
- Demotion reason codes appear in `SOUNDINGS.md`, `drydock validate` output, and the score facts.
- `prompts/BLUEPRINTS_CONTRACT.md` names each detector so authoring agents know the bar.

## Implementation Plan

1. Add an AST visitor per detector in `proof_integrity.py`, returning `(demoted, reason_code)` and keeping the existing three checks intact.
2. Define the reason-code vocabulary in one module constant and reference it from `score.py`, `validate_specification.py`, and the SOUNDINGS writer.
3. Extend `acceptance.py` so a demotion overrides a PASS exit status when writing the criterion result.
4. Add the counts to the fact bundle for `prompts/score_release.md` under `build_quality`.
5. Document the detector list in `prompts/BLUEPRINTS_CONTRACT.md` Programmatic Acceptance section, replacing the current prose warning.
6. Build `tests/test_proof_integrity.py` fixtures: one demoted and one legitimate proof per reason code.

## Specification Impact

The `drydock score` paragraph enumerating the three vacuity forms, and the glossary `Proof integrity` entry, would need the author's approval to list the expanded detector set.

## Risks

- False positives on legitimate staging checks — a story whose whole job is to stage an asset genuinely has an existence proof; the detector must allow an inline-justified `Vacuity: allowed — staging story` marker parallel to DDF-003's exemption.
- Demoting previously-passing criteria will lower scores on existing Targets, which will look like a regression until the acceptance is strengthened.

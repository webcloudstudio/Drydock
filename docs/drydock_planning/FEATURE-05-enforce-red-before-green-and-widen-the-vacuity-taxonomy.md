---
id: DDF-005
title: Enforce RED before GREEN and widen the vacuity taxonomy
area: drydock build
impact: 8
complexity: 5
rank: 5
generated_at: 2026-07-26T22:46:01-04:00
review_model: claude-opus-5
source: drydock score drydock
---

# FEATURE DDF-005: Enforce RED before GREEN and widen the vacuity taxonomy

| Field | Value |
|---|---|
| Area | drydock build |
| Impact | 8/10 |
| Complexity | 5/10 |
| Rank | 5 |
| Project Types | All, Especially machine learning and analytics, where a distributional criterion is easily replaced with a non-discriminating one |

## Problem

The specification advertises 'Pre-Build RED->GREEN enforcement' as a feature, then states in its Execution Rules that the pre-build observation 'does not block the build' and that a story whose proof passes pre-build 'does not fail for that reason alone'. The declared vacuity taxonomy — empty body, constant assertion, self-comparison — passes `assert result is not None`, `assert len(items) >= 0`, `assert isinstance(x, str)`, and any check that only asserts a file exists. Because the build agent writes the implementation and the tests that prove it in the same step, a story can close on acceptance that was already green before a line was written.

## Intent

`Drydock_Specification.md` § Drydock Features > Verification: 'Pre-Build RED->GREEN enforcement - Vacuous and unneeded AC are demoted'; Glossary § Proof integrity: 'so a passing test cannot lift the score without actually proving behavior'.

## Evidence

`Drydock_Specification.md` § Execution Rules: 'Drydock may run the same `Programmatic Acceptance` before the build as an observation. A proof that already passes is recorded as `GREEN (prepassed)` or `GREEN (vacuous)`. This does not block the build.' `prompts/BLUEPRINTS_CONTRACT.md` names existence-style staging as a defect ('Naming the suite file or asserting it is staged (`Path(...).is_file()`) is staging, not testing') but the enumerated demotion rules in `Drydock_Specification.md` § drydock score do not cover it.

## Recommendation

On a story's first build, a check that passes pre-build is blocking unless it declares `Prepass: <reason>`; on a refit rebuild of an already-closed story, prepass is expected, recorded, and non-blocking. Extend the vacuity taxonomy to existence-only assertions, non-discriminating predicates (`is not None`, `>= 0`, bare `isinstance`, truthiness of a literal-bearing expression), and checks that reference no symbol, route, or interface point the spec declares in `Provides`. Record `pre:` alongside the post verdict in `SOUNDINGS.md`.

## Stories

### Story 1: Block on unjustified prepass at first build

As the Commander, I want a story whose acceptance was already green to stop before it builds, so that Definition of Done means something was proven.

**Acceptance Criteria**

- A story in state `pending` that has never been built halts with a named error when any of its checks passes pre-build and lacks a `Prepass:` line.
- A check carrying `Prepass: <non-empty reason>` is recorded GREEN-prepassed-justified and does not halt the build.
- A rebuild of a story previously `closed/verified` records prepass without halting.
- The halt message names each prepassing check id and the exact remedy.

**Tests (RED first)**

- test_first_build_halts_on_unjustified_prepass
- test_prepass_with_reason_does_not_halt
- test_refit_rebuild_prepass_does_not_halt
- test_prepass_halt_message_names_check_ids

### Story 2: Widen the vacuity taxonomy

As the Commander, I want proofs that cannot distinguish a stub from an implementation to be demoted, so that the score is not lifted by decorative assertions.

**Acceptance Criteria**

- A check whose only assertion is a filesystem existence test is classified UNVERIFIED-vacuous.
- A check whose only assertions are `is not None`, a `>= 0` length comparison, or a bare `isinstance` is classified UNVERIFIED-vacuous.
- A check that names no identifier appearing in its spec's `Provides` and performs no subprocess invocation is flagged unbound-to-surface.
- A check asserting a concrete value, status code, or exception type is not demoted by any of the above rules.

**Tests (RED first)**

- test_existence_only_assertion_demoted
- test_non_discriminating_predicates_demoted
- test_check_unbound_to_provides_surface_flagged
- test_concrete_value_assertions_not_demoted

### Story 3: Record the pre-build verdict in SOUNDINGS.md

As the Commander, I want to see which proofs never went red, so that I can judge which parts of the build were actually driven by tests.

**Acceptance Criteria**

- Each `SOUNDINGS.md` criterion row carries a `pre:` value of RED, GREEN, GREEN-justified, or VACUOUS alongside its post verdict.
- `score release`'s `test_coverage` evidence facts include the count of criteria whose `pre:` was not RED.
- The QuarterDeck Soundings artifact renders the pre-build column.

**Tests (RED first)**

- test_soundings_row_carries_pre_verdict
- test_release_facts_include_non_red_prebuild_count
- test_quarterdeck_soundings_renders_pre_column

## Definition of Done

- A fixture story whose spec asserts only file existence cannot close.
- A fixture story whose proof passes against an empty build directory halts with a named remedy.
- The specification's advertised RED-to-GREEN enforcement is backed by a named check with a negative fixture.
- Refit rebuild paths are demonstrably unaffected.

## Implementation Plan

1. Extend `proof_integrity.py` with the widened taxonomy, each rule implemented as a named AST predicate with its own fixture.
2. Add the prepass gate to `build_run.py` before the build call, reading prior story state from `build_plan.py` to distinguish first build from rebuild.
3. Add the `Prepass:` heading-block line to the check parser in `acceptance.py` and document it in `prompts/BLUEPRINTS_CONTRACT.md`.
4. Add the `pre:` column to `SOUNDINGS.md` generation in `score.py` and `standard_artifacts.py`.
5. Add the non-RED count to the evidence facts consumed by `prompts/score_release.md`.
6. Add fixtures: existence-only check, is-not-None check, prepassing check without reason, prepassing check with reason, genuinely red check.

## Specification Impact

§ Execution Rules ('This does not block the build' becomes conditional) and § drydock score (demotion rule list). Requires the author's approval.

## Risks

- Legitimate regression-guard checks and cross-story invariants will prepass; the `Prepass:` escape must be discoverable or builds will halt spuriously.
- An over-eager unbound-to-surface rule will demote valid integration checks that exercise a surface indirectly.
- Halting at first build changes the failure profile of every existing Target on its next run.

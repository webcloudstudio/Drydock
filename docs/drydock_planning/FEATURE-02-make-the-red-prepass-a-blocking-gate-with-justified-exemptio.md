---
id: DDF-003
title: Make the RED prepass a blocking gate with justified exemptions
area: drydock build
impact: 9
complexity: 5
rank: 2
generated_at: 2026-07-26T20:31:43-04:00
review_model: claude-opus-5
source: drydock score drydock
---

# FEATURE DDF-003: Make the RED prepass a blocking gate with justified exemptions

| Field | Value |
|---|---|
| Area | drydock build |
| Impact | 9/10 |
| Complexity | 5/10 |
| Rank | 2 |
| Project Types | All, Legacy brownfield modernization |

## Problem

Drydock advertises `Pre-Build RED->GREEN enforcement` but the Execution Rules state a pre-passing proof `does not block the build` and is merely `marked as weak evidence`. A story whose Definition of Done is already green before any code exists is not proving that story, yet it closes `closed/verified` on the same terms as a real one. The advertised discipline is an observation.

## Intent

Specification `Verification` — `Pre-Build RED->GREEN enforcement - Vacuous and unneeded AC are demoted`; and `The Blueprint's Programmatic Acceptance is the story's Definition of Done — declared before the build`.

## Evidence

Specification Execution Rules: `Drydock may run the same Programmatic Acceptance before the build as an observation. A proof that already passes is recorded as GREEN (prepassed) or GREEN (vacuous). This does not block the build.` and `A story whose proof passes before the build is marked as weak evidence and does not fail for that reason alone.`

## Recommendation

Before the LLM invocation, `build_run.py` runs every declared proof for the block. Each must be RED, or carry `Prepass: green-allowed — <reason>` in its heading block. An unjustified GREEN proof halts the block before any tokens are spent, records the offending check ids, and raises a QuarterDeck action item directing the Commander to strengthen the acceptance or justify the exemption. Justified exemptions are counted and reported by `drydock score release`.

## Stories

### Story 1: Blocking prepass verdict

As the Commander, I want a story whose acceptance already passes to stop before the build, so that no story closes on a proof that never went red.

**Acceptance Criteria**

- A block whose declared proofs include one passing check with no `Prepass:` line does not invoke the LLM and exits non-zero.
- The halt writes an evidence record naming each prepass-green check id and its spec file.
- A block whose proofs all fail at prepass proceeds to the LLM invocation unchanged.
- Prepass execution never writes to the build directory beyond the temp script location.

**Tests (RED first)**

- tests/test_build_run.py::test_unjustified_prepass_green_halts_before_llm
- tests/test_build_run.py::test_prepass_halt_records_offending_check_ids
- tests/test_build_run.py::test_all_red_prepass_proceeds
- tests/test_build_run.py::test_prepass_does_not_mutate_build_directory

### Story 2: Justified green exemption

As the Commander, I want to declare when a proof legitimately passes before a build, so that refits and invariant checks are not blocked by the gate.

**Acceptance Criteria**

- A proof carrying `Prepass: green-allowed — pre-existing invariant asserted by refit` passes the gate and the build proceeds.
- A `Prepass: green-allowed` line with no reason text after the dash is rejected by `drydock validate`.
- The exemption count per Target is written into the score facts and reported in `SCORECARD.md`.

**Tests (RED first)**

- tests/test_build_run.py::test_justified_green_exemption_proceeds
- tests/test_validate_specification.py::test_prepass_exemption_requires_reason
- tests/test_score.py::test_exemption_count_appears_in_score_facts

### Story 3: Prepass results feed the acceptance score

As the Commander, I want prepass outcomes visible in scoring, so that weak acceptance lowers the release verdict instead of hiding.

**Acceptance Criteria**

- `test_coverage` facts supplied to `score_release.md` include counts of proofs that were RED at prepass, GREEN-exempt, and never prepassed.
- `SOUNDINGS.md` records a prepass column per criterion.
- A Target where more than a configurable fraction of proofs were GREEN-exempt is reported as a named release warning.

**Tests (RED first)**

- tests/test_score.py::test_soundings_records_prepass_column
- tests/test_score.py::test_prepass_facts_are_supplied_to_release_prompt
- tests/test_score.py::test_high_exemption_ratio_raises_release_warning

## Definition of Done

- No story can reach `closed/verified` on a proof that was green before its build and carries no justification.
- Prepass state is durable in `SOUNDINGS.md` and the score facts.
- The Specification's Execution Rules and the Verification feature list agree with the implemented behavior.

## Implementation Plan

1. Extend the proof heading parser to accept `Prepass: green-allowed — <reason>`.
2. In `build_run.py`, run the block's proofs through `acceptance.py` before prompt assembly; classify each as RED, GREEN-exempt, or GREEN-unjustified.
3. Halt on any GREEN-unjustified: write the evidence file, append a QuarterDeck action item through `standard_artifacts.py`, and exit with the blocked status `drydock status --check` already defines.
4. Persist prepass classification per criterion in `SOUNDINGS.md` via `score.py`, and add the counts to the fact bundle assembled for `prompts/score_release.md`.
5. Update `prompts/BLUEPRINTS_CONTRACT.md` (Programmatic Acceptance section) and `prompts/plan_create.md` step 5 to describe when a `Prepass:` exemption is legitimate.
6. Add tests in `tests/test_build_run.py`, `tests/test_validate_specification.py`, and `tests/test_score.py`.

## Specification Impact

The `Execution Rules` sentences `This does not block the build` and `does not fail for that reason alone` would need the author's approval to change, as would the glossary entry for proof integrity. The Verification feature bullet already claims this behavior.

## Risks

- Brownfield adoption and refit runs legitimately start green and will now require exemptions at scale — DDF-012's baseline pass must land alongside or the gate becomes an obstacle.
- Prepass execution costs wall-clock time on every block; proofs that start services or touch the network must be bounded by the same timeout policy the post-build run uses.

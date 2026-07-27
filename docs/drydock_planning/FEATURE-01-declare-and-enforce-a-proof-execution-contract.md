---
id: DDF-004
title: Declare and enforce a proof execution contract
area: drydock score
impact: 9
complexity: 6
rank: 1
generated_at: 2026-07-26T22:46:01-04:00
review_model: claude-opus-5
source: drydock score drydock
---

# FEATURE DDF-004: Declare and enforce a proof execution contract

| Field | Value |
|---|---|
| Area | drydock score |
| Impact | 9/10 |
| Complexity | 6/10 |
| Rank | 1 |
| Project Types | Web application with authentication and sessions, REST and GraphQL API services, Event-driven and streaming systems, Data pipeline / ETL, Multi-service systems |

## Problem

`BLUEPRINTS_CONTRACT.md` states each fenced check is written to its own script and run in its own process from the build directory, sharing no imports, variables, or order. It never says what exists around the check: no environment, no service lifecycle, no port allocation, no fixture, no working-directory isolation, no timeout, no teardown. Yet plan_create requires SCREEN proofs to literally call every route, which needs a running application. Two proofs that each bind a fixed port collide; a proof that writes a database file pollutes the next; a hung server hangs `score ac`. `score ac` then reports a bare FAIL or UNVERIFIED without distinguishing 'behavior is wrong' from 'the check could never run' — so a project can score badly for reasons that have nothing to do with the software.

## Intent

`Drydock_Specification.md` § drydock score ('verifies acceptance deterministically, with no LLM call by running the acceptance criterion') and Glossary § Proof integrity ('so a passing test cannot lift the score without actually proving behavior') — which has no counterpart for proofs that never execute.

## Evidence

`prompts/BLUEPRINTS_CONTRACT.md`: 'Drydock writes each fenced block to its own script and runs it in its own process from the build directory. Checks in the same file share no imports, no variables, and no execution order.' `prompts/plan_create.md` mentions a suite timeout exactly once — 'declares `Suite: scoped` on its own line so the check receives the suite timeout' — with no contract defining it, and requires SCREEN assertions to 'literally call every route'.

## Recommendation

Add a runtime declaration block to each check — `Needs:` (named services), `Timeout:` (seconds), `Env:` (key=value) — and a Drydock-owned runner that allocates a free port into a documented environment variable, runs each check in a per-check temporary working directory seeded from the build directory, enforces the timeout, tears down services, and records a typed outcome: PASS, FAIL, ERROR-import, ERROR-timeout, ERROR-setup, or UNVERIFIED-vacuous. `SOUNDINGS.md` records the class; `score release` scores 'proved false' differently from 'never ran'.

## Stories

### Story 1: Declare the runtime block in the Blueprint contract

As the Commander, I want a check to declare what it needs to run, so that a proof requiring a live service is not silently unverifiable.

**Acceptance Criteria**

- A check heading block may carry `Needs:`, `Timeout:`, and `Env:` lines between the intent sentence and the fenced block, in any order.
- A `Timeout:` value that is not a positive integer is a validation error naming the check id.
- A `Needs:` entry naming a service not defined in `ARCHITECTURE.md` or the runtime registry is a validation error.
- Absent lines resolve to documented defaults and are recorded as defaults in the run record.

**Tests (RED first)**

- test_runtime_block_parses_in_any_order
- test_non_integer_timeout_is_error_naming_check
- test_unknown_needs_service_is_error
- test_absent_runtime_lines_resolve_to_recorded_defaults

### Story 2: Isolate and bound each proof run

As the Commander, I want each proof to run isolated and bounded, so that one check cannot poison or hang another.

**Acceptance Criteria**

- Each check executes with a fresh temporary working directory seeded from the build directory; files it writes are absent from the next check's directory.
- A check exceeding its timeout is terminated and recorded as ERROR-timeout, and the run continues to the next check.
- A check that needs a port receives a free port through the documented environment variable, and two checks needing ports in the same run receive different ports.
- Declared services are torn down after each check, verified by the absence of the bound port afterwards.

**Tests (RED first)**

- test_check_writes_do_not_leak_to_next_check
- test_timeout_terminates_and_run_continues
- test_two_port_checks_receive_distinct_ports
- test_declared_service_torn_down_after_check

### Story 3: Report typed proof outcomes

As the Commander, I want SOUNDINGS.md to tell me whether a proof failed or never ran, so that I fix the right thing.

**Acceptance Criteria**

- `SOUNDINGS.md` records one of PASS, FAIL, ERROR-import, ERROR-timeout, ERROR-setup, UNVERIFIED-vacuous per criterion, with a timestamp.
- A check whose script raises ImportError or ModuleNotFoundError before any assertion is recorded ERROR-import, never FAIL.
- `drydock score ac --step <id>` prints the outcome class and the captured stdout and stderr for each check.
- `score release`'s supplied evidence facts distinguish executed-and-failed from never-executed counts.

**Tests (RED first)**

- test_soundings_records_typed_outcome_classes
- test_import_error_classified_not_fail
- test_scoped_score_prints_class_and_captured_output
- test_release_evidence_separates_failed_from_unexecuted

## Definition of Done

- A web fixture with three route proofs against one app runs green with no port collision and no residual process.
- A deliberately hanging proof is terminated at its declared timeout and the remaining proofs still run.
- `BLUEPRINTS_CONTRACT.md` documents the runtime block and the default values.
- Blueprints with no runtime block behave exactly as today apart from the added isolation.

## Implementation Plan

1. Extend the check parser in `acceptance.py` to read `Needs:`, `Timeout:`, and `Env:` from the heading block.
2. Add a proof runner in `score.py` that creates a per-check temp CWD, resolves ports, exports the documented env, runs with a subprocess timeout, and tears down.
3. Add a service registry contract in `ARCHITECTURE.md` (start command, readiness probe, teardown) and document it in `prompts/BLUEPRINTS_CONTRACT.md`.
4. Extend the outcome enum used by `score.py` and rendered by `standard_artifacts.py` into `SOUNDINGS.md`.
5. Extend the evidence facts passed to `prompts/score_release.md` to carry executed and unexecuted counts separately.
6. Add fixtures: a three-route app, a hanging check, an import-error check, a port-collision pair.

## Specification Impact

§ drydock score (SOUNDINGS.md status vocabulary currently 'PASS / FAIL / UNVERIFIED') and § Specification File Format (Programmatic Acceptance section description). Requires the author's approval for the expanded status set.

## Risks

- A per-check temporary CWD changes relative-path semantics for existing proofs that write into the build directory intentionally.
- Service lifecycle management is the most failure-prone part; a bad readiness probe converts working proofs into ERROR-setup.
- Expanded status vocabulary flows into QuarterDeck badges, `score release` scoring, and `SCORECARD.md`.

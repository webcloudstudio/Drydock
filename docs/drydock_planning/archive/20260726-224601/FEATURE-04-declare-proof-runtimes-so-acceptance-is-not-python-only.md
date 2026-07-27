---
id: DDF-002
title: Declare proof runtimes so acceptance is not Python-only
area: cross-cutting
impact: 9
complexity: 7
rank: 4
generated_at: 2026-07-26T20:31:43-04:00
review_model: claude-opus-5
source: drydock score drydock
---

# FEATURE DDF-002: Declare proof runtimes so acceptance is not Python-only

| Field | Value |
|---|---|
| Area | cross-cutting |
| Impact | 9/10 |
| Complexity | 7/10 |
| Rank | 4 |
| Project Types | Mobile / desktop client, TypeScript / Node service, Library / SDK in any language, Embedded, Infrastructure as code |

## Problem

Programmatic Acceptance is defined as Python fenced blocks executed as standalone scripts. Any Target not implemented in Python — mobile, desktop, TypeScript services, Go, Rust, JVM — cannot express its Definition of Done, so the TDD goal is unreachable there even when an organization supplies complete Rigging, which the Specification names as the supported extension path.

## Intent

Specification `Test Driven Development` — `Programmatic acceptance criteria created using a checklist`; and `Drydock Rigging` — `COLLABORATORS should create Rigging for other implementation languages`.

## Evidence

`prompts/BLUEPRINTS_CONTRACT.md`: `Programmatic Acceptance contains executable Python assertion snippets` and `Drydock writes each fenced block to its own script and runs it in its own process from the build directory`; Specification `Specification File Format`: `Executable Python assertions`. `Rigging/stack/typescript.md` exists but no acceptance can be written in it.

## Recommendation

A proof heading block may declare `Runtime: <id>` on its own line, defaulting to `python`. Rigging declares runtimes in `Rigging/runtimes/<id>.md` with a fenced metadata block giving the file extension, the argv template, and an availability probe command. `acceptance.py` resolves the runtime, writes the fence to a temp file with the declared extension, and executes the argv template from the build directory. An unknown or unavailable runtime records `UNVERIFIED (runtime-unavailable)` — never PASS.

## Stories

### Story 1: Runtime registry in Rigging

As the Commander, I want to declare an acceptance runtime in Rigging, so that my organization's language is executable without changing Drydock's code.

**Acceptance Criteria**

- A `Rigging/runtimes/node.md` declaring extension `.mjs`, argv `[node, {script}]`, and a probe `[node, --version]` is discoverable by `paths.py` resolution in both source-tree and installed-package layouts.
- A runtime file missing any required key is reported by `drydock rigging verify` as an invalid runtime and is not registered.
- `python` is registered as a built-in runtime with no Rigging file required, preserving current behavior byte-for-byte.

**Tests (RED first)**

- tests/test_runtimes.py::test_node_runtime_is_discovered
- tests/test_runtimes.py::test_invalid_runtime_file_is_rejected
- tests/test_runtimes.py::test_default_python_runtime_matches_legacy_execution

### Story 2: Runtime-aware proof execution

As the Commander, I want a non-Python proof to run and produce a real verdict, so that acceptance means the same thing in every language.

**Acceptance Criteria**

- A proof declaring `Runtime: node` with a fence exiting non-zero records FAIL with captured stdout and stderr in `SOUNDINGS.md`.
- The same proof exiting zero records PASS.
- A proof declaring an unregistered runtime records `UNVERIFIED` with reason `runtime-unknown` and never PASS.
- A registered runtime whose probe command is absent on the host records `UNVERIFIED` with reason `runtime-unavailable`.
- A proof with no `Runtime:` line executes through the Python path with identical output to the pre-change implementation.

**Tests (RED first)**

- tests/test_acceptance.py::test_node_proof_failure_records_fail_with_output
- tests/test_acceptance.py::test_node_proof_success_records_pass
- tests/test_acceptance.py::test_unknown_runtime_records_unverified
- tests/test_acceptance.py::test_missing_interpreter_records_unverified
- tests/test_acceptance.py::test_default_runtime_is_python

### Story 3: Contract and validation support for Runtime

As the Commander, I want the planning prompts to author runtime-declared proofs correctly, so that non-Python plans validate.

**Acceptance Criteria**

- `drydock validate` accepts a `Runtime:` line in a proof heading block and rejects a fence whose declared language tag contradicts the declared runtime.
- The Python-only static checks (unbound name, unparseable snippet, raw-literal escape defect) are applied only to `python` proofs and are skipped without error for others.
- `plan_create.md` and `plan_conform.md` instruct the agent to declare `Runtime:` when the Target's stack is not Python, and to keep proofs standalone under that runtime.

**Tests (RED first)**

- tests/test_validate_specification.py::test_runtime_line_is_accepted
- tests/test_validate_specification.py::test_fence_language_mismatch_is_rejected
- tests/test_validate_specification.py::test_python_static_checks_skipped_for_other_runtimes

## Definition of Done

- A Target whose stack file is `typescript.md` can carry a passing and a failing acceptance proof end to end through `drydock score ac`.
- `SOUNDINGS.md` records the runtime id alongside each criterion's status.
- No existing Python Blueprint changes behavior; the legacy corpus produces identical `SOUNDINGS.md` content.

## Implementation Plan

1. Extend the proof heading parser (shared by `acceptance.py`, `validate_specification.py`, and `proof_integrity.py`) to read `Runtime:` alongside `Sea Trials:` and `Suite:`.
2. Add `drydock/runtimes.py` with registry loading from `Rigging/runtimes/*.md` through `paths.py`, plus a built-in `python` entry.
3. Refactor the proof executor in `acceptance.py` to take a `Runtime` record (extension, argv template, probe) rather than hardcoding `python3`.
4. Gate `proof_integrity.py` AST analysis on `runtime == python`; record `UNVERIFIED (integrity-unavailable)` for other runtimes until per-runtime analyzers exist.
5. Add `Rigging/runtimes/README.md` plus a reference `node.md` and `pytest.md`; register them in `Rigging/MANIFEST.md` so `discovery-stack.json` can surface them.
6. Update `prompts/BLUEPRINTS_CONTRACT.md` `Programmatic Acceptance` section and `prompts/plan_create.md` step 5 with the `Runtime:` contract.

## Specification Impact

`Specification File Format` (`Executable Python assertions`) and the `drydock score ac` description would need the author's approval to say `executable assertions in a declared runtime, defaulting to Python`. The `Drydock Rigging` section gains runtimes as a fourth governed layer.

## Risks

- Proof integrity analysis is Python-AST based, so non-Python proofs lose vacuity detection until DDF-004 analyzers exist per runtime — this must be reported as a distinct status rather than silently trusted.
- Executing arbitrary interpreter argv widens the build-time execution surface; the Specification's containment guidance (Docker/bwrap) becomes load-bearing and should be restated in the runtime README.

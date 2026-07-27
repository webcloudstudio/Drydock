---
id: DDF-012
title: Add a baseline mode so Drydock can plan against code that already exists
area: cross-cutting
impact: 6
complexity: 8
rank: 12
generated_at: 2026-07-26T22:46:01-04:00
review_model: claude-opus-5
source: drydock score drydock
---

# FEATURE DDF-012: Add a baseline mode so Drydock can plan against code that already exists

| Field | Value |
|---|---|
| Area | cross-cutting |
| Impact | 6/10 |
| Complexity | 8/10 |
| Rank | 12 |
| Project Types | Legacy brownfield modernization, Multi-service systems, Any project adopting Drydock after work has started |

## Problem

`drydock import --format source` brings an existing codebase under Drydock, but every downstream contract assumes greenfield authoring. `analyze.md` states there are no typed specs at analyze time; `plan_create.md` treats specs as 'a structured rewrite' of the sources; each Blueprint file gets exactly one story whose job is to build it; and `drydock build --reset` with no selector 'wipes the build directory'. There is no story mode meaning 'this code exists, verify it', no way to seed `applied_specs` for pre-existing files, and no protection against regenerating a working system. A Commander who imports a live product and runs the loop is invited to have it rewritten.

## Intent

`Drydock_Specification.md` § drydock import ('`drydock import <Target> <Source> --format <source|speckit>` imports specifications from other systems') and § SAIL Phase 4 — Loop ('lets the Commander update the application while keeping the Blueprint and built software aligned') — an intent the import surface implies but the build model never states.

## Evidence

`prompts/analyze.md` Hard Rules: 'Do not write to `blueprint/` or read `MANIFEST.md`. Read imported sources — there are no typed spec files at analyze time'; `prompts/plan_create.md` § Inputs: 'The authored spec files are fundamentally a structured rewrite of this material per the file map'; `Drydock_Specification.md` § drydock build: '`--reset` ... with no selector it resets every block and wipes the build directory'; module inventory `import_source.py: Import existing source code into a Drydock Blueprint by preserving files under sources/`.

## Recommendation

A baseline disposition. `drydock import --format source` records the imported tree's digests and seeds the build directory. Analyze classifies those files as existing implementation in `## Source Roles`. Plan emits Blueprint files carrying `Baseline: existing` and stories carrying `mode: verify`, whose gate is the spec's `Programmatic Acceptance` run against the code as it stands — expected to pass, closing on proof rather than on a diff, with DDF-005's prepass rule inverted for this mode. Only stories whose proofs fail, or that carry a change ticket, become buildable. `--reset` refuses to wipe a build directory containing baseline files without an explicit force flag.

## Stories

### Story 1: Record a baseline on source import

As the Commander, I want importing existing code to establish a baseline, so that Drydock knows which software already exists.

**Acceptance Criteria**

- `drydock import --format source` writes a baseline manifest of imported paths with content digests.
- The imported tree is seeded into the build directory without invoking an LLM.
- Re-importing the same tree is idempotent and records no new baseline entries.

**Tests (RED first)**

- test_source_import_writes_baseline_digests
- test_source_import_seeds_build_directory_without_llm
- test_reimport_of_identical_tree_is_idempotent

### Story 2: Add the verify story mode

As the Commander, I want a story that verifies existing code rather than writing it, so that adopting Drydock does not mean regenerating my product.

**Acceptance Criteria**

- A story may declare `mode: verify`; the default remains `build`.
- A `verify` story issues no build LLM call and closes `closed/verified` when its spec's proofs pass against the existing code.
- A `verify` story whose proofs fail becomes `closed/failed` with the failing check named, and is convertible to `mode: build` from the QuarterDeck.
- A `verify` story's prepass is expected and does not trigger the DDF-005 halt.

**Tests (RED first)**

- test_verify_mode_field_parses_with_build_default
- test_verify_story_closes_on_passing_proofs_without_llm_call
- test_verify_story_fails_naming_check_and_is_convertible
- test_verify_story_prepass_does_not_halt

### Story 3: Seed applied_specs from the baseline

As the Commander, I want drift detection to start from the imported state, so that my first refit detects real change instead of reporting everything stale.

**Acceptance Criteria**

- Closing a `verify` story records its implemented spec in `applied_specs` with the baseline digest and `applied_by` naming the verify story.
- A subsequent `drydock refit` with no changes reports a no-op and exits 0.
- Editing a baseline spec then running refit marks exactly that spec's work for rebuild.

**Tests (RED first)**

- test_verify_close_records_applied_specs_entry
- test_refit_after_baseline_is_noop_exit_zero
- test_edited_baseline_spec_marks_only_its_work_for_rebuild

### Story 4: Protect a baseline build directory from reset

As the Commander, I want reset to refuse to wipe imported working software, so that one flag cannot destroy the product.

**Acceptance Criteria**

- `drydock build --reset` with no selector exits non-zero when the build directory contains baseline-tracked files and no force flag is given.
- The refusal message names the count of baseline files and the explicit force flag required.
- `--reset --step`/`--story` on a `verify` story resets plan state without deleting baseline files.

**Tests (RED first)**

- test_reset_refuses_baseline_directory_without_force
- test_reset_refusal_names_count_and_force_flag
- test_scoped_reset_of_verify_story_preserves_baseline_files

## Definition of Done

- A brownfield fixture imports, analyzes, plans, and verifies without a single build LLM call, ending with a clean refit no-op.
- A failing verify story is convertible to a build story and rebuilds only its own scope.
- `--reset` cannot destroy a baseline tree without an explicit force flag.
- Greenfield behavior is unchanged in every fixture.

## Implementation Plan

1. Extend `import_source.py` to write a baseline digest manifest and seed the build directory through `source_roles.py` staging.
2. Add `existing implementation` as a Source Role in `prompts/analyze.md` § Source Roles with a `baseline` plan disposition.
3. Add `Baseline:` to the typed header field table in `prompts/BLUEPRINTS_CONTRACT.md` and `mode:` to the story field table in `prompts/MANIFEST_CONTRACT.md` and `prompts/plan_create.md`.
4. Implement verify-mode execution in `build_run.py` (proof run, no LLM call) and closure through `build_review.py`.
5. Seed `applied_specs` on verify closure in `build_plan.py`.
6. Add the reset guard to `build_run.py` and the force flag to the `build` subparser in `cli.py`.
7. Add a brownfield fixture with a small existing package, its specs, and one deliberately failing proof.

## Specification Impact

§ drydock import (baseline recording), § The Manifest Graph Database story fields (`mode:`), § drydock build (`--reset` guard and new flag), and § Specification File Format (`Baseline:`). Requires the author's approval.

## Risks

- Reverse-specifying existing code well enough that its proofs are meaningful is the hard part; weak specs will produce verify stories that pass trivially — DDF-005's vacuity rules are the compensating control.
- Baseline digests interact with the staged-asset immutability rules and could double-report violations.
- A verify mode that closes without a build call weakens the meaning of `closed/verified` unless the proofs are strong enough to distinguish working code from a stub.

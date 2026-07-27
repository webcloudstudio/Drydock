---
id: DDF-002
title: Split plan creation into a skeleton pass and resumable per-file authoring
area: drydock plan
impact: 9
complexity: 7
rank: 2
generated_at: 2026-07-26T22:46:01-04:00
review_model: claude-opus-5
source: drydock score drydock
---

# FEATURE DDF-002: Split plan creation into a skeleton pass and resumable per-file authoring

| Field | Value |
|---|---|
| Area | drydock plan |
| Impact | 9/10 |
| Complexity | 7/10 |
| Rank | 2 |
| Project Types | All, Decisive for any project above roughly 20 stories, Multi-service systems, Legacy brownfield modernization |

## Problem

`plan_create.md` demands every authored Blueprint file — each with several fenced Python proofs — plus `MANIFEST.md` in one response with nothing outside the delimiters, while `analyze.md` permits roughly 100 stories. `artifact_blocks.py` parses strictly, so one truncation or one mismatched END delimiter discards the entire run. There is no partial commit, no resume, and no per-file retry. The most consequential and most expensive step in the pipeline is also the least recoverable, and it is configured `model: sonnet` with no `effort:` while a self-assessment prompt runs at `effort: max`.

## Intent

`Drydock_Specification.md` § Drydock Features: 'Build large projects with low-end models' and 'Context optimization — LLM usage minimized'; § drydock plan: '`drydock plan` is rerun-safe. It preserves reviewed work where possible'.

## Evidence

`prompts/plan_create.md` § Output Contract: 'Emit one block for every authored Blueprint spec file, followed by one `MANIFEST.md` block' and 'Any output outside a delimited block is a protocol violation and will cause the run to fail'; `prompts/analyze.md` step 4: 'Story cap: ~100 stories'; module inventory `artifact_blocks.py: Strict parsing for LLM-emitted artifact blocks`; `plan_create.md` frontmatter `model: sonnet` with no `effort` key against `prompts/README.md` § Prompt contract which defines `effort`.

## Recommendation

Two-phase planning. Phase A emits only the file map and the `MANIFEST.md` skeleton — ids, `implements`, `covers`, `accepts`, `depends`, grouping, instructions — which is small, cheap, and is what the Commander reviews on the Compass. Phase B authors each spec file in its own bounded call with `BLUEPRINTS_CONTRACT.md`, that file's manifest row, and its `Depends On` neighbours' compact surfaces injected. Drydock writes each file as its call returns and records progress, so `drydock plan --continue` resumes after a failure and `drydock plan --file <NAME>` re-authors one spec.

## Stories

### Story 1: Author the skeleton planning prompt

As the Commander, I want planning to produce a reviewable Manifest before any spec prose is written, so that I can correct decomposition before paying to author 60 files.

**Acceptance Criteria**

- `prompts/plan_skeleton.md` exists with valid frontmatter and emits exactly one `=== MANIFEST.md ===` block and one `=== PLAN_FILEMAP.md ===` block.
- The skeleton run emits no Blueprint spec file blocks; a run that emits one fails validation with a named error.
- Every `implements:` value in the skeleton Manifest appears exactly once in `PLAN_FILEMAP.md`, and every filemap row is implemented by exactly one story.

**Tests (RED first)**

- test_plan_skeleton_prompt_frontmatter_valid
- test_plan_skeleton_emits_only_manifest_and_filemap
- test_plan_skeleton_rejects_emitted_spec_blocks
- test_skeleton_implements_and_filemap_are_bijective

### Story 2: Author each spec file in its own call

As the Commander, I want each Blueprint file authored in a bounded call, so that one failure costs one file rather than the whole plan.

**Acceptance Criteria**

- For a filemap of N rows, `drydock plan` issues N authoring calls and writes each returned file to `blueprint/` before the next call is issued.
- Each authoring prompt injects `BLUEPRINTS_CONTRACT.md`, the file's manifest row, and the compact derivatives of its `Depends On` neighbours where they exist.
- A malformed or truncated block in call k leaves files from calls 1..k-1 on disk and marks row k `failed` in the plan ledger.

**Tests (RED first)**

- test_plan_issues_one_call_per_filemap_row
- test_authoring_prompt_injects_blueprints_contract
- test_truncated_authoring_block_preserves_prior_files
- test_failed_row_recorded_in_plan_ledger

### Story 3: Resume and re-author

As the Commander, I want to resume a partially completed plan and re-author one file, so that a transient failure does not force a full replan.

**Acceptance Criteria**

- `drydock plan <Target> --continue` authors only rows whose ledger state is `pending` or `failed` and exits 0 when all rows are `written`.
- `drydock plan <Target> --file FEATURE-Catalog.md` re-authors exactly that file and touches no other Blueprint file's mtime.
- `drydock plan <Target> --continue` on a complete plan is a no-op that exits 0 and issues zero LLM calls.

**Tests (RED first)**

- test_plan_continue_only_authors_incomplete_rows
- test_plan_file_flag_rewrites_single_spec_only
- test_plan_continue_on_complete_plan_is_noop_zero_calls

### Story 4: Per-phase model and effort selection

As the Commander, I want the decomposition pass to run at higher reasoning depth than the per-file authoring pass, so that reasoning budget lands where the irreversible decisions are made.

**Acceptance Criteria**

- `plan_skeleton.md` frontmatter declares a model and an `effort` value drawn from the set in `prompts/README.md`.
- The per-file authoring prompt declares its own model independently of the skeleton prompt.
- `drydock plan --dry-run` prints the resolved model and effort for each phase without issuing a call.

**Tests (RED first)**

- test_skeleton_prompt_declares_effort_from_allowed_set
- test_phase_models_resolve_independently
- test_plan_dry_run_prints_phase_models_without_llm_call

## Definition of Done

- A 60-file plan completes with no single response exceeding a configured output budget.
- Killing the process mid-plan and rerunning with `--continue` produces the same final Blueprint as an uninterrupted run.
- `plan_create.md` is retained only for small plans or retired in favour of the two-phase path, with the choice recorded in `prompts/README.md`.
- The plan ledger is written under the Target workspace and is readable by `drydock status`.

## Implementation Plan

1. Add `prompts/plan_skeleton.md` (Manifest + filemap only) and `prompts/plan_author_spec.md` (one file, contract-injected), both with frontmatter validated by `drydock.prompts.load_prompt`.
2. In `planning_session.py`, add a two-phase driver plus a `PLAN_LEDGER.json` under the Target workspace recording `{filename, state, sha256, attempts}`.
3. Extend `cli.py` `plan` subparser with `--continue` and `--file <NAME>`; keep `--overwrite` and `--no-conform` semantics.
4. Reuse `artifact_blocks.py` strict parsing per call; on parse failure mark the single row failed rather than aborting the session.
5. Inject neighbour context via `rigging_compact.py` derivatives and `prompt_context.py` labels.
6. Add fixtures for a 3-row filemap with an induced truncation on row 2 and assert rows 1 and 3 behaviour.

## Specification Impact

§ SAIL Phase 2 — Agile Analyze § drydock plan (Replan behavior) and the § Commands synopsis would gain `--continue` and `--file`; the Artifact I/O Matrix gains a plan-ledger row. Author approval needed for the CLI surface change.

## Risks

- Cross-file consistency (`Depends On`, `Provides`, SCREEN `Consumes`) is harder to keep coherent when files are authored independently; the skeleton must carry the computed graph and the authoring prompt must be forbidden from editing it.
- N calls may cost more total tokens than one call for small plans; the driver should fall back to single-pass below a row threshold.
- Resume semantics interact with `--overwrite` and with drift detection in `applied_specs`.

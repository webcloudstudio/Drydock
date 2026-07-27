---
id: DDF-007
title: Validate prompt frontmatter against the Artifact I/O Matrix and the prompt inventory
area: cross-cutting
impact: 6
complexity: 3
rank: 11
generated_at: 2026-07-26T22:46:01-04:00
review_model: claude-opus-5
source: drydock score drydock
---

# FEATURE DDF-007: Validate prompt frontmatter against the Artifact I/O Matrix and the prompt inventory

| Field | Value |
|---|---|
| Area | cross-cutting |
| Impact | 6/10 |
| Complexity | 3/10 |
| Rank | 11 |
| Project Types | All |

## Problem

`prompts/README.md` declares `inputs:` to be 'the agent's source of truth for which files it consumes and in what order', 'derived directly from the Artifact Feed Matrix' — and nothing checks it. Today `plan_create.md`, `plan_reuse.md`, and `plan_create_speckit.md` all list `SOUNDINGS.md` and describe it as coming from analyze, while `analyze.md` states it is written only by `drydock score ac` and the matrix gives plan no `I` for it — a prompt asking for information that does not exist at that point in the pipeline. The README calls the matrix by a different name than the specification, defines the `QUESTIONNAIRES` token as `spike-*.json` while analyze emits `discovery-*.json`, lists `drydock build` as deferred naming two prompt files that do not exist while `build.md` does, and omits nine prompts that ship. `build_score.md` and `score_release.md` are near-duplicate scorers whose text has already diverged, and `build_score.md` declares a command that is not in the CLI.

## Intent

`Drydock_Specification.md` § Artifact I/O Matrix (the declared authority on what each command reads and writes) and § Governance ('Persistent intent injection at each process stage').

## Evidence

`prompts/plan_create.md` frontmatter `inputs: ... SOUNDINGS.md ...` and body '**`SEA_TRIALS.md`** and **`SOUNDINGS.md`** — product objectives and acceptance milestones from analyze' versus `prompts/analyze.md` step 5 'Do not emit `SOUNDINGS.md` — it is written only by `drydock score ac`' and the matrix row `SOUNDINGS.md | Target root | · | · | · | O | ·`. `prompts/README.md` token table (`QUESTIONNAIRES` → `spike-*.json`) versus `analyze.md` output (`discovery-<slug>.json`). `prompts/README.md` command table lists `build_story.md` and `build_spike.md` as not yet ported while `prompts/build.md` exists. `prompts/build_score.md` frontmatter `command: drydock build score`, which does not appear in the CLI usage block.

## Recommendation

A `drydock prompt validate` gate, run in CI, that asserts: every prompt's frontmatter parses through `drydock.prompts.load_prompt`; every `inputs:` entry is either a filename carrying `I`, `O/I`, `O*/I`, or `X` in that command's Artifact I/O Matrix row, or a logical token registered in the assembler; every `command:` names a real CLI verb; every prompt file on disk appears in the `prompts/README.md` table and vice versa; and no two prompt bodies exceed a similarity threshold.

## Stories

### Story 1: Validate inputs against the matrix

As the Commander, I want a prompt that asks for a file the pipeline never produces at that stage to fail a test, so that agents are not told to look for artifacts that do not exist.

**Acceptance Criteria**

- The validator parses the Artifact I/O Matrix from `docs/Drydock_Specification.md` into a command-to-artifact map.
- A prompt listing `SOUNDINGS.md` under `command: drydock plan create` fails with a message naming the prompt, the token, and the matrix row.
- A prompt listing a token absent from the assembler registry fails with a message naming the token.
- All currently shipped prompts pass after the known offenders are corrected.

**Tests (RED first)**

- test_matrix_parses_into_command_artifact_map
- test_plan_prompt_listing_soundings_fails_validation
- test_unregistered_logical_token_fails_validation
- test_all_shipped_prompts_pass_input_validation

### Story 2: Validate the prompt inventory and commands

As the Commander, I want the prompt table to be true, so that I can tell which prompts are live.

**Acceptance Criteria**

- Every file matching `prompts/*.md` other than the contracts and README appears in the README table.
- Every prompt named in the README table exists on disk.
- Every prompt `command:` value matches a verb or verb-and-sub-verb in the CLI parser.
- Contract files (`MANIFEST_CONTRACT.md`, `BLUEPRINTS_CONTRACT.md`) are recognized as contracts and exempted from the command rule.

**Tests (RED first)**

- test_every_prompt_file_listed_in_readme
- test_every_readme_prompt_exists_on_disk
- test_every_prompt_command_matches_cli_verb
- test_contract_files_exempt_from_command_rule

### Story 3: Detect duplicate prompts

As the Commander, I want near-duplicate prompts to fail a test, so that two copies of the release scorer cannot drift apart unnoticed.

**Acceptance Criteria**

- Two prompt bodies exceeding a documented similarity threshold fail validation, naming both files.
- `build_score.md` and `score_release.md` are reduced to one prompt, or the retained duplicate declares an explicit exemption with a stated reason.
- The exemption list is a file, not an inline suppression, and each entry carries a reason string.

**Tests (RED first)**

- test_near_duplicate_prompts_fail_validation
- test_release_scorer_deduplicated_or_exempted_with_reason
- test_exemption_entries_require_reason

## Definition of Done

- `drydock prompt validate` exits 0 on a clean tree and non-zero on each seeded defect.
- The three plan prompts no longer request `SOUNDINGS.md`.
- `prompts/README.md` names the matrix by the specification's own term and lists every shipped prompt with an accurate status.
- The duplicate release scorer is resolved.

## Implementation Plan

1. Add a matrix parser and a prompt-frontmatter validator to `prompts.py`, reachable as `drydock prompt validate` in `cli.py` alongside the existing `prompt review`.
2. Register logical tokens (`QUESTIONNAIRES`, `TYPED_SPEC`, `IMPORTED_SOURCES`, `RIGGING_MANIFEST`, `EXISTING_SPIKES`, `EVIDENCE`, `SPEC_FILE`, `INTENT_DOCUMENT`) in one table in `prompt_assembly.py` and make the README table generated from it.
3. Correct `inputs:` in `plan_create.md`, `plan_reuse.md`, `plan_create_speckit.md`; correct the `QUESTIONNAIRES` token definition to `discovery-*.json`.
4. Rewrite the `prompts/README.md` command table and generate it from disk plus frontmatter.
5. Retire `build_score.md` or record its exemption; align its command with the CLI.
6. Add seeded-defect fixtures for each rule.

## Specification Impact

none — the matrix is already the declared authority; this makes it enforceable.

## Risks

- Parsing a Markdown table out of the specification is brittle if the table format changes; the parser should fail loudly rather than silently pass everything.
- Similarity thresholds produce false positives across the three `rigging_compact_*` prompts, which are legitimately parallel and will need exemptions.

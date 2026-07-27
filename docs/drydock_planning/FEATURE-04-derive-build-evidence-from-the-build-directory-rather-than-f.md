---
id: DDF-010
title: Derive build evidence from the build directory rather than from the agent
area: drydock build
impact: 8
complexity: 4
rank: 4
generated_at: 2026-07-26T22:46:01-04:00
review_model: claude-opus-5
source: drydock score drydock
---

# FEATURE DDF-010: Derive build evidence from the build directory rather than from the agent

| Field | Value |
|---|---|
| Area | drydock build |
| Impact | 8/10 |
| Complexity | 4/10 |
| Rank | 4 |
| Project Types | All |

## Problem

`build.md` requires the agent to close with a self-reported `RESULT`, `FILES CHANGED`, `SUMMARY`, and `BLOCKERS` block, and instruction 13 makes the agent responsible for the accuracy of its own file list. Drydock owns the build-directory commit after the agent returns, so it has the authoritative diff and does not use it. `score_release.md` is then told the supplied evidence 'are the complete assessment record' — meaning the assessed party wrote the record. A step that failed can report SUCCESS with a plausible narrative, and the specification's promise of reviewable build evidence resolves to prose.

## Intent

`Drydock_Specification.md` § Governance ('Writes reviewable build evidence for completed work') and § What is Drydock ('Trust But Verify').

## Evidence

`prompts/build.md` items 12–13: 'End your response with this exact closing structure ... `FILES CHANGED` must list only files actually written'; `prompts/score_release.md`: 'The evidence facts appended below are the complete assessment record'; `Drydock_Specification.md` § drydock build item 11: 'Drydock owns the final build directory commit after you return.'

## Recommendation

After each block, Drydock derives the evidence record itself: files added, modified, and deleted with digests; test files added versus modified; each declared proof with its typed outcome; the dependency-manifest delta with the `dependency_gate.py` verdict; staged-asset digest comparison; and the exit status of every command it ran. `RESULT: SUCCESS` is accepted only when the derived diff is non-empty and every declared proof of the block passed. The agent's narrative is retained as a clearly labelled unverified `notes:` field inside the deterministic record, and `evidence/<id>.md` renders both.

## Stories

### Story 1: Derive the file-change record from the build directory

As the Commander, I want the file list in evidence to be measured, not claimed, so that a step cannot report work it did not do.

**Acceptance Criteria**

- The evidence record lists added, modified, and deleted paths with content digests, derived from the build directory state before and after the step.
- A step whose derived diff is empty is recorded FAILED regardless of the agent's declared RESULT.
- A path the agent listed under FILES CHANGED that does not appear in the derived diff is recorded as an unverified claim, not as a change.
- Staged assets under `sources/` whose digest changed are recorded as violations and restored.

**Tests (RED first)**

- test_evidence_lists_derived_diff_with_digests
- test_empty_diff_forces_failed_result
- test_unbacked_agent_file_claim_marked_unverified
- test_modified_staged_asset_recorded_and_restored

### Story 2: Bind SUCCESS to proof outcomes

As the Commander, I want a block to be recorded successful only when its declared proofs passed, so that the state in the Manifest matches reality.

**Acceptance Criteria**

- A block whose declared proofs did not all pass is recorded `closed/failed` even when the agent declared SUCCESS.
- The evidence record carries one row per declared check with its typed outcome from DDF-004.
- The failure reason written to the block's `finding:` is derived from the failing check, not from the agent's summary.

**Tests (RED first)**

- test_failed_proof_forces_closed_failed_despite_agent_success
- test_evidence_carries_row_per_declared_check
- test_finding_derived_from_failing_check

### Story 3: Record dependency and command facts

As the Commander, I want dependency changes and executed commands captured deterministically, so that supply-chain and build behavior are auditable.

**Acceptance Criteria**

- The evidence record lists every added or changed Python dependency with the `dependency_gate.py` verdict for each.
- A dependency the gate could not verify is recorded and surfaced as a release blocker in `score release` facts.
- The record carries the exit status of every command Drydock ran on behalf of the step.

**Tests (RED first)**

- test_dependency_delta_recorded_with_gate_verdicts
- test_unverified_dependency_surfaces_as_release_blocker
- test_command_exit_statuses_recorded

### Story 4: Separate narrative from fact in the evidence file

As the Commander, I want the agent's summary visibly marked as unverified, so that I do not read a claim as a measurement.

**Acceptance Criteria**

- `evidence/<id>.md` renders a deterministic facts section and a separately headed agent-notes section.
- The agent-notes section is labelled unverified in the rendered output and in the QuarterDeck.
- The facts passed to `score_release.md` include only the deterministic section plus a flag indicating notes exist.

**Tests (RED first)**

- test_evidence_file_separates_facts_from_notes
- test_agent_notes_labelled_unverified_in_quarterdeck
- test_release_facts_exclude_agent_narrative

## Definition of Done

- A fixture step that writes nothing but declares SUCCESS is recorded FAILED.
- A fixture step that writes files but fails a proof is recorded `closed/failed` with a derived finding.
- `score release` receives no agent-authored prose as a scored fact.
- `build.md`'s closing block is retained for readability but is no longer the record of truth.

## Implementation Plan

1. Capture pre-step and post-step build-directory state in `build_run.py` using the same commit machinery that already owns the final commit.
2. Emit a structured evidence record through `execution.py` into the append-only JSONL log and render `evidence/<id>.md` from it.
3. Move `RESULT` adjudication out of parsing the agent's closing block and into the derived record; keep the closing block parse for the notes and blockers fields.
4. Wire `dependency_gate.py` verdicts and `source_roles.py` staged-asset digests into the record.
5. Update `prompts/build.md` to state that FILES CHANGED is advisory and that Drydock measures the diff.
6. Update the evidence facts assembled for `prompts/score_release.md` in `score.py`.
7. Add fixtures: no-op step, files-but-failing-proof step, staged-asset mutation step, dependency-adding step.

## Specification Impact

§ drydock build (evidence semantics), § Governance ('Writes reviewable build evidence'), and § Execution Rules (`finding:` provenance). Requires the author's approval.

## Risks

- Steps that legitimately produce no diff (a spike answering a question) must be exempted by block type or they will all fail.
- Digest capture over a large build directory adds per-step latency.
- Existing evidence files and QuarterDeck renderers assume the current prose shape.

---
id: DDF-009
title: Reconcile self-reported build evidence against the real diff
area: drydock build
impact: 8
complexity: 3
rank: 5
generated_at: 2026-07-26T20:31:43-04:00
review_model: claude-opus-5
source: drydock score drydock
---

# FEATURE DDF-009: Reconcile self-reported build evidence against the real diff

| Field | Value |
|---|---|
| Area | drydock build |
| Impact | 8/10 |
| Complexity | 3/10 |
| Rank | 5 |
| Project Types | All |

## Problem

A build step closes on the agent's own report: `RESULT: SUCCESS`, a `FILES CHANGED` list, and a prose summary. `build.md` instructs the agent not to claim success without writing files, but nothing checks. A step that wrote nothing, wrote outside the build directory, or wrote files it did not report can still advance the frontier, and the Commander's review artifact is a narrative the Commander cannot verify.

## Intent

Specification `Trust But Verify - the Commander reviews in the Quarterdeck`; `Governance` — `Writes reviewable build evidence for completed work`.

## Evidence

`prompts/build.md` items 10, 12, and 13: `Do not claim success unless you actually created or modified project files`, the `FILES CHANGED` closing structure, and `FILES CHANGED must list only files actually written`. All three are honor-system instructions with no named verifier.

## Recommendation

`build_run.py` snapshots the build directory before and after each step (tracked and untracked, excluding `sources/`, which is already digest-protected) and reconciles the real diff against the parsed `FILES CHANGED`. `RESULT: SUCCESS` with an empty diff fails the step. Unreported changes and reported-but-unchanged paths are recorded in the evidence file and surfaced in the QuarterDeck. Any write outside the build directory aborts the step and is reported as a containment violation.

## Stories

### Story 1: Before/after build-directory snapshot

As the Commander, I want a deterministic record of what a step actually changed, so that build evidence is fact rather than narrative.

**Acceptance Criteria**

- A snapshot enumerates every file under the build directory with its sha256, excluding `.git/` and `sources/`.
- The diff of two snapshots reports added, modified, and deleted paths exactly.
- Snapshotting a ten-thousand-file tree completes without loading file contents into memory simultaneously.

**Tests (RED first)**

- tests/test_build_run.py::test_snapshot_enumerates_digests_excluding_sources
- tests/test_build_run.py::test_snapshot_diff_reports_add_modify_delete
- tests/test_build_run.py::test_snapshot_streams_large_tree

### Story 2: Reconciliation gate

As the Commander, I want a step that reports success without changing anything to fail, so that the frontier only advances on real work.

**Acceptance Criteria**

- A step returning `RESULT: SUCCESS` with an empty real diff is recorded `closed/failed` with reason `no-files-written`.
- A step whose real diff contains paths absent from `FILES CHANGED` is recorded with a `unreported-changes` note listing them, and the evidence file names them.
- A step whose `FILES CHANGED` lists paths with no real change is recorded with a `phantom-changes` note.
- A step whose reports and diff agree proceeds to acceptance verification unchanged.

**Tests (RED first)**

- tests/test_build_run.py::test_success_with_empty_diff_is_failed
- tests/test_build_run.py::test_unreported_changes_are_recorded
- tests/test_build_run.py::test_phantom_changes_are_recorded
- tests/test_build_run.py::test_agreeing_report_proceeds

### Story 3: Containment violation detection

As the Commander, I want writes outside the build directory to abort the step, so that the Blueprint and Manifest cannot be edited by the build agent.

**Acceptance Criteria**

- A step that modifies any file under the Target workspace (`blueprint/`, `MANIFEST.md`, Compass files) is recorded `closed/failed` with reason `containment-violation` naming the paths.
- The workspace snapshot covers `MANIFEST.md`, `COMPASS.md`, and `blueprint/**` and is taken with the build-directory snapshot.
- The violation is surfaced as a QuarterDeck action item.

**Tests (RED first)**

- tests/test_build_run.py::test_blueprint_modification_is_containment_violation
- tests/test_build_run.py::test_manifest_modification_is_containment_violation
- tests/test_build_run.py::test_containment_violation_raises_quarterdeck_item

## Definition of Done

- Every completed step's evidence file contains the reconciled diff, not only the agent's summary.
- No step can advance the frontier without a non-empty verified diff.
- The QuarterDeck build view shows reconciliation status per block.

## Implementation Plan

1. Add `drydock/build_evidence.py` with `snapshot(root, exclude) -> dict[path, sha256]` and `diff(before, after) -> Changes`.
2. In `build_run.py`, snapshot the build directory and the Target workspace before the LLM call and after it returns; reconcile against the `FILES CHANGED` block already parsed from the response.
3. Extend the evidence writer to emit a `## Verified Changes` section with added/modified/deleted paths and the reconciliation notes.
4. Map the reconciliation outcomes onto block states through the decision writer named in `MANIFEST_CONTRACT.md` (`Plan State Writer`) so no other component mutates state.
5. Reuse the staged-asset digest restore path already specified for `sources/` rather than duplicating it.
6. Add tests in `tests/test_build_run.py` with a fake LLM returning crafted `FILES CHANGED` blocks.

## Specification Impact

None required. The `drydock build` output-files table and the `Trust But Verify` statement already imply this; the Specification could gain one sentence naming the reconciliation.

## Risks

- Build steps that legitimately generate large artifact trees (node_modules, build outputs, virtualenvs) will produce enormous diffs; the exclusion set must be configurable per Target and default to the stack's ignore conventions.
- Snapshot cost on very large trees adds latency per step; digests should be computed only for files whose size and mtime changed.

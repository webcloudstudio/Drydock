# SURVEY-SPEC: drydock status

| Field       | Value |
|-------------|-------|
| Version     | 20260613 V1 |
| Description | Acceptance authority for `drydock status` — orientation across all invocation forms. |
| Command     | drydock status |
| Scored In   | Survey/scores.jsonl |
| Source      | src/drydock/status.py |

## Goal

In one glance, a user knows **where the project stands, what to do next, and what just happened**.
`drydock status` answers three questions for the active Target: the current **status** (phase and
detail), the **next step** (the exact command to run), and a **history of the last 10 commands run
against that Target**. It never requires the user to be in any particular directory and never lies
about completion.

## Acceptance Criteria — Code

| ID | Criterion | Dim | Check | Weight | Verify |
|----|-----------|-----|-------|--------|--------|
| STATUS-C1 | Output states the status: phase + one-line detail | D1 | A | 2 | output contains a phase/detail line |
| STATUS-C2 | Output states the next step as a runnable command | D1 | A | 2 | output contains a `drydock …` next-op line |
| STATUS-C3 | Output shows the **last 10** commands for the Target, newest-relevant, filtered by target | D1 | A | 3 | seed 11 history records for two targets; assert exactly 10 for the queried target |
| STATUS-C4 | Three invocation forms work: no-args, `<Blueprint>`, `<Blueprint> <Target>` | D1 | A | 2 | `tests/test_status.py` all forms |
| STATUS-C5 | No-args form is CWD-first, then last-activity fallback | D1 | A | 1 | run in/out of a Target dir |
| STATUS-E1 | Exit 0 on success; non-zero only on real failure | D5 | A | 1 | CLI exit-code test |

## Acceptance Criteria — Specification

| ID | Criterion | Dim | Check | Weight | Verify |
|----|-----------|-----|-------|--------|--------|
| STATUS-D1 | A spec/feature file describes the same three outputs (status, next step, last-10 history) | D2 | J | 2 | read the status feature spec |
| STATUS-D2 | Artifact names match the current contract — `MANIFEST.md`, not a legacy build-plan filename | D5 | A | 2 | grep `src/drydock/status.py` for legacy artifact names |
| STATUS-D3 | History limit is specified as 10 and named, not a magic number | D2 | A | 1 | grep for `limit` default in source |

## Guardrails

- Status must never report a Target as further along than its artifacts prove (no fake completion).
- Status must not depend on the caller being inside the Drydock or Prototyper repository.
- Status must not write any file — it is read-only orientation.
- The history must be filtered by Target; never show another Target's commands.

## Open Questions

- Does "last 10 commands" count failed runs (`return_code != 0`) toward the 10, or only successful
  ones? (Assumed: all attempts, with the return code shown.)
- Is the history source `logs/history.jsonl` (workspace) authoritative, or should per-Target
  `executions.jsonl` be merged in?

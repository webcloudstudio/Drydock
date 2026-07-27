---
id: DDF-008
title: Pin compact derivatives to their source digest instead of mtime
area: rigging
impact: 7
complexity: 3
rank: 11
generated_at: 2026-07-26T20:31:43-04:00
review_model: claude-opus-5
source: drydock score drydock
---

# FEATURE DDF-008: Pin compact derivatives to their source digest instead of mtime

| Field | Value |
|---|---|
| Area | rigging |
| Impact | 7/10 |
| Complexity | 3/10 |
| Rank | 11 |
| Project Types | All, Web application, API service |

## Problem

Compaction freshness is an mtime comparison surfaced as a warning, and the Specification itself documents `touch` as the way to suppress it. A stale `DATABASE_compact.md` is therefore injected silently into downstream feature builds, which then implement a superseded persistence interface with no drift signal anywhere — the exact failure the `applied_specs` sha256 mechanism was built to prevent for full specs.

## Intent

Specification `Compaction` — `Use of Full files and Compact files is determined automatically by the build graph` and `Drydock track compaction`; `Complete change-management methodology` — `Track cksum and git commit ids for built blueprints`.

## Evidence

Specification `Compaction`: `drydock plan warns when a source is newer than its derivative... To control this you can touch the files to change the compacted file create time to later than the main file.`

## Recommendation

Compaction writes `source_path` and `source_sha256` into the derivative's metadata header, using the same JSON-backed prompt-header mechanism the codebase already has. `drydock build` refuses to inject a compact whose recorded digest differs from the current source digest: it recompacts (already documented behavior) and re-pins, or fails the step when recompaction is unavailable. `rigging verify` reports every digest mismatch. The mtime comparison and the `touch` workaround are removed.

## Stories

### Story 1: Digest-stamped compact derivatives

As the Commander, I want each compact file to record what it was made from, so that staleness is a fact rather than a timestamp guess.

**Acceptance Criteria**

- `drydock rigging compact` writes `source_path` and `source_sha256` into every generated `*_compact.md`.
- Recompacting an unchanged source produces a byte-identical file including the stamp.
- A compact file with no stamp is treated as stale, not as fresh.

**Tests (RED first)**

- tests/test_rigging_compact.py::test_compact_records_source_digest
- tests/test_rigging_compact.py::test_unchanged_source_produces_identical_compact
- tests/test_rigging_compact.py::test_unstamped_compact_is_treated_as_stale

### Story 2: Build refuses stale compacts

As the Commander, I want a build to never inject a compact that no longer describes its source, so that a story cannot be built against a dead interface.

**Acceptance Criteria**

- Given a modified `DATABASE.md` and an unrefreshed `DATABASE_compact.md`, `drydock build` regenerates the compact before assembling the prompt and the assembled prompt contains the new content.
- When regeneration is unavailable, the step fails with a named error identifying the stale derivative, and no LLM call is made.
- A fresh compact is injected with no extra work and no extra LLM call.

**Tests (RED first)**

- tests/test_build_run.py::test_stale_compact_is_regenerated_before_assembly
- tests/test_build_run.py::test_unregenerable_stale_compact_fails_before_llm
- tests/test_build_run.py::test_fresh_compact_causes_no_recompaction

### Story 3: Verification and removal of the mtime path

As the Commander, I want one truthful staleness signal, so that no workaround can hide drift.

**Acceptance Criteria**

- `drydock rigging verify` lists each compact whose recorded digest does not match its source and exits non-zero.
- No code path compares source and derivative modification times.
- `drydock plan`'s compaction warning names the digest mismatch, not the timestamp.

**Tests (RED first)**

- tests/test_rigging_verify.py::test_digest_mismatch_is_reported_and_exits_nonzero
- tests/test_rigging_compact.py::test_no_mtime_comparison_remains
- tests/test_planning_session.py::test_plan_warning_names_digest_mismatch

## Definition of Done

- Every compact derivative on disk carries a source digest after one `drydock rigging compact --all` run.
- Touching a file no longer changes any staleness decision anywhere in the system.
- A stale compact can no longer reach a build prompt.

## Implementation Plan

1. Extend `rigging_compact.py` to compute the source sha256 and write it through `prompt_headers.py`, matching the existing metadata convention for prompt-facing files.
2. Add `compact_is_current(source, derivative) -> bool` in `rigging_compact.py`; have `build.py` call it during context selection and trigger regeneration through the documented auto-compaction path.
3. Remove the mtime comparison from the plan warning and from any freshness gate; replace with the digest check.
4. Extend `rigging_verify.py` to report mismatches and set a non-zero exit.
5. Update the Specification's Compaction guidance text in `prompts/BLUEPRINTS_CONTRACT.md` where it references derivative freshness.
6. Add tests in `tests/test_rigging_compact.py`, `tests/test_rigging_verify.py`, and `tests/test_build_run.py`.

## Specification Impact

The `Compaction` section's freshness paragraph, including the `touch` guidance, would need the author's approval to be replaced with the digest rule.

## Risks

- Auto-recompaction during a build spends an LLM call mid-step; this must be logged as a distinct job in `logs/llm.jsonl` so cost attribution stays honest.
- The `output it VERBATIM unless the contract changed` rule in the three compaction prompts is what keeps re-pinning cheap; if a model ignores it, digests churn and recompaction becomes frequent.

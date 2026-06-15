# SURVEY-SPEC: drydock analyze

| Field       | Value |
|-------------|-------|
| Version     | 20260613 V1 |
| Description | Acceptance authority for `drydock analyze` — conform/assess the Blueprint before planning. |
| Command     | drydock analyze |
| Scored In   | Survey/scores.jsonl |
| Source      | src/drydock/analyze.py (to be built) · prompts/analyze.md · docs/SPEC_ANALYZE.md |

## Goal

Before any plan is drawn, a user knows whether the Blueprint is **ready**: its files form a
consistent dependency graph, its project type is identified, its required files and sections are
present, its stack is declared, and its open questions are captured as spike candidates. Where a
genuine unknown blocks planning, analyze raises a questionnaire instead of guessing.

## Acceptance Criteria — Code

| ID | Criterion | Dim | Check | Weight | Verify |
|----|-----------|-----|-------|--------|--------|
| ANL-C1 | Builds a dependency graph from typed headers, topologically ordered | D1 | A | 3 | parse graph table order vs `Depends On` |
| ANL-C2 | Classifies project type; ambiguous → questionnaire item | D1 | J | 2 | type vs known blueprint shape |
| ANL-C3 | Completeness check reports each missing required file/section | D1 | A | 2 | inject a gap, assert it appears |
| ANL-C4 | Stack gate emits `stack_declaration` when stack absent/empty/TBD | D1 | A | 2 | clear stack, assert item present |
| ANL-C5 | Every non-`None.` Open Question becomes a spike candidate | D1 | A | 2 | count bullets == candidates |
| ANL-C6 | Readiness verdict matches rules (blocked when COMPASS absent) | D1 | A | 2 | remove COMPASS, assert `blocked` |
| ANL-E1 | Hard gate: METADATA absent → exit 1; any verdict otherwise → exit 0 | D5 | A | 1 | exit-code tests |

## Acceptance Criteria — Specification

| ID | Criterion | Dim | Check | Weight | Verify |
|----|-----------|-----|-------|--------|--------|
| ANL-D1 | `ANALYSIS.md` has all required sections from SPEC_ANALYZE.md | D2 | A | 2 | section presence check |
| ANL-D2 | `planning.json` is valid JSON; items carry `gate: plan_create` where required | D2 | A | 2 | JSON parse + schema |
| ANL-D3 | Deterministic work (graph, completeness, gates) does **not** require an LLM | D4 | A | 2 | survey runs graph/gate checks with no model call |
| ANL-D4 | LLM writes only prose sections; module writes files | D3 | A | 1 | output-write path is in the module |

## Guardrails

- Analyze must not create or modify `MANIFEST.md`.
- Analyze must not modify any Blueprint spec file.
- Outputs go only to `<Target>/QuarterDeck/planning/` and `…/questionnaires/`.
- A `blocked` verdict must not cause a non-zero exit (advice, not failure).

## Open Questions

- When `<Target>` code exists, what is the minimum viable drift check (routes/commands only, or
  deeper)? Where drift detection is uncertain, prefer reporting "unknown" over a false gap.

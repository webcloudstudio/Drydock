# SURVEY-SPEC: drydock import

| Field       | Value |
|-------------|-------|
| Version     | 20260613 V1 |
| Description | Acceptance authority for `drydock import` — bringing source material into a Blueprint. |
| Command     | drydock import |
| Scored In   | Survey/scores.jsonl |
| Source      | src/drydock/import_markdown.py, import_source.py, import_speckit.py |

## Goal

A user can bring existing material — a Markdown bundle, a source tree, or a Spec Kit project — into
a Target's Blueprint **without losing information**. Markdown is preserved verbatim under
`sources/`; source and Spec Kit imports produce Blueprint files plus an honest conversion report
that names what was and was not translated.

## Acceptance Criteria — Code

| ID | Criterion | Dim | Check | Weight | Verify |
|----|-----------|-----|-------|--------|--------|
| IMP-C1 | `--format markdown` preserves the bundle under `<Target>/blueprint/sources/` byte-faithful | D1 | A | 3 | hash source vs preserved |
| IMP-C2 | `--format source` assembles the prompt and writes Blueprint files | D1 | A | 2 | `test_import_source.py` |
| IMP-C3 | `--format speckit` translates to Blueprint and emits a conversion report | D1 | A | 2 | `test_import_speckit.py` |
| IMP-C4 | `--format auto` detects format from the source layout | D1 | A | 2 | detection test per layout |
| IMP-E1 | Unreadable/empty source fails with exit 1 and a clear message | D5 | A | 1 | point at empty dir |

## Acceptance Criteria — Specification

| ID | Criterion | Dim | Check | Weight | Verify |
|----|-----------|-----|-------|--------|--------|
| IMP-D1 | Imported Blueprint files conform to BLUEPRINTS_CONTRACT header format | D2 | A | 2 | parse typed headers |
| IMP-D2 | Conversion report names every source artifact and its disposition (translated / skipped / lossy) | D2 | J | 2 | read report |
| IMP-D3 | No source content silently dropped | D3 | J | 2 | spot-check report vs source inventory |

## Guardrails

- Import (markdown) must be file-copy only — no LLM call, no content rewriting (per current spec).
- Import must write only inside the target Blueprint; never modify the source tree.
- Import must not invent specification content the source does not support.

## Open Questions

- For `--format source`, what is the boundary between "decompose into FEATURE/SCREEN files" and
  "preserve verbatim"? Where the LLM is uncertain, does it create a spike rather than guess?

# DESIGN: drydock prompt

| Field | Value |
|---|---|
| Version | 2026-10-15 V1 |
| Route | prompt |
| Modules | `prompt_review.py` |
| Prompts | `prompt_review.md` |
| Tests | `tests/test_prompt_review.py` |
| Topics | — |
| Pending spec | 0 |
| Pending impl | 0 |

## Behavior

### Purpose

Hidden command. `prompt review <component>` critiques one LLM prompt contract against its
specification section, its design file, and its consumer contracts, and writes a scored review.

### Syntax

```text
drydock prompt review <component>     components: analyze, plan
```

### Rules

`2026-10-22` · **Structured model calls declare their output format to `llm.run_prompt`.**
The adapter strips only bounded plain narration around intact artifact envelopes or one complete
JSON object/array; it also removes a surrounding JSON code fence. It preserves artifact bodies,
JSON values, and original execution output. The execution record reports removed spans, cleanup
defects, and the normalized payload hash. Ambiguous output remains unchanged for the command's
validators and existing bounded recovery; the adapter does not add model calls. JSON consumers
reject duplicate keys, non-JSON numeric constants, and content-shaped surrounding text. Format
cleanup does not replace the command's schema or semantic checks. *Broken:* wrapper narration
pollutes an artifact, or broad substring extraction silently hides malformed output.

`2026-06-15` · **A review is assembled from four sources.** The prompt file, its design file
(`design/commands/<command>.md`, `2026-10-15`), one named specification section, and support
files. Each is required; a missing one fails before any model call. Cost when broken: a review
scored against a partial picture.

`2026-06-15` · **The score is computed, not asserted.** Five weighted categories —
`spec_alignment` 0.30, `input_realism` 0.20, `output_contract_safety` 0.20,
`analytical_effectiveness` 0.20, `ambiguity_control` 0.10 — produce the overall score and band
(`Strong` ≥ 9.0, `Workable` ≥ 7.5, `Brittle` ≥ 6.0, else `Needs Rewrite`). Cost when broken: a
model-reported score that cannot be compared across runs.

`2026-06-15` · **A new review archives the previous one.** Reviews are written to
`docs/prompt_reviews/<component>.md`; the prior review moves to `archive/` stamped with time and
model. Cost when broken: no trend across prompt revisions.

### Mechanism

1. Resolve the component. 2. Read prompt, design file, specification section, support files.
3. One review call. 4. Compute scores, archive the prior review, write the new one.

### Exit codes

| Code | Condition |
|---|---|
| `0` | Review written. |
| `1` | Missing input file, missing specification section, or LLM failure. |
| `2` | Unknown component or usage error. |

### Spec divergence

- The specification does not document `drydock prompt`.

## Decisions

-

## Open Questions

1. **Both components are broken today.** `analyze` cites `### Analyze Your Specification` and
   `plan` cites `### Building and Reviewing the Build Plan / Manifest`; neither heading exists in
   the current specification, so every review raises `spec section not found`. Repoint them to
   `### drydock analyze` and `### drydock plan`?

## Open Actions

- Repoint both components' `spec_heading` once Open Question 1 is answered.

## Working Notes

-

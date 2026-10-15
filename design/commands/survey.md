# DESIGN: drydock survey

| Field | Value |
|---|---|
| Version | 2026-10-15 V1 |
| Route | survey |
| Modules | `survey.py` |
| Prompts | `survey.md`, `survey_import.md` |
| Tests | `tests/test_survey*.py` |
| Topics | — |
| Pending spec | 0 |
| Pending impl | 0 |

## Behavior

### Purpose

Hidden command. Score a Target's build process and specifications against per-command
acceptance criteria and emit generalized, actionable fixes. `score` measures the delivered
product; `survey` measures process and specification quality.

### Syntax

```text
drydock survey <Target> [--command <name>] [--raw]    render the scoreboard (no LLM)
drydock survey <Target> --run [--command <name>]      score each command and append results
drydock survey <Target> --import <path>               regenerate survey/ac/SURVEY-<command>.md
```

### Rules

`2026-06-13` · **The model judges; the module scores.** The LLM marks each criterion `pass`,
`partial`, or `fail` and writes recommendations; `survey.py` computes every number. Cost when
broken: scores that cannot be reproduced.

`2026-06-13` · **The scoring function is fixed and deterministic.**

**Five dimensions, fixed weights:**

| Dim | Weight | Measures |
|-----|--------|----------|
| D1 | 0.30 | Behavioral correctness (code AC) |
| D2 | 0.25 | Specification quality (spec/artifact AC) |
| D3 | 0.20 | Process integrity (guardrails, unresolved uncertainty) |
| D4 | 0.15 | Evidence & reproducibility |
| D5 | 0.10 | Contract conformance (names, paths, exit codes) |

- Result value: `pass=1.0`, `partial=0.5`, `fail=0.0`.
- Dimension score = `100 × Σ(weight·value) / Σ(weight)` over that dimension's assessed AC.
- Composite = weighted mean of assessed dimensions, redistributed across only the assessed dimensions.
- `provisional = true` when not every dimension that has AC was assessed.

**Bands:** `SEAWORTHY` ≥ 90 · `SEA_TRIALS` ≥ 75 · `TAKING_WATER` ≥ 60 · `DRY_DOCK` < 60.
A `guardrail-breach` or `regression` flag caps the band at `TAKING_WATER` regardless of score.

**Root-cause flags:** `guardrail-breach`, `unresolved-uncertainty`, `contract-drift`,
`missing-evidence`, `decomposition-defect`, `regression`, `incomplete`.

`2026-06-13` · **`scores.jsonl` is append-only.** One record per command per run under
`targets/<Target>/survey/`; a prior line is never rewritten. Cost when broken: lost history of
process quality.

`2026-06-13` · **`--command` uses `dest="command_filter"`.** A bare `--command` collides with the
top-level subparsers' `dest="command"` and silently nulls the dispatch. Cost when broken: every
survey invocation dispatches nothing.

### Mechanism

1. Default: render the scoreboard from `scores.jsonl`.
2. `--run`: assemble criteria and artifacts, one judging call per command, compute, append, render.
3. `--import`: read `<path>/*.md`, regenerate the criteria files, exit.

### Exit codes

| Code | Condition |
|---|---|
| `0` | Success. |
| `1` | Missing criteria directory, LLM failure. |
| `2` | Usage error, missing Target. |

### Spec divergence

- The specification does not document `drydock survey`.

## Decisions

-

## Open Questions

-

## Open Actions

-

## Working Notes

-

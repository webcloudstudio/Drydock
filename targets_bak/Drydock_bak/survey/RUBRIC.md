# Survey Rubric — Generalized Scoring Function

**Version:** 20260613 V1
**Applies to:** every Drydock command/process. The same function scores `status`, `import`,
`analyze`, `plan create`, `init`, and every command added later — so all processes are comparable
on one scale.

---

## Five dimensions

Every command is scored on the same five dimensions. Each dimension is the weighted pass-rate of
the AC items assigned to it in `ac/SURVEY-<command>.md` (each AC declares its dimension).

| # | Dimension | Weight | What it measures |
|---|-----------|--------|------------------|
| D1 | Behavioral correctness | 0.30 | Does the command do what its **code AC** says (the observable behavior)? |
| D2 | Specification quality | 0.25 | Does the produced/conformed **spec or artifact** meet the standard (its **spec AC**)? |
| D3 | Process integrity | 0.20 | Were guardrails honored? Were Open Questions / spikes resolved **before** implementing, not bypassed? |
| D4 | Evidence & reproducibility | 0.15 | Is there evidence in `logs/` or `evidence/`? Can the result be re-derived deterministically? |
| D5 | Contract conformance | 0.10 | Correct exit codes, output contract, file names, and file locations. |

**Dimension score** = `100 × (Σ weight of passing AC in the dimension) / (Σ weight of all AC in the dimension)`.
A partially-met AC scores proportionally (e.g. "last 10" when only 5 are returned = 0.5).

**Command score** = `Σ (dimension_weight × dimension_score)`, rounded to integer 0–100.

If a dimension has no AC for a command, redistribute its weight proportionally across the
dimensions that do. Record which dimensions were assessed; a survey that skips a dimension is
flagged `incomplete` and the score is marked provisional.

---

## Check types

| Type | Cost | How it runs |
|------|------|-------------|
| `assertion` | No LLM | A shell command, file test, or parse that returns pass/fail/partial. Reproducible by `drydock survey`. **Prefer this.** |
| `judgment` | LLM | Read prose/evidence and rate quality or detect uncertainty. Used only where correctness is not mechanically decidable. |

Every AC in a Surveyor spec declares its check type. The phase target is **assertion-first**: most AC
should be assertions so the score is reproducible without spending tokens.

---

## Score bands (nautical)

| Band | Range | Meaning | Gate |
|------|-------|---------|------|
| `SEAWORTHY` | 90–100 | DONE-quality. Ship it. | Phase-done gate per command |
| `SEA_TRIALS` | 75–89 | Works; minor defects, no guardrail breach. | Acceptable to proceed, fix listed |
| `TAKING_WATER` | 60–74 | Material gaps or a contract drift. | Do not build on top; fix first |
| `DRY_DOCK` | < 60 | Broken, or a guardrail breach. | Stop. Re-plan the command. |

A `guardrail-breach` or `regression` flag caps the band at `TAKING_WATER` regardless of the
numeric score — a breach is never "minor."

---

## Root-cause flags

Attached per survey to make the score actionable. Each flag pairs with a one-line note naming the
file/AC and the fix.

| Flag | Meaning |
|------|---------|
| `guardrail-breach` | A declared guardrail was violated. |
| `unresolved-uncertainty` | An Open Question / spike was bypassed and the work implemented anyway. |
| `contract-drift` | Output, file name, or location diverges from the contract (for example a legacy build-plan filename vs `MANIFEST.md`). |
| `missing-evidence` | No reproducible evidence in `logs/` or `evidence/`. |
| `decomposition-defect` | Scrum Master finding: bad story/AC/spike granularity, ordering, or dependency. |
| `regression` | A previously-passing AC now fails. |
| `incomplete` | Survey could not assess every dimension; score is provisional. |

---

## scores.jsonl record schema (v1)

One JSON object per line, append-only. Never rewrite a prior line.

```json
{
  "schema": 1,
  "recorded_at": "2026-06-13T00:00:00",
  "command": "drydock status",
  "surveyed_commit": "cae9e8f",
  "run_ref": "code-read | logs/executions.jsonl#<id> | manual",
  "dimensions": { "D1": 70, "D2": null, "D3": null, "D4": null, "D5": 50 },
  "assessed": ["D1", "D5"],
  "score": 64,
  "band": "TAKING_WATER",
  "provisional": true,
  "flags": ["contract-drift", "incomplete"],
  "ac": [
    { "id": "STATUS-C3", "result": "partial", "note": "history limit=5; AC requires 10" },
    { "id": "STATUS-D2", "result": "fail", "note": "reads a legacy build-plan filename; MANIFEST_CONTRACT says MANIFEST.md" }
  ],
  "actions": [
    "status.py: raise history limit 5 -> 10",
    "status.py: read MANIFEST.md and load_target_plan, drop legacy build-plan filename references"
  ]
}
```

The first line of `scores.jsonl` is a `{"schema":1,"type":"meta",...}` marker; data records follow.

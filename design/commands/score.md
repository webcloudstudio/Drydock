# DESIGN: drydock score

| Field | Value |
|---|---|
| Version | 2026-10-15 V1 |
| Route | score |
| Modules | `score.py`, `score_spec.py`, `score_report.py`, `score_drydock.py`, `scorecard.py`, `sea_trials.py`, `acceptance.py`, `llm_usage.py` |
| Prompts | `score_spec.md`, `score_release.md`, `score_drydock.md` |
| Tests | `tests/test_score*.py`, `tests/test_sea_trials*.py`, `tests/test_gate_policy*.py` |
| Topics | [acceptance_criteria](../topics/acceptance_criteria.md) |
| Pending spec | 0 |
| Pending impl | 0 |

## Behavior

### Purpose

Close out a project: audit the imported specification, verify story acceptance, report build
evidence, judge release readiness against Sea Trials, and publish a sealed receipt. Each command
stamps its verdict onto one regenerated `SCORECARD.md`, which is the project's retrospective.

### Syntax

```text
drydock score spec <Target>                      SPECIFICATION_SCORECARD.md (LLM, advisory)
drydock score ac <Target> [--step <id>] [--full] SOUNDINGS.md (deterministic)
drydock score build <Target>                     build evidence report (deterministic)
drydock score llm [<Target>] [--all|--include-incomplete]
drydock score release <Target>                   acceptance gate + LLM Sea Trials judgment
drydock score report <Target>                    drydock_receipt/index.html, sealed
drydock score drydock                            self-assessment → docs/drydock_planning/
drydock score <Target>                           read-only summary of the last runs
```

`--step` is accepted only with `score ac`.

### Rules

`2026-08-21` · **`SCORECARD.md` is rebuilt whole, never merged.** Every score command regenerates
it from `PROJECT_STATUS.jsonl` (which stamps ran, when, pass/fail) joined with each command's own
evidence: `SPECIFICATION_SCORECARD.md`, `SOUNDINGS.md`, the build report,
`evidence/score-release.json`, and material `DECISIONS.json` entries. `PROJECT_STATUS.jsonl` stays a
thin fact log; narrative lives in evidence files. Cost when broken: one score command clobbers
another's section.

`2026-08-21` · **Every score command stamps its own approval.** `spec`, `ac`, `build`, and
`release` each record a quoted Markdown stamp — verb, command, UTC timestamp. `ac` and `build`
regenerate only on a whole-Target run, not `--step`. `score spec` is not on the status ladder; its
stamp uses the `SPECIFICATION_SCORECARD.md` mtime. Cost when broken: a retrospective that cannot
say which checks ran.

`2026-08-10` · **Sea Trials separate testability from consequence.** Each criterion declares
`Testability` (`deterministic`, `judgeable`, `neither`) and `Consequence` (`blocks`, `scores`,
`attests`) as independent columns. When undeclared, testability derives from `Verification` and
consequence is `blocks` for a guardrail or required criterion, else `scores`. Cost when broken:
declaring a prohibition unprovable and declaring it harmless became the same statement — the
guardrail-hardening loop.

`2026-08-10` · **Gate severity is data in `SEA_TRIALS.md`, not code.** The default policy: on
`FAIL`, `blocks` fails the gate, `scores` costs marks, `attests` is reported; on `INCONCLUSIVE`,
`blocks` becomes a human attestation. A demonstrated shortfall fails; an unsettled one never
does. Cost when broken: a definition of done hardens into a gate no correct build can pass.

`2026-08-10` · **Story acceptance is reported, not consumed by the release gate.** `score ac`
verifies every Programmatic Acceptance assertion with no LLM and updates Soundings; `FAIL` exits
`1`, `UNVERIFIED` is shown but does not fail. `score release` runs the governed acceptance gate,
then an LLM judges Sea Trials. Cost when broken: two definitions of done collapse into one brittle
gate.

`2026-08-21` · **`score build` is deterministic and still gates.** It reads logs only — acceptance,
repairs, tokens, cache hit rate — and exits `1` on missing evidence or unverified blocks, by
decision. Cost when broken: a build with no evidence reads as clean.

`2026-08-21` · **`score report` publishes; it never re-scores.** It seals
`targets/<Target>/drydock_receipt/index.html` with a workspace snapshot and record JSON, reading
`SCORECARD.md` as one input. `score <Target>` only reads. Cost when broken: the receipt describes a
different verdict than the scorecard.

### Mechanism

1. Run the sub-command against recorded state or the built tree.
2. Record its rung in `PROJECT_STATUS.jsonl`.
3. Regenerate `SCORECARD.md` (whole-Target `spec`, `ac`, `build`, `release`).
4. `report` assembles the receipt fresh from every source on each run.

### Exit codes

| Code | Condition |
|---|---|
| `0` | Pass: `ac` has no `FAIL`; `release` verdict `PASSED`; summaries and reports written. |
| `1` | `ac` has a `FAIL`; `release` not `PASSED`; `build` missing evidence or unverified blocks; operational failure. |
| `2` | Usage error, including `--step` outside `score ac`. |

### Spec divergence

- The specification omits `score llm` and `score drydock`.
- The specification does not state that every score command regenerates `SCORECARD.md`, or that
  `score build` exits `1` on missing evidence.

## Decisions

-

## Open Questions

1. **Two release verdict channels.** `score report` carries a `LABEL_LADDER` workflow stamp and a
   separate `_receipt_checks()` exit-code table. Unify them now that `SCORECARD.md` carries stamped
   state? (Carried from notes, "Not in scope yet".)

## Working Notes

-

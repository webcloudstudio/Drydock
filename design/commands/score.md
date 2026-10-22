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

`2026-10-22` · **Structured model calls declare their output format to `llm.run_prompt`.**
The adapter strips only bounded plain narration around intact artifact envelopes or one complete
JSON object/array; it also removes a surrounding JSON code fence. It preserves artifact bodies,
JSON values, and original execution output. The execution record reports removed spans, cleanup
defects, and the normalized payload hash. Ambiguous output remains unchanged for the command's
validators and existing bounded recovery; the adapter does not add model calls. JSON consumers
reject duplicate keys, non-JSON numeric constants, and content-shaped surrounding text. Format
cleanup does not replace the command's schema or semantic checks. *Broken:* wrapper narration
pollutes an artifact, or broad substring extraction silently hides malformed output.

`2026-10-19` · **`score ac` and `score release` require `postgres_dsn` for a `postgres.md`
stack** and export it as `DATABASE_URL`, as build does. Cost when broken: scoring observes a
SQLite store the stack did not select.

`2026-08-13` · **Release observes the finished tree; build history is not evidence.** `score
release` runs the governed gate and every command a trial names, reads the files trials cite, and
lets the grader write an ephemeral probe for a behavior with no command. AC results, block states,
and the Manifest are never read. *Broken:* a release verdict inherited from block 3 that block 7
broke.

`2026-08-13` · **Three trial verdicts, three run verdicts.** Trials are `MET`, `NOT MET` (must cite
what the grader saw), or `MANUAL` (no machine can settle it; attested, never blocking). The run is
`PASSED`, `FAILED`, or `ERROR` (Drydock could not grade). Inference may raise a trial to `MET`,
never to `NOT MET`. *Broken:* a finished, correct project reported `INCOMPLETE` five times
(ReadingList `20260814.001652`).

`2026-08-13` · **Probes are the only model-authored tests that grade.** A probe is written after the
code exists, against source the grader read, and discarded after one verdict. No repair budget at
score. *Broken:* predicted expectations decide release.

`2026-08-13` · **Sea Trials are referenced by nothing.** Trials flow into `plan` as context; no AC,
proof tag, or `Verification:` value points back or selects a mechanism. *Broken:* a missing tag
reads as a missing capability (D-026).

`2026-08-10` · **Sea Trials keep testability and consequence as separate columns.** `Testability`
(`deterministic`, `judgeable`, `neither`) and `Consequence` (`blocks`, `scores`, `attests`) are
parsed independently. *Broken:* "unprovable" and "harmless" collapse into one statement.

`2026-08-10` · **Story acceptance is reported, never consumed by release.** `score ac` runs every
Programmatic Acceptance assertion with no LLM and writes `SOUNDINGS.md`; `FAIL` exits `1`,
`UNVERIFIED` is shown only. *Broken:* two definitions of done collapse into one brittle gate.

`2026-08-21` · **`SCORECARD.md` is rebuilt whole by every score command.** It is rendered from
`PROJECT_STATUS.jsonl` plus each command's evidence; each command adds a quoted stamp (verb,
command, UTC time). `ac`/`build` regenerate only on whole-Target runs. *Broken:* one command
clobbers another's section.

`2026-08-21` · **`score build` is deterministic and still gates.** Logs only; exits `1` on missing
evidence or unverified blocks, by decision. *Broken:* a build with no evidence reads clean.

`2026-08-21` · **`score report` publishes; it never re-scores.** It seals `drydock_receipt/`,
reading `SCORECARD.md` as one input. `score <Target>` only reads. *Broken:* receipt and scorecard
disagree.

`2026-10-15` · **`score release` exits `1` unless `PASSED`.** This reverses the UAT gate model's
X-2 rule (`PASSED` and `FAILED` exit `0`, only `ERROR` exits `1`). Exit codes follow shell
convention; a command documents its own meaning in its exit table, as `status --check` does.

### Mechanism

1. Run the sub-command against recorded state or the built tree.
2. Record its rung in `PROJECT_STATUS.jsonl`.
3. Regenerate `SCORECARD.md` (whole-Target `spec`, `ac`, `build`, `release`).
4. `report` assembles the receipt fresh from every source on each run.

### Exit codes

| Code | Condition |
|---|---|
| `0` | `ac` has no `FAIL`; `release` verdict `PASSED`; summaries and reports written. |
| `1` | `ac` has a `FAIL`; `release` `FAILED` or `ERROR`; `build` missing evidence or unverified blocks; operational failure. |
| `2` | Usage error, including `--step` outside `score ac`. |

### Spec divergence

- The specification omits `score llm` and `score drydock`.
- The specification does not state that every score command regenerates `SCORECARD.md`, or that
  `score build` exits `1` on missing evidence.

## Decisions

-

## Open Questions

1. **Two release verdict channels.** `score report` carries a `LABEL_LADDER` workflow stamp and a
   separate `_receipt_checks()` exit-code table. Unify them?
2. **Does `accepts:` retire with proof tags?** The direction rule says no build-layer reference
   points back to a trial; `accepts:` is the only human-readable record of which trial motivated a
   block, and gates nothing. Recorded as *retire*, never settled explicitly.
3. **Is the ephemeral probe stored as evidence?** It must be, to serve as a `NOT MET` citation:
   per-run under `evidence/`, or inlined in the verdict?

## Open Actions

-

## Working Notes

-

# DESIGN: drydock analyze

| Field | Value |
|---|---|
| Version | 2026-10-15 V1 |
| Route | analyze |
| Modules | `analyze.py`, `sea_trials.py`, `technology_stack.py`, `quarterdeck_state.py` |
| Prompts | `analyze.md` |
| Tests | `tests/test_analyze*.py`, `tests/test_sea_trials*.py` |
| Topics | [foundations](../topics/foundations.md) |
| Pending spec | 0 |
| Pending impl | 0 |

## Behavior

### Purpose

Read every imported source once and hand the Commander a reviewable decomposition: a story list,
Sea Trials, blockers, and questions. Analyze proposes; the Commander ratifies. Nothing the Commander
has decided may be lost to a rerun, because the Commander reruns Analyze until Quality is `Ready`.

### Syntax

```text
drydock analyze <Target> [--model <model>] [--llm-provider <p>]
```

### Rules

`2026-06-18` · **A rerun never destroys a Commander answer.** Existing questionnaires are never
overwritten (identity refreshes from `METADATA.md`); `TECHNOLOGY_STACK.md` and `ANALYZE_COMPASS.md`
are proposed once; `COMPASS.md` is written only when absent, unpopulated, or pending import;
Commander story guidance merges over derived; `METADATA.md` backfills only blanks. *Broken:*
settled questions re-asked every loop.

`2026-06-16` · **`BLOCKERS.md` exists only when a real blocker does.** Written from a validated
block, deleted otherwise; an empty block fails closed.

`2026-06-22` · **Quality is computed.** `Blocked` if `BLOCKERS.md` was written, `Questions` if any
questionnaire is open, else `Ready`; the model's line is overwritten.

`2026-07-29` · **Imported prose is always read.** `EXCLUDE_FILES` limits injection only; the
inventory covers every file and withheld content warns. *Broken:* a withheld spec is a lost story.

`2026-07-18` · **Sea Trials admission is structural.** Unparseable `SEA_TRIALS.md` is not written
and becomes a blocker; EARS and plain English are both accepted.

`2026-08-10` · **A Commander `SEA_TRIALS.md` is exclusive.** The model's trials are discarded, not
merged. *Broken:* the model writes its own exam.

`2026-08-22` · **Unattended runs answer their own questions.** Under `DRYDOCK_UAT=1` ambiguities
are resolved from sources and Compass and recorded; questionnaires and blockers are dropped.

`2026-07-18` · **Analyze reads the Rigging catalog, never the rule files.** `Rigging/MANIFEST.md`
supplies filename, category, purpose, and prerequisites; unknowns stay visibly unset.

`2026-07-18` · **One output protocol, fixed order:** `ANALYSIS.md`, `SEA_TRIALS.md`, `BLOCKERS.md`,
`COMPASS.md`, identity questionnaire, stack questionnaire, then other questionnaires lexically.
A questionnaire never resolves a blocker.

`2026-10-21` · **A reply without artifacts is retried once, with the reason.** A successful reply that holds no artifact delimiter — prose, a question, a refusal — prints
`[analyze] response without artifacts, retrying once with the reason: "<excerpt>"` and reruns the
unchanged prompt with an appended `Artifact retry` block that quotes the reply and forbids asking,
refusing, or explaining; an unattended run states that no Commander is available. A second such reply fails the ordinary parse. Shared mechanism:
`artifact_blocks.retry_reply_without_artifacts`. *Broken:* LayersTesting `20261021.180733`
ended at analyze when Haiku asked which output form to use instead of emitting.

`2026-10-21` · **Stray text is discarded, never fatal.** Up to three lines of plain narration
before, between, or after intact artifact blocks are dropped and printed as `[analyze] stray text
<where> discarded: "<text>"`. Outside text shaped like content — a heading, list, table, fence,
JSON, markup, `===`, more than three lines or 500 characters — or beside an orphan close still fails
the parse. *Broken:* a weak model's one-line preamble fails the run, or a body that lost its opener
is silently dropped.

### Mechanism

1. **Seed** — clear errors, collect sources, seed `COMPASS.md`, create `ANALYZE_COMPASS.md` and
   `EXCLUDE_FILES`.
2. **Assemble and execute** — one call with sources, Compass, feedback, prior blockers and
   questionnaires, the Rigging catalog, and identity.
3. **Parse and admit** — artifact defects, Commander Sea Trials rule, `METADATA.md` backfill.
4. **Write** — analysis, trials, Compass, questionnaires, stack, blockers.
5. **Finalize** — compute Quality, merge story guidance, stamp `analyzed`, create
   `PLAN_COMPASS.md`, refresh the Commanders Chair.

### Exit codes

| Code | Condition |
|---|---|
| `0` | Analysis written, including when Quality is `Blocked` or `Questions`; blockers are rendered and the `ANALYZED` rung is recorded. |
| `1` | Provider or parse failure; `ANALYZED` recorded failed. |
| `2` | Usage error. |

### Spec divergence

- The specification lists stories, questionnaires, blockers, and `SEA_TRIALS.md` as outputs.
  Analyze also writes `TECHNOLOGY_STACK.md`, `ANALYZE_COMPASS.md`, `EXCLUDE_FILES`,
  `PLAN_COMPASS.md`, and `COMPASS.md` when absent or unpopulated.
- The specification does not state that a `Blocked` analysis exits `0`; the halt is enforced by
  `drydock plan`, not by Analyze's exit status.

## Decisions

-

## Open Questions

-

## Open Actions

-

## Working Notes

-

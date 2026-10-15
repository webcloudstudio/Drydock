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

`2026-06-16` · **`BLOCKERS.md` exists only when a real blocker does.** Its presence is the flag that
halts planning. It is written only from a validated, structured block and deleted otherwise; an
empty or placeholder block fails closed. Cost when broken: planning parked on a blocker with no
content, or a genuine blocker silently dropped.

`2026-06-18` · **A rerun never destroys a Commander answer.** An existing questionnaire is never
overwritten; the identity questionnaire only refreshes its answers from `METADATA.md`.
`TECHNOLOGY_STACK.md` (`2026-07-30`) and `ANALYZE_COMPASS.md` are proposed once and owned by the
Commander thereafter. `COMPASS.md` is written only when absent, unpopulated, or pending an import.
Commander story-guidance entries are loaded first and merged over derived ones (`2026-08-17`).
`METADATA.md` fields are backfilled only when blank and only from a concrete value. Cost when
broken: settled questions re-asked and hand-edited decisions erased on every loop.

`2026-06-22` · **Quality is computed, not reported.** `Blocked` if `BLOCKERS.md` was written,
`Questions` if any questionnaire is open, otherwise `Ready`; the model's summary line is
overwritten with that result. Cost when broken: a model-asserted `Ready` admits an unreviewed plan.

`2026-07-18` · **Sea Trials admission is structural only.** A `SEA_TRIALS.md` that cannot be parsed
into criteria is not written and becomes a blocker. Wording is not admission: EARS and plain
English are both accepted. Cost when broken: Plan and scoring proceed with no machine-usable
release criteria.

`2026-07-29` · **Imported prose is always read.** `EXCLUDE_FILES` controls prompt injection only;
the source inventory in `ANALYSIS.md` covers every imported file, and withheld content raises a
warning. Cost when broken: a withheld specification is a lost story.

`2026-08-10` · **A Commander `SEA_TRIALS.md` is exclusive.** When one exists the model's Sea Trials
output is discarded, not merged. Cost when broken: the model writes the exam it is graded on, and
runs stop being comparable.

`2026-08-22` · **An unattended run answers its own questions.** Under `DRYDOCK_UAT=1` the prompt
carries the Unattended UAT policy: resolve each ambiguity from sources, Compass, fixture inputs, and
stated precedence, choose the narrowest consistent behavior, and persist that choice in the
analysis. Questionnaires and blockers are dropped even if the provider emits them. Cost when broken:
a UAT run halts on a question no one is present to answer.

`2026-07-18` · **Analyze reads the Rigging catalog, never the rule files.** `Rigging/MANIFEST.md`
is injected as the compact catalog of every selectable `Rigging/stack/*.md` source and every
`Rigging/BRA*.md` file: filename, category, purpose, and prerequisites where known. Unknown
prerequisites stay visibly unset for Commander review. Cost when broken: full rule files inflate
the one Analyze prompt, and invented prerequisites steer the stack recommendation.

`2026-07-18` · **One output protocol, in a fixed order.** `ANALYSIS.md`, `SEA_TRIALS.md`,
conditional `BLOCKERS.md`, conditional `COMPASS.md`, conditional identity questionnaire, the
mandatory stack questionnaire, then gap and discovery questionnaires in stable lexical order. A
questionnaire never resolves a blocker, and a source-named technology informs the stack
recommendation without confirming it. Cost when broken: parsers and reviewers see artifacts that
contradict one another across reruns.

### Mechanism

1. **Seed** — clear the error record, collect `blueprint/` sources, seed `COMPASS.md` from sources
   when absent or unpopulated, create `ANALYZE_COMPASS.md` and `EXCLUDE_FILES` if absent.
2. **Assemble** — `_assemble_prompt_assembly` injects sources (minus excluded names), Compass,
   feedback, prior `BLOCKERS.md`, existing questionnaires, `Rigging/MANIFEST.md`, and identity.
3. **Execute** — one `run_prompt` call; all outputs arrive as delimited artifact blocks.
4. **Parse** — `_parse_output` reports artifact defects and returns every artifact.
5. **Admit** — apply the Commander Sea Trials rule, parse Sea Trials, backfill `METADATA.md`.
6. **Write** — `ANALYSIS.md`, `SEA_TRIALS.md`, `COMPASS.md` with its guardrail, new questionnaires,
   the Sea Trials questionnaire, `TECHNOLOGY_STACK.md`, then `BLOCKERS.md` or its deletion.
7. **Finalize** — compute Quality, normalize the summary, attach the source-material handoff and
   resolved-blocker history, merge story guidance, stamp `analyzed`, create `PLAN_COMPASS.md`,
   refresh the Commanders Chair.

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

1. **Blocked analysis exits `0`.** A batch loop cannot detect `Blocked` from the exit status and
   must rely on `drydock plan` refusing. Should `Blocked` exit non-zero?

## Working Notes

-

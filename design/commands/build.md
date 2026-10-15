# DESIGN: drydock build

| Field | Value |
|---|---|
| Version | 2026-10-15 V1 |
| Route | build |
| Modules | `build.py`, `build_run.py`, `build_plan.py`, `acceptance.py`, `artifact_blocks.py`, `lineage.py`, `model_config.py` |
| Prompts | `build.md` |
| Tests | `tests/test_build*.py`, `tests/test_acceptance*.py`, `tests/test_lineage*.py` |
| Topics | [acceptance_criteria](../topics/acceptance_criteria.md), [foundations](../topics/foundations.md) |
| Pending spec | 0 |
| Pending impl | 0 |

## Behavior

### Purpose

Execute the dependency-ready frontier of `MANIFEST.md` one block at a time and close each story
only on evidence. Everything a build agent writes — code, tests, and the criteria it is graded
against — shares one author and one set of assumptions, so Build spends a bounded repair budget on
model-authored signal but hands the verdict only to evidence the model did not write.

### Syntax

```text
drydock build <Target> [--step <id|name> | --story <id|name>] [--continue | --reset]
                       [--ungate] [--override] [--normalize-order] [--dry-run [--show-prompt]]
                       [--build-dir <path>] [--repair-attempts <n>] [--repair-stall-limit <n>]
                       [--model <model>] [--llm-provider <p>]
drydock build status <Target>
```

Options may precede or follow `<Target>`. `--step`/`--story` and `--continue`/`--reset` are
mutually exclusive. `--continue` is the default behavior. `--ungate` releases prior
acceptance-only failures as `UNVERIFIED` before continuing.

### Rules

`2026-06-26` · **Blueprint drift halts the build before any mutation.** Applied spec hashes are
checked first; a changed Blueprint stops the run and directs the Commander to `drydock refit`.
Cost when broken: code built against a specification that no longer says it.

`2026-07-22` · **Staged assets are read-only.** Assets Analysis marks `stage` are copied into
`<build_dir>/sources/`, recorded by digest, and restored before grading if a step rewrote them.
Cost when broken: a block graded against a test suite of its own making.

`2026-07-23` · **The agent's own verdict is advisory.** A self-reported `FAILURE` does not fail a
block that wrote files and carries criteria; the deterministic gate decides. An `AC_BROKEN:` claim
is recorded evidence, not a stop (`2026-08-13`). Cost when broken: the party under test ends its
own examination.

`2026-07-23` · **Failure is attributed per story.** The story owning a failed check carries its own
AC finding. A failed block resumes in place, seeded with its live failure.

`2026-10-14` · **No story closes on a failed step.** Nothing orders stories within a step, so a
group-mate whose own checks passed is `closed/failed` with `finding: step <id> failed: <checks>`,
and the step rebuilds whole. Cost when broken: ReadingList closed its DATABASE story
`closed/implemented` inside a failed step whose consumer could not import the package it provides.

`2026-08-11` · **Repair is bounded by progress, not by count.** A pass continues when the passing set
grows without regression, or holds while a case tally improves and none regresses. Both limits are
configuration: the stall limit (`--repair-stall-limit`, `DRYDOCK_REPAIR_STALL_LIMIT`, default 2
consecutive flat passes) is the stop condition; the pass budget (`--repair-attempts`,
`DRYDOCK_REPAIR_ATTEMPTS`, default 6, `0` disables repair) is the outer bound. Every pass runs
on the step's model unless the price-limit rule below moves it; `--escalate-model` was removed
`2026-10-13`. Cost when broken: budget spent on a model that has stopped moving the score.

`2026-10-13` · **Tokens are the running model's tokens, and the model's row decides cost and
routing.** `model_config.jsonl` (user copy beside `.env`, seeded from `Rigging/`) gives each model
family its `bytes_per_token`, the CLI's fixed first-request payload (`overhead_tokens` by `build` or
`text` mode), `prompt_target_tokens` (stacking target, 70000), `prompt_warning_tokens` (120000),
and optionally `prompt_limit_tokens` with `escalate_model`. Story points are
`ceil(bytes / bytes_per_token)` for the active model (`--model` is published to `DRYDOCK_MODEL`).
`llm.run_prompt` runs a call on `escalate_model` when `estimate + overhead` (or, on a resumed
Claude session, the session's last context plus the new prompt) exceeds 98% of
`prompt_limit_tokens`; the call line shows `upgraded=prompt_limit ...`. Haiku 5.5 bills 5x above
100K prompt tokens, so its row escalates to `sonnet`. Measured on 2026-10-13: `bytes/4`
undercounts the 5.5 tokenizer by ~1.5x (2.61 bytes/token), and the Claude CLI adds 2,813 tokens
with no tools, 14,300 with its default 24 tools, 7,437 with the build set. Cost when broken: a
Haiku step silently priced at the upper tier, or a stacking target that is not the model's tokens.

`2026-10-13` · **A builder gets builder tools only.** Provider rows in `model_config.jsonl` set the
tool surface: Claude builds run `--tools Bash,Read,Edit,Write,Glob,Grep --strict-mcp-config`,
text-only runs `--tools "" --strict-mcp-config`; codex builds `--disable` apps, browser, computer
use, image generation, multi-agent, plugins, skill search, tool suggest, goals, sleep, and the
in-app browser. Cost when broken: every request carries schemas for tools the prompt never needs.

`2026-10-13` · **Calibration is evidence; the configuration changes only on request.** Every
successful Claude call appends its first-request size to `logs/model_calibration.jsonl`. After each
build step a `calibration:` line reports a measured value more than 5% from the live row (p10 of
bytes per token over at least 3 non-resumed runs) or a CLI version the overhead was not probed on.
`drydock config calibrate` lists the proposals, `--probe` measures overhead with two trivial
prompts, and `--apply` writes them. Codex reports usage per turn, so it is not calibrated. Cost when
broken: estimates drift with each CLI or model release.

`2026-09-19` · **Build refuses a plan it cannot execute.** Before any state changes or calls,
`build_target` runs the `drydock plan verify` check: a criterion that cannot run (syntax error,
unbound or sibling-bound name, unclosed container) or a table-declaring `DATABASE.md` that cannot
be read refuses the build. A criterion that runs and merely might fail is graded as usual; a
runtime kit fault still settles `UNVERIFIED`. Cost when broken: stories closed on criteria that
never tested anything, and every story after DATABASE built without a persistence layer.

`2026-08-13` · **A governed gate outranks a model-authored criterion.** `ACCEPTANCE.json` is
Commander-owned and its argv runs directly. Where a gate covers a story it is the verdict and the
criteria are diagnostic; where none does, a binding criterion decides; with no evidence a story
closes `implemented`, never verified. A re-typed expectation that misses settles `DISPUTED`; a kit
fault settles `UNVERIFIED`. Cost when broken: Toml left blocks 4–8 unbuilt behind a fabricated
expectation at block 3.

`2026-08-15` · **Each green block is swept against everything proven before it.** A criterion green
after the previous block and red now is a regression of this block and repaired here. Cost when
broken: Toml shipped ten blocks with its decoder's argument guard deleted at block 3.

`2026-10-05` · **Git deltas supply mechanical build lineage.** Existing application and Target
changes receive a baseline checkpoint. Each agent execution, including repair and failure,
commits application changes and appends `BUILD_LINEAGE.jsonl`, then commits Target evidence.
Rows retain Manifest node fields, only `implements:` as built specifications, specification hashes,
UTC timestamps, execution/run identities and log links, available usage, and acceptance results.
Completed-step rows retain final states and deterministic outputs without duplicating usage.
Git supplies additions, modifications, deletions, and detected renames; no agent attribution is
requested. The association is many-to-many at execution scope. Cost when broken: a regenerated
Manifest or reused block number severs the connection between specification versions and code.

`2026-10-05` · **Checkpoint identities survive interruption and reset.** Application and Target
commits carry the receipt ID; the Target commit is resolved by trailer to avoid a self-reference.
A pending receipt in Target Git metadata survives a failed checkpoint. Recovery finishes a
confirmed application commit's receipt, or stops if the application checkpoint is unconfirmed.
Full reset preserves `.git`; command epilogue outputs get a separate checkpoint. Commits respect
ignore rules and use configured Git identity. Cost when broken: false success after Git failure,
unrelated baseline changes attributed to a specification, or lineage pointing at erased history.

`2026-09-22` · **A stack or rules file is compact once an earlier finished block used it.** A step
receives `X_compact.md` for a `stack:` or `rules:` file named by an earlier block in Manifest
order whose state is finished; otherwise it receives `X`. No git state enters the decision, and
`implements:` is never compacted. A compact whose provenance hash no longer matches its source
falls back to the full file with a warning naming `drydock rigging compact`. The lineage of a refit
ticket being built (parent specification and earlier tickets) always enters `context:` in full.
Cost when broken: a root rebuild or refit builds from a summary of the code it must change, and
every unrelated Drydock commit re-injects full stack files.

`2026-09-19` · **The persistence layer is shipped and generated, never written by the agent.**
`Rigging/database/{db,sqlite,postgres}.py` is copied in unchanged and tested once in Drydock's own
suite; `schema.py` is emitted from `DATABASE.md` and carries no SQL. A build agent writes callers,
not a repository. Cost when broken: 126 lines of prose in `sqlalchemy.md` and `alembic.md` were
the entire specification of the layer, reinterpreted on every build and validated only by the
Target's own acceptance tests, so a drift between the declared operations and the implemented ones
was invisible until the code ran.

`2026-09-19` · **The schema is rendered from the declaration, never authored beside it.**
Indexes are derived — foreign-key child columns, and a `read` pattern's `Input:` fields, which are
the predicate it filters on. `read-write` is excluded because its inputs are part predicate and
part payload and the declaration does not say which. Cost when broken: an index invented at build
time and recorded only in a decision log is not in `DATABASE.md`, so the next render drops it and
nothing detects the loss — the built database and the declaration disagree with no defect
reported anywhere.

### Mechanism

1. **Guard** — require `MANIFEST.md`; `_ensure_applied_specs_current`; clear the error record.
2. **Reset** — `--reset` with no selector checkpoints existing work, resets every block, clears the
   build directory while preserving `.git`, and clears applied-spec provenance; a scoped reset
   applies after selection.
3. **Stage** — copy `stage` assets into `<build_dir>/sources/`.
4. **Select** — `_select_build_unit` picks the next block whose external dependencies are
   `closed/verified`, or the `--step` / `--story` target.
5. **Assemble** — `build.assemble_step` stacks Compass, rules, stack guidance (compact per
   `compact_stack_for`), context, and `implements:` files; the resolved file is what is costed,
   and the QuarterDeck previews the same rule assuming earlier blocks finish.
6. **Observe** — run the block's criteria before the build; a pass is recorded `prepassed`.
7. **Attempt loop** — run the agent, snapshot the file delta, restore staged assets, grade the
   criteria and governed gates, sweep for regressions, checkpoint the execution with lineage,
   and repair while progress holds.
8. **Close** — the governed gate decides; state is written per story with a one-line `finding:`,
   evidence is written, and the proven set grows by this block's green criteria.
9. **Persistence** — a pre-step hook: before the agent runs a unit that implements `DATABASE.md`,
   `_write_persistence` copies the shipped engines from `Rigging/database/` into `persistence/`,
   emits `persistence/schema.py` from the declaration, writes and applies `schema.sql`, and
   records the derived index set as one `DECISIONS.json` entry. Plan writes `DATABASE.md`, so the
   hook depends on nothing the step produces; it is idempotent, so a resumed step regenerates the
   same package. Migration records advance to `built` only when the step closes. (`2026-10-14`:
   moved from post-close; a same-step consumer could never pass acceptance.)
10. **Checkpoint** — append the completed-step receipt with final Manifest node states and
    checkpoint remaining application outputs and Target evidence. The console names the block,
    `implements:` files, call/event, and both repository commits. The command epilogue commits
    generated README and lifecycle updates separately.

### Exit codes

| Code | Condition |
|---|---|
| `0` | Selected work built and closed, or `--dry-run`. |
| `1` | A block failed or stalled; Blueprint drift; `plan verify` refusal; operational failure. |
| `2` | Usage error (exclusive options, negative `--repair-attempts`, provider/model conflict). |

### Spec divergence

- The specification documents `--escalate-model`; it was removed `2026-10-13`. Escalation is now
  per-model in `model_config.jsonl` (`escalate_model`, `prompt_limit_tokens`).
- The specification's syntax omits `--override`, `--normalize-order`, `--show-prompt`, and
  `--repair-stall-limit`.
- The specification's configuration table lists `drydock_build_escalate_model`; no such key exists. Escalation
  is the model-row setting above.

## Decisions

-

## Open Questions

- Does the prompt header (METADATA context block) belong in Rigging (governed, ships with tool)
  or in the target's Blueprint (per-project customizable)?
- What is the output contract for build? Same delimited-block pattern as analyze
  (`=== FILENAME === ... === END FILENAME ===`), or different? Filenames come from the plan item,
  not a fixed known set.
- What does "foundational first" mean concretely in the ordering — derived from graph topology
  (dependency traversal), or a declared tier on each group? (Not yet explored.)

## Working Notes

-

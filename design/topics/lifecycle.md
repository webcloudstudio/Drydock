# MEMORY: lifecycle

| Field | Value |
|---|---|
| Version | 2026-10-25 V1 |
| Description | One build workflow, defined once, executed by `drydock run builder` in place and by `drydock uat` in a sealed run. |
| Modules | `lifecycle.py`, `uat.py` (`run_fixture`), `cli.py` (`cmd_run_builder`) |
| Tests | `tests/test_lifecycle.py` |
| Governs | [run](../commands/run.md), [uat](../commands/uat.md) |

## Intent

One invariant workflow from an empty Target to a complete build, whoever runs it. `drydock run
builder` and `drydock uat` show the same steps, labels, and console, and differ only in where they
run, how blockers are answered, and what UAT adds after the build.

## Guardrails

- `2026-10-25` · One workflow definition. A second copy of the stage sequence or build loop (the
  retired `drydock_build_loop.sh`) is a defect. Cost when broken: the runner and UAT drift, and a
  UAT pass stops predicting a real build.
- `2026-10-25` · `drydock run builder` ends at a complete build. Scoring is UAT-only. Cost when
  broken: a build run spends score calls nobody asked for.

## Details

`2026-10-25` · **`Lifecycle` owns argv, labels, and loop policy; the caller owns execution.**
`STAGES = init, import, analyze, plan, verify, build`; `uat.STAGES` appends `refit, test, score`.
`Policy` carries `repair_attempts`, `max_build_passes` (default 25), `diagnose_attempts`,
`unattended` (adds `--override` to `plan` and `build`), and `plan_model` (appended as
`--plan-override-model` to every `plan` child). `build(stage)` loops `status --ready` → `build
--repair-attempts N`. An empty frontier is checked with `status --check`
(`<stage>-unstarted-check` before the first pass, `<stage>-complete` after it). It returns
`complete`, `incomplete`, or `halted`. Within `diagnose_attempts`, a failed build or an unfinished
check runs `diagnose --apply` (`<stage>-diagnose-<n>`) and loops. A failed diagnosis halts.
`verify_plan` runs `plan verify`, one `plan repair` and `plan-verify-after-repair`, and halts if
the plan still cannot run.

`2026-10-25` · **UAT is a pure extraction.** `run_fixture` drives `Lifecycle` with its own
`execute` (sequence numbers, evidence, `to_step`, halt raising) and `halt` (degraded line plus
`declare_stop`). Policy: unattended, `diagnose_attempts=0`, and its own build-failure explanation.
Seven fake-runner scenarios produced byte-identical child sequences before and after the
extraction. `test_uat_lifecycle_sequence_is_unchanged` pins the happy path.

`2026-10-25` · **`BuildRun` runs in place and derives its position.** `Position.of(target_dir)`
reads `METADATA.md`, visible files under `blueprint/sources/`, `ANALYSIS.md`, `MANIFEST.md`, and
any `BUILDING`/`BUILT` row in `PROJECT_STATUS.jsonl`. Established stages are skipped, so start and
resume are one operation. `verify` runs when the plan was just made or no build state exists. It
uses the build stage name `initial` and takes `after-plan` and `after-initial-build` build-status
snapshots, which `StepConsole` compacts as it does in UAT. A Target with no sources and no inputs
stops after `init` with `NO SOURCES` (exit 2). Inputs are ignored once sources exist.

`2026-10-25` · **Blockers are settled before each pass and after any failing step.** A nonzero
child while `BLOCKERS.md` stands raises `Blocked`. The run then shows the banner. At a terminal it
asks `How should we proceed?` through `cli._ask_how_to_proceed`; unattended it requires
`batch_may_run_owner`. It reruns the owner as step `owner-rerun-<verb>` with `DRYDOCK_OWNER_RERUN`,
then re-derives the position. A declined or refused settlement ends `BLOCKED` (exit 1). At most 10
settlements per run.

`2026-10-25` · **Journal.** `<Target>/logs/runs/<run-id>/RUN.jsonl` records events in order:
`start` (run, target, `stages`, `next_stage`, standing state, policy, inputs); one `step` per
child (step, stage, label, argv, started, elapsed_ms, returncode, stdout/stderr relative to the
run directory, standing state after); `blocker` (owner, outcome, blockers, resolved); `halt`;
`note`; `end` (status, reason, steps, build_passes, elapsed_ms, state). Child logs are
`commands/NN-<label>.{stdout,stderr}.log`. Children run without `DRYDOCK_PARENT_TRANSCRIPT`; the
parent transcript receives their output through the step console.

## Decisions

- None.

## Questions

- `2026-10-25` · UAT runs with `diagnose_attempts=0`; `run builder` defaults to 3, carrying over
  the retired loop's `diagnose --apply` recovery. Should UAT diagnose too? Either answer is a
  `Policy` value in `run_fixture`. It changes UAT step sequences and cost, so it needs Ed's call.

## Actions

- `2026-10-25` · `StepConsole`, `format_argv`, and `command_heading` still live in
  `uat_console.py`. Move them to a shared step-console module once the concurrent
  `uat_console.py` edits land. Closes when `lifecycle`/`cli` stop importing from `uat_console`.

## Working Notes

- None.

# DESIGN: process_stops

| Field | Value |
|---|---|
| Version | 2026-10-22 V1 |
| Route | process_stops |
| Modules | `stop_condition.py`, `llm.py`, `cli.py`, `uat.py` |
| Prompts | — |
| Tests | `tests/test_process_stop.py`, `tests/test_stop_condition.py` |
| Governs | [build](../commands/build.md), [status](../commands/status.md), [uat](../commands/uat.md), [diagnose](../commands/diagnose.md), [plan](../commands/plan.md), [analyze](../commands/analyze.md) |
| Pending spec | 0 |
| Pending impl | 0 |

## Behavior

### Purpose

A provider failure that another call cannot fix ends the Target's LLM work and says so where every
driver and operator looks. ReadingList `20261022.205653` hit a codex usage limit on its first build
call; the build printed `BUILD STALLED`, exited the generic `1`, and both shell drivers went on to
`drydock diagnose --apply` against the exhausted quota while UAT told the operator to diagnose the
failing block.

### Rules

`2026-10-22` · **Fatal provider failures are rate or usage limits, expired logins, timeouts,
outages, and an unrunnable provider CLI.** `llm.fatal_stop_reason` classifies a failed call:
`provider rate limit`, `provider authentication required`, `provider timeout`, `provider outage`
(a 5xx status, overload, or connection failure in the provider's error), and `provider
unavailable` (the CLI could not start). A malformed, truncated, or refused response is not fatal:
its shape is observed and the calling command repairs or retries it. A timeout is fatal because a
timed-out call may already have spent its tokens. Cost when broken: a loop resubmits into a limit,
or a recoverable response halts the run.

`2026-10-22` · **One fatal failure ends the process's provider work.** `run_prompt` records the
first fatal failure, and every later `run_prompt` call in that process raises `LlmError` without
sending the prompt. The standoff diagnosis is skipped. Cost when broken: a retry or repair loop
above the adapter spends against the same wall.

`2026-10-23` · **An invalid model is fatal.** `run_prompt` refuses, before sending, a model that
`model_config.jsonl` does not allow for the selected provider, and records the fatal kind
`invalid model` with execution id `not-sent`. A provider response naming a rejected model
(`model is not supported`, `model_not_found`, `model not found`, `unknown model`, `invalid model`,
`issue with the selected model`) is the same kind. Its recovery names `--model`,
`drydock config set drydock_model`, and every allowed model. Cost when broken: each later call
fails the same way, with the reason buried in a provider payload.

`2026-10-22` · **The failure is recorded as `STOP_NOW.md`.** At exit, a command that recorded a
fatal failure writes the Target's `STOP_NOW.md` with the command as its stage, the kind, provider
message and execution id as its reason, and a `## Recovery` section naming the operator action
and the exact command to rerun; it prints the same banner to stderr and exits `1`. The first
declaration wins, so `drydock uat` reports the provider cause rather than its own consequence.
`build` prints `BUILD STOPPED — <kind>` in place of `BUILD STALLED`. Cost when broken: the cause
is buried mid-transcript and the last line an operator reads is wrong.

`2026-10-22` · **Every LLM-assisted command checks `STOP_NOW.md` before it runs.** Commands that
reach a model (`_invocation_uses_llm`) and `diagnose` refuse while it exists; `uat` and `run` are
exempt, and deterministic sub-verbs (`build status`, `plan verify`) are not gated. With a
terminal on stdin and stdout the command prints the stop and asks `Clear this stop and continue?
[y/N]`; `y` deletes the file and proceeds. Otherwise it prints the stop to stderr and exits `1`.
Cost when broken: an unattended driver spends past a halt, or an operator cannot continue without
finding the file.

`2026-10-22` · **`status --ready` reports a stop and exits `1`.** It prints `STOPPED: <Target>
(<stage>: <reason>; see STOP_NOW.md)` ahead of any buildable work, so `while drydock status <T>
--ready` loops end. `drydock status <Target>` ends with the stop banner. No new exit code exists.
Cost when broken: drivers keep looping into a stopped Target.

### Mechanism

1. `llm.run_prompt` classifies each failed call and latches the first `FatalStop`.
2. `cli.main` calls `_process_stop_gate` before dispatch and `_declare_process_stop` after it.
3. `stop_condition.write_stop` / `read_stop` / `render_stop` own the file and its banner.

### Spec divergence

- The specification does not describe `STOP_NOW.md`, the interactive clear, or the `STOPPED`
  verdict of `status --ready`.

## Decisions

## Open Questions

## Open Actions

## Working Notes

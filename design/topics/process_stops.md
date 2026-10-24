# MEMORY: process_stops

| Field | Value |
|---|---|
| Version | 2026-10-24 V3 |
| Description | A provider failure that another call cannot fix ends the Target's LLM work and says so where every driver and operator looks. |
| Route | process_stops |
| Modules | `stop_condition.py`, `llm.py`, `cli.py`, `uat.py`, `quarterdeck_state.py`, `QuarterDeck/app.py`, `scripts/uat_repair_loop.sh` |
| Prompts | — |
| Tests | `tests/test_process_stop.py`, `tests/test_stop_condition.py` |
| Governs | [run](../commands/run.md), [build](../commands/build.md), [status](../commands/status.md), [uat](../commands/uat.md), [diagnose](../commands/diagnose.md), [plan](../commands/plan.md), [analyze](../commands/analyze.md) |
| Pending spec | 0 |
| Pending impl | 5 |

## Intent

A provider failure that another call cannot fix ends the Target's LLM work and says so where every
driver and operator looks. ReadingList `20261022.205653` hit a codex usage limit on its first build
call; the build printed `BUILD STALLED`, exited the generic `1`, and both shell drivers went on to
`drydock diagnose --apply` against the exhausted quota while UAT told the operator to diagnose the
failing block.

## Guardrails

- None.

## Details

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

`2026-10-24` · **Every Target command checks `STOP_NOW.md` before it runs.** Every command
naming a Target refuses while the file exists, deterministic sub-verbs (`build status`, `plan
verify`) included; `status` (which reports the stop), `run` (whose Commander's Chair shows it),
and `uat` (whose runs use fresh workspaces, and whose sealed run stops are evidence) are exempt. The refusal prints `drydock
<command> refused: <Target> is stopped.`, the stop banner, the file's path and verbatim contents,
and `rm '<path>'`. With a terminal on stdin and stdout the command then asks `Clear this stop and
continue? [y/N]`; `y` deletes the file and proceeds. Otherwise it prints to stderr and exits `1`.
Supersedes the `2026-10-22` LLM-only gate. Cost when broken: an unattended driver runs past a
halt, or an operator cannot find the file to clear.

`2026-10-24` · **A stopped Target's Commander's Chair is the stop.** When the QuarterDeck serves
`/raw/commanders_chair?variant=html`, `quarterdeck_state.with_stop_view` replaces the Chair's
`chair-overview` pane with `STOPPED: <Target> · <stage> · <declared>`, the reason, the recovery,
the file's path and verbatim contents, and `rm '<path>'`; the other Chair tabs remain. It is
applied when served and never written into `commanders_chair.html`, so clearing the stop restores
the overview without a refresh. Cost when broken: the Commander reads a healthy overview of a
Target every command refuses.

`2026-10-24` · **`scripts/uat_repair_loop.sh` ends on a declared halt.** When the UAT log holds
`: stopped at `, the loop prints `LOOP ABORTED`, the failure line, the run's `STOP_NOW.md`
contents, and the command to start a fresh loop, then exits `1` without a repair session. The
sealed run's file is never deleted. *Broken:* FxRates `20261024.183153` stopped at `plan-repair`
and the loop launched a repair session past the halt.

`2026-10-22` · **`status --ready` reports a stop and exits `1`.** It prints `STOPPED: <Target>
(<stage>: <reason>; see STOP_NOW.md)` ahead of any buildable work, so `while drydock status <T>
--ready` loops end. `drydock status <Target>` ends with the stop banner. No new exit code exists.
Cost when broken: drivers keep looping into a stopped Target.

### Mechanism

1. `llm.run_prompt` classifies each failed call and latches the first `FatalStop`.
2. `cli.main` calls `_process_stop_gate` before dispatch and `_declare_process_stop` after it.
3. `stop_condition.write_stop` / `read_stop` / `render_stop` / `render_refusal` own the file, its
   banner, and the gate's refusal.

### Spec divergence

- The specification does not describe `STOP_NOW.md`, the interactive clear, or the `STOPPED`
  verdict of `status --ready`.

## Decisions

`BLOCKERS.md` becomes the one file that blocks a Target. `STOP_NOW.md` is retired. `ERRORS.md`
stays the record of the last failure and blocks nothing. Build the sections below in order, one
slice, each with tests.

### 1. One blockers format, written by one function
`2026-10-24` · `spec:na` · `impl:unimplemented`

Drydock writes `BLOCKERS.md`; a model supplies only titles and questions. One owner per file:
only the owner may run while the file exists, so a second owner cannot arise.

```
# Blockers: Rate Limit Hit
- target: FxRates
- source: drydock build FxRates --model gpt-6-luna
- owner: build FxRates
- declared: 2026-10-24T18:38:12Z
- execution: 20261024.183251.657Z-bc03c7b9
- attempts: 1

## blocker-001: Provider usage limit
- kind: environmental            (environmental | decision)
- class: provider rate limit
- auto-continue: after 21:31     (environmental only)
### Error
<verbatim message>
### Question                     (decision only)
### Commander Resolution
```

- `Blockers:` is a short summary of the whole file.
- `owner` is the verb, sub-verb and Target; options may differ on a rerun.
- Environmental classes: `provider rate limit`, `provider authentication required`,
  `provider timeout`, `provider outage`, `provider unavailable`, `invalid model`, `uat stage`.
- A decision blocker may be raised only by an owner whose prompt takes the resolution
  (initially `analyze` and `refit`); the write function enforces this.
- `analyze` model-written blockers are converted to this format by the module.

### 2. Gate and batch rules
`2026-10-24` · `spec:na` · `impl:unimplemented`

- While `BLOCKERS.md` exists, every Target command except `status`, `run` and `uat` is refused,
  with the standard blockers banner (rendered from the file).
- For an `analyze` decision blocker, `plan --override` still passes. `--override` never waives
  an environmental blocker.
- Batch (stdin or stdout not a terminal) never prompts. A non-owner command is refused and exits
  `1`. The owner reruns only when every decision blocker has a `Commander Resolution`, or every
  blocker is environmental, may auto-continue (timeout, outage, rate limit after the stated
  reset), and `attempts < 2`.
- Expired login, invalid model and unrunnable provider CLI never auto-continue.

### 3. Interactive "How should we proceed?" and owner rerun
`2026-10-24` · `spec:na` · `impl:unimplemented`

- At a terminal, any blocked command shows the banner and asks, per blocker,
  `How should we proceed?`
  - Text is written into that blocker's `Commander Resolution`.
  - Enter keeps the existing resolution, or none, which is fine for environmental blockers.
  - `q` aborts with exit `1`.
- Drydock then reruns the owner. If the owner succeeds and the requested command differs, the
  requested command continues.
- Owner succeeds: resolved blockers are archived (`analyze` keeps archiving into `ANALYSIS.md`)
  and the file is deleted.
- Owner fails with the same environmental class: `attempts + 1` and the time is updated.
- Owner fails for an ordinary reason: environmental blockers clear and the failure goes to
  `ERRORS.md`. The owner rewrites unresolved decision blockers.

### 4. Resolution as primary instruction
`2026-10-24` · `spec:na` · `impl:unimplemented`

When any `Commander Resolution` is present, the owner's rerun injects it at the top of its
prompt as its primary instruction. When none exists (for example a rate limit), the prompt is
unchanged.

### 5. Retire `STOP_NOW.md` and move its readers
`2026-10-24` · `spec:na` · `impl:unimplemented`

- Move `status` (phase routing, `--ready`), the `plan` gate, the `uat` stop check,
  `scripts/uat_repair_loop.sh` and the Commander's Chair stop view to `BLOCKERS.md`.
- Remove `STOP_NOW.md`, its `Clear this stop and continue? [y/N]` prompt, and
  `stop_condition.py`'s file contract. No compatibility shim.
- A provider failure another call cannot fix writes an environmental blocker owned by the
  command that hit it. A `uat` stage halt writes one in the run workspace.
- Rewrite `## Behavior` once implemented.

## Questions

## Actions

## Working Notes

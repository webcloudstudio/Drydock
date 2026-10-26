# MEMORY: process_stops

| Field | Value |
|---|---|
| Version | 2026-10-24 V4 |
| Description | A provider failure that another call cannot fix ends the Target's LLM work and says so where every driver and operator looks. |
| Route | process_stops |
| Modules | `blockers.py`, `llm.py`, `cli.py`, `analyze.py`, `refit.py`, `planning_session.py`, `status.py`, `uat.py`, `quarterdeck_state.py`, `QuarterDeck/app.py`, `scripts/uat_repair_loop.sh` |
| Prompts | — |
| Tests | `tests/test_process_stop.py` |
| Governs | [run](../commands/run.md), [build](../commands/build.md), [status](../commands/status.md), [uat](../commands/uat.md), [diagnose](../commands/diagnose.md), [plan](../commands/plan.md), [analyze](../commands/analyze.md), [refit](../commands/refit.md) |
| Pending spec | 0 |
| Pending impl | 0 |

## Intent

A provider failure that another call cannot fix ends the Target's LLM work and says so where every
driver and operator looks. ReadingList `20261022.205653` hit a codex usage limit on its first build
call; the build printed `BUILD STALLED`, exited the generic `1`, and both shell drivers went on to
`drydock diagnose --apply` against the exhausted quota while UAT told the operator to diagnose the
failing block.

## Guardrails

- None.

## Details

`2026-10-26` · Provider stop markers include Claude's identifier forms `usage_limit_reached` and
`rate_limit_error` (rate limit) and `OAuth token has expired` (authentication), so a quota or
expired-login result is a fatal provider stop rather than an ordinary failure (CsvStat
`20261024.221659`). Generic `authentication_error` is deliberately not a marker: agent output can
contain it as ordinary code text. Stabilization F17.

`2026-10-25` · `render_banner` frames the banner with `console.box`: a rounded box with the
`BLOCKED: <Target> · <declared>` heading set into the top edge. The frame fits the widest line,
capped at the terminal width, and widens rather than split a word, so paths stay whole. The ASCII
tier renders it as `+-|`. The box is red for an environmental stop and yellow when only
decisions remain, through `console.paint`. Color requires a color terminal on the `stream`
argument (default stdout). Redirects, pipes, and `NO_COLOR` stay plain, so logs carry no escapes.

`2026-10-24` · Operator presentation uses local timestamps with a UTC offset and separates
the error, optional `Why blocked` explanation, recovery, and rerun command. Console banners omit
owner, execution, attempts, kind/class, and auto-continue bookkeeping; refusals link to the file
without duplicating it or recommending deletion as the error's remedy. Environmental blockers
omit empty Commander Resolution sections; decisions retain their question and resolution.
The file's owner, execution, and attempts now persist in a `drydock-state` JSON HTML comment;
the parser also accepts earlier header fields and UTC dates. Retry caps, ownership gates,
provider classifications, and resolution injection are unchanged. This presentation supersedes
the visible-header and verbatim-console details in the historical rules below. No master
specification edit is made; the existing specification divergence still applies.

`2026-10-24` · Fatal-provider console output ends with the environmental blocker and its error.
The CLI suppresses secondary generic and recorded-error reports when a fatal provider stop is
latched, skips standoff diagnosis, flushes stdout, and prints the provider cause last on stderr.
Stage 2 exits before manufacturing a generation stall. UAT treats environmental blockers as
fatal even for optional children and stops its kit sweep; its final blocker is printed after
receipts, report links, and kit checkpoints. `scripts/uat_repair_loop.sh` repeats the recorded
failure after its recovery instructions. Tests use fake providers and temporary fixture roots;
no published UAT evidence is executed or modified.

`2026-10-25` · `drydock run builder` replaces `drydock_build_loop.sh` and `drydock_runner.sh`
(now a deprecated shim). A nonzero child while `BLOCKERS.md` stands ends the pass. At a terminal
the run asks per blocker through `cli._ask_how_to_proceed`; unattended it requires
`batch_may_run_owner`. It reruns the owner as `owner-rerun-<verb>` with `DRYDOCK_OWNER_RERUN`,
then re-derives its position, or ends `BLOCKED` (exit 1). `run` stays exempt from the stop gate.
See [lifecycle](lifecycle.md). The entry below is historical.

`2026-10-24` · `drydock_build_loop.sh` resolves the Target through `drydock config env` and
checks `BLOCKERS.md` before work, before diagnosis, and after diagnosis. A recorded blocker
ends the loop with exit `1` and `status --ready`'s blocked cause last; it never invokes diagnosis
or another build past the file. `drydock_runner.sh` propagates that failure through `set -e`.
Regression evidence: `tests/test_diagnose_recovery.py::test_recovery_loop`, using a fake CLI.

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

`2026-10-24` · **One format, written by one function.** `blockers.write_blockers` is the only
writer; a model supplies only titles and questions. The header is `# Blockers: <summary>` and
`- target`, `- source` (the full invocation), `- owner` (verb, sub-verb, Target; options are not
part of it), `- declared`, `- execution`, `- attempts`. Each `## blocker-NNN: <title>` carries
`- kind: environmental | decision`; an environmental blocker adds `- class`, `- auto-continue`
(`yes`, `after HH:MM` local, or `no`) and `### Error`; a decision adds `### Question`; both end
with `### Commander Resolution`. Environmental classes are the six fatal kinds plus `uat stage`.
Only `analyze` and `refit` owners may raise a decision; the writer raises `ValueError` otherwise.
`analyze` converts the model's blockers into this format, and `refit` raises each unincorporated
change ticket as a decision. Cost when broken: two formats, two owners, and a gate that cannot
tell a quota from a question.

`2026-10-24` · **Every Target command except `status`, `run`, and `uat` checks the file.**
`cli._process_stop_gate` runs before dispatch. Only the owner may run. A non-owner is refused with
`drydock <command> refused: <Target> is blocked.`, the banner, the file's path and contents, and
`rm '<path>'`. `plan --override` passes an `analyze`-owned decision-only file and records one
`analysis-blocker` waiver per decision; `--override` never waives an environmental blocker.
Supersedes the `2026-10-22` `STOP_NOW.md` gate and its `Clear this stop and continue? [y/N]`
prompt. Cost when broken: an unattended driver runs past a halt.

`2026-10-24` · **Batch never prompts.** With stdin or stdout not a terminal, the owner is
admitted only when every decision carries a Commander Resolution, every environmental blocker may
auto-continue (a timeout, an outage, or a rate limit after its stated reset), and environmental
`attempts < 2`. An expired login, an invalid model, an unrunnable CLI, and a halted UAT stage
never auto-continue. Cost when broken: a loop resubmits into a limit that has not reset.

`2026-10-24` · **At a terminal a blocked command asks `How should we proceed?` per blocker.**
Text is written into that blocker's Commander Resolution; Enter keeps the existing one, or none;
`q` refuses with exit `1`. When the requested command is the owner it runs. Otherwise the owner
reruns as a child (`python -m drydock <source>`, with `DRYDOCK_OWNER_RERUN` naming the owner so the
child is admitted without asking); a failed child ends the requested command with its exit code,
and a successful one lets the requested command continue. Cost when broken: the operator edits a
file by hand and reruns two commands to answer one question.

`2026-10-24` · **An admitted owner settles the file.** A fatal failure of the same class adds 1 to
`attempts` and updates `declared`, `execution`, and `source`; another class replaces the
environmental blocker with `attempts: 1`; decisions are kept. Success appends the file as
admitted to `logs/blockers.md` and deletes it unless the owner rewrote it (`analyze` also keeps
archiving decisions into `ANALYSIS.md`). An ordinary failure clears the environmental blockers,
keeps the decisions, and writes `ERRORS.md` when the owner did not. A fatal failure in `plan
--override` past an `analyze` file is written to `ERRORS.md`; the file keeps its owner. Cost when
broken: a resolved block survives its fix, or a stale quota block outlives an ordinary defect.

`2026-10-24` · **A Commander Resolution is the owner's primary instruction.** When the admitted
file carries any resolution, `llm.set_primary_instruction` prepends `# Commander Resolution —
primary instruction` and each resolution to every prompt the owner sends, as the first prompt
part. With none (a rate limit, for example) the prompt is unchanged. Cost when broken: the rerun
repeats the call that raised the question.

`2026-10-24` · **Readers read `BLOCKERS.md`.** `status --ready` prints `BLOCKED: <Target>
(<stage>: <reason>; see BLOCKERS.md)` and exits `1` ahead of any buildable work; `drydock status
<Target>` ends with the banner and its recovery; only an `analyze` decision-only file routes the
phase to Arrange. The QuarterDeck replaces the Chair's `chair-overview` pane, when served, with
`BLOCKED: <Target> · <owner> · <declared>`, the blockers, the owner rerun, the file verbatim, and
`rm '<path>'`; the other tabs remain. `build` prints `BUILD STOPPED — <kind>` in place of `BUILD
STALLED`. Cost when broken: the Commander reads a healthy view of a Target every command refuses.

`2026-10-24` · **A halted UAT stage is an environmental blocker in the run workspace.**
`declare_stop` writes class `uat stage`, titled with the stage and owned by `uat <Target>`, unless
an environmental blocker is already recorded (the first one wins); a stage clears environmental
blockers on entry, never decisions. A required child that fails over an environmental blocker
raises `stopped at <stage>: <reason>`; a decision blocker is a failed stage, not a halt.
`scripts/uat_repair_loop.sh` ends on `: stopped at `, prints the run's `BLOCKERS.md`, and starts no
repair session. *Broken:* FxRates `20261024.183153` stopped at `plan-repair` and the loop launched
a repair session past the halt.

### Mechanism

1. `llm.run_prompt` classifies each failed call and latches the first `FatalStop`; it prepends
   the primary instruction when one is set.
2. `cli.main` calls `_process_stop_gate` before dispatch, then `_declare_process_stop` and
   `_settle_owner_run` after it.
3. `blockers.py` owns the file: `write_blockers`, `read_blockers`, `parse_blockers`,
   `batch_may_run_owner`, `render_banner`, `render_refusal`, `archive_blockers`,
   `primary_instruction`.

### Spec divergence

- The specification does not describe `BLOCKERS.md` ownership, environmental blockers, the
  `How should we proceed?` prompt, owner reruns, or the `BLOCKED` verdict of `status --ready`.

## Decisions

`BLOCKERS.md` becomes the one file that blocks a Target. `STOP_NOW.md` is retired. `ERRORS.md`
stays the record of the last failure and blocks nothing. Build the sections below in order, one
slice, each with tests.

### 1. One blockers format, written by one function
`2026-10-24` · `spec:na` · `impl:implemented`

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
`2026-10-24` · `spec:na` · `impl:implemented`

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
`2026-10-24` · `spec:na` · `impl:implemented`

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
`2026-10-24` · `spec:na` · `impl:implemented`

When any `Commander Resolution` is present, the owner's rerun injects it at the top of its
prompt as its primary instruction. When none exists (for example a rate limit), the prompt is
unchanged.

### 5. Retire `STOP_NOW.md` and move its readers
`2026-10-24` · `spec:na` · `impl:implemented`

- Move `status` (phase routing, `--ready`), the `plan` gate, the `uat` stop check,
  `scripts/uat_repair_loop.sh` and the Commander's Chair stop view to `BLOCKERS.md`.
- Remove `STOP_NOW.md`, its `Clear this stop and continue? [y/N]` prompt, and
  `stop_condition.py`'s file contract. No compatibility shim.
- A provider failure another call cannot fix writes an environmental blocker owned by the
  command that hit it. A `uat` stage halt writes one in the run workspace.
- Rewrite `## Behavior` once implemented.

## Questions

- `2026-10-24` · `plan --override` passes an `analyze` decision file, but the file stays, so every
  later non-owner command (`plan verify`, `build`) is still refused
  (`src/drydock/cli.py` `_process_stop_gate`). UAT runs `plan --override`, then `plan verify`.
  Closes when Ed decides whether a successful `plan --override` archives and clears the analysis
  decisions it waived.

## Actions

- `2026-10-24` · `b1b3ee9` fixes the CsvStat `20261024.221659` provider-stop reporting
  defect and the earlier jq recurrence; both ledger rows remain `unverified` pending live
  evidence. Local proof: 530 affected-module tests, 18 recovery tests, and four targeted
  Stage 2 stop scenarios pass; Ruff and shell syntax pass. Closes when Ed observes a provider
  halt ending with the blocker error and no subsequent child, kit, or diagnosis call.

## Working Notes

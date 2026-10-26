# MEMORY: drydock uat

| Field | Value |
|---|---|
| Version | 2026-10-15 V1 |
| Description | Make a release decision trustworthy: build known fixtures unattended, end every run in a verdict about the product, and separate a defect in the product from a defect in Drydock's own checkers. |
| Route | uat |
| Modules | `uat.py`, `uat_report.py`, `uat_console.py`, `blockers.py`, `sea_trials.py` |
| Prompts | `uat_diagnostic.md` (via `/ddk-uat`) |
| Tests | `tests/test_uat*.py` |
| Topics | [acceptance_criteria](../topics/acceptance_criteria.md) |
| Pending spec | 1 |
| Pending impl | 2 |

## Intent

Make a release decision trustworthy: build known fixtures unattended, end every run in a verdict
about the product, and separate a defect in the product from a defect in Drydock's own checkers.
Three properties define done (UAT gate model, 2026-08-14):

1. **A run finishes** and reports every defect it can observe, not only the first.
2. **The verdict is the user's.** Release comes from Sea Trials traced to user intent; story
   criteria guide the build and never reach the release verdict (see [score](score.md)).
3. **Drydock fails a project only by exhibiting a failure.** Absence of evidence is never failure;
   Drydock's bookkeeping never fails anything.

## Guardrails

- None.

## Details

`2026-10-25` · New receipts retain assertion `passed`, `failed`, and `unverified` counts
and replace inferred `product_defects`/`harness_defects` with
`defect_ownership_undetermined = failed + unverified`. Executing an assertion and obtaining FAIL
does not adjudicate whether the product, criterion, governed source, or environment is defective.
Published receipts remain unchanged. The four-key tally is verified with synthetic block evidence,
including a contradictory-oracle-shaped failure; no published UAT run is executed by these tests.

Specification clarification proposed (not applied): Assertion outcomes record PASS, FAIL, or
UNVERIFIED. Failed and unverified outcomes do not assign defect ownership; diagnosis establishes
whether the product, acceptance criterion, source contract, or execution environment is defective.


`2026-10-25` · The init-through-build steps run through the shared `Lifecycle`
([lifecycle](../topics/lifecycle.md)) with an unattended policy and `diagnose_attempts=0`.
`STAGES` is the lifecycle's stages plus `refit, test, score`. Child argv, labels, numbering,
halts, degraded lines, and evidence are unchanged. Seven fake-runner scenarios matched HEAD
byte for byte. `build_failure_detail` moved to `lifecycle.py`.

`2026-10-25` · The verdict, `STEP ERROR`, and `NOT READY` boxes use `console.box` (rounded,
heading in the top edge): verdict green when passed and red otherwise, `STEP ERROR` red, `NOT READY`
yellow. A child's framed banner arrives plain through the pipe. `StepConsole` paints stderr lines
that begin with a frame edge red and omits the `!` gutter on them. Evidence logs stay plain.

`2026-10-24` · Compact build-status snapshots mark verified and built rows with green checks,
question-blocked rows with a yellow warning, and failed or blocked rows with red failure marks.
The UAT console paints only its terminal presentation; child command evidence remains plain.
When acceptance case totals improve between repair calls, the build repair loop treats that as
forward progress and continues within the configured repair budget. It stops on two consecutive
flat passes by default (`repair_stall_limit`), not on an unchanged aggregate criterion count when
individual conformance totals are improving.

`2026-10-24` · Live step headers use uppercase command/positional argv instead of internal
step labels. The full invocation, preserving argument case and options, remains on the next
line. Counts use the option-free command within each kit: the first occurrence has no suffix;
subsequent occurrences show `[2]`, `[3]`, etc. A streaming first occurrence cannot anticipate
whether a later repeat will occur. Hidden status snapshots do not consume visible counts.
Child stdout `Next:` lines are suppressed, including fragmented lines. Headers and compacted
plan progress are blue, successful completion rules green, and failure boxes red. Final UAT
verdict boxes use the actual destination stream's color capability: green for a passed run,
red otherwise. `NO_COLOR`, redirected streams, and limited terminals retain plain output.
Quiet breadcrumbs, recorded labels, resume step numbers, child evidence, and execution are
unchanged. This supersedes the earlier display of the snapshot's next action.

`2026-10-24` · A failed build's stage blocker preserves the child's stderr (stdout when stderr
is empty or unavailable), up to 12,000 characters, with explicit truncation and both full evidence
paths. Missing diagnostics are stated explicitly. The error names the command and exit code;
`Why blocked` separately explains that the unfinished application prevents acceptance and scoring.
The same diagnostic survives into the run's recorded error. Existing provider blockers still win.
This fixes the hidden persistence-generation error in FxRates `20261025.014047`; it does not
repair the inconsistent generated `Rate` DTO or change published evidence.

`2026-10-24` · Terminal presentation is compacted in `uat_console.py`; child evidence and
execution order are unchanged. Plan progress frames become one line per batch. Copyright,
Git housekeeping, and Claude session ids are omitted. The three status commands still execute
and record full evidence; only build-status totals, frontier, next action, and failed rows are
shown on stdout. Snapshot stderr retains the blocker explanation but omits the duplicate raw
`BLOCKERS.md` dump. Nonzero children receive a `#`-bordered `STEP ERROR` box, except readiness
probes (`NOT READY`). Ordinary partial lines and carriage-return progress continue streaming.
After checkpointing, every result, including `--quiet`, ends with a boxed recorded verdict,
execution and acceptance states, blocker summary, last failed non-status/non-readiness command,
its first three stderr lines (bounded read), run error, and manual attestations. A step failure
can recover; only the final box states the recorded UAT result. Console summaries no longer dump
Markdown artifact inventories. No execution, evidence, report, or exit-code contract changes.

`2026-10-24` · Receipt assertion counts use `build_report.total_checks` as the graded
PASS/FAIL denominator; it already excludes UNVERIFIED results. Failed assertions are
`max(total_checks - passed_checks, 0)` and unverified results are counted separately. Temporary
block-evidence regressions cover mixed failures/exclusions, all-unverified, and no-exclusion
cases. This corrects CsvStat `20261025.011759` reporting zero failed assertions despite one FAIL;
it changes no published receipt or evidence and does not establish the failing criterion's validity.

`2026-10-24` · Read-only companion `helpers/list_failed_uat_runs.sh` uses the cleanup helper's
exact `status: "failed"` selection and symlink exclusions. It prints sorted absolute paths,
one per line, to stdout; counts and unreadable-receipt warnings go to stderr. `--uat-root`
overrides the repository-relative default. Requires Python 3; exit codes are 0 success,
1 filesystem failure, 2 usage error. No deletion flag or writes. Tests use temporary kit trees.

`2026-10-24` · Operator helper `helpers/delete_failed_uat_runs.sh` previews cleanup of
`uat/*/runs/*` using only `result.json` with exact `status: "failed"`; `--delete` removes
those directories. `--uat-root <path>` overrides the repository-relative default. Passed,
degraded, missing, malformed, and unknown receipts are retained; symlinked kit, runs, run,
and receipt paths are skipped. Python 3 is required. Exit codes: 0 success, 1 filesystem
failure, 2 usage error. Run only while UAT is stopped. The helper does not update kit indexes,
checksums, latest-run pointers, or Git histories; the operator reconciles published evidence.
Development verification uses temporary fixtures and never executes against published `uat/`.

`2026-10-24` · Run reports show `BLOCKED: <summary>` when the recorded Target holds blockers,
or `<state> — FAILED` for a failed workflow-state attempt; successful release remains
`PROJECT COMPLETE`. Failure and blocker stamps use the failure style. Markdown and HTML
conformance receipts distinguish a configured suite that was not executed, an explicitly absent
configuration, and missing configuration evidence. Recorded run `ACCEPTANCE.json` is preferred
to the kit's `uat.json`; recorded `-test` executions remain authoritative. Rendering changes no
run verdict or execution result. Published evidence is not rebuilt by development sessions.

`2026-10-24` · Every failed child is checked for an environmental `BLOCKERS.md`, including
optional readiness, verification, and repair calls. A provider halt stops before another child
or another kit starts. The runner still records the failed run; the CLI checkpoints and prints
summaries, counts, attestations, and report links before ending with the blocker banner and
`Error: <recorded run failure>`, including in quiet mode. Ordinary nonzero control-flow results
without an environmental blocker keep their existing handling. Regression evidence:
`tests/test_uat.py::test_a_provider_block_ends_optional_steps_and_the_kit_sweep` and
`tests/test_process_stop.py::test_uat_prints_the_halt_after_reports_and_checkpointing`.

### Syntax

```text
drydock uat [<Project>] [--uat-root <path>] [--max-build-passes <n>] [--repair-attempts <n>]
            [--repair-stall-limit <n>] [--capture-output-limit <mb>]
            [--plan-override-model <model>] [--quiet]
drydock uat status <Project> [--run <dir>]
drydock uat resume <Project> [--from <stage>]
drydock uat report [<Project>]
drydock uat <Project> --from-step <n> [--to-step <n>] [--run <dir>]
drydock uat <Project> --steps [--run <dir>]
```

Stages: `import`, `analyze`, `plan`, `verify`, `build`, `refit`, `test`, `score`. Only Ed runs
this command (AGENTS.md §UAT Evidence).

### Rules

`2026-10-24` · **UAT diagnosis requires clean execution as well as operational success.**
`ddk-uat` investigates warnings, rejected artifacts, repairs, defective-output retries, and
source-contract substitutions in running and completed runs, including successful runs. It
starts downstream-failure analysis at the earliest warning, traces the affected artifacts through
later stages, and distinguishes established, ruled-out, and undetermined causal links. Recovered
defects remain actionable and recorded in `design/skills/ddk-uat.md`; later success alone cannot
close them. Reports state the recorded verdict and diagnostic cleanliness (`clean`, `not clean`,
or `undetermined`) separately. Expected contractual observations require source and execution
evidence. The diagnostic classification does not change the runner's recorded verdict or exit
codes. Cost when broken: an upstream warning is dismissed after recovery and its downstream
failure is repaired several steps later while the generating defect remains.

`2026-10-22` · **A child's provider stop is the run's cause.** A required step that fails while the run workspace's `BLOCKERS.md` holds an environmental blocker raises `stopped at <stage>: <reason>` from that file, and `declare_stop` announces the recorded halt rather than its own reason, because the first declaration wins ([process_stops](../topics/process_stops.md)). Cost when broken: `result.json` blames the failing block for a provider limit.

`2026-10-14` · **Resume selects the recorded run and its failed stage together.** `drydock uat resume <Project>` selects the recorded run and its failed lifecycle stage as one recovery point. Losing the stage would send the selected run to `init`, which the runner rejects before recovery.

`2026-10-14` · **The CLI resolves run and entry stage before the runner starts.** The CLI resolves the selected run and entry stage before invoking the UAT runner. An explicit `--from <stage>` or `--from-step <n>` supplies the entry stage; otherwise `resume` infers it from the recorded failed command.

`2026-10-22` · **`--plan-override-model` runs the plan stage on its own model.** Every
`drydock plan` child command (create, verify, repair) is invoked with `--plan-override-model
<model>`, so its argv records the model; every other command uses `--model`. `result.json` records it as `environment.plan_model`, and the
executed-model list names both. Cost when broken: a model too weak to plan cannot be measured on
build at all.

`2026-10-14` · **Receipts name the executed model, not the requested one.** Run receipts and kit indexes name models from LLM execution records, preferring the provider-reported model. `requested_model` remains provenance; using it as the run model misattributes routed and mixed-model runs. Report rebuilds derive the model from preserved evidence without rerunning UAT.

`2026-08-10` · **A run distinguishes executed failures from unverified checks.** A check that cannot
reach the code under test settles `UNVERIFIED`, not `FAIL`; a build that stopped part way is a
named shortfall (`degraded`), and the scoring command is not run against it. Cost when broken: the
four-day loop of 2026-08 — runs failing on Drydock's own checkers while reporting product failures.

`2026-08-10` · **A fixture's frozen `SEA_TRIALS.md` is the exam.** A kit may seed
`TECHNOLOGY_STACK.md`, `SEA_TRIALS.md`, `COMPASS.md`, and story guidance after `init`; Analyze never
overwrites an existing `SEA_TRIALS.md`. Cost when broken: the model writes the exam it is graded
on, every run draws a fresh exam, and a regression is undetectable.

`2026-08-22` · **No Commander is present.** Child commands run with `DRYDOCK_UAT=1` and decide
within the fixture's governed inputs, recording each choice instead of asking. Cost when broken: a
run parked on a question no one will answer.

`2026-09-19` · **An unrunnable plan gets one repair, then the run halts.** After `plan`, the run
executes `plan verify`; on failure, one `plan repair`, then verify again and stop if still
unrunnable. A stop declared by an earlier attempt is cleared on re-entry. Cost when broken: the
build spends its repair budget on criteria that cannot execute and stops on a score that never
moved.

`2026-08-10` · **A kit and its run history are one publishable tree.** Each run lives in
`<kit>/runs/<run-id>/` inside the kit's own git repository; `drydock uat report` rebuilds proof
kits from completed runs without rerunning them. Cost when broken: published evidence no longer
attests to the build it describes.

### Mechanism

1. **Resolve** — kits under `--uat-root` (default `<workspace>/uat`); the run directory and
   entry stage are resolved by the CLI.
2. **Seed** — `init` the Target in the run's isolated workspace, then seed the kit's frozen inputs.
3. **Lifecycle** — run each stage as a child `drydock` command with `DRYDOCK_UAT=1`, streaming
   output; `plan` is followed by verify / one repair.
4. **Build loop** — build passes until the frontier is empty or `--max-build-passes` is reached;
   each refit update runs its own build stage.
5. **Score** — the kit's test command runs from the application root, then the score commands.
6. **Record** — `result.json`, the run receipt, and the kit index, with executed models from LLM
   records.

### Exit codes

| Code | Condition |
|---|---|
| `0` | Every selected kit passed. |
| `1` | Any kit failed, or an operational failure. |
| `2` | Usage error (`--from-step` without `<Project>`, invalid step bounds, invalid stage). |

### Spec divergence

- The specification does not document `drydock uat`.

## Decisions

### Executable deterministic Sea Trials blocks
`2026-08-10` · `spec:approved` · `impl:unimplemented`

A Sea Trial settles one of three ways:

1. **Own check** — carries its own Programmatic Acceptance, self-contained, run against the
   finished build.
2. **Bound** — a `Sea Trials: st-NNN` reference reaches a story assertion (the CommonMark case).
3. **Judged or attested** — not deterministically verifiable, by declaration.

Only (3) needs the attestation machinery. (1) removes the binding as a *requirement*: the criterion
that failed a clean 27-of-27 ReadingList run (`78f9233`) had no way to be proved except by a story
declaring `Sea Trials: st-003`.

Own checks obey both cross-cutting rules below: state as oracle, and three-valued outcome.

### proof_integrity analyzers demoted to authoring-time
`2026-08-10` · `spec:approved` · `impl:unimplemented`

The seven analyzers (`analyze_proof`, `analyze_literals`, `analyze_structure`, `analyze_invocation`,
`analyze_shell_escapes`, `analyze_swallowed_output`, tally-vocabulary) are the real prize of the
last four days: each is a documented, tested description of a way an LLM writes a broken assertion.

As **gates** they fight the model after the fact and accumulate false positives.
As **prompt content and authoring-time warnings** they are exactly the corpus that teaches the model
not to write those assertions. Keep the knowledge, drop the enforcement.

Action: convert each analyzer from a blocking defect into (a) prompt guidance in the acceptance
authoring contract, and (b) a warning that may cost marks, never a hard gate.

## Questions

- `2026-10-25` · Proposed specification clarification in Details requires Ed's block-specific approval; implementation is complete independently of that editorial decision.

1. **Two decisions of 2026-08-10 have unverified status.** Executable deterministic Sea Trials
   blocks, and demoting `proof_integrity` analyzers to authoring time (`validate` no longer runs
   them; `acceptance.py`, `acceptance_status.py`, and `ac_repair.py` still import it). Implemented,
   superseded, or open?

## Actions

- `2026-10-24` · FxRates `20261025.014047` stops before a build-agent call because
  `blueprint/DATABASE.md:118` declares `Rate` without `rate`, unlike the earlier three-field
  `Rate` outputs. Shared output-row validation now rejects this at admission and verification;
  a fake-runner regression repairs it before freezing, and a temporary SQLite round trip uses
  distinct `Rate` and `RatesDeleteOutput` classes. This is separate from the fixed blocker
  presentation. The local fix is complete; close live verification on Ed's later clean UAT.

- `2026-10-24` · CsvStat `20261025.011759`: local fixes address the five diagnosis ledger
  findings; Ed must verify a fresh run with valid CSV fixtures, post-build native checks,
  complete actionable repair feedback, visible planning warnings, and accurate receipt counts.
  Published evidence is unchanged; close on later clean stage evidence.

- `2026-10-24` · `5e9962e` corrects the CsvStat `20261024.221659` report defects; both ledger
  rows are `unverified` pending later report evidence. Local proof: all 71 report tests pass,
  including failed/blocked plan states and configured/unexecuted conformance. Closes when Ed's
  later generated report preserves these distinctions; published runs remain untouched.

- `2026-10-24` · DupFind `20261024.140514` passed and is not yet diagnosed. It has no ledger rows.

## Working Notes

- `2026-10-24` · Ed strongly prefers the pink and green highlighting and explicitly requests
  more of it. The affected surface (terminal, web reports/QuarterDeck, or chat change display)
  is pending clarification; preserve this preference in subsequent presentation work.

- **Deferred: per-branch stall (P-3a, 2026-08-14).** A failed block would stop only its dependents
  while independent branches keep building, so one run reports every independent defect. Deferred
  as an efficiency gain, not a convergence fix; `build_run` still stops at the first failed block.
- **Deferred: residue observation (§35).** See
  [acceptance_criteria](../topics/acceptance_criteria.md).
- The UAT gate model's history — 31-gate inventory, defect catalog D-001…D-027, 18-run evidence,
  and Parts I–VI — stays in the private `notes/notes_uat_gates.md`. Its current model (Part VII) is
  folded into [score](score.md) and [acceptance_criteria](../topics/acceptance_criteria.md).

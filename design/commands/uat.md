# DESIGN: drydock uat

| Field | Value |
|---|---|
| Version | 2026-10-15 V1 |
| Route | uat |
| Modules | `uat.py`, `uat_report.py`, `uat_console.py`, `stop_condition.py`, `sea_trials.py` |
| Prompts | `uat_diagnostic.md` (via `/ddk-uat`) |
| Tests | `tests/test_uat*.py` |
| Topics | [acceptance_criteria](../topics/acceptance_criteria.md) |
| Pending spec | 0 |
| Pending impl | 2 |

## Behavior

### Purpose

Make a release decision trustworthy: build known fixtures unattended, end every run in a verdict
about the product, and separate a defect in the product from a defect in Drydock's own checkers.
Three properties define done (UAT gate model, 2026-08-14):

1. **A run finishes** and reports every defect it can observe, not only the first.
2. **The verdict is the user's.** Release comes from Sea Trials traced to user intent; story
   criteria guide the build and never reach the release verdict (see [score](score.md)).
3. **Drydock fails a project only by exhibiting a failure.** Absence of evidence is never failure;
   Drydock's bookkeeping never fails anything.

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

`2026-10-22` · **A child's provider stop is the run's cause.** A required step that fails while the run workspace's `STOP_NOW.md` exists raises `stopped at <stage>: <reason>` from that file, and `declare_stop` announces the recorded halt rather than its own reason, because the first declaration wins ([process_stops](../topics/process_stops.md)). Cost when broken: `result.json` blames the failing block for a provider limit.

`2026-10-14` · **Resume selects the recorded run and its failed stage together.** `drydock uat resume <Project>` selects the recorded run and its failed lifecycle stage as one recovery point. Losing the stage would send the selected run to `init`, which the runner rejects before recovery.

`2026-10-14` · **The CLI resolves run and entry stage before the runner starts.** The CLI resolves the selected run and entry stage before invoking the UAT runner. An explicit `--from <stage>` or `--from-step <n>` supplies the entry stage; otherwise `resume` infers it from the recorded failed command.

`2026-10-22` · **`--plan-override-model` runs the plan stage on its own model.** Every
`drydock plan` child command (create, verify, repair) is invoked with `--plan-override-model
<model>`, so its argv records the model; every other command uses `--model`. `result.json` records it as `environment.plan_model`, and the
executed-model list names both. Cost when broken: a model too weak to plan cannot be measured on
build at all.

`2026-10-14` · **Receipts name the executed model, not the requested one.** Run receipts and kit indexes name models from LLM execution records, preferring the provider-reported model. `requested_model` remains provenance; using it as the run model misattributes routed and mixed-model runs. Report rebuilds derive the model from preserved evidence without rerunning UAT.

`2026-08-10` · **A run distinguishes a harness defect from a product defect.** A check that cannot
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

## Open Questions

1. **Two decisions of 2026-08-10 have unverified status.** Executable deterministic Sea Trials
   blocks, and demoting `proof_integrity` analyzers to authoring time (`validate` no longer runs
   them; `acceptance.py`, `acceptance_status.py`, and `ac_repair.py` still import it). Implemented,
   superseded, or open?

## Open Actions

-

## Working Notes

- **Deferred: per-branch stall (P-3a, 2026-08-14).** A failed block would stop only its dependents
  while independent branches keep building, so one run reports every independent defect. Deferred
  as an efficiency gain, not a convergence fix; `build_run` still stops at the first failed block.
- **Deferred: residue observation (§35).** See
  [acceptance_criteria](../topics/acceptance_criteria.md).
- The UAT gate model's history — 31-gate inventory, defect catalog D-001…D-027, 18-run evidence,
  and Parts I–VI — stays in the private `notes/notes_uat_gates.md`. Its current model (Part VII) is
  folded into [score](score.md) and [acceptance_criteria](../topics/acceptance_criteria.md).

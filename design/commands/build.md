# MEMORY: drydock build

| Field | Value |
|---|---|
| Version | 2026-10-15 V1 |
| Description | Execute the dependency-ready frontier of `MANIFEST.md` one block at a time and close each story only on evidence the model did not write. |
| Route | build |
| Modules | `build.py`, `build_run.py`, `build_state.py`, `build_plan.py`, `acceptance.py`, `artifact_blocks.py`, `lineage.py`, `model_config.py` |
| Prompts | `build.md` |
| Tests | `tests/test_build*.py`, `tests/test_acceptance*.py`, `tests/test_lineage*.py` |
| Topics | [acceptance_criteria](../topics/acceptance_criteria.md), [foundations](../topics/foundations.md) |
| Pending spec | 0 |
| Pending impl | 0 |

## Intent

Execute the dependency-ready frontier of `MANIFEST.md` one block at a time and close each story
only on evidence the model did not write. Code, tests, and criteria share one author, so Build
spends a bounded repair budget on model signal and hands the verdict to independent evidence.

## Guardrails

- None.

## Details

### Current contract

| Concern | Contract |
|---|---|
| Authority | Approved Blueprints, source constraints and generated foundation contracts. |
| Preconditions | Buildable plan, delivered prerequisites and provisioned persistence after its owner step. |
| Mutations | Agent changes implementation; development tests use disposable SQLite state after provisioning. |
| Invariants | Canonical managed state and unrelated records survive; model SUCCESS is advisory; generated criteria do not override source intent; repair quotes AC intent verbatim and never licenses changing an expected result. |
| Recovery | Retain private pre-call store snapshot on detected mutation; never automatically overwrite concurrent state; identify DATABASE owner. |
| Proof | Real temporary-store write/deletion/concurrency regressions, per-test pytest isolation and build integration; PostgreSQL and process isolation remain explicit gaps. |

`2026-10-26` · Corpus repair feedback carries one bounded input/expected/actual example beside
the assertion, retains the case inventory/full log, and explicitly flags an unchanged passing
case count. Repair instructions require reproducing a failing example before editing, tracing
the actual failing branch, adding a red regression, running it and a passing neighbor, and
revising an ineffective edit within the call. Test claims must name executed commands/results;
unrun checks remain unrun. This is prompt guidance, not enforcement that a provider executed tests;
deterministic acceptance and the two-flat-call stop still own the verdict.

Prose criterion-dispute inference requires the failing check, defect language and a criterion
noun in the same sentence/report field. A product's malformed reference definitions no longer
combine with a different field's suite name to route product failures to Plan. Explicit
`AC_BROKEN` claims and genuine local prose claims remain advisory and retain existing recovery.

Historical dated entries follow; where behavior has changed, this current contract and the
newest dated entry describe the implemented behavior. See [stabilization](../topics/stabilization.md).

`2026-10-26` · **Repair feedback quotes AC intent verbatim.** `_render_repair_feedback` adds a
`### Criterion intent` section listing each failing or regressed criterion's original `Intent:`
lines (`AcceptanceRunResult.intent_lines`), never the ID fallback. The instructions and this
section are never truncated; `_REPAIR_FEEDBACK_CAP` applies only to the diagnostics after them.
The repair instructions state that fixtures are Plan-selected, a failure does not authorize
changing an expected result, and a demonstrated contradiction is reported with `AC_BROKEN`
(`tests/test_ac_intent.py`).

`2026-10-26` · **Regression-led repairs are labelled as measured.** The repair line counts the
block's failing checks plus checks the regression sweep found broken:
`repair: attempt N/M · K failing check(s) (R regressed)`; `agent-reported` appears only when
Drydock measured nothing failing. Stabilization S4 scenario
`tests/test_build_recovery_scenario.py` connects partial gains, a green-but-regressed call,
recovery, stall exhaustion, owner recovery (`drydock build <Target>`, never the earlier block) and
resume with retained lineage. The sweep runs only on a call whose own checks are green, by design.
The disputed-criterion banner is asserted to match the persisted recovery.

`2026-10-26` · **Imported sources resolve as context.** `StepRoots.roots_for("context")` is
`(blueprint, target, blueprint/sources)`: a bare `INSTRUCTIONS.md` reaches the governed source brief
with its `path=` provenance instead of `Missing context`; an authored Blueprint or Target file of the
same name wins; absent files stay missing; sources are read only (FxRates `20261026.011843`).

`2026-10-26` · **Per-test store isolation inside an agent call.** `AgentStore` stages Drydock's
`pytest_store_isolation.py` as `drydock_store_isolation` in the call directory and gives only the
provider child `PYTHONPATH`, `PYTEST_ADDOPTS=-p drydock_store_isolation` and
`DRYDOCK_STORE_TEMPLATE`. An autouse fixture copies the provisioned call store into each test's
`tmp_path` and points `DATABASE_URL`/`DATABASE_PATH` at the copy, so committed rows and
`cli_runner` writes cannot reach another test (FxRates `20261026.173232`). Nothing is written into
the product; operator pytest runs and canonical acceptance keep their own lifecycle. Limit: code
that resolves the DSN at import time keeps the shared call store; PostgreSQL is unchanged.

`2026-10-26` · **Absent acceptance results are never passes.** `_run_valid_criteria` returns one
result per declared criterion: excluded ones as before, and a selected criterion the executor
returned nothing for as UNVERIFIED `not executed (no result returned)`. A story whose criteria
all vanished therefore closes `closed/implemented` with the unexamined finding, not verified.
The `AC_BROKEN` dispute line is indented under its call and passes the normal console filter
(FxRates `20261024.051856`). Stabilization S1 matrix: `tests/test_build_truthful_closure.py`
connects execution, outcomes, Manifest state, console tally and `completion_check` for success,
no-run, partial, agent failure and verification-only (prepassed → implemented) cases.

`2026-10-26` · `build_state.AgentStore` isolates agent-call SQLite tests after persistence
provenance exists. It provisions a fresh schema in a unique `.drydock-tests` subdirectory and
passes both DSNs only to the provider child, without changing the parent process environment.
Managed canonical stores inside the build tree receive a private SQLite backup under Target
`evidence/managed-state`; main-file/WAL changes retain the backup and stop as managed-state
violation before acceptance. No automatic restore clobbers concurrent data. External SQLite
stores are not read or backed up; agent tests still receive a disposable store. PostgreSQL is
unchanged, and per-test isolation within an agent call remains the project's fixture obligation.
Recovery identifies the DATABASE owner and requires data preservation before continuation;
post-call persistence failures use managed state verification phase. Inline diagnosis does not
replace this deterministic action. See stabilization for remaining resource classes.

`2026-10-25` · The build prompt requires a current-file read before contextual patches
and a reread/rebased patch after a verification failure. A repeated stale patch is not a repair.
The FastAPI foundation keeps the published TestClient API, uses httpx2 for Starlette >=1.2,
and locks a compatible dependency set without suppressing deprecations; older selected stacks
may retain httpx. This is authoring guidance, not a vendor pin or a change to existing Targets.
The current Starlette TestClient documentation confirms the transport preference:
https://www.starlette.io/testclient/ . Warning-free execution in a newly generated Target remains
to be verified by Ed's next UAT.


`2026-10-25` · CLI failure banners and stderr choose one representative per execution,
preferring a story that owns a failed binding acceptance check over an earlier sibling that
shares the block failure. Aggregate block status and Manifest states remain authoritative;
no passing sibling is reclassified. A provider failure without an owned failing check retains
its first story. Synthetic regressions cover a later conversion owner, independent executions,
and failures with no owned check. FxRates `20261025.200850` previously named initialization
as the cause of a conversion assertion failure.


`2026-10-26` · **Measured status is grouped by story.** Each call prints the total passing
check count, then each owning story and each check's PASS/FAIL/DISPUTED/UNVERIFIED result.
Suite tallies are labeled `cases=<passed>/<selected> passed` with `change=<signed count>`
relative to the preceding measurement. Case counts remain per check: overlapping scopes are
never added into a story or project case total. Checks without tallies show only their outcome.
An ungraded call still prints `status not measured` with its cause.

`2026-10-26` · **One acceptance verdict belongs to Drydock.** The build agent reads existing
failure logs, changes implementation, and runs targeted tests. It need not repeat every declared
acceptance suite before Drydock executes those same checks. Silence from a running suite does not
establish a hang. Repair feedback gives measured case decreases priority over remaining failures;
previous agent notes remain advisory. This revises the duplicate full-scope execution instructions
in build prompt V11 and the repair preamble. No timeout, acceptance gate, or budget is weakened.

`2026-10-25` · **An agent's interrupted verification is advisory, like its self-reported
failure.** With checks declared, deterministic acceptance still runs and decides the pass.
Progress is compared against the last measured pass, an ungraded pass leaves the flat-pass count
unchanged, and it keeps the last measured failures as the next repair's work queue. CommonMark
`20261025.023211`: call 3 was skipped, call 4 got no failing checks, and its +22 was counted flat,
stopping the block at call 5 of 22. *Broken:* real progress ends a block as `stall`.

`2026-10-25` · **A failed `assert` renders as an acceptance result.** The `BUILD FAILED` block
prints `AC FAILED  <id>  <passed>/<selected> passed (<n> failed)` with Intent and Source, without
exit code, `Error: AssertionError`, or traceback. Any other exception or classified error keeps
the full Code/Result/Stderr rendering.

`2026-10-25` · A successful, non-dry-run build whose `execution_state` is `complete`
ends with a green `BUILD COMPLETE: <Target>` box: the completion reason, the count built this run,
and the elapsed time. A partial build (`--step`, open frontier) prints no box.

`2026-10-24` · Repair feedback renders actionable check diagnostics before excluded checks.
Exclusions are summarized by count with pointers to `evidence/acceptance-status.json` and the
block's pre-build observation instead of consuming the 4,000-character feedback budget with
repeated status messages. Regression and resource diagnostics retain priority. Native Go
`not-run` at baseline records `VALID product-missing`, so newly written tests execute after the
build; absent tests after the build still report `UNVERIFIED`. This extends the absent-file
baseline distinction from `c6a910f` for CsvStat `20261025.011759`.

`2026-10-24` · No-op verification steps run their declared acceptance even when the agent
reports failure and changes no files. The report remains advisory; provider/execution failures
remain terminal. Already-green criteria retain their existing PREPASSED attribution, and only a
governed story gate can override that attribution. The build prompt permits SUCCESS without
edits when the step is already satisfied. Attempt evidence labels bypassed grading as
`checks not executed (<n> declared)` and labels an agent report advisory only when it did not
determine the failure. This revises the file-delta restriction from `98c2f82`; it does not change
the master specification. CsvStat `20261025.001433` previously spent seven calls without grading.

`2026-10-25` · `drydock_build_loop.sh` is removed. `drydock run builder` drives the build loop
through `Lifecycle.build` ([lifecycle](../topics/lifecycle.md)) and settles `BLOCKERS.md`
before each pass and after any failing step; the entry below is historical.

`2026-10-24` · The normal `drydock_build_loop.sh` driver checks the resolved Target's
`BLOCKERS.md` before building and before or after recovery diagnosis. Any blocker ends the
driver with exit `1`, no further diagnosis/build call, and the blocked cause last. The parent
`drydock_runner.sh` also stops on that exit. Temporary fake-CLI scenarios verify pre-existing,
build-time, and diagnosis-time provider blocks in `tests/test_diagnose_recovery.py`.

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

`2026-10-22` · **A provider stop is not a stall.** When a fatal provider failure ends the build, the console prints `BUILD STOPPED — <kind>` in place of `BUILD STALLED`, the Target's `BLOCKERS.md` names the cause in an environmental blocker owned by the build, and the failed block stays `closed/failed`, which a plain `drydock build` resumes ([process_stops](../topics/process_stops.md)). Cost when broken: a quota stop reads as a planning deadlock.

`2026-10-24` · **A build never joins an enclosing uv workspace.** Before anything observes the build directory, a Python Target's build without a `pyproject.toml` receives a standalone one (`target_environment.seed_python_project`), so an agent's `uv init` refuses to run and `uv lock` writes the build's own `uv.lock`. Every tool-using agent call snapshots each `pyproject.toml` and `uv.lock` above its working directory; when one gains a workspace member reaching the working directory, `llm.run_prompt` restores that project's two files and fails the call naming them. Other changes to an enclosing project belong to concurrent writers and are kept. This replaces the `uv` PATH shim of `39e4e10`, which a login shell (Codex's `bash -lc`) bypasses by re-sourcing `~/.profile`. Cost when broken: the build registers in the Drydock repository's `pyproject.toml`, its dependencies lock into Drydock's `uv.lock`, and a second same-name build breaks every `uv add` and `uv lock` (FxRates 20261024.073528, 20261024.164835).

`2026-10-22` · **Acceptance uses the provisioned application store.** The DATABASE step emits
runtime catalog/count probes, applies schema, verifies declared columns, keys, constraints and
indexes, and records `evidence/persistence-verification.json`; these probes are a precondition, and the persistence story verifies only on `DATABASE.md`'s own criteria. Later acceptance runs verify without
applying DDL and refuse a missing or incompatible store. Verification starts only at the
provenance record `.drydock-persistence.json` that Drydock writes when it emits persistence
(`2026-10-24`); `schema.sql`, `schema-verification.json`, or a `persistence/` package written by an
earlier step is not checked, and step close prints `persistence: <files> written by the agent
before the DATABASE step; that step regenerates it`. A missing artifact after that step names the
missing files. Provisioning (`score`, the DATABASE step) still starts at `schema.sql` or
`schema-verification.json`. Criterion isolation is one harness-owned rollback
transaction per Python criterion (`2026-10-24`); see
[acceptance_criteria](../topics/acceptance_criteria.md). Cost when broken: criteria test an
unprovisioned store or leave shared residue.


`2026-10-22` · **A DATABASE-only step is graded, not built.** When every story in a step
implements only `DATABASE.md` and the persistence package was generated, no model is called. The
step's criteria run against the generated package and decide the close: `closed/verified`,
`closed/implemented` when unexamined, `closed/failed` on a red criterion or when no criterion
runs, since 0/0 grades nothing. Persistence is generated
after the criteria baseline, so those criteria are red before the step. Cost when broken: the agent
can only report that it wrote nothing, and every repair fails the same way (ReadingList
`20261022.231143`).

`2026-10-19` · **A `postgres.md` stack requires `postgres_dsn`.** Build refuses before any
mutation or model call when it is unset, and otherwise exports it as `DATABASE_URL` to schema
application, acceptance runs and the application. Cost when broken: the build silently falls back
to SQLite and never exercises PostgreSQL.

`2026-10-19` · Build requires a valid approved stack before mutation or model execution. The language foundation receives full language guidance; all other build and repair prompts receive the shipped compact once, included in prompt costing. Keyed persistence operations require their declared key; keyless deletes fail before SQL. SQL owns schema validation. Breaking these rules risks wrong-language code or unintended deletion.

**Guards**

`2026-06-26` · **Blueprint drift halts before any mutation** and directs the Commander to
`drydock refit`.

`2026-09-19` · **Build refuses a plan it cannot execute.** The `plan verify` check runs first; an
unrunnable criterion or unreadable `DATABASE.md` refuses the build. `2026-10-22`: so does a story
with no criterion (`criteria-missing`, including a story naming no Blueprint or a file outside
`blueprint/`) and a declared repository operation no `DATABASE.md` criterion calls
(`operation-untested`). Plan refuses both too; Build repeats the check because a Manifest can be
approved past Plan's gate (Refit, a hand edit, an older plan). *Broken:* stories closed on
criteria that tested nothing, or on none.

`2026-07-22` · **Staged assets are read-only.** Copied to `<build_dir>/sources/`, digested, and
restored before grading. *Broken:* a block graded against tests it rewrote.

**Verdict**

`2026-07-23` · **The agent's own verdict is advisory.** A self-reported `FAILURE` does not fail a
block that wrote files and carries criteria; `AC_BROKEN:` is evidence, not a stop.
The repair feedback says the same (`_render_repair_feedback`, `2026-10-20`). *Broken:* feedback
that promised `AC_BROKEN:` ends the budget spent a call the agent expected not to run (LayersTesting
`20261020.183046`).

`2026-08-13` · **A governed gate outranks model-authored criteria.** `ACCEPTANCE.json` is
Commander-owned and runs directly; where it covers a story it decides. Without evidence a story
closes `implemented`, never verified. See [acceptance_criteria](../topics/acceptance_criteria.md).

`2026-10-14` · **No story closes on a failed step.** Group-mates of a failed check are
`closed/failed` with `finding: step <id> failed`, and the step rebuilds whole. Failures are
attributed per story (`2026-07-23`).

`2026-08-15` · **Each green block is swept against everything proven before it**; a regression is
repaired in the block that caused it.

**Repair and cost**

`2026-08-11` · **Repair is bounded by progress.** Continue while the passing set grows without
regression or a case tally improves. Stop after `repair_stall_limit` flat passes (default 2) or
`repair_attempts` passes (default 6; `0` disables).

`2026-10-13` · **The model row decides tokens, cost, and routing.** `model_config.jsonl` gives each
family `bytes_per_token`, fixed CLI overhead, `prompt_target_tokens` (70000),
`prompt_warning_tokens` (120000), and optional `prompt_limit_tokens` with `escalate_model`; a call
over 98% of the limit runs on `escalate_model` (Haiku → `sonnet`). *Broken:* a step silently billed
at the upper tier.

`2026-10-23` · **A model row may set a default effort.** A row's optional `effort` applies when
no effort is requested by `--effort`, `drydock_effort`, or prompt frontmatter, and is read from
the row of the model that runs, after escalation. The seed sets `low` for `opus` and `sol`. *Broken:*
an unflagged Opus or Sol run spends the provider's default effort.

`2026-10-13` · **A builder gets builder tools only.** Claude builds run
`--tools Bash,Read,Edit,Write,Glob,Grep --strict-mcp-config`; codex disables non-build features.

`2026-10-13` · **Calibration is evidence; configuration changes only on request.** Each call logs
its first-request size; `drydock config calibrate --apply` writes proposals.

**Context**

`2026-09-22` · **A stack or rules file is compact once an earlier finished block used it.** No git
state enters the decision; `implements:` is never compacted; a stale compact falls back to the full
file with a warning; a refit ticket's lineage enters in full.

**Persistence**

`2026-09-19` · **The persistence layer is shipped and generated, never agent-written.**
`Rigging/database/{db,sqlite,postgres}.py` is copied in; `schema.py` and `schema.sql` are emitted
from `DATABASE.md`, before the step that implements it (`2026-10-14`). Indexes are derived: FK
child columns and `read` pattern inputs. *Broken:* a schema reinterpreted on every build.

`2026-10-20` · **A create returns its declared Output row.** Python and Go read the row back by its
key (the supplied key, else the engine's generated one); a create with no Output, or a Go table
with no key, returns the key. *Broken:* criteria written against `DATABASE.md` fail on a SQLite
rowid (LayersTesting `20261020.132808`).

`2026-10-23` · **A delete returns its declared Output, built from the key.** Python and Go return
the Output row from the supplied key when a row was removed, and `None`/`nil` when none was. An
update with an Output returns the row read back by key, or `None`/`nil` when no row matched. A
delete or update with no Output returns the count. *Broken:* criteria written against `DATABASE.md` fail on
an int (ReadingList `20261023.200606`).

`2026-10-20` · **Persistence autocommits by default.** Python connections open in
autocommit mode and Go executes every statement, schema included, outside a transaction. Explicit acceptance rollback scopes suspend autocommit on their owned connection. A rejected command changes nothing by
validating before its first write. *Broken:* builds hand-roll driver wrappers to fake a scope.

**Lineage**

`2026-10-05` · **Git deltas supply build lineage.** Every agent execution commits application
changes, appends `BUILD_LINEAGE.jsonl`, and commits Target evidence; receipts carry Manifest
fields, spec hashes, usage, and acceptance. Checkpoint identity survives interruption and reset;
reset preserves `.git`. *Broken:* specification versions severed from code.

`2026-10-18` · Persistence generation dispatches on the selected language. Python templates and libraries come from its bundle; Go receives a linked local module with generated typed repositories. The Go language foundation must create go.mod before the DATABASE step. Go schema application runs the generated command. Cost when broken: the selected stack and generated runtime disagree.

`2026-10-22` · Build progress reports the persisted per-story state rather than the aggregate step verdict; grouped summaries omit a single state and list each member story. Cost when broken: the console claims verification the Manifest does not record.

`2026-10-24` · **A failed block reports its complete acceptance set.** Failure summaries,
assertion details, baseline movement, and recovery selection use the block's checks; story-owned
checks remain available for attribution. Cost when broken: a block failing five criteria reports
4/4 passing from its first story (DupFind `20261024.073506`).

`2026-10-24` · **Criterion disputes survive subsequent repair calls.** Build retains the IDs
reported defective during any attempt and filters them to still-failing criteria at completion.
The claim remains advisory and does not change repair budgets or verdicts. Terminal and recorded
error recovery direct inspection through `plan verify`, with `plan repair` for confirmed mechanical
defects, before rebuilding. Cost when broken: a later report omits `AC_BROKEN` and recovery advises
an unchanged rebuild against the same immutable criterion.

### Mechanism

1. **Guard** — Manifest present, specs current, plan verifiable.
2. **Reset** (`--reset`) — checkpoint, reset blocks, clear the build directory except `.git`.
3. **Stage** assets; **select** the next block whose dependencies are `closed/verified`, or the
   `--step`/`--story` target.
4. **Assemble** — Compass, rules, stack guidance (compact per rule), context, `implements:`.
5. **Baseline** criteria, then the **attempt loop**: agent, file delta, restore assets, grade,
   sweep, checkpoint, repair while progressing.
6. **Close** — per-story state and `finding:`, evidence, proven set grows.
7. **Checkpoint** — completed-step receipt; epilogue outputs committed separately.

### Exit codes

| Code | Condition |
|---|---|
| `0` | Selected work built and closed, or `--dry-run`. |
| `1` | A block failed or stalled; Blueprint drift; `plan verify` refusal; operational failure. |
| `2` | Usage error (exclusive options, negative `--repair-attempts`, provider/model conflict). |

### Spec divergence

- The approved-stack precondition and shared type-count policy are implemented here; the master specification is unchanged.

- The specification documents `--escalate-model`; it was removed `2026-10-13`. Escalation is now
  per-model in `model_config.jsonl` (`escalate_model`, `prompt_limit_tokens`).
- The specification's syntax omits `--override`, `--normalize-order`, `--show-prompt`, and
  `--repair-stall-limit`.
- The specification's configuration table lists `drydock_build_escalate_model`; no such key exists. Escalation
  is the model-row setting above.

## Decisions

-

## Questions

-

## Actions

- `2026-10-26` · CommonMark convergence review: story status, regression feedback and one
  deterministic acceptance owner are implemented with synthetic build regressions. Ed must
  verify live convergence across the UAT kits; local tests do not establish model compliance.
  Automatic best-candidate restoration is deferred: counts do not identify which cases changed,
  and restoring an application tree must preserve generated files and evidence. Close this action
  only on measured clean runs, or an explicit decision to retain the current repair policy.


- `2026-10-25` · CommonMark `20261025.023211`: interrupted-verification grading, last-measured
  stall comparison, and scoped case denominators are fixed locally
  (`test_interrupted_agent_verification_is_still_graded_and_counts_as_progress`). Unverified:
  Ed's next CommonMark resume must show a `status` line for every call and `/286`, `/356`, `/655`
  denominators. Also open: the agent's 60-second no-output watchdog kills the multi-minute full
  suite; the build prompt does not say the suite is long-running.

- `2026-10-24` · CsvStat `20261025.011759`: local fixes address the five diagnosis ledger
  findings; Ed must verify a fresh run with valid CSV fixtures, post-build native checks,
  complete actionable repair feedback, visible planning warnings, and accurate receipt counts.
  Published evidence is unchanged; close on later clean stage evidence.

- `2026-10-24` · CsvStat `20261025.001433`: local regressions cover no-op grading, measured
  failed-check repairs, governed story verification, and bypassed-grading evidence. Ed's next
  UAT must pass the verification step without empty repair calls; the diagnosis ledger records
  the fix as unverified until that evidence exists.

- `2026-10-20` · The acceptance-failure Recovery still says `drydock build <Target>` when the agent
  disputes the criterion in prose that neither `_defective_acceptance_claim` (`build_run.py`) nor
  `_BLUEPRINT_REPAIR_SIGNALS` (`cli.py`) recognizes. LayersTesting `20261020.161323` blocker: "The
  `load-transactions-valid` acceptance setup omits required account/category fixtures." A rerun
  repeats the failure. Deferred: phrase matching on agent prose is fragile.
- `2026-10-20` · An `AC_BROKEN:` claim on a binding criterion has no route to AC repair:
  `ac_repair.select_repairs` selects only `malformed` and `DISPUTED` criteria, so Recovery says
  rerun `drydock build`, which cannot pass. LayersTesting `20261020.183046`, `transaction-post-read`.
  Deferred: reverses the `90757da` decision that the claim is evidence, not a verdict.

## Working Notes

- `2026-10-26` · Dependency/reporting cleanup verification: full regression run completed with
  4,517 passed, two skipped and seven failures. Four refit expectations were updated to preserve
  sequential ticket gates; two stale status/feedback expectations were corrected; one checkout
  casing failure was retested from canonical `drydock`. All seven and four additional regressions
  pass in the final 11-case run. Prompt/memory contracts: 83 passed. Lint, changed-file formatting,
  wheel build and packaged prompt smoke pass. No UAT or provider call was run. Concurrent gate
  prerequisite work remains outside this change's commit and verification claim.

-

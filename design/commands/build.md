# MEMORY: drydock build

| Field | Value |
|---|---|
| Version | 2026-10-15 V1 |
| Description | Execute the dependency-ready frontier of `MANIFEST.md` one block at a time and close each story only on evidence the model did not write. |
| Route | build |
| Modules | `build.py`, `build_run.py`, `build_plan.py`, `acceptance.py`, `artifact_blocks.py`, `lineage.py`, `model_config.py` |
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

-

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
only on evidence the model did not write. Code, tests, and criteria share one author, so Build
spends a bounded repair budget on model signal and hands the verdict to independent evidence.

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

`2026-10-22` · **A provider stop is not a stall.** When a fatal provider failure ends the build, the console prints `BUILD STOPPED — <kind>` in place of `BUILD STALLED`, the Target's `STOP_NOW.md` names the cause and recovery, and the failed block stays `closed/failed`, which a plain `drydock build` resumes ([process_stops](../topics/process_stops.md)). Cost when broken: a quota stop reads as a planning deadlock.

`2026-10-22` · **Acceptance uses the provisioned application store.** The DATABASE step emits
runtime catalog/count probes, applies schema, verifies declared columns, keys, constraints and
indexes, and records `evidence/persistence-verification.json`; these independent probes gate the persistence story even when it has no model-authored criteria. Later acceptance runs verify without
applying DDL and refuse a missing or incompatible store. Python `db_session()` and Go
`OpenSession(ctx, dsn)` use one explicit rollback transaction on the configured store; ordinary
application operations retain autocommit. Same-connection feature code receives the yielded
store; no schema/commit/connection-lifetime escape is permitted. Expected operation failures use
savepoints so PostgreSQL can continue inside the criterion. Multi-connection and durability
criteria use committed, owned records with idempotent setup and checked cleanup. Plan rejects
recognized DSN mutations and schema calls. Cost when broken: criteria test an unprovisioned store,
leave shared residue, or claim durability they never tested.


`2026-10-19` · **A `postgres.md` stack requires `postgres_dsn`.** Build refuses before any
mutation or model call when it is unset, and otherwise exports it as `DATABASE_URL` to schema
application, acceptance runs and the application. Cost when broken: the build silently falls back
to SQLite and never exercises PostgreSQL.

`2026-10-19` · Build requires a valid approved stack before mutation or model execution. The language foundation receives full language guidance; all other build and repair prompts receive the shipped compact once, included in prompt costing. Keyed persistence operations require their declared key; keyless deletes fail before SQL. SQL owns schema validation. Breaking these rules risks wrong-language code or unintended deletion.

**Guards**

`2026-06-26` · **Blueprint drift halts before any mutation** and directs the Commander to
`drydock refit`.

`2026-09-19` · **Build refuses a plan it cannot execute.** The `plan verify` check runs first; an
unrunnable criterion or unreadable `DATABASE.md` refuses the build. *Broken:* stories closed on
criteria that tested nothing.

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

## Open Questions

-

## Open Actions

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

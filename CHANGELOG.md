# Changelog

All notable changes to Drydock are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and Drydock follows
[Semantic Versioning](https://semver.org/spec/v2.0.0.html). While the version remains `0.x`, the
command surface and Typed Specification contract are unstable and may change between releases.

## [Unreleased]

### Added

- 2026-10-29: Documentation: three Reddit posts condense
  `docs/posts/20261029.specdrivendevelopment.md` and the specification's SAIL Method for
  r/codex, r/ClaudeCode, and r/ClaudeWorkflows. They retain Set Up, Analyze and Plan,
  Implement, and Loop, including `refit` for incremental change, with group-specific
  provider context and reported test results. Publication and moderation acceptance
  remain unverified.

- 2026-10-25: `drydock run builder <Target>` starts or continues one Target through to a complete
  build in place. It is the lifecycle `drydock uat` runs (init, import, analyze, plan, plan
  verification, build loop), now defined once in `lifecycle.py` and shown with the same step
  console. The position is derived from the Target directory, so completed stages are skipped and
  a complete Target reports `BUILD COMPLETE` and exits 0. Repeated `--infile` and `--indir`
  arguments, each optionally prefixed `<format>=`, import in command-line order while the Target
  has no sources. Unfinished work is repaired with `diagnose --apply` up to `--diagnose-attempts`
  times (default 3). `BLOCKERS.md` is settled before each pass and after any failing step: at a
  terminal the run asks per blocker and reruns the owner, and unattended it ends `BLOCKED`
  (exit 1) unless the file admits the owner. Each run is journaled to
  `<Target>/logs/runs/<run-id>/RUN.jsonl`, with the stage topology, one record per step, blocker
  settlements, and the outcome. `--plan-override-model` is accepted.

- 2026-10-24: UAT build-status snapshots color verified and built rows green with check marks,
  question-blocked rows yellow with a warning mark, and failed or blocked rows red with a fail
  mark. Color remains terminal-only; recorded child stdout and stderr remain plain text.

- 2026-10-24: `helpers/list_failed_uat_runs.sh` lists runs with exact `result.json` status
  `failed` without changing evidence. It accepts `--uat-root`, prints sorted paths to stdout,
  and sends the count and unreadable-receipt warnings to stderr.

- 2026-10-24: Operator helper `helpers/delete_failed_uat_runs.sh` previews failed-run cleanup
  from `uat/*/runs/*/result.json`; `--delete` removes only explicit `failed` runs.
  `--uat-root` selects another kit root. Passed, degraded, incomplete, and unreadable runs
  are retained. Kit indexes, checksums, pointers, and Git histories require operator reconciliation.

- 2026-10-24: `DATABASE.md` access patterns express ranges and list order. A `| Match |` term
  `<column> <op> <field>` (`=`, `<`, `<=`, `>`, `>=`) compares an Input field that is not a column
  with that column, as `date >= start_date`, on a `list`, `update`, or `delete`. A `list` declares
  `| Order | <column> [asc|desc], ... |`. Plan validates both, the generated Operation Surface shows
  the terms, the order, and the SQL, and the shipped Python and Go persistence runtimes execute
  them as bound parameters. Terms and Order enter the contract fingerprint only when declared, so
  existing operations keep their fingerprints.
- 2026-10-24: `drydock plan` and `plan verify` refuse a criterion that calls a repository
  operation `DATABASE.md` does not declare (`operation-undeclared`): Python
  `db.<table>.<verb>(`, Go `db.<Table>.<Verb>(`, judged only on declared tables. The generated
  package raises `UnknownOperation` for such a call on every run, so the criterion could never
  pass; Stage 2 now routes it to artifact repair and the defect names the table's declared
  operations. Build failure blocks also print exception lines whose class does not end in
  `Error` or `Exception`, such as `persistence.db.UnknownOperation`. This closes FxRates
  `20261024.145257`, whose `rates-upsert` criterion read back through an undeclared
  `db.rates.get`.

- 2026-10-23: `DATABASE.md` operations are named methods with a Kind. `Repository operation` is
  `<table>.<name>`, called as `db.<table>.<name>(...)`; a `| Kind |` row (`get`, `list`,
  `create`, `update`, `upsert`, `delete`) says how it runs, and a name that is itself a Kind needs
  none. A table may hold several operations of one Kind, such as `rates.update` by `PK` and
  `rates.reprice_currency` by currency; a synonym (same Kind, Match, Sets, and Output) fails the
  plan. The generated `## Operation Surface` now gives each operation's full contract: call,
  Kind, Rows, Match, Sets, Input and Output JSON in caller types, the exact SQL the runtime
  executes, and a contract fingerprint.

- 2026-10-23: `DATABASE.md` access patterns declare the rows each operation reaches. An optional
  `| Match |` row names the Input fields that select rows (equality, AND, all required), and
  the new `upsert` verb inserts the row a declared unique key identifies or replaces its other
  columns in one `INSERT … ON CONFLICT` statement. A Match covering the `PK` or a declared
  `UNIQUE` reaches one row; any other reaches many, and a many-row `update` or `delete` returns
  a count. `get` must match a unique key, `upsert` must match exactly one, and a table grants
  each verb once; each breach fails the plan with the rule named. The Python and Go runtimes
  update by any Match rather than only the `PK`. `DATABASE_compact.md`, both from Plan and from
  `drydock rigging compact`, carries a generated `## Operation Surface`: per table, each call's
  Match, Sets, Rows, and Returns. This closes FxRates `20261023.234755`, where "a stored (date,
  currency) is replaced" had no operation to express it.

- 2026-10-23: Documentation: `docs/posts/devlog_2026-10-23.md` and its Slate HTML rendering
  consolidate the unannounced September development post into a 0.8 beta announcement draft:
  the acceptance-criteria verify-and-repair loop, Full UAT Harness, generated persistence,
  diagnosis, REFIT changes, model controls, and delivery evidence. The announcement describes
  the UAT Harness's 10 projects scored on Haiku and Luna. Publication follows UAT.

- 2026-10-23: `drydock report uat_summary` prints a read-only 30-day UAT pass matrix,
  with every kit directory and Claude/Codex columns. `Y` marks at least one passed run
  completed in the preceding 30 days; older receipts fall back to the UTC run id.
  The report takes no Target, writes no files, and is excluded from `report --all`.

- 2026-10-23: `model_config.jsonl` provider rows name the models each provider accepts and the
  aliases that select the newest one. Codex aliases `sol`, `luna`, `astra`, and `terra` resolve to
  the highest-versioned match in `~/.codex/models_cache.json`, falling back to the row's `models`
  list. Claude and Gemini aliases pass through to their CLIs. An invalid model is a fatal
  `invalid model` stop that writes `STOP_NOW.md` before any call is sent, and a provider
  response rejecting the model is the same stop. Both name every allowed model.
  `drydock config set drydock_model` refuses an invalid model, and `drydock config show` shows
  alias resolution, flags an invalid model, and lists each provider's allowed models. The seed
  moved from `Rigging/model_config.jsonl` to the repository root.

- 2026-10-22: Every story must carry at least one Programmatic Acceptance criterion, `DATABASE.md`
  included. `drydock plan` refuses a Stage 2 response whose story Blueprints declare none
  (`criteria-missing`, sent to artifact repair). `drydock plan verify` reports the same defect,
  so a plan that still lacks criteria ends `unbuildable` with a `draft` Manifest. `- None.` is no
  longer an exemption. `DATABASE.md` criteria exercise each repository operation through
  `persistence.testing.db_session()` and are no longer replaced by an invariant statement. A
  criterion opening `sqlite3.connect(":memory:")` is an `acceptance-store` defect.
  `plan_create.md` V44, `BLUEPRINTS_CONTRACT.md` V27, and the `DATABASE.md` template state the
  rule.

- 2026-10-22: Fatal provider failures halt the Target through `STOP_NOW.md`. A rate or usage
  limit, expired login, timeout, outage, or unrunnable provider CLI ends the command's provider
  work: later calls in the same process are not sent, the standoff diagnosis is skipped, and the
  command writes `STOP_NOW.md` with its stage, the provider message, the execution id, and a
  Recovery section naming the operator action and the command to rerun. Every LLM-assisted command
  and `drydock diagnose` refuse while the file exists; at a terminal they offer
  `Clear this stop and continue? [y/N]`. `drydock status <Target> --ready` prints
  `STOPPED: <Target>` and exits `1`, `drydock status <Target>` ends with the stop banner,
  `drydock build` prints `BUILD STOPPED` instead of `BUILD STALLED`, and `drydock uat` reports the
  recorded provider cause. Malformed or truncated responses remain recoverable.

- 2026-10-22: Go CLI acceptance criteria run the built executable through
  `drydock_go.cli_runner(*args, package=None, input=None)`, which builds the single `./cmd/<name>`
  main package once with `go build` and returns `(exit_code, stdout, stderr)`. A build failure
  settles the criterion as `execution-error`. `drydock plan verify` reports a `go-run` defect for
  any criterion that launches the application with `go run`, which reports every non-zero exit as
  `1`, and `plan_repair.md` V12 rewrites such calls to `cli_runner`. The harness-exit,
  unchecked-call and staged-value checks now apply to Go criteria.

- 2026-10-22: DATABASE builds record runtime table-count and catalog verification in
  `evidence/persistence-verification.json`, backed by generated `schema-verification.json`.
  Python and Go database acceptance fixtures use the configured store in an explicit rollback
  transaction; normal application operations retain autocommit. Criteria no longer receive a
  fresh database or automatic schema application. Missing or incompatible stores fail validation;
  committed HTTP, subprocess and durability checks use owned records and idempotent recovery.
  `plan verify` rejects recognized criterion DSN overrides and schema provisioning calls.

- 2026-10-22: `--plan-override-model <model>` runs the plan stage on its own model.
  `drydock plan` uses it in place of `--model` and the configured default. `drydock uat` passes it
  to every `drydock plan` step while the other steps use `--model`, so a model can be measured on
  build with a plan authored by a stronger one, and `result.json` records it as
  `environment.plan_model`. Every other command refuses the flag with exit `2`.
- 2026-10-22: `drydock plan` Stage 2 accepts `BLUEPRINT_BLOCKED.txt`, a structured report of a
  Current-batch Blueprint the model cannot author: `Blueprint`, `Error type` (`missing-input`,
  `conflict`, `insufficient-specification`, `other`), `Cited input`, `Details`, and
  `Required action`. Drydock refutes claims its own prompt disproves, such as a "missing" input
  that is present or an accepted Blueprint withheld by design. The next batch receives each entry
  and finding as `Prior run error type` and `Prior run error details`. Prose refusals are fed back
  the same way as `unstructured-refusal`. A block never stops planning on its own. A `conflict` or
  `insufficient-specification` block still standing when retries run out is recorded as a deferred
  product decision (exit `2`). Other standing blocks are named in the `plan generation stalled`
  record.
- 2026-10-21: `/ddk-uat` keeps a diagnosis ledger at `design/uat_diagnoses.md`: one row per
  diagnosed UAT run and root cause, with the implicated Area, the Fix commit, and an Outcome of
  `open`, `unverified`, `fixed`, or `recurred`. `uat_diagnostic.md` V4 reads it before diagnosing,
  updates earlier Outcomes from the new run, recommends revising a recurred fix instead of adding
  another beside it, and appends its own rows. This ledger is the only file the diagnostic writes.
  Seeded with the LayersTesting runs of 2026-10-21.
- 2026-10-20: `drydock report uat_report` prints a read-only `UAT RUN REPORT` comparing every
  passed UAT run under `<workspace>/uat`, newest first, by project, date, and executed model. It
  counts Drydock LLM calls by category (Build, Repair, Plan, Plan Rep, Other) beside the
  Manifest's story count, splits tokens into fresh input, cache read, and output,
  counts agent tool calls as Shell, Edit, and Other across Claude and Codex transcripts, and sums
  LLM minutes over every execution including resumes. Exits `1` when `<workspace>/uat` is absent.
- 2026-10-20: `drydock plan verify` reports a `harness-exit` defect when a Programmatic Acceptance
  call that passes a staged source file asserts an exit status that no line of a staged
  `sources/*.sh` harness expects for the same command and file. Only the first such call in a
  criterion is compared, and harness lines are read only in the `<exit> [<program>] <args...>`
  shape. `drydock plan repair` (`plan_repair.md` V9) may change that one expected exit to the
  harness value and correct later assertions that followed from it. `drydock plan` leaves such a
  Manifest `draft`/`unbuildable` and exits `1`.

### Changed

- 2026-10-28: `/ddk-uat` handoffs explain the failure and proposed repair in plain English, identify the scope and purpose of unfamiliar mechanisms, and distinguish recommendations from implemented fixes.

- 2026-10-28: Build repair feedback directs agents to diagnose and fix related failure clusters
  within each call, using representative examples and regression checks instead of a single-example
  instruction. Acceptance and stall limits remain unchanged.

- 2026-10-27: Build agents receive the SQLite configuration-test helper and task-oriented
  persistence Rigging, including generated schema and initializer paths. Managed SQLite changes
  are compared against the retained logical backup so WAL checkpointing does not alone block a
  build; changed or unverifiable data still stops with the backup preserved. Planning warnings
  describe weak individual HTTP assertions without claiming the full criterion passes.

- 2026-10-26: `drydock plan` instructs Stage 1 to close each artifact before opening the next.
  Its malformed-output retry revises and completes the existing draft, retaining valid work
  while returning both complete updated artifacts. The one-retry budget and validation gates
  remain unchanged; the retry permits necessary content corrections rather than only inserting
  closing markers.

- 2026-10-26: Acceptance criteria intent is a governed contract. `drydock plan` requires one or
  two nonblank `Intent:` lines per newly authored criterion (`missing-intent`, corrected in the
  bounded artifact repair loop and forgiven on exhaustion); `plan verify` does not check it, so
  existing Blueprints still build. `drydock build` repair prompts quote each failing criterion's
  `Intent:` lines verbatim in a `### Criterion intent` section that is never truncated, and state
  that Plan-selected fixtures are intentional and a failure never authorizes changing an expected
  result. `BLUEPRINTS_CONTRACT.md` V41.

- 2026-10-26: `drydock plan verify` no longer emits the unknown-decimal-provenance warning.
  Plan is authorized to choose fixtures and calculate expected results; a decimal expectation
  absent from source material is ordinary test design, not a review item. Dependency, oracle,
  readiness and citation checks are unchanged.

- 2026-10-26: `python tests/uat_corpus.py <corpus-root>` regenerates the gate-policy corpus only
  from the directory named on the command line; nothing reads published `uat/` implicitly.

- 2026-10-26: Documentation and `/ddk-uat`: stabilization applies to any Target through
  deterministic acceptance/TDD audit slices and Ed's manual diagnosis, repair-review and rerun
  workflow. No fixed kit roster or provider matrix defines completion. Diagnoses persist in one
  memory per Target, resolved using actual on-disk casing; the central ledger remains historical.
  Compact reports retain full evidence and explicit repair authorization. PostgreSQL live testing
  and scoring changes remain outside this stabilization effort.

- 2026-10-26: Planning preserves delivery gates when grouping work: only independent ready
  stories share a new build block, while started blocks retain their resume identity. Token-cost
  packing still applies within the ready frontier without an acceptance-count cap. Planning
  guidance retains source-defined algorithms and interfaces in the owning stories. Build progress
  groups checks by story and labels per-check case counts and deltas explicitly. Repair feedback
  prioritizes measured case losses; the agent runs targeted tests and Drydock owns complete
  deterministic acceptance, removing duplicate mandatory suite runs from the build contract.

- 2026-10-25: `drydock build` prints one `status` line per LLM call after grading, replacing the
  pre-call `fixing=` line and the post-call `acceptance=` line:
  `status  2/5  block-parsing-conformance(248/286 +16),...`. Each failed check shows cases passing,
  cases that check selected, and the change since the last measured call. In the `BUILD FAILED`
  report, a criterion whose own `assert` failed prints `AC FAILED  <id>  <passed>/<selected> passed
  (<n> failed)` with its intent and source instead of an exit code, `Error: AssertionError`, and a
  traceback.

- 2026-10-25: The blocker banner printed by blocked commands, refusals, and UAT stops is a rounded
  box with the `BLOCKED: <Target> · <declared>` heading in its top edge, replacing the `=` rules.
  Long lines wrap at spaces under their indent, paths are never split, and the ASCII glyph tier
  draws the frame with `+-|`. Boxes are colored by outcome: an environmental blocker is red, a
  decision-only blocker yellow. `drydock build` closes a run that completes the Target with a green
  `BUILD COMPLETE: <Target>` box. The UAT verdict box is green when passed and red otherwise,
  `STEP ERROR` is red, and `NOT READY` is yellow. All of these replace `#` frames. A child's banner
  shows red in the UAT live console without the stderr `!` gutter. Color is written only to a color
  terminal; redirected output, pipes, captured evidence, and `NO_COLOR` remain plain text.

- 2026-10-24: Live UAT step headers use uppercase commands and positional arguments, with
  the exact invocation below. The first occurrence has no suffix; repeats within a kit append
  `[2]`, `[3]`, and so on. Batch output omits child `Next:` guidance. Terminal headers and plan
  progress are blue, successful completions and final verdicts green, and failures red;
  redirected output and `NO_COLOR` remain plain. Evidence and execution labels are unchanged.

- 2026-10-24: `drydock uat` shortens terminal output: plan progress uses one line per batch,
  redundant status views and housekeeping stay in evidence, and failed steps receive bordered
  error boxes. After reports and checkpointing, each kit ends with a prominent recorded verdict,
  blocked state, failed command, and diagnostic, including with `--quiet`. Readiness probes are
  labelled `NOT READY`. Full stdout/stderr logs and run behavior are preserved.

- 2026-10-24: `design/` is redefined as Drydock's Memory Files, the persistent project memory
  shared by every session and provider. AGENTS.md `## Memory Files` replaces `## Design` with an
  index, one format, and completion gates. Every Memory File is `# MEMORY: <name>`, a Field/Value
  table, then `## Intent`, `## Guardrails`, `## Details` (formerly `## Behavior`), `## Decisions`,
  `## Questions`, `## Actions`, and `## Working Notes`. A `design/skills/` kind holds state a skill
  keeps across runs. The `/ddk-uat` ledger moves from `design/uat_diagnoses.md` to
  `design/skills/ddk-uat.md` (`uat_diagnostic` prompt V7). The language-agnostic and planner
  step-validation plans move to `design/topics/`. Every operation closes four gates before it
  reports completion: Details updated, open questions and actions written to the Memory File,
  `CHANGELOG.md` entry, commit. `docs/Drydock_Specification.md` must be correct but need not be
  complete or explanatory. `tests/test_design_coverage.py` enforces the index and the format.
- 2026-10-24: `BLOCKERS.md` is the one file that blocks a Target; `STOP_NOW.md` and its
  `Clear this stop and continue? [y/N]` prompt are removed. Drydock writes the file in one format
  (`# Blockers: <summary>`, `target`, `source`, `owner`, `declared`, `execution`, `attempts`, then
  `## blocker-NNN` entries of kind `environmental` or `decision`, each ending in `### Commander
  Resolution`). A fatal provider failure writes an environmental blocker owned by the command
  that hit it; `analyze` and `refit` write decision blockers, and only they may. While the file
  exists every Target command except `status`, `run`, and `uat` is refused unless it is the
  owner. At a terminal a blocked command asks `How should we proceed?` per blocker, records the
  answer as its Commander Resolution, reruns the owner with the resolutions prepended to every
  prompt as its primary instruction, then continues. Unattended, the owner reruns only when every
  decision is resolved and every environmental blocker may auto-continue (timeout, outage, or a
  rate limit past the reset its message states), once. Owner success archives the file to
  `logs/blockers.md` and deletes it. An ordinary failure clears environmental blockers and writes
  `ERRORS.md`. `plan --override` now passes an `analyze` decision-only file, recording
  `analysis-blocker` waivers. `status --ready` prints `BLOCKED: <Target>`. The Chair stop view,
  `drydock uat` halts (class `uat stage`), and `scripts/uat_repair_loop.sh` read `BLOCKERS.md`.
- 2026-10-24: Repository pytest runs cap each invocation at eight workers, including
  `python -m pytest -n auto` and `bash bin/test.sh`, to bound concurrent test load.

- 2026-10-24: `ddk-uat` investigates warnings, rejected artifacts, repairs, and defective-output
  retries in successful and running runs as well as failed runs. Diagnoses assess clean execution
  separately from the recorded result, trace upstream findings through later failures, and keep
  recovered defects open until a corrected run reaches the affected stage without recurrence.
  The FxRates kit brief specifies uniqueness of `(date, currency)` rather than prescribing a
  composite primary key; historical run inputs remain unchanged.

- 2026-10-24: `drydock plan` Stage 2 progress no longer prints `Rejected:` for a refused
  Blueprint batch that will be retried. `Batch Result:` reads `Retrying (<n> left): <reason>`,
  then `Retries exhausted: <reason>` on the refusal that ends the no-progress allowance, and
  `Failed:` when the model call itself fails.
- 2026-10-24: `drydock rigging compact` always refreshes stale compact and no-surface siblings
  throughout shipped `Rigging/`, including SQLite guidance. A bare run needs no Target; a Target
  or explicit include paths add sources to the same run. `--all` remains accepted but is
  redundant. Fresh derivatives and Rigging files without existing siblings remain untouched;
  explicit exclusions and `--force` retain their behavior. Internal build compaction keeps its
  explicit source scope.

- 2026-10-24: Acceptance isolation is owned by the harness, not the criterion. Each Python
  Programmatic Acceptance criterion runs inside one store transaction that the acceptance runner
  begins before the criterion and rolls back when it ends, pass or fail. Every `Database` the
  criterion's process opens joins it, including `persistence.testing.db_session()`, the
  application behind an in-process `web_client()`, and commands run through `cli_runner()`, so a
  request made after a `with db_session()` block now sees its setup. Criteria no longer commit or
  clean up, and `committed_session()` is for project test suites. Processes a criterion launches
  do not inherit the transaction, and `drydock plan verify` reports an `acceptance-store` defect
  for a criterion that both imports `persistence` and launches a process. Go criteria keep their
  `OpenSession` rollback scopes.

- 2026-10-23: `drydock plan` exits `0` when it writes a plan that `plan verify` rejects. The
  Manifest stays `draft` with sub-state `unbuildable`, so Build still refuses it; `ERRORS.md`
  records the defects, and the command prints the report and
  `drydock plan verify <Target> || drydock plan repair <Target>`. `plan` writes, `plan verify`
  judges, `plan repair` fixes. Exit `1` now means no plan was written. `drydock uat` reaches its
  verify-and-repair stage instead of halting on the plan's exit (FxRates `20261024.015228`).

- 2026-10-23: The `DATABASE.md` operation fingerprint recorded in the Manifest hashes only what a
  caller depends on: name, Kind, Match, rows, return shape, and each field's name and caller
  type. A column length, nullability, `Required`, `DEFAULT`, or index change no longer makes Refit
  rebuild the Features citing the operation. Manifests recorded with the earlier fingerprint read
  an unchanged declaration as unchanged. The Go runtime's `get` no longer appends `LIMIT 1`; a
  `get` matches a unique key, and both runtimes now build identical statements.

- 2026-10-23: Package version advances to `0.8.0`; the project remains beta. The version
  prepares the next announcement and does not mark the unreleased changes as shipped.

- 2026-10-23: Every `DATABASE.md` table declares exactly one `PK` column. `drydock plan`
  refuses a table with no `PK` or with two, naming `id | INTEGER PK` as the fix and a
  `- UNIQUE (a, b)` bullet for a natural key over several columns. The generated persistence
  package reads, updates, and deletes a row by that key, so a keyless table previously planned
  cleanly and then failed every update at the DATABASE build step. `BLUEPRINTS_CONTRACT.md` V28
  and the `DATABASE.md` template state the rule.

- 2026-10-23: `model_config.jsonl` model rows accept an optional `effort` that applies when no
  effort is requested by `--effort`, `drydock_effort`, or prompt frontmatter. The seed gives
  `opus` and `sol` rows `effort: low`. Opus is split from the `fable|claude` row. `sol` selects
  the `codex` provider. An existing live `model_config.jsonl` keeps its rows until it is replaced
  from the seed.

- 2026-10-23: `drydock plan` packs build blocks by assembled token cost alone. The per-block
  cap of 5 Programmatic Acceptance criteria (`DEFAULT_BLOCK_ACCEPTANCE_LIMIT`) is removed. Once
  every story carried criteria, typically 3–8 each, the cap forbade every merge: ReadingList
  planned 14 single-story blocks of 3–11K tokens against a 70K target, with one model call per
  story. Stories now merge while the block stays under `prompt_target_tokens` and the merge
  saves at least `block_min_savings`.

- 2026-10-23: `drydock plan` keeps every block under the model's escalation limit. For a model
  row that sets `prompt_limit_tokens`, the absolute block ceiling is 90% of that limit less the
  row's build overhead, in place of `prompt_warning_tokens`. For Haiku that is 82,563 planned
  tokens, about a 90K request, against the 98K point where a call escalates to Sonnet. The
  multi-story target is clamped to the ceiling, and a single story over it fails planning instead
  of building on `escalate_model`.

- 2026-10-22: Every built story is guaranteed a criterion. `drydock build` now refuses, before any
  model call, a story whose implemented Blueprints carry no Programmatic Acceptance
  (`criteria-missing`) instead of leaving that refusal to `drydock plan` alone. A story naming no
  Blueprint, or a file outside `blueprint/` such as a Rigging stack file, now counts as having
  none, and a Refit ticket under `blueprint/changes/` is counted from the ticket itself.
  `plan verify`, Plan's Stage 2 gate, and Build also refuse a `DATABASE.md` whose criteria never
  call a declared repository operation (`operation-untested`; Python `db.<table>.<verb>(...)`, Go
  `db.<Table>.<Verb>(ctx, ...)`). `plan_create` V45 requires one criterion per operation. The
  buildable `Rigging/spec_template/` files (ARCHITECTURE, DATABASE, FEATURE, HOMEPAGE, SCREEN, UI,
  UI-Component) seed a required-acceptance note in place of `- None.`.

- 2026-10-22: `drydock build` grades a DATABASE-only step without a model call. When every story
  in the step implements only `DATABASE.md` and the persistence package was generated, the step's
  criteria run against the generated package and close it `closed/verified`,
  `closed/implemented`, or `closed/failed`. Persistence is now generated after the criteria
  baseline, so those criteria are red before the step and can verify it. The runtime probes in
  `evidence/persistence-verification.json` no longer verify the persistence story on their own.
  Previously the agent had nothing to write, reported `RESULT: FAILED`, and spent every repair
  on the same report.

- 2026-10-22: `/ddk-uat` records every failed run it diagnoses. `uat_diagnostic.md` V5 appends a
  `design/uat_diagnoses.md` row even when no cause is established (`undetermined:` plus the missing
  evidence), and a row for each contributing, independent, or reporting defect, marked in Stopped.
  The report closes with the rows appended and the Outcomes changed.
- 2026-10-22: `drydock plan` Stage 2 refutes three more kinds of `BLUEPRINT_BLOCKED.txt` claim, so
  a block that names no real decision is answered in the retry instead of standing and deferring to
  the Commander (exit `2`): an entry whose `Required action` names no decision ("None needed", "can be
  authored"); a claim of any error type that rests on accepted Blueprints, which batches do not
  receive; and, under `DRYDOCK_UAT=1`, any `insufficient-specification` entry, which the batch
  resolves by choosing the narrowest behavior consistent with its inputs. Unattended, only a
  standing `conflict` defers.

- 2026-10-22: Structured Analyze, Plan, score, and prompt-review calls declare an optional output
  format at `llm.run_prompt`. Narrow cleanup removes bounded wrapper narration and JSON fences,
  preserves raw evidence, and records every removal. JSON consumers reject duplicate keys and
  ambiguous surrounding content; existing command validators and retry budgets remain authoritative.

- 2026-10-22: `drydock plan` preserves source schema contracts when accepting its database
  batch. The database is authored first regardless of topology text order, so no Feature is
  frozen against an absent declaration. Missing seeded tables, columns, and composite
  `UNIQUE`/`INDEX` constraints are restored;
  a changed seeded column type or constraint rejects that batch with a precise retry reason.
  Whole-command regression coverage exercises CRUD declarations through Manifest creation and
  `plan verify`, including recovery from a changed source column.

- 2026-10-21: `drydock plan` authors `DATABASE.md` in one Stage 2 step instead of keeping it open
  as a cumulative, append-only declaration. Every file a batch may emit is named in its Current
  batch. `DATABASE.md` is a batch of its own when it comes due (a batch ends before it), starts from
  the Rigging and source seed, must declare every table and repository operation the frozen
  topology needs, and is frozen once it parses; seeded tables the model drops are appended. Later
  batches receive it as `DATABASE_compact.md`, a deterministic copy with authoring comments and
  examples removed, and a batch that changes it is refused whole. `plan_continue.md` V3,
  `plan_create.md` V42, and `BLUEPRINTS_CONTRACT.md` V25 state the contract. Previously the seed
  sat outside every Current batch under an instruction to emit nothing else, no batch added the
  update and delete operations later Features needed, and plan stalled on refusals.
- 2026-10-21: Acceptance binding accepts deterministic known answers. A literal of printable
  ASCII text, newlines, and tabs binds, and its only allowed backslash is an escaped quote `\"`.
  A CSV report, a status line, or quoted output no longer settles `DISPUTED` on a miss.
  Another backslash, a carriage return, or non-ASCII text still marks a re-typed value.
- 2026-10-21: `drydock plan verify` reports two new acceptance defects, and `plan_repair.md` V10
  repairs both. `unchecked-call`: a `cli_runner` call whose exit status no `assert` reads.
  `staged-value`: a criterion whose first call on a key from a staged CSV's first column expects
  a non-zero exit, without loading that file. Previously, a silently failed setup call or an
  unloaded seed record left a criterion testing state that did not exist, and the product was
  charged for it.
- 2026-10-21: `drydock analyze`, `plan`, `survey`, `survey import`, and `document` discard short
  model narration outside artifact blocks instead of failing, and print each discard as
  `[<command>] stray text <where> discarded: "<text>"`. Only up to three plain lines (500
  characters) qualify. Outside text shaped like content — a heading, list, table, fence, JSON,
  markup, `===` — or beside an orphan close still fails the parse, and `plan` discards only when
  every artifact opens and closes exactly once. A one-line preamble from a low-end model no longer
  fails the run. The analyze, plan, and survey prompts drop their dead tool-call prohibitions,
  since non-build calls run with tools disabled, and state a no-stray-text rule instead.

### Fixed

- 2026-10-28: Source distributions include `model_config.jsonl`, allowing `uv build` and the
  PyPI/TestPyPI publishing scripts to build the wheel from the sdist with its model seed intact.

- 2026-10-28: `drydock plan repair` uses the acceptance parser’s declaration boundaries, recovering criteria with spaced metadata or whitespace-only separators without duplicate probe fields or inserting metadata into Python.

- 2026-10-28: `drydock plan repair` retains the original acceptance criterion when applying probe declarations, so model formatting or incidental proof changes cannot block a valid declaration or alter the test.

- 2026-10-28: `drydock plan repair` recovers matching full-command selection probes into flag-only declarations, chooses the listing count protocol, and continues to reject empty selections while preserving the acceptance test.

- 2026-10-27: Generated Python persistence exports `initialize_database(dsn)` for explicit
  application initialization. It creates missing tables and indexes from DATABASE-generated
  `schema.sql`, preserves existing records, resolves the script independently of cwd, and joins
  acceptance rollback. Ordinary opens do not initialize; initialization never resets or migrates
  tables. FxRates instructions now require this lifecycle, and its supplied grader initializes a
  fresh isolated store through the application before running the unchanged 35 checks. Changed
  instructions require a fresh kit run; historical runs remain unchanged.

- 2026-10-27: `/ddk-uat` diagnoses failures with concrete, evidence-verified repair recommendations
  naming the owning files, resulting behavior, regression proof and rerun boundary for a separate
  implementation loop. Unproved hypotheses and optional low-value improvements remain notes;
  explicitly authorized repairs are completed within the active pass.

- 2026-10-27: Planning authoring contracts explicitly require exit assertions on every
  `cli_runner` call, including final readbacks. Shared and current-batch guidance includes
  setup, rejection and incorrect/correct readback examples to prevent unchecked calls in initial
  AC generation; verification and repair behavior are unchanged.

- 2026-10-27: Stage 2 planning repeats current-batch topology instructions and interfaces beside
  its work queue. Corpus selection guidance preserves deferred cross-feature coverage: a section
  containing later capabilities belongs on an integration after those providers exist, while the
  earlier story verifies its own API. A nonempty selection probe does not prove schedule validity.

- 2026-10-27: SQLite configuration acceptance can test `DATABASE_URL` prefix/precedence,
  `DATABASE_PATH` fallback, default paths and source-required open failures through the
  harness-owned `database_environment` fixture, with disposable cwd/paths and exception-safe
  restoration. Planning and mechanical repair share this contract; ordinary persistence
  criteria continue using the provisioned store. Database-interface parsing preserves shared
  citations when an empty input or unobserved output field list is omitted.
- 2026-10-27: Build repair feedback includes a concrete failing corpus example and identifies
  unchanged case counts, directing the agent to reproduce and regress the actual failing branch
  before returning an edit. Descriptions of malformed product input no longer combine with a
  suite name in a different report field to falsely dispute acceptance and recommend Plan repair.

- 2026-10-26: Provider quota and expired-login results that Claude reports as
  `usage_limit_reached`, `rate_limit_error` or `OAuth token has expired` stop the process as
  provider stops instead of reading as ordinary failures. `drydock build` labels a repair driven
  by the regression sweep with its measured failing and regressed check counts instead of
  `agent-reported`.

- 2026-10-26: `drydock build` resolves a bare context name such as `INSTRUCTIONS.md` against
  `blueprint/sources/` after the Blueprint and Target, so the imported source brief reaches the
  build prompt instead of being reported as missing context. `drydock rigging compact` and
  `drydock status` treat a derivative as fresh only when its recorded source sha256 matches,
  regardless of timestamps. `drydock plan verify` accepts helper functions that unpack
  `cli_runner` and return its exit status first. `drydock plan repair` routes criteria outside the
  `=== AC <id> ===` form to replanning without a model call and keeps `REPAIR_IMPOSSIBLE` reasons.

- 2026-10-26: Project pytest tests run by a `drydock build` agent each receive their own copy of
  the call's provisioned SQLite store through a Drydock-staged pytest plugin, so one test's
  committed rows or `cli_runner` writes no longer contaminate another. The plugin reaches only the
  provider child (`PYTEST_ADDOPTS`, `PYTHONPATH`); generated product code is unchanged.

- 2026-10-26: `drydock build` settles a declared criterion that the executor returned no result
  for as `UNVERIFIED` (`not executed`) instead of dropping it, so a story whose criteria never ran
  closes `closed/implemented`, never `closed/verified`. The agent's `AC_BROKEN` dispute line
  (`agent reports defective (recorded, not accepted)`) now prints in normal build output.
  `drydock plan repair` that leaves the plan buildable retires the `plan verify` error it
  superseded, so `drydock status` no longer reports `plan cannot be built as written`; errors
  owned by other commands are kept.

- 2026-10-26: Decimal provenance limitations become nonblocking advisories instead of triggering
  source-aware repair that can invent rounding. SQLite build-agent calls use fresh provisioned
  disposable stores and private pre-call snapshots of managed application state; detected changes
  stop the block with retained recovery evidence rather than silently overwriting concurrent data.
  Persistence recovery identifies its DATABASE owner, uses the managed-state phase and bypasses
  speculative inline diagnosis. Memory files gain concise current contracts, `/ddk-uat` gains an
  assistant-owned assumptions review, and the stabilization plan defines state ownership, minimal
  frozen regressions and staged validation before the ten-kit release matrix.

- 2026-10-26: Planning validates staged selection probes before finalization and lineage using
  the same gate as `plan verify`; rejected criteria enter bounded source-aware artifact repair
  with only the implicated runner source. Exhausted repairs retain draft/unbuildable state.
  Declared consumed interfaces require a prerequisite path to a provider, preserving independent
  story grouping. Shared recovery policy routes authoring and graph faults to replanning instead
  of repeatedly recommending mechanical repair. Planning prompts clarify source-stage and
  interface dependencies, supported probe arguments, authoring review versus computed schedule,
  and Blueprint ownership of executable acceptance.

- 2026-10-26: `drydock plan` prechecks validator imports before calling a model or rewriting a
  plan. An incompatible installation now exits 1 with `PRECHECK FAILURE` and an internal-error
  record instead of failing only after Blueprint generation. Import errors during validation
  stop model repair and identify an internal planning failure; recovery directs the operator to
  repair the installation and start a fresh process from a consistent checkout. Precheck errors
  do not trigger automatic model diagnosis. This addresses LayersTesting `20261026.161555`.

- 2026-10-26: `drydock plan verify` rejects a criterion declaring `python-package=httpx` when
  another criterion of the same Target declares `httpx2` (`test-transport`); `drydock plan repair`
  may replace only that `Requires:` line. Planning and Blueprint contract examples now name
  `httpx2`, the Starlette 1.2+ FastAPI TestClient transport. When `drydock build` fails on
  `authorized acceptance prerequisite unavailable`, the failure detail lists each missing
  requirement once with its declaring criteria and names an installed alternative TestClient
  transport, so diagnosis corrects the declaration instead of the Target. FxRates
  `20261026.153843` failed block-3 on three `httpx` declarations while the Target locked `httpx2`.

- 2026-10-25: Planning instructions place function acceptance before downstream CLI integration
  gates. `drydock plan verify` rejects literal CLI calls whose declared command provider builds
  in a later block (`acceptance-order`), including calls through local forwarding helpers and
  literal command loops. Same-block calls remain valid; unknown expressions do not invent
  dependencies. Mechanical repair preserves coverage and reports the need to replan rather than
  weakening criteria or adding a dependency cycle. This prevents the DrydockStats filter/report
  acceptance deadlock diagnosed in run `20261026.011913`.

- 2026-10-25: Planning and verification reject fixture-row expectations that contradict declared
  repository order and immediate spawn-only service checks; mechanical repair preserves their
  intent. Artifact repair rechecks criterion imports before admission. Lineage gets one bounded
  correction of invalid story ids without changing source text or valid links. Untiered additive
  guidance no longer requires a runtime foundation. FastAPI tooling recognizes modern httpx2 and
  explicitly selected legacy httpx transports. New UAT receipts report check outcomes and
  undetermined defect ownership instead of equating executed failures with product defects.


- 2026-10-25: `drydock plan` and `plan verify` reject unsupplied literal formatted decimal
  expectations (`decimal-oracle`) unless the cited source contains the exact answer. Numeric
  acceptance authoring derives its oracle from fixture inputs and source-defined rounding;
  mechanical `plan repair` reports this authoring defect without guessing or spending a call.
  Build failure banners and stderr select the story owning the failed criterion within a grouped
  execution. Planning advisories distinguish criterion declarations from project stack selection
  and acknowledge indirect route coverage; authoring places Requires metadata inside AC blocks.

- 2026-10-25: `drydock plan` resubmits a malformed Stage 1 topology response once with its
  rejected output and exact artifact-boundary defects. Prose-only and malformed-envelope replies
  share one correction allowance; another invalid response stops planning, and a retry provider
  failure reports its own cause. The correction preserves strict validation and original evidence.

- 2026-10-25: Planning names invalid `DATABASE.md` operation headings and the required uppercase
  ID and em-dash grammar, including invalid headings beside valid ones. Artifact parsing keeps
  bare acceptance closes inside their Blueprint for criterion validation instead of treating
  `END AC` as another artifact and reporting an incomplete envelope.

- 2026-10-25: Scoring commands suppress grader JSON fragments beginning with punctuation or
  indentation instead of displaying them as broken progress lines. Explicit provider telemetry
  and the final verdict listing remain visible, including when called by `drydock uat`.

- 2026-10-25: A build agent that interrupts its own verification command no longer skips
  deterministic acceptance. The pass is graded, the next repair receives the measured failures,
  and repair progress is compared against the last graded pass, so a gain after an ungraded pass
  is no longer counted as a flat pass that stops the block early. Scoped conformance tallies use
  the cases the check selected as the denominator (`total - skip`), not the whole corpus.

- 2026-10-24: Planning and `drydock plan verify` reject conflicting `DATABASE.md` output DTO
  definitions before persistence generation. Admission and the Python emitter share class-name
  and field-type normalization; diagnostics identify both operations and their shapes and suggest
  an operation-derived name for a distinct projection. Identical output contracts still share
  one class. This fixes FxRates planning accepting `Rate` with three fields for reads/upserts
  and two for delete; mutation return behavior is unchanged.

- 2026-10-24: Failed UAT builds retain the child error and stdout/stderr evidence locations in
  `BLOCKERS.md`, console output, and the recorded stop reason instead of replacing the cause with
  a generic frontier message. A separate explanation states why the unfinished build stops
  acceptance and scoring. Blocker timestamps use local time; console messages omit internal
  ownership and retry metadata, duplicate file dumps, and empty environmental resolution fields.
  Internal gate state remains persisted, including retry limits.

- 2026-10-24: CsvStat-driven acceptance corrections keep unwritten native Go tests eligible
  after implementation, preserve actionable assertion failures ahead of excluded checks in
  bounded build repair feedback, and stop UAT receipt accounting from hiding failures when
  unverified checks are present. `drydock plan` prints warning details without `--debug` and
  removes an obsolete debug-path import. Blueprint authoring guidance requires serialized CSV
  success fixtures with padding inside quoted values; malformed CSV remains a rejection case.
  Published UAT evidence and generated Target data remain unchanged.

- 2026-10-24: `drydock build` grades no-op verification steps even when the agent reports
  failure without changing files; a green step no longer spends its repair budget on empty
  feedback. The build prompt permits verification without edits, and attempt evidence distinguishes
  bypassed acceptance from failed checks. Existing prepassed and governed verification rules
  remain in force. `plan verify` accepts a helper's directly returned `cli_runner` result when
  every caller asserts the exit, while rejecting discarded or rebound exits. These corrections
  address CsvStat's false terminal verification failure and recovered helper-call rejections.

- 2026-10-24: Staged corpus probes in `drydock plan` and `plan verify` resolve
  `os.path.abspath("literal-path")` against the criterion working directory without evaluating
  criterion code or requiring the candidate to exist. Corpus paths, filters, and assertions remain
  unchanged. Other unresolved command arguments now report `unresolved-probe-arguments` with
  argument positions; `plan repair` leaves them unchanged without spending a model call on
  declaration edits that cannot repair the command body. This corrects CommonMark's five
  probe failures after the selector and JSON-count fix.

- 2026-10-24: `drydock plan verify` identifies staged corpus selectors independently of
  program and corpus-path arguments and preserves the complete literal runner arguments when
  probing. `Probe Count: json` counts JSON array elements; empty arrays fail as empty selections,
  and JSON cannot pass by counting output lines. `plan repair` receives the implicated runner
  source and corrects failed probe flags/count protocols without changing the criterion's scope,
  command, or assertions. Planning guidance uses the supplied runner's supported listing mode
  rather than assuming `--list`. This addresses CommonMark's 19 pre-build probe failures and
  five false coverage passes.

- 2026-10-24: Repeated artifact filenames in one LLM response are full updates: planning and
  the shared artifact parser select the last body before normal validation, preserving unrelated
  files and the original response evidence. An unclosed final update requires recovery rather
  than silently restoring an earlier draft. This replaces conflicting-copy rejection; Stage 2
  malformed-response feedback also retains the exact parser defect.
- 2026-10-24: UAT Markdown and HTML reports display recorded blockers and failed workflow-state
  attempts instead of presenting a failed `PLAN CREATED` attempt as success. Conformance receipts
  distinguish a configured suite that was not executed from an absent or unrecorded definition,
  preferring the run's recorded acceptance contract over the kit definition. Run verdicts and
  published evidence remain unchanged.

- 2026-10-24: Fatal provider failures stop `drydock plan` without a misleading generation-stall
  report. CLI commands end with the recorded `BLOCKERS.md` cause; UAT prints it after summaries,
  report links, and checkpoints, including with `--quiet`. A failed optional verify/repair child
  with an environmental blocker ends the run immediately, and an environmental halt stops the
  multi-kit sweep before another kit starts. The UAT repair loop repeats the failure last and
  starts no repair session; `drydock_build_loop.sh` checks `BLOCKERS.md` before further build or
  diagnosis work and ends with the blocked cause. This addresses CsvStat `20261024.221659`, where a session limit was
  followed by stale artifact-rejection diagnostics and routine summary output.

- 2026-10-24: `drydock plan` and `plan verify` accept a `cli_runner` call inside a function when
  that function asserts its exit status. Each `def` or `class` body is now judged as its own
  scope; before, every such call was reported `unchecked-call`, which stopped DupFind
  `20261024.183232` at plan verify. `drydock plan` and `plan verify` also refuse a criterion that
  defines a top-level function nothing calls (`uncalled-function`): a criterion runs as a script,
  so a `def test_*` module passed without exercising the product. `drydock plan` refuses newly
  emitted Blueprints whose Programmatic Acceptance uses Markdown ```` ```python ```` fences instead
  of `=== AC <id> ===` blocks (`fenced-criteria`), which `plan repair` cannot address, and returns
  both defects to artifact repair. `plan verify` and Build still read existing fenced Blueprints.
  Recovery of a missing first artifact delimiter no longer mistakes `=== END AC <id> ===` for an
  artifact close.
- 2026-10-24: `drydock build` keeps a build out of any enclosing uv workspace. A Python Target's
  build receives a standalone `pyproject.toml` before the first agent call, and every tool-using
  agent call that registers its working directory as a workspace member of an enclosing project
  has that project's `pyproject.toml` and `uv.lock` restored and fails with both files named.
  This replaces the `uv` PATH shim, which Codex's login shell bypassed.
- 2026-10-24: Programmatic Acceptance binding detection no longer demotes an assembled
  expectation of plain text. An f-string, concatenation, `%` template, or `.format` call binds
  unless its typed text is escapable (backslash, carriage return, non-ASCII, `!r`/`!a`), the
  same rule a whole literal follows. A derived expectation such as `f"{mean:.6f}"` now gates
  its story instead of settling `DISPUTED` behind an analyze warning.
- 2026-10-24: `drydock plan verify` accepts a criterion that cites several source ranges, one
  `Cite:` line each; every range must resolve, and literal derivation searches their combined
  text. `drydock plan repair` treats the run of consecutive `Cite:` lines as one declaration, so
  a citation repair may rewrite, add, or drop ranges without being rejected as a proof change.

- 2026-10-24: Acceptance binding detection treats a string calculation compared with a literal
  as the observed expression, in either operand order, while retaining escaping checks on the
  literal and assembled-expectation checks elsewhere. `status`, `validate`, and `plan verify`
  no longer mislabel `f"{usd:.4f}"` as a retyped expectation. Empty-tree passes still cannot
  verify stories. Planning guidance requires criteria to observe the delivered application,
  rather than a replacement implementation inside the check; Stage 2 explicitly requires the
  three terminal sections, including source-derived Guardrails. This addresses the misleading
  warnings and generated self-tests observed in DrydockStats `20261024.155305`.

- 2026-10-24: `drydock plan` handles artifact-free Stage 2 replies with an additive
  instruction-failure correction while retaining the normal Blueprint batch. Automatic
  reduction to one file is removed. Retry evidence includes the refused reply, attempt count,
  execution id, and saved response path; the correction distinguishes authoring criteria from
  executing the future product and directs genuine source problems to `BLUEPRINT_BLOCKED.txt`.
  Repeated failures retain the existing bounded stop policy.

- 2026-10-24: `drydock plan verify` recognizes exit assertions over CLI results collected in
  a dictionary and checked in a subsequent complete `.items()` loop. Bounded validation retains
  rejection of discarded, overwritten, filtered, and rebound results. This removes the
  DrydockStats `REM-007` false rejection without requiring a `plan repair` model call.

- 2026-10-24: `DATABASE.md` contract checks report every defect in one pass. A table that does not
  declare exactly one PK column is reported beside the access-pattern defects instead of hiding
  them; unbound Input and Output fields are judged on every pattern that parses; duplicate
  operation names and synonyms are judged on every pattern whose fields bind. A Stage 2 rejection
  from the seed merge now lists the draft's other defects too, so `drydock plan` and
  `drydock plan verify` no longer reveal one tier of faults per pass. Closes FxRates
  `20261024.143213`.

- 2026-10-24: `drydock plan` Stage 2 returns a rejected `DATABASE.md` to the retry. The next
  batch receives its own merged draft in place of the seed and is told to correct each listed
  contract defect in it and change nothing else, instead of re-authoring the declaration from
  the defect text. The `plan generation stalled` detail now prints each rejection defect on its
  own line ahead of the blocked reports and the missing-Blueprint list, so the 800-character cap
  no longer drops the cause from stderr. Closes FxRates `20261024.140521`.

- 2026-10-24: `drydock build` starts persistence verification only at `.drydock-persistence.json`,
  the provenance record Drydock writes when it emits persistence from `DATABASE.md`. A story built
  before the DATABASE step that writes `schema.sql` itself no longer has every criterion failed
  unexecuted as "persistence artifacts missing" and its block closed without repair. Step close
  names such files as written before the DATABASE step, and a missing artifact after that step is
  named in the failure. Closes FxRates `20261024.073528`, which revised the presence check from
  ReadingList `20261022.220045`.

- 2026-10-24: `drydock plan verify` refuses a criterion that imports `persistence` on a story
  whose block precedes the `DATABASE.md` story's block (`persistence-order`, repaired by
  `drydock plan repair`). Such a criterion could pass only if the builder hand-wrote the
  generated persistence layer.

- 2026-10-24: Agent subprocesses run with a `uv` shim first on `PATH` that adds `--no-workspace`
  to `uv init`. A Target build nested inside another uv project, such as a UAT run under the
  Drydock repository, no longer registers itself in that project's `pyproject.toml`. Two such
  builds of one name had broken every `uv add` and `uv lock` in the build.

- 2026-10-24: `drydock plan verify` accepts resolving citations on already-binding numeric
  and plain-text expectations instead of rejecting an empty re-typed-expectation set.
  Escapable-literal citations still require a verbatim match. `plan repair` receives numbered
  referenced source files for `bad-citation`, may change only `Cite:`, and rejects removed or
  still-invalid citations and changes to the proof or other metadata. Missing supporting
  source evidence remains `REPAIR_IMPOSSIBLE`.

- 2026-10-24: Build failure reports use the complete block acceptance set and retain criterion
  disputes across attempts; disputed failures direct verification and mechanical repair before
  rebuilding, while claims remain advisory and repair budgets remain unchanged.

- 2026-10-24: `drydock plan` routes Go CLI `go-run`, `go-cli-args`, and `go-package-launch`
  defects into its existing artifact repair loop. `plan verify` rejects direct launches of
  `./cmd/<name>` source-package directories and literal list/tuple arguments passed to imported
  `drydock_go.cli_runner`; the client builds a separate executable and accepts separate strings
  or an unpacked sequence. `plan repair` includes the client contract, preserves arguments and
  assertions, removes one enclosing Python fence from an otherwise valid returned criterion,
  and rejects repairs that retain these defects. Structured CLI output guidance permits parsing
  CSV/JSON stdout and requires data assertions instead of exit-only checks. This extends the Go
  CLI correction introduced on 2026-10-22.

- 2026-10-24: `DATABASE.md` access patterns must name their DTO on the `Input:` and `Output:`
  line. A bare label previously took the next line's `| Field | Type |` header as its name, so
  every such pattern shared one generated row class, `FieldType`, and a `delete` whose Output
  is its key raised during the deterministic DATABASE build step. The bare label is now a
  contract defect that `drydock plan` refuses and repairs. The Python `schema.py` emitter
  refuses one DTO name declared with two field sets, as the Go emitter already did.

- 2026-10-24: Artifact-format LLM calls repair an exact final `=== END ARTIFACT` missing its
  trailing ` ===` when the envelope sequence is unambiguous, preserving bodies and original
  execution evidence. `logs/llm.jsonl` records `output_contract.repaired`; `drydock plan` prints
  repairs and names unrepaired envelope defects in progress and retry instructions, including
  after partially accepted batches. This prevents the Quakes 10/11 Blueprint stall caused by
  repeatedly discarding the final verification artifact without explaining its malformed close.

- 2026-10-23: An `update` with a declared Output returns that row read back by key, or
  `None`/`nil` when no row matched, in the Python and Go repositories. Its Output fields must be
  table columns. An `update` with no Output still returns the count.

- 2026-10-23: Generated persistence now returns what `DATABASE.md` declares. `drydock plan`
  refuses an `Output:` field that the operation cannot return. `get`, `list`, and `create`
  Output fields must be table columns, so a `list` Output declares the row, never a wrapper
  such as `books: list[Book]`. Each `delete` Output field must be an Input field. A `delete`
  with an Output returns that row built from the key, or `None`/`nil` when nothing matched, in
  both the Python and Go repositories. A `delete` with no Output still returns the count. The
  SQLite and PostgreSQL stack guidance and the `DATABASE.md` template state each verb's return
  shape for the planner.
- 2026-10-23: Foundational stories no longer claim `covers:` or `accepts:`. `drydock plan` drops
  both from every `type: foundational` story and from the story implementing `DATABASE.md`, and
  the Feature or Screen that delivers the behavior owns the analyzed story and its Sea Trials.
  `drydock analyze` no longer turns a stated language, database, or mandated table into a story.
  It records the fact in `TECHNOLOGY_STACK.md` or as a `COMPASS.md` constraint.

- 2026-10-23: `drydock score release` reads a tool-using grader's JSON from its final turn when
  the narration streamed from earlier turns fails JSON cleanup, and records `earlier-turn text` as
  removed. Unreadable grader output (invalid JSON, an unknown, duplicate, or missing Sea Trial, or
  an invalid trial verdict) is now an `ERROR` verdict written to `evidence/score-release.json`, not
  an exception. Previously, UAT inferred an acceptance `FAIL` from the exit code.

- 2026-10-22: Build progress reports each story's persisted state, including implemented-only
  stories, and Blueprint naming validation accepts the standard `VERIFICATION.md` release gate.

- 2026-10-22: `drydock plan` refuses a `DATABASE.md` access pattern whose `Input:` field is not a
  column of the table its operation reaches, naming the table's columns. The generated repository
  bound such a field as a column, and SQLite compared it as a string literal, so a `delete` keyed
  on `book_id` against `books(id)` removed nothing without an error. A placeholder Input row such
  as `(none)` now declares no field instead of a field named `(none)`, and generated Python row
  classes annotate fields with Python types (`int`, `str`, `float`) instead of SQL type names.
- 2026-10-21: `drydock analyze`, `drydock survey import`, `drydock document`, and
  `drydock import --format compass` retry once when a successful reply holds no artifact blocks.
  The retry resends the unchanged prompt with an appended `Artifact retry` block that quotes the
  reply and forbids asking, refusing, or explaining, and the console prints
  `[<command>] response without artifacts, retrying once with the reason: "<excerpt>"`. A model
  that answered with a question previously ended the run at that command.
- 2026-10-21: `drydock plan` retries a Stage 2 batch answered without artifact blocks as a
  one-Blueprint batch, and the retry says so, so it asks for less as well as explaining why the
  last reply was refused. An accepted batch restores the batch size of 5. The refusal excerpt
  (`[plan] response without artifacts: "<excerpt>"`) now prints without `--debug`. A model that
  kept refusing the same five-Blueprint batch previously stalled the plan.
- 2026-10-21: `drydock plan` tells a retried Stage 2 batch why the previous attempt was refused
  (`Previous attempt rejected — <reason>` in the ledger) instead of resending a byte-identical
  prompt, and prints the start of a response that held no artifact blocks. `plan_continue.md`
  V2 forbids answering with questions, tool requests, or refusals; open points go under
  `## Questions`. A model that asked instead of emitting previously stalled the plan.
- 2026-10-21: `drydock plan` keeps the seeded `DATABASE.md` (Rigging template plus
  `sources/DATABASE.md` tables) into the first Blueprint batch. The Stage 1 truncation check read
  the seed as a cut artifact, because the response never emitted it, and discarded it, so batch 1
  rewrote the declaration from scratch and could lose source-declared tables.
- 2026-10-21: `drydock plan` refuses a Stage 2 batch's `DATABASE.md` when the merged declaration
  does not parse, instead of accepting it and failing only after the last batch. The whole batch
  is refused, because its Features cite operations the declaration failed to hold. The console
  prints `Rejected: DATABASE.md does not parse: <defects>` without `--debug`, and the next ledger
  lists `DATABASE.md` as defective with the reason even though the seeded declaration is never in
  a batch's tranche. The `## Access Patterns has no named operation` defect now states the
  required `### <FEATURE-DOMAIN-NNN> — <Operation>` section form. Previously the defect reached no
  later batch and Features were accepted against the bare template.
- 2026-10-20: `drydock plan` requires every Programmatic Acceptance setup call to assert the success
  its source declares (`plan_create.md` V40, `BLUEPRINTS_CONTRACT.md` V24). A criterion that
  expected loading a valid staged asset to exit `1` created no state and failed against a correct
  loader. The `drydock build` repair feedback no longer claims `AC_BROKEN:` ends the repair budget.
  The claim is recorded as evidence and the budget is spent as for any other failure.

- 2026-10-20: Acceptance binding treats a comma as a contract-token character, so an expected
  literal such as a declared CSV header `account,name,transactions,balance` or total row
  `TOTAL,,0,0.00` is no longer reported as re-typed. Such criteria now gate their stories, and
  `drydock plan verify` and `drydock validate` stop warning about them. Whitespace, backslashes,
  quotes, and non-ASCII still make a literal non-binding.

- 2026-10-20: `drydock plan` requires every Programmatic Acceptance criterion to create the rows,
  files, or records its input refers to before the action under test (`plan_create.md` V39,
  `BLUEPRINTS_CONTRACT.md` V23). A valid-load criterion that named an account and category it
  never created previously failed against a correct product, and rejection criteria passed for
  the wrong reason.

- 2026-10-20: The shipped Python and Go persistence libraries autocommit every statement and use no
  database transactions. Python connections open in autocommit mode and the per-write `commit()`
  and failure `rollback()` calls are removed; Go applies the schema without a transaction. The Go
  generator maps SQL column types in `DATABASE.md` fields, such as `VARCHAR(12)`, to Go types
  instead of rejecting them.

- 2026-10-20: A generated `create` operation in the shipped Python and Go persistence libraries
  returns the row declared as its `Output:` in `DATABASE.md`, read back by key, instead of the
  engine's inserted key. SQLite reported its internal rowid even for a text primary key, so a
  criterion written against the declared row failed with `AttributeError` and no build could
  repair it. A create with no declared output, or a Go table with no key, still returns the key.

- 2026-10-20: `drydock build` records a pre-build acceptance criterion whose own code raises
  `FileNotFoundError` as `VALID product-missing` instead of `ERROR environment`. A criterion that
  reads a deliverable its story creates, such as `pyproject.toml`, previously was excluded from
  every post-build run and settled `UNVERIFIED` although the delivered file satisfied it.

- 2026-10-20: The shipped Python persistence library translates a refused or failed connection
  into `PersistenceError` from every declared operation and from `Database.execute_script`. An
  unreachable PostgreSQL server previously escaped as the raw driver exception, which no build
  could repair because `persistence/` is copied into the Target unchanged.

- 2026-10-20: The artifact-contract error raised by `drydock analyze`, `drydock plan` and the other
  delimited-artifact commands names where stray model text sits (before the first block, between
  blocks, after the last block, or with no block) and quotes its first line, truncated at 120
  characters. A rejected response no longer requires opening the preserved model output to locate
  the violation.

- 2026-10-19: `drydock build`, `drydock score ac` and `drydock score release` refuse a Target
  whose `TECHNOLOGY_STACK.md` selects `postgres.md` when no PostgreSQL connection is configured,
  instead of silently building and testing against SQLite. New `drydock config` key
  `postgres_dsn` (`POSTGRES_DSN`) holds the connection string, accepts only `postgresql://` or
  `postgres://`, is masked by `config show`, and is exported to schema application, acceptance
  runs and the application as `DATABASE_URL`. Added `docs/HOW_TO_SETUP_POSTGRES.md`.

- 2026-10-19: Python and Go Target workflows validate stack type counts and language prerequisites
  from shared Rigging policy before approval, planning and building. QuarterDeck preserves invalid
  drafts with validation errors and clears approval when language or database changes. Build,
  repair and Target compaction receive selected-language guidance. Native Go outcomes survive
  acceptance execution; shipped persistence libraries reject keyless deletes before SQL.

- 2026-10-14: `drydock plan` starts each Stage 2 Blueprint batch in a fresh Claude session with
  the frozen topology, decisions, current ledger, and cumulative `DATABASE.md`. Earlier batch
  output and thinking no longer grow every later batch's input context. Stage 1 retry and repair
  sessions retain their existing resume behavior.
- 2026-10-14: UAT run receipts and kit indexes report the models recorded for executed LLM calls,
  including automatic model upgrades, instead of labelling the run with the requested `--model`.
  `result.json` retains `requested_model` separately; mixed-model runs list every executed model.
- 2026-10-14: `drydock uat resume <Project>` preserves the inferred failed stage when it
  selects a recorded run. The CLI previously reset the stage to `init`, so the runner rejected
  the run with `A UAT run can only be selected together with a resume stage.`
- 2026-10-14: `drydock plan` treats a `PLAN_CREATE_ERROR.txt` or `PLAN_CREATE_BLOCKED.txt`
  block wrapped in prose as that Error or Blocked Mode report, not as an outside-text format
  failure. It now reaches the conflict challenge and `ERRORS.md` with its `Required action`.
  Previously the report was hidden and the recovery said to remove the outside text. The
  unattended UAT policy now states that an unstated status code, exit status, or error channel is
  never Error Mode: the planner chooses it and records it in `DECISIONS.json`. ReadingList's plan
  stopped twice on a refusal over unstated HTTP status codes.
- 2026-10-14: `drydock build` generates the persistence package before the DATABASE step runs,
  not after it closes. `DATABASE.md` is a Plan output, so the package depends on nothing the step
  produces. A story in the same step that imports `open_database` is now accepted against the real
  package. ReadingList's `web-server-foundation` shared block-2 with `database` and failed every
  attempt with `persistence` missing. The `sqlite.md` and `postgres.md` Foundation Contracts state
  the new timing.
- 2026-10-14: `drydock build` closes no story in a failed step. A group-mate whose own criteria
  passed is now `closed/failed` with `finding: step <id> failed: <checks>` and rebuilds with the
  step. Previously it closed `closed/verified` or `closed/implemented` beside the failure.
- 2026-10-14: The acceptance runner no longer replaces a criterion's exception with one raised
  while collecting diagnostics. A Flask `current_app` proxy in the failing frame raised "Working
  outside of application context" from the tally search and hid the real `ModuleNotFoundError`.
- 2026-10-13: `drydock plan` asks once more when the Stage 1 topology reply contains no
  artifact blocks. The model sometimes answers with questions instead of planning. The retry quotes
  that reply back and tells the model to resolve each point and record it in `DECISIONS.json`. A
  resumed Claude session receives only the instruction. If the second reply is also prose, the plan
  stops with a recorded `model artifact contract failed` error that shows the first 400 characters
  of the reply and points to the execution output. It no longer advises removing outside text.
- 2026-10-13: The `sqlite.md` and `postgres.md` Foundation Contracts (and their compact copies)
  now state how Drydock builds the persistence package. `DATABASE.md` declares the store. The
  story that implements it is the DATABASE step, and its builder writes no persistence code. When
  it closes, Drydock copies the shipped `db.py`, `sqlite.py`, and `postgres.py`, generates
  `schema.py`, `__init__.py`, `testing.py`, and `schema.sql`, and applies the schema. The previous
  wording said both that a synthesized story built the package and that the build never wrote it.
  A planner refused to plan ReadingList over that contradiction.
- 2026-10-13: `drydock uat` and `drydock uat report` treat UAT-kit Git initialization and
  checkpointing as best effort. A Git lock or commit failure no longer prints a secondary error or
  replaces the lifecycle or report exit status; other selected kits still get a checkpoint attempt.

### Added

- 2026-10-18: Python and Go persistence libraries and templates ship inside language bundles.
  DATABASE.md generates Python declarations or Go typed repositories; Go schema application uses
  the generated module. Both bindings support SQLite and PostgreSQL, including generated integer
  identities. Go SQLite requires CGO and a C compiler. Technology approval requires one language;
  the selector permits zero or more persistence engines. Real PostgreSQL integration covers both
  language bindings; generated schemas create absent objects and do not migrate existing tables.

- 2026-10-18: Python and Go language bundles group instruction contracts and acceptance support.
  Planning and build resource resolution find bundled instructions by their existing filenames.
  Go native tests report fresh results through the existing Blueprint AC harness, including
  missing/skipped tests and execution errors, without duplicating acceptance state handling.

- 2026-10-18: Rigging documentation defines common mandatory questions for Python/Go language
  instructions and SQLite/PostgreSQL engine instructions, classified by `Type`. Answers cover AC
  execution and measurement, persistence libraries, configuration and verification limitations;
  compact files retain the answers verbatim. Go persistence remains unsupported.

- 2026-10-13: `drydock report token <Target>` writes `reports/token.txt`, one row per LLM call
  in start order: start time (UTC), stage, call, model, prompt bytes, estimated prompt tokens, run
  time, and status. Failed and incomplete calls are included. Scope matches `drydock report llm`:
  since the latest successful `init`, or all recorded history when no init boundary exists.

- 2026-10-13: **Per-model token accounting and price-limit routing in `model_config.jsonl`.**
  Each model family's row gives its tokenizer ratio (`bytes_per_token`), the CLI's fixed
  first-request payload by `build` or `text` mode, the stacking target `prompt_target_tokens`
  (default 70000, replacing the global `prompt_warn_tokens` at 50000), the warning threshold
  `prompt_warning_tokens` (replacing `prompt_error_tokens`), and an optional `prompt_limit_tokens`
  with `escalate_model`. Story points, plan stacking, and warnings now count the active model's
  tokens; the former `ceil(bytes / 4)` undercounted Claude 5.5-family prompts by about 1.5x. Every
  LLM call whose estimated first request (or a resumed session's context plus the new prompt)
  exceeds 98% of its model's limit runs on the escalation model; the Haiku 5.5 row escalates to
  `sonnet` above 100K tokens, where its price rises fivefold. The build call line reports
  `upgraded=prompt_limit <from>-><to> (<estimate> > 98% of <limit>)`. The live file is user
  configuration beside `.env`, seeded from `Rigging/model_config.jsonl`; `DRYDOCK_MODEL_CONFIG`
  overrides its path. `--model` is now published to `DRYDOCK_MODEL` for the whole invocation.
- 2026-10-13: **Builders get builder tools only.** Provider rows in `model_config.jsonl` set each
  CLI's tool surface. Claude builds run with `--tools Bash,Read,Edit,Write,Glob,Grep
  --strict-mcp-config` instead of the CLI's default 24 tools, cutting the fixed per-request payload
  from 14,300 to 7,437 tokens on Haiku 5.5; codex builds `--disable` the app, browser, computer-use,
  image-generation, multi-agent, plugin, skill-search, tool-suggest, goals, sleep, and in-app
  browser features.
- 2026-10-13: **`drydock config calibrate [--probe] [--apply]`.** Every successful Claude call
  appends its measured first-request size to `logs/model_calibration.jsonl`. `calibrate` proposes
  a row's `bytes_per_token` (10th percentile over at least three non-resumed runs) and its
  `overhead_tokens` (from `--probe`, two trivial prompts) when they differ from the live value by
  more than 5%, and `--apply` writes them; nothing else rewrites the file. `drydock build` prints a
  `calibration:` line after a step when the evidence disagrees with the configuration or the CLI
  version was never probed. Codex reports usage per turn and is not calibrated.

- 2026-10-13: **The regression sweep covers every finished block.** After each green block,
  `drydock build` re-runs the criteria of every `closed/verified` or `closed/implemented` block,
  read from the Manifest, not only those proven earlier in the same invocation, so a build started
  by the outer loop still detects an earlier pass's deliverable being broken. A criterion whose last
  recorded run passed counts as green for attribution. Sweep results are recorded in
  `BUILD_LINEAGE.jsonl` as `swept` and feed per-criterion history (`drydock score ac`, AC repair).
  Criteria with an excluded status and blocks closed failed are not swept.

- 2026-10-12: **AC repair in `drydock diagnose`; DISPUTED holds `drydock status --check`.**
  Before diagnosing, `diagnose --apply` and the interactive default mode select criteria the build could not use as evidence:
  those whose last run settled DISPUTED and whose code is still non-binding, and those recorded
  `ERROR malformed`. One `diagnose_ac_repair` call receives each criterion's declarations, code,
  and fault, its specification, and the imported `sources/` with line numbers — never the build
  tree or product output. A repair is kept only when it parses under the same id, runs, is binding,
  cites truthfully, is not vacuous, and records `VALID` on the empty-directory baseline (an
  environment error is retried once). The default mode confirms each verified repair; a declined
  one changes nothing and stays selected, and `--no-apply` or a session that cannot prompt skips
  AC repair. A kept repair's Blueprint consumers reset for rebuild and the Target is
  committed. A rejected repair or `REPAIR_IMPOSSIBLE` reverts the criterion and records
  `UNFIXABLE`. `status --check` is RETRYABLE while a DISPUTED criterion remains selectable;
  `UNFIXABLE` criteria no longer hold it. A citation resolves to the cited source text including
  line terminators.

- 2026-10-12: **Empty-directory acceptance baseline.** Before each block, `drydock build` also runs
  its criteria in an empty temporary directory holding only the staged `sources/` inputs and no
  Target `.venv`. A criterion green there records `PREBUILD_PASSES` (`empty-tree`), keeps
  running, and cannot verify its story; one red there and green on the current tree records `VALID`
  (`existing-behavior`), keeps running, and still cannot verify the story that owns it. Baseline
  runtime roughly doubles.

- 2026-10-12: **Binding detection covers assembled and cited expectations.** An f-string, a `+`
  concatenation with a string, `"..." % args`, or `"...".format(...)` on either side of `==`/`!=`
  is a re-typed expectation unless the same expression is supplied as input, so such criteria
  settle DISPUTED rather than FAIL. An AC block may declare `Cite: sources/<file>:<line>` or
  `sources/<file>:<start>-<end>`; a literal found verbatim in the cited lines counts as derived.
  `drydock plan verify` reports a `bad-citation` defect when a citation does not resolve under
  `sources/` or its lines contain none of the criterion's expected literals. The Blueprints
  contract documents both rules.

- 2026-10-12: **`drydock build` runs only criteria that can measure the product.** A criterion
  whose current status is `ALWAYS_PASSES`, `ERROR`, `UNFIXABLE`, or `FLAKY` is not run after a
  block; it settles UNVERIFIED under the terminal `excluded check` prefix and the console lists it.
  `PREBUILD_PASSES` criteria keep running but cannot verify their story. Vacuity
  detection now prunes control flow decided by the source text: assertions under a constant-false
  branch or after `return`/`raise`/`break`/`continue`, and assertions inside a `try` whose
  `AssertionError`/`Exception`/bare handler does not re-raise or inside `suppress(...)`. A vacuous
  criterion records `ALWAYS_PASSES` from its code whatever its baseline outcome.

- 2026-10-12: **Per-criterion acceptance status and FLAKY detection.** `drydock build` records
  each criterion's baseline status in `evidence/acceptance-status.json` (`VALID`, `ERROR`,
  `ALWAYS_PASSES`, `PREBUILD_PASSES`, `UNFIXABLE`, `FLAKY`) with an error code that separates
  `product-missing` (a valid red) from `environment` and `malformed` (the criterion could not
  run). Entries are bound to a digest of the criterion code, so an edited criterion is
  re-classified; `ALWAYS_PASSES`, `UNFIXABLE`, and `FLAKY` survive later baselines otherwise. The
  file replaces `evidence/prepassed-acceptance.json`. After each pass, a binding FAIL that is not
  suite-bound is rerun once; when the rerun passes and the build tree is byte-identical, the
  criterion records `FLAKY`, settles UNVERIFIED under the terminal `flaky check` prefix, and is
  never repaired. `drydock score ac` adds Binding, Baseline, Previously Passed, and Last Block
  columns to `SOUNDINGS.md`, the last two projected from `BUILD_LINEAGE.jsonl`; boards are read by
  column name, so older boards still load.

- 2026-10-05: **`drydock report` publishes deterministic Target reports.** A report registry
  exposes status, Manifest progress, recorded run state, build evidence, command history, LLM
  usage, and score history through `drydock report help`. `drydock report <name> <Target>` writes
  one text artifact; `drydock report --all` writes all seven for every initialized Target under
  `targets/<Target>/reports/`, and `--all <Target>` limits the run to one Target. Paths print
  relative to the current directory when possible. A workspace sweep continues past a Target
  whose report fails and exits nonzero after naming the failure.
  Reports reuse recorded projections and evidence without executing builds, checks, UAT, or models.

- 2026-10-05: **`drydock build` records mechanical specification-to-code lineage.** Each agent
  execution, including repairs and failures, checkpoints application changes and appends
  `BUILD_LINEAGE.jsonl` in the Target. Records preserve runtime Manifest fields, implemented
  specification paths and hashes, timestamps, available token usage, acceptance results, execution
  and command-log links, and committed file deltas including deletions and renames. Completed-step
  records capture final states and generated outputs. Console commit lines name the block and
  only its `implements:` files. Target checkpoint trailers link receipts without a circular SHA;
  interrupted confirmed checkpoints recover their receipt. Existing changes receive a baseline
  checkpoint, and full resets preserve Git history. The build agent makes no attribution calls.

- 2026-09-22: **`drydock refit add` appends a REFIT ticket from plain text, and `/ddk-refit` drives
  it from chat.** `drydock refit add <Target> <Blueprint> <File>` writes
  `blueprint/<Blueprint>_refit_<NNN>.md` and appends one `pending` Manifest story. The filename is
  the ticket's identity: the number fixes order and parent, so a later ticket overrules an earlier
  one and the Blueprint. The story depends on the previous ticket's story, or on every story
  implementing the Blueprint for `001`, inherits the Blueprint story's stack, and sets
  `acceptance: yes` when the ticket carries `=== AC` blocks. Any authored Blueprint accepts
  tickets. The command never builds. The shipped `/ddk-refit` skill writes a change as acceptance
  criteria in the Blueprint's own form and calls the command. It is now the only skill Drydock
  ships; `drydock init` installs it. The design-discussion skills are renamed `/ddk-think` and
  `/ddk-think-apply`, and `/drydock-uat` becomes `/ddk-uat`. All three stay in the repository.

- 2026-09-20: **The block packer declines a merge that saves nothing worth having.** Merge
  candidates were ranked by shared-context savings alone, so any overlap above zero was worth
  taking and two stories sharing nothing but a compacted language file grouped for a few hundred
  tokens — a saving nobody can spend, bought by widening the context one model call must hold.
  The new `block_min_savings` configuration key sets the least shared context that justifies a
  merge, in tokens, and defaults to `1000`. `0` restores the prior behavior. Grouping is
  otherwise unchanged and still bounded by the block token target and the acceptance-criteria
  ceiling; no block composition is forbidden, including two tiers in one block. The floor applies
  wherever the shared optimizer runs, so `drydock plan` and a `normalize` edit of a computed
  `MANIFEST.md` group identically.

- 2026-09-20: **Language is a foundation, and it is built first.** `python.md`, `go.md` and
  `typescript.md` declare `**Foundation:** language` and publish an environment contract —
  `source_root`, `test_command`, the environment, and the dependency manifest — rather than a
  package and a fixture. A Target has exactly one language, refused in the same place two web
  servers are. A web server, a database or a CLI is built *into* the tree, the environment and the
  test runner the language foundation lays down; `fastapi.md` was never standalone.
- 2026-09-20: **The build chain is declared and ordered as six tiers.** Every Rigging file may
  carry a `**Tier:**` header. Tiers 1 to 5 are the foundation: 1 `language`, 2 `platform` —
  sub-ordered 2.1 `database`, 2.2 `web-server`, 2.3 `cli` — 3 `branding`, 4 `interface`,
  5 `screen-foundation`. Each holds at most one selected file per kind, publishes a contract, and
  is built into the tier before it: the palette before the shell that shows it, the shell before
  the screen idiom built on it. Tier 2's three kinds are independent, so they order by what
  imports what — a web server and a CLI import persistence, and persistence imports neither.
  Tier 6 is `application`: every service and every screen the Blueprints describe, with no
  internal order, ranked against each other by `depends:` alone. A file or story with no
  `**Tier:**` belongs to tier 6, which is how a service stays free to land either side of the
  interface tier. A tier is a rank *inside* a phase — never a phase, never a block — and the
  chain repeats in every phase, exactly as `MANIFEST_CONTRACT.md` already described it. Ordering
  the tiers forbids no block composition: two tiers may legally share a block, and what keeps
  unrelated work apart is that it shares no context, so the block packer finds no saving in
  merging it.

- 2026-09-20: Rigging files publish a **foundation contract**. A file that defines a foundation
  declares its kind in the header (`**Foundation:** web-server`) and its shape in a
  `## Foundation Contract` section naming the package, the entry point, and the test fixture.
  `fastapi.md`, `flask.md` and `django.md` publish `web-server`; `sqlite.md` and `postgres.md`
  publish `database`; the new `cli.md` publishes `cli`. Every web server builds `app_server` and
  offers `web_client`, every database builds `persistence` and offers `db_session`, so an
  acceptance criterion writes one name whichever framework the Commander selected — in Marina_Luna
  those names were invented 47 Blueprints at a time, splitting 98 imports of `app` against 77 of
  `marina_app` and calling Flask's `test_client()` 134 times on a FastAPI application. Kinds are
  open: a new exclusive foundation is a new Rigging file with a new `**Foundation:**` value.
  `prompts/BLUEPRINTS_CONTRACT.md` requires criteria to call the published fixture.
- 2026-09-20: `Rigging/stack/cli.md` — command-line application guidance: `main(argv) -> int` that
  returns rather than exits, argparse construction separated from behavior, exit codes `0`/`1`/`2`,
  and bash plus PowerShell launchers that share one `python -m cli` invocation so the two cannot
  drift in behavior.

### Changed

- 2026-10-20: The developer test suite runs in parallel. `pytest-xdist` is a `dev`
  dependency and `bin/test.sh` passes `-n auto`. On a 32-core WSL2 host the full suite drops from
  about 35 minutes to about 9.

- 2026-10-12: **`drydock build` verifies, progresses, and repairs on binding criteria only.** An
  ungoverned story reaches `closed/verified` only when an own binding criterion passes that was
  not green before the build; otherwise it closes `closed/implemented` with a finding naming the
  cause: no criterion ran, none is binding, or every binding pass was prepassed. Repair progress
  compares binding criteria only and requires an identical executed set between passes. DISPUTED
  misses no longer enter repair feedback, the resume seed, or the kit-fault stop test, and a
  non-binding criterion no longer fails a later block as a regression. A resumed block keeps the
  baseline recorded when it first built instead of re-baselining its own partial work. Verified
  counts drop for builds whose criteria were already green or re-typed.

- 2026-10-09: **Claude Haiku 5.5 runs as an effort-sized model.** `--model claude-haiku-5-5`
  and the bare `haiku` alias no longer receive the fixed `MAX_THINKING_TOKENS` budget, which
  Haiku 5.5 rejects. They size thinking from `--effort` like other current Claude models, and
  an inherited budget is removed from the subprocess environment. `haiku_thinking_tokens` now
  applies only to Haiku 4.x and older (`claude-haiku-4-5`). Output-truncation advice for Haiku
  5.5 names `--effort` instead of the thinking budget.

- 2026-09-22: **Bootstrap 5, Django, and Flask Rigging now contain only shared build contracts.**
  `bootstrap5.md` defers theme and asset delivery to Target UI guidance; `django.md` and
  `flask.md` retain their application and callable test client contracts. Their compact
  derivatives drop sample routes, settings, branding, and command scripts. Django acceptance
  now names `app_server.wsgi` as the `create_app` import module.

- 2026-09-22: **Python and FastAPI Rigging now publish only shared build contracts.**
  `stack/python.md` defines the language environment, dependency manifest, and test command;
  `stack/fastapi.md` defines the application factory, package, and callable test client.
  Both files and their compact derivatives drop example applications, routes, settings, shell
  process commands, and framework-specific guidance unrelated to the selected Target.

- 2026-09-22: **`/ddk-refit` resolves user-known surfaces to Blueprint owners.** A request may
  identify a page URL, API route, CLI command, screen, feature, file, error, or desired behavior.
  The skill uses Blueprint routes and contracts to assign tickets and adds service or database
  tickets only when the requested change requires them. A page request does not require the user
  to know its backing API.

- 2026-09-22: **Refit automatically groups accumulated unbuilt work by shared context savings.**
  `drydock refit` and `drydock refit add` run the deterministic optimizer on computed Manifests;
  `/ddk-refit` receives the same behavior through `refit add`. REFIT stories inherit explicit
  Rigging rules as well as Blueprint context and stack guidance. The optimizer retains Manifest
  context, rules, and instructions, prefers compact context, and counts full implementation
  inputs once. Ordered tickets from separate calls can share a block within the existing token
  and acceptance limits. Blocks containing non-pending work keep their membership, numbering,
  state, and recorded fields. Optimization errors roll back the refit transaction.

- 2026-09-21: **Foundation clients are plain functions criteria call against the built
  application.** A Programmatic Acceptance criterion runs as a standalone script, so the pytest
  fixtures the Foundation Contracts published (`web_client`, `db_session`, `cli_runner`) could not
  be called from one. Each contract in `fastapi.md`, `flask.md`, `django.md`, `sqlite.md`,
  `postgres.md` and `cli.md` now publishes the callable in `<package>/testing.py`
  (`fixture_source`), and `conftest.py` wraps the same function for the pytest suite. A criterion
  writes `from app_server.testing import web_client` and exercises the application in-process; it
  may also run the application's pytest suite, importing the foundation package first. Plan
  rewrites `create_app().test_client()` to the published `web_client()` and reports each rewrite.
- 2026-09-21: **A criterion against an unbuilt foundation fails cleanly.** Acceptance no longer
  runs a criterion that imports a foundation package (`app_server`, `persistence`, `cli`) the
  build directory does not contain. The result is FAIL with the error `foundation not built`,
  naming the package and the Rigging file that builds it, instead of a `ModuleNotFoundError`
  traceback or a pytest collection error. It is not a terminal failure: building the package is
  the build's work.

- 2026-09-20: `drydock plan verify` refuses a criterion that imports a package no selected
  foundation publishes — defect kind `unknown-package`, and the plan is written `unbuildable`.
  `app_server`, `persistence` and `cli` are reserved names meaning *the selected foundation of
  that kind*, so importing one the stack did not select raises `ModuleNotFoundError` in the
  criterion's own frame on every run. Importing a published entry callable from any other package
  is refused with the package it should have come from — the `app` / `marina_app` split, named
  before a build call is paid for. Nothing else is judged: whether an arbitrary third-party import
  resolves is a fact about the build environment, not the Blueprint.
- 2026-09-20: The QuarterDeck **Technology Stack** page selects foundations with one radio group
  per kind, captioned with its tier and in build order — Tier 1 Language, then Tier 2.1 Database,
  2.2 Web Server and 2.3 CLI — instead of a free-text row and
  a dropdown. The underlying fact is a choice, not a set, and a checkbox list invited the second
  selection `plan verify` then refuses. A Target with no rows starts on `python.md` /
  `fastapi.md` / `sqlite.md`; a Target that has rows and names no web server has decided it has
  none, and is left alone. Non-foundation technologies keep the free-text table, whose headings
  now read **Technology Label** and **Rigging File**, and a **Build order — six tiers** legend
  shows where a file with no exclusive choice — `bootstrap5.md`, `BRANDING_MAIN.md` — lands, and
  that tier 6 holds every service and screen.
- 2026-09-20: `django.md` rewritten against the published contract. The Django project package
  *is* `app_server` — `app_server/settings.py`, `app_server/urls.py`, `app_server/wsgi.py` — and
  `create_app() -> WSGIHandler` wraps `get_wsgi_application()`, so a criterion written against
  `app_server` and `web_client` runs unchanged whether the Commander selected Django, FastAPI or
  Flask. The old `config/` package is gone and the testing section publishes `web_client` rather
  than shadowing pytest-django's own `client` fixture.
- 2026-09-20: `bootstrap5.md` and `ui-flask.bootstrap-client.md` moved from category `Web Server`
  to `Frontend`. Neither is a web server; both were offered to the Commander beside the three
  files that are.

- 2026-09-20: `drydock plan verify` refuses a Technology Stack that cannot yield one foundation per
  kind, a new `foundation` defect. Two files of one kind — FastAPI and Flask — are refused, because
  that is two application shapes in one build tree rather than a richer stack. A row naming a
  technology whose Rigging publishes a foundation but leaving the Rigging column blank is refused
  too: Drydock does not choose a web server on the operator's behalf. Checked at plan, not at
  analyze — `drydock analyze` proposes the questionnaire and an unanswered row is a normal
  intermediate state there.
- 2026-09-20: `drydock rigging compact` carries a `## Foundation Contract` section verbatim. The
  section is removed before the prompt is assembled and spliced back into the output, so the model
  never sees it and cannot shorten it. A compacted contract is a changed contract, and the builder's
  copy and the Blueprint author's copy would drift silently.
- 2026-09-20: `fastapi.md` and `flask.md` name the application package `app_server` rather than
  `app`. `app` is also the conventional name of the ASGI/WSGI instance, and a package and an
  instance sharing a name is the ambiguity that made `from app import create_app` followed by
  `app.test_client()` look plausible.

### Fixed

- 2026-10-13: **`drydock build` applies the generated schema to the Target's store.** The DATABASE
  step generated `schema.sql` but nothing applied it, and Rigging forbids the application from
  creating schema at startup, so a criterion driving the application hit `no such table`. Drydock
  now applies `schema.sql` through the build's own `persistence` package to `DATABASE_URL`, else
  `DATABASE_PATH`, else `data/app.db` — at the DATABASE step (failure stops the step), before every
  programmatic acceptance run, before every governed gate, and before `drydock score` observes Sea
  Trials. The engine is the one the DSN selects, so SQLite and PostgreSQL are both covered. The
  DDL is idempotent.

- 2026-10-13: **The persistence foundation contract matches the generated package.**
  `Rigging/stack/sqlite.md` and `postgres.md` published `open_session() -> Session`, which the
  generated package never exported, so a build's `persistence/testing.py` failed to import and the
  pytest suite failed at `conftest` load. The contract now publishes `open_database(dsn) ->
  Database`, and Drydock generates `persistence/testing.py` with `db_session()`, a fresh store with
  `schema.sql` applied.

- 2026-10-13: **`drydock plan create` refuses a story that implements a Target input.** A topology
  story whose `implements:` names `TECHNOLOGY_STACK.md`, `METADATA.md`, `COMPASS.md`,
  `SEA_TRIALS.md`, or a forbidden artifact is sent to declaration repair before Stage 2, and an
  unrepaired one stops with `plan topology rejected`. Previously Stage 2 authored a Blueprint under
  that name in `blueprint/`, shadowing the input and leaving `ARCHITECTURE.md` undelivered.

- 2026-09-22: **`drydock plan create` preserves the short Compass produced by Analyze.** Imported
  Markdown classified as author intent remains source provenance and is no longer appended verbatim
  to `COMPASS.md`. Build steps receive one project orientation instead of repeated source pages.

- 2026-09-22: **`drydock build` compacts stack and rules files by Manifest order, not git HEAD.**
  A step receives `<file>_compact.md` for a `stack:` or `rules:` file that an earlier
  `closed/verified` or `closed/implemented` block named; the first block, a rebuilt root, and
  blocks after an unfinished predecessor receive the full file. Previously eligibility required
  the manifest `applied:` registry entry to equal the Drydock repository HEAD, so any unrelated
  commit re-injected full stack files (observed on refit blocks). A compact whose provenance
  sha256 no longer matches its source now falls back to the full file with a
  `WARNING: <file>_compact.md is stale` line naming `drydock rigging compact --include-file`.
  `implements:` files are never compacted, and a refit ticket's parent specification and earlier
  tickets always enter `context:` in full. The `applied:` manifest field is no longer read or
  written.
- 2026-09-21: **`drydock plan` derives omitted access-pattern DTOs from `## Schema`.** A
  `DATABASE.md` pattern whose Repository operation names one declared table and one verb
  (`get`, `list`, `create`, `update`, `delete`) now receives any missing `Input:`/`Output:` table
  from that table's columns before the persistence gate runs; a warning names each completed
  pattern. Previously a repair pass that added patterns to cover uncited tables but omitted their
  DTO tables failed the plan with `requires Input and Output tables`. Patterns with invalid
  operations or undeclared tables still fail the gate.
- 2026-09-21: **`drydock plan` writes criteria against the selected foundation's package.** The
  `unknown-package` gate added with Foundation Contracts refused every criterion importing
  `create_app` from an invented package, but nothing gave the author the package name: the plan
  prompt carried the stack table without the contracts, and the Blueprints Contract example still
  wrote `from app import create_app`. Marina_Luna lost a plan to 153 such criteria. The selected
  foundations' `## Foundation Contract` sections now accompany `TECHNOLOGY_STACK.md` in the plan
  prompt, the example imports from `app_server`, and Plan rewrites a lone import of a published
  entry callable to the module the contract names (`app_server.main` for FastAPI), reporting each
  rewrite. An import that also takes other names from the invented package is left for
  `plan verify`.
- 2026-09-20: `drydock plan verify` refuses a criterion that reads a Blueprint document, a new
  `blueprint-read` defect. Acceptance runs with the build directory as its working directory and
  the Blueprint is an input to the build, so `pathlib.Path("ARCHITECTURE.md").read_text()` raises
  `FileNotFoundError` on every run — no implementation and no repair pass can turn it green. The
  reading is worthless where it succeeds, too: grepping a specification for the words it was
  written with asserts that the document contains itself and passes against an empty build
  directory. Paths under `sources/` are exempt, because the Analysis stages those into the build.
  `drydock plan` already gates on verify, so such a plan is now written `unbuildable` and named at
  plan time instead of blocking a story a block at a time; in Marina_Luna this is 14 criteria
  across four Blueprints, the first three of which blocked the first build block after a paid
  model call. `prompts/BLUEPRINTS_CONTRACT.md` states the authoring rule.
- 2026-09-20: `drydock plan` no longer writes a plan that `drydock plan verify` refuses over a
  criterion reading the module it imported its factory from. `from app import create_app` followed
  by `client = app.test_client()` binds nothing named `app`, so the criterion raises `NameError`
  before it asserts anything; the plan was written `unbuildable` and the operator paid for a repair
  pass to recover a name the criterion's own import already determines. Plan now inserts
  `app = create_app()` below the criterion's last import, deterministically and with a warning.
  The rewrite is taken only where nothing else is plausible: the unbound name is not a standard
  library module, exactly one name is imported from the module rooted at it, and no attribute read
  of the name matches a submodule of that import — `marina.db` after `from marina.db import
  Session` means the module and is still reported by `drydock plan verify`. In Marina_Luna this
  repaired the four criteria that failed the plan and touched nothing else in 47 Blueprints.

### Removed

- 2026-10-25: `drydock_build_loop.sh` and its `DRYDOCK_RUNNER_MAX_BUILDS` bound are removed.
  `drydock_runner.sh` is deprecated: it forwards `<target> <model>` to `drydock run builder` and
  refuses an import-script argument. Its fixed model list and its haiku-to-sonnet analyze and plan
  substitution are gone; model choice is `--model` and `--plan-override-model` through
  `model_config`. `Import_Marina.sh` now builds `--infile` arguments and execs
  `drydock run builder`.

- 2026-10-13: **`prompt_warn_tokens` and `prompt_error_tokens` configuration keys.** Their values
  are per-model `prompt_target_tokens` and `prompt_warning_tokens` in `model_config.jsonl`.
- 2026-10-13: **`drydock build --escalate-model` and the `drydock_build_escalate_model`
  configuration key (`DRYDOCK_BUILD_ESCALATE_MODEL`).** Every repair pass now runs on the step's
  model, and the build call line no longer carries `escalated=yes`.

### Changed

- 2026-09-19: Table ownership has one rule: only a Feature owns an access pattern, and a pattern no
  single Feature owns names `DATABASE.md` as its `| Owner |`. A Screen renders data through a
  Feature's service and may no longer be named an owner. A `DATABASE.md`-owned pattern is shared —
  any Blueprint may cite it, none is required to, and the declaration cites nothing itself. This is
  the shape an activity log takes: in Marina_Luna six Features append to `activity_events` and two
  Screens read it, so every candidate owner was a lie and a repair pass invented a Blueprint file
  name for the gap. `drydock plan` now rewrites an `| Owner |` that names no Feature in the plan to
  `DATABASE.md` deterministically, with a warning and no LLM pass, and `drydock plan verify` reads
  the same rule. `prompts/BLUEPRINTS_CONTRACT.md` and the `DATABASE.md` template state it.

### Added

- 2026-09-19: `drydock build` now generates the Target's persistence package at the DATABASE step.
  `write_persistence_package` copies the shipped engines into `persistence/` and emits
  `persistence/schema.py` from `DATABASE.md`: the declared tables, the declared operations, and a
  frozen dataclass per read output. The generated module contains no SQL — statements are built by
  the driver for the engine in use — and its field annotations are emitted as declared and never
  evaluated, so a declared type the module cannot import is preserved rather than dropped. The
  declaration is now the source of the persistence layer rather than a description checked against
  one a build agent rewrote from prose each build. `schema.sql` is written beside the package.
- 2026-09-19: Drydock now ships the persistence layer itself. `Rigging/database/` holds `db.py`,
  `sqlite.py`, and `postgres.py` — Python source copied into a build unchanged, not guidance a
  build agent reinterprets. It is hardened and tested once in Drydock's own suite, so every Target
  inherits a persistence layer that has already passed rather than one re-derived from 126 lines of
  prose on each build. The caller surface is one attribute per declared table and one method per
  declared access pattern: `db.tickets.get(id=7)`. Values are bound, never formatted into SQL, and
  identifiers come only from the generated schema, which Drydock validated before emitting. Both
  engines are copied into every build and selected at runtime from the DSN, because the same build
  runs SQLite in test and PostgreSQL in production. A verb a table does not declare raises
  `UnknownOperation` naming what it does grant, rather than reaching the database. `drydock.paths`
  resolves the directory through `get_database_dir()`.
- 2026-09-19: `drydock build` now renders `DATABASE.md` into `schema.sql` beside the build when the
  DATABASE story closes, so a fresh environment is created from the declaration rather than from
  whatever the last build happened to execute. Indexes are derived, not decided: a foreign key is
  indexed by its child column and a `read` access pattern's `Input:` fields are the predicate it
  filters on, while `read-write` is excluded because its inputs are part predicate and part payload
  and the declaration does not say which. Derivation keeps the schema reproducible — an index
  invented at build time and recorded only in a decision log is dropped by the next render with
  nothing detecting the loss. The derived set is reported as one `DECISIONS.json` record rather than
  one per index, because it is one step of one build.

### Changed

- 2026-09-19: `drydock plan` console progress names the stage of each LLM call —
  `Calling CODEX/<model> (plan · topology)...`, then `plan · blueprint batch <n>`,
  `plan · conflict challenge`, `plan · topology repair`, `plan · declaration repair`, or
  `plan · artifact repair`. `llm.run_prompt` renders its `sub_command` into the Calling and
  Completed lines; the recorded `command_name` stays `plan`, so evidence and usage classification
  are unchanged.

- 2026-09-19: `drydock rigging compact --all` now runs without a `<Target>`. Rigging is Drydock's
  own shipped tree and has no Target, so refreshing its stale compacts no longer requires naming an
  unrelated Blueprint whose scope is then also compacted. `--all` alone refreshes only Rigging;
  `--all` with a `<Target>` keeps the previous behavior and adds that Blueprint's scope. Invoking
  the command with neither a `<Target>` nor `--all`, `--include-file`, or `--include-dir` remains a
  usage error and now names `--all` among the scopes that satisfy it.

- 2026-09-19: Relational persistence no longer requires an ORM or migration-framework selection.
  `sqlalchemy.md` and `alembic.md` are no longer mandatory for a Python Target with a `DATABASE.md`,
  because Build generates the persistence package from the declaration instead of asking an agent to
  implement one from prose. The stack gate is now keyed on the Target's language rather than on
  Python: a Target declaring a `DATABASE.md` in a language Drydock ships no adapter for is refused
  by `drydock plan`, `technology_stack.approve`, and QuarterDeck, naming the language. The previous
  check returned nothing at all for such a Target, so a Go Target with a database was never gated
  and reached a build with no persistence layer to write. `technology_stack.required_rigging` and
  `missing_required_rigging` are replaced by `declared_language` and `unsupported_persistence`.
- 2026-09-19: `Rigging/stack/persistence.md`, `sqlite.md`, and `postgres.md` are rewritten for the
  generated layer. `persistence.md` no longer carries a hand-rolled `Database`/table-class example
  to copy — it states the generated package's call surface and forbids writing a repository,
  session factory, connection helper, or migration by hand. `sqlite.md` and `postgres.md` are now
  store references that dispatch on language and state what each engine enforces: SQLite ignores
  `VARCHAR(n)` length and column types, so a green SQLite test is not evidence about either, and
  PostgreSQL is the authority on both. `## Persistence Interfaces` is removed from
  `Rigging/spec_template/DATABASE.md` and `prompts/BLUEPRINTS_CONTRACT.md` — it named per-feature
  repository modules that no longer exist. The stale `*_compact.md` siblings of the three rewritten
  files are deleted: stack compaction substitutes a compact sibling without a freshness check, so a
  stale one would have injected the superseded guidance into every build after its first use.
- 2026-09-19: `DATABASE.md` table declarations now carry the constraints a real schema needs, and
  Drydock renders executable DDL from them. A type cell is
  `<TYPE> [PK] [NOT NULL] [UNIQUE] [DEFAULT <literal>] [REFERENCES <table>(<column>)]`, where
  `<TYPE>` is `INTEGER`, `TEXT`, `REAL`, `NUMERIC`, or `VARCHAR(<n>)`; `BLOB` is no longer
  declarable. `DEFAULT` takes a closed literal set — a single-quoted string, a number, `NULL`,
  `CURRENT_TIMESTAMP`, `CURRENT_DATE`, or `CURRENT_TIME` — because the rendered DDL is executed
  against a live connection, so an open cell is a DDL injection path rather than merely a malformed
  declaration. A constraint spanning several columns is declared as a `- UNIQUE (a, b)` or
  `- INDEX (a, b)` bullet under the table's field table. Foreign keys are resolved against the same
  file: a key naming an undeclared table or column fails the plan, and `CREATE TABLE` statements are
  emitted in dependency order so the schema is portable rather than accidentally SQLite-shaped —
  SQLite tolerates any order, PostgreSQL does not. A key cycle is named instead of rendered.
  `VARCHAR(<n>)` is emitted verbatim to both engines: PostgreSQL enforces the length and SQLite
  parses the identical declaration and ignores it, so no engine-specific stripping exists.
- 2026-09-19: An access pattern in `DATABASE.md` now declares exactly one repository operation, and
  its verb is one of `get`, `list`, `create`, `update`, or `delete`. The cell previously accepted a
  comma-separated list, but a pattern carries exactly one `Input:` and one `Output:` table, so
  `settings.get, settings.set` described two operations with one pair of DTOs and left which fields
  belonged to which undeclared. The closed verb set exists because the generated persistence layer
  builds each statement rather than carrying SQL text. Both rules are stated in
  `prompts/BLUEPRINTS_CONTRACT.md` (V19), `Rigging/spec_template/DATABASE.md`, and
  `prompts/rigging_compact_database.md`, which now preserves column constraints verbatim so
  compaction cannot drop a constraint the built database would then not have.
- 2026-09-18: `drydock plan` now reads persistence ownership from `DATABASE.md` rather than from a
  story's `stack:`. An access pattern's `| Owner |` row carries the owning Blueprint's file name,
  and that decides who must cite: a Blueprint named as an Owner states the operations it owns, a
  Blueprint named nowhere declares `- None`. A stack selection says which technology a story is
  built with, not whether it reaches a repository — every Python story selects `sqlalchemy.md` and
  `alembic.md`, so the previous gate demanded a citation from the application shell that only runs
  the startup migration, while a Go or C++ Target was never gated at all. An `Owner` naming
  something that is not a Blueprint in the plan is now reported once against `DATABASE.md` as
  `database-owner-unknown` instead of resurfacing as a wrong-owner conflict in every Blueprint that
  cites it, and a citation conflict is reported against both the Blueprint and `DATABASE.md` so the
  repair loop can correct whichever side is wrong. A plan run had spent four of five repair passes
  re-emitting one Blueprint that could not be fixed from its own contents, leaving twelve further
  defects unattempted. `Owner` semantics are stated in `prompts/BLUEPRINTS_CONTRACT.md` and
  `Rigging/spec_template/DATABASE.md`.
- 2026-09-18: The `## Database Interface` entry grammar is now stated in
  `prompts/BLUEPRINTS_CONTRACT.md` and `Rigging/spec_template/DATABASE.md`, and a Blueprint that
  reaches no repository declares `- None — <why>.` The grammar `parse_database_interface` enforces
  — one bullet per line carrying an access-pattern id, access level, `supplies:`, and `returns:` —
  appeared in no prompt the model reads, so a plan run emitted the prose the contract asked for and
  21 Blueprints failed as malformed citations; the repair loop, which is handed the defect message
  and nothing else, returned the same prose for five passes. A Screen that delegated persistence to
  a Feature had no declared way to say so and failed for writing it in prose. Every bullet under
  the heading is now checked rather than only those that happen to match, so prose beside one
  well-formed citation no longer passes, and declaring `None` alongside a citation is a defect. The
  parse failure quotes the offending line and the accepted form.
- 2026-09-17: `drydock plan` now decides the persistence boundary rather than asking about it. The
  schema, the operation surface, and each Blueprint's citations either agree or they do not, and
  nothing about a disagreement needs a Commander, so four checks run at plan time: a Blueprint
  whose story declares persistence in `stack:` cites the operations it uses, a citation never
  widens what its pattern grants, every table in `## Schema` is reached by some access pattern, and
  every operation names a table the schema declares. `Repository operation` is now a checked
  `<table>.<verb>` form — it is the only place the declaration says which table a pattern reaches,
  so table coverage is read from its prefix and free text there fails the plan. A live plan
  declared four tables, reached three, and nothing looked at the fourth. Defects drive the existing
  artifact repair loop, five Blueprints per pass with a budget that reaches every chunk, and unlike
  an acceptance criterion they are not forgiven when that budget is spent: the run fails and writes
  nothing rather than hand Build a storage contract known to be wrong. This replaces the material
  and blocking decisions the previous entry describes, which reported the defect instead of
  repairing it and left 17 Blueprints of a live plan citing no operation at all.
  `Rigging/stack/persistence.md` binds the other end at build: a repository's public methods are
  exactly the declared operations, none added and none missing.
- 2026-09-17: `## Database Interface` is now required, not optional, for every Blueprint whose
  story declares persistence in `stack:`. The machinery to check one has always existed —
  `validate_database_interfaces` rejects an unknown operation, a wrong owner, access the pattern
  does not grant, a field the DTO does not carry, and a required field left out — but nothing
  called it outside `drydock refit`, so in practice no Blueprint carried the section and the
  persistence boundary was prose. `drydock plan` now parses every citation and validates it against
  the declaration, and reports a Blueprint that reaches the database while citing nothing. A live
  plan had 22 Blueprints in exactly that state. A citation that disagrees with the declaration
  blocks that Blueprint's story, because Build would implement the disagreement; one that is merely
  absent is recorded as a material decision, because the story builds correctly and only its
  storage access goes unchecked. Access gains a third declared level, `read-write`,
  because a repository surface is often genuinely both and forcing it apart invents a split the
  declaration never intended; a citation may claim less access than the pattern grants but never
  more.
- 2026-09-17: `drydock plan` now grades acceptance criteria for strength, not only for whether they
  can execute. A criterion whose accepted-status set admits `404` beside any other status is true
  of an application with no routes at all, and one admitting both a 2xx and a 5xx holds whatever
  the implementation does; a live plan had 35 such criteria, 21% of its gates, reporting acceptance
  no build had earned. Both shapes are now reported as a warning and a material decision against
  the owning Blueprint. Specifying a stub stays legitimate — a stub that answers `200` is a real
  contract and a real test — and `404` asserted alone remains a deliberate negative probe.
- 2026-09-17: `DATABASE.md` is now a cumulative Blueprint rather than a write-once one. `drydock
  plan` seeds it before the first Blueprint batch from `Rigging/spec_template/DATABASE.md` plus
  every table the imported source specification already declared, and keeps it open for the whole
  planning run. A batch emits only additions — new `` ## `table_name` `` sections, new field rows
  on a table already declared, and new `## Access Patterns` entries — and Drydock appends them.
  Nothing already declared can be retyped, reordered, or removed, so a Feature authored in a late
  batch can add the storage it needs without a model restating, and paraphrasing away, the
  declaration it was handed. The Stage 2 ledger lists `DATABASE.md` as `Open` instead of listing it
  among the accepted artifacts a batch must not re-emit. The template marks its illustrative blocks
  with `<!-- drydock:example -->`, which seeding strips, and declares its schema in the top-level
  `` ## `table_name` `` form the schema reader has always required.

### Fixed

- 2026-09-19: Persistence repair no longer spends the plan's repair budget on sections Drydock
  derives itself. `_normalize_database_interfaces` used to bail on every Blueprint as soon as one
  access pattern named an Owner that is not a Blueprint in the plan; a live Marina_Luna run sent
  four `## Database Interface` sections to the model that `DATABASE.md` defines exactly, and
  failed. Each owner's section is now written from the declaration regardless, since it is a
  function of the patterns naming that owner. Only `- None` is withheld while an unknown owner
  exists, because the unknown name may be that Blueprint's own, misspelled.
- 2026-09-19: A plan artifact repair pass now carries every defect its files have, not only the
  defects of one kind. One `DATABASE.md` with three defects consumed three passes, each fixing
  what it was shown and failing on the next.
- 2026-09-19: A repair pass that re-emits `DATABASE.md` is given the Blueprint file names in the
  plan — the only legal `| Owner |` values. A pass asked to split an access pattern invented
  `FEATURE-ACTIVITY-EVENTS.md`, an owner no Blueprint answers to and no later pass could resolve.
- 2026-09-19: The `ERRORS.md` record for a failed plan validation carries every defect instead of
  the first 800 characters. The truncation hid four of five defects from the operator repairing
  the plan.
- 2026-09-19: `drydock plan` now records a failed plan-verify gate in `ERRORS.md` (phase
  `plan verify`, the rendered unbuildable criteria, recovery `drydock plan repair <Target>`).
  The gate previously raised with no error record, so the only evidence was console output and
  `helpers/plan_fix.sh` exited with nothing to fix from. `plan_fix.sh` also falls back to the
  newest plan log when `ERRORS.md` is absent.
- 2026-09-19: Plan normalization now adds an import a criterion omits when every sibling criterion
  in the same Blueprint binds that name with the same import statement (`create_app()` read in one
  AC, `from app import create_app` in its neighbours). Criteria execute as isolated scripts, so the
  omission made the criterion unrunnable and failed the plan after the repair budget was spent.
  Ambiguous or unbound names are left for plan verify to report.
- 2026-09-19: `drydock plan` no longer reports success over a plan Build cannot execute. The plan
  ends on the `drydock plan verify` check; when a criterion cannot run or `DATABASE.md` cannot be
  read, the Blueprint and Manifest are still written for repair, but `MANIFEST.md` is left
  `state: draft`, `build_sub_state` is `unbuildable`, `PLAN CREATED` is recorded as failed, and the
  command exits `1` with the defect list. Neither `--override` nor an unattended run waives it.
  Previously these defects were demoted to `DECISIONS.json` entries (downgraded to `material` when
  unattended) and the command stamped `approved`.
- 2026-09-19: An unreadable `DATABASE.md` access-pattern surface now raises `DatabaseDefect` into
  the artifact repair loop, and every incomplete pattern is reported in one pass. It was recorded
  as a decision, and because the table-coverage and citation checks skip a contract that does not
  parse, an unreadable declaration silenced every persistence gate. `| Owner |` values naming no
  Blueprint are reported even when the contract does not parse. Persistence checks also run in the
  repair-exhausted fallback pass, which previously skipped them.
- 2026-09-19: Malformed acceptance containers are raised into the artifact repair loop instead of
  being recorded as blocking decisions. The fused-boundary normalizer now repairs the two shapes
  it missed: an `Intent:` line containing an apostrophe (the cut check tokenized the prose), and a
  chain closed by an id-less `=== END AC`.
- 2026-09-19: `drydock plan verify` reports `DATABASE.md` contract, unknown-owner, and table
  coverage defects when the declaration declares tables, and names `drydock plan <Target>` as
  their repair. `drydock plan repair` leaves those defects outstanding instead of sending
  `DATABASE.md` to the criterion prompt, records `PLAN REPAIRED` as passed only when the
  post-repair verification is clean, and sets the Manifest `approved` or `draft` to match.
- 2026-09-19: `drydock build` refuses to start when `drydock plan verify` fails — a criterion that
  cannot run, or a `DATABASE.md` that declares tables and cannot be read — and stops when the
  DATABASE step cannot generate the persistence package instead of printing `persistence: not
  generated` and continuing. Such criteria previously settled UNVERIFIED and let their story close.
- 2026-09-19: `DATABASE.md` type cells accept column modifiers wrapped in the square brackets of the
  documented form (`TEXT NOT NULL [UNIQUE]`, `[DEFAULT 0]`, `[REFERENCES t(c)]`); the brackets are
  removed before validation instead of failing `drydock plan` with an unknown column modifier after
  repair passes return the same cell. The form text in `BLUEPRINTS_CONTRACT.md` and the parse error
  now state that brackets mark optional entries and are not written.
- 2026-09-19: `drydock plan` now writes an invalid or missing `## Database Interface` section itself
  from `DATABASE.md` instead of sending it to the LLM repair loop. A Blueprint named as an access
  pattern's `Owner` cites every pattern it owns at the declared access with the full Input and Output
  field lists; any other Blueprint declares `- None`. A valid section, including a narrowed
  citation, is left unchanged, and each rewrite is reported as a plan warning. Previously a live run
  lost 41 accepted Blueprints when three repair passes, which had no DTO field names to work from,
  never produced a well-formed citation.
- 2026-09-17: A `DATABASE.md` defect no longer discards the plan that found it. A live run lost 39
  accepted Blueprints across 9 LLM calls, writing nothing, because one `Access` cell read
  `read-write` where the contract admits `read` or `write`. Two changes settle it. `drydock plan`
  now reads every unambiguous `Access` spelling — `read/write`, `append`, `create`, `select` and
  the rest — as the contract value it means, collapsing a combined operation to `write` because a
  citation Drydock widens can never under-declare access, and reporting each rewrite. A spelling
  Drydock cannot read without guessing is never reinterpreted. Anything the contract parser still
  rejects is raised as a blocking decision against the story implementing the declaration rather
  than as a fatal, which is the response already settled for an acceptance criterion that does not
  compile: Build still cannot proceed on a contract it cannot read, but the cost is one story
  instead of the whole run.
- 2026-09-17: `drydock plan` now validates the `DATABASE.md` operation surface, not only its
  schema. Build reads `## Access Patterns` through `database_operation_fingerprints`, so a
  declaration it cannot parse used to stop the build only after a block had already been spent — a
  live run failed on `DATABASE.md: ## Access Patterns has no named operation` with block 1 already
  accepted at 5/5. The plan integrity check parses the same contract and refuses the plan for free.
  `Rigging/spec_template/DATABASE.md` and the Blueprints contract now state the required shape:
  one `### FEATURE-<DOMAIN>-<NNN> — <Operation>` section per operation, never a single table of
  operation rows. The check is reported as a blocking decision, not a fatal, so the plan survives
  it.
- 2026-09-17: `drydock plan` now repairs a *chain* of fused acceptance boundaries, not only a
  single fusion. When the plan model closes one criterion with the next criterion's id and never
  opens that one, the same slip can repeat down a file — a live run produced
  `workflow-columns` → `workflow-production-terminal` → `workflow-catalog-boundary`, where every
  wrong id appeared exactly once as a closer and the previous rule declined the whole chain,
  shipping a Blueprint that acceptance parsing rejected before any test ran. Each link is now
  carried forward as the next pending opener, and the repaired text is accepted only when its
  markers alternate strictly; a speculative repair that would leave any block unclosed, stray, or
  duplicated is discarded whole and the hard parse error stands.
- 2026-09-17: A `DATABASE.md` that declares no tables now fails the plan integrity check instead of
  passing silently. A project without persistence has no `DATABASE.md` at all; one that exists and
  declares nothing is an empty contract, and Build filled that vacuum by inventing a schema no
  Blueprint described — models created by `create_all()` alone, which never alters a table that
  already exists, so the first story needing a new column on an existing table deadlocked the build
  against a database file that predated it.

- 2026-09-16: `drydock config env` is a pure query again. Every command outside a small read-only
  set checkpoints the named Target's Git store, and that checkpoint prints `Target - committed
  project workspace git store` to stdout. For `config env`, whose output a caller passes straight
  to `eval`, the banner became a stray command: `drydock_runner.sh` died with
  `Target: command not found`, attributed by bash to an unrelated line, whenever a Target had
  uncommitted changes. `config` now joins `status` as read-only, so it neither creates nor commits
  a Target's Git store.

- 2026-09-16: A failed LLM run now names its cause. Commands reported only `LLM execution
  failed`, leaving the provider's explanation in an evidence file the operator had no reason to
  suspect existed; a retired model, an expired key, and a rate limit were indistinguishable. The
  gemini adapter now also reads the error payload from stderr, where the CLI writes it when a run
  fails before producing any response and stdout stays empty — the case that hid the withdrawal of
  `gemini-2.5-flash-lite` behind a bare exit code. `llm.failure_reason` and `llm.failure_detail`
  render the cause, preferring Drydock's own judgement, then the provider's structured error, then
  the first informative stderr line, with console notices and stack frames dropped. `drydock
  import --format compass`, `drydock analyze`, and plan repair report through it.

### Changed

- 2026-09-16: Import format detection no longer inspects another tool's layout. `--format auto`
  previously looked for a Spec Kit `.specify/` directory, which was unreachable — `auto` rejects
  directories before detection runs, and `.specify` is only ever a directory — and the usage error
  it raised named `speckit` as a remedy. Importing Spec Kit sources still works when `--format
  speckit` is named explicitly, so the capability is the operator's stated intent rather than
  something Drydock inferred.

- 2026-09-16: `drydock_runner.sh` accepts only `gemini-3.5-flash-lite` among Gemini models.
  `gemini-2.5-flash-lite` is withdrawn from new API projects and retires 2026-10-20, and
  `gemini-3.1-flash-lite` is unverified; both were offered with quoted prices that implied they
  had been tested.

- 2026-09-15: `drydock_runner.sh` takes an optional third argument naming an import script, so a
  Target goes from nothing to built in one command instead of stopping twice for a manual
  `drydock import`. The runner owns the import mechanism and defines `import_compass`,
  `import_spec`, `import_directory`, and `import_code`; the script is an ordinary bash script that
  sets `SOURCE_DIR` and calls them. It is sourced from its own directory, so both `SOURCE_DIR` and
  the paths given to the helpers may be relative to the script, and it can sit beside the project
  it describes. The runner sources it only when the Target has no imported sources, so a rerun or
  resume never re-imports; a missing script, an unset `SOURCE_DIR`, or a script that imports
  nothing each fail with a naming diagnostic. Each helper prints the exact `drydock import`
  command before running it. `Import_Marina.sh` is the worked example and the template to copy.

- 2026-09-15: The two runner scripts move to the repository root as `drydock_runner.sh` and
  `drydock_build_loop.sh` (previously `helpers/drydock_runner.sh` and `helpers/build_loop.sh`).
  `drydock_runner.sh` now accepts only an enumerated list of models rather than inferring a
  provider from any name that looked plausible, and rejects anything else by printing the list
  with each model's cost, so a metered Gemini run is always a deliberate choice. It no longer
  passes `--llm-provider`, since the model selects the provider.

- 2026-09-15: `--llm-provider` is now optional. A recognized model name states which provider
  serves it, so `--model gemini-3.5-flash` runs on gemini, `--model gpt-5.6-luna` on codex, and
  `--model claude-opus-5` on claude, with no second flag. An inferred provider overrides the
  configured `llm_provider`, which remains the fallback for a model name Drydock does not
  recognize. An explicit `--llm-provider` still wins and is still checked against the model, so a
  contradiction such as `--llm-provider claude --model gemini-3.5-flash` is reported rather than
  silently resolved.

- 2026-09-15: The model must now be specified. `drydock_model` has no built-in default, and an
  unset model fails with a configuration error naming both remedies instead of falling back to
  `sonnet`. The fallback became unsafe once the model selects the provider: a workspace
  configured for one vendor would have quietly executed on another whenever the model went
  unstated.

### Added

- 2026-09-15: `gemini` joins `claude` and `codex` as a selectable LLM provider, available through
  `--llm-provider gemini`, `LLM_PROVIDER`, and `drydock config set llm_provider gemini`. It is the
  first metered provider: it authenticates with `GEMINI_API_KEY` from the environment rather than a
  subscription, so a run bills per token. Drydock invokes the `gemini` CLI headlessly with
  `--approval-mode plan` for text-only commands and `--approval-mode yolo` for `drydock build`,
  mirroring the read-only/writable split already applied to the other providers, and isolates the
  subprocess under `~/.drydock/gemini-home` so no user setting, extension, MCP server, or
  `GEMINI.md` reaches an assembled prompt. Gemini reports one terminal JSON object instead of an
  event stream, and bills more than one model per call — a router model precedes the answering
  model — so execution evidence sums tokens across every model billed and reports the model that
  served the `main` role. Gemini exposes no reasoning-effort control, so `drydock_effort` does not
  apply to it, and it reports no per-call cost.

### Changed

- `drydock score llm` now renders cache writes as `—` when a provider does not report that token
  category. The score no longer represents unreported Codex cache writes as zero; recorded Claude
  cache-creation tokens remain separately included in Input and Total.

- `drydock plan` keeps Claude Blueprint continuation passes in one explicit Claude Code session
  and sends only the changing ledger after the initial planning context. This preserves provider
  cache reuse across batches while retaining the existing self-contained continuation path for
  other providers.

- 2026-09-15: LLM execution evidence now records `job.claude_session` as `start` or `resume` with
  its session ID, and the per-call `.llm.log` records the same session mode and ID. This makes
  Claude session reuse directly auditable without parsing provider CLI arguments.

- 2026-09-15: Claude session selection is now prompt-aware for Plan and Build. A logical sequence
  resumes only when the next prompt byte-extends its previous context (or deliberately sends only
  its delta); changed prompts and model changes start a new session. Build repair feedback is
  cumulative, so same-model repair passes resume the block session.

### Added

- 2026-09-14: `drydock score llm [<Target>]` reports successful LLM executions since the
  Target's latest successful `init`, grouped by lifecycle stage, subtype, and provider/model.
  It merges workspace and Target-local execution journals by execution ID. `--include-incomplete`
  retains incomplete runs in that lifecycle; `--all` reports all history and failures.

- 2026-09-14: `drydock plan <Target>` accepts `--lineage-model <model>` for its post-plan,
  non-blocking source-to-story attribution pass. Plan synthesis, Blueprint authoring, and repairs
  continue to use `--model`; lineage inherits that model unless explicitly overridden.

- 2026-09-12: Claude runs now set their own output limits. `max_output_tokens` (default 128000)
  is passed as `CLAUDE_CODE_MAX_OUTPUT_TOKENS`, which the Claude CLI caps at each model's
  maximum: Haiku rises from the CLI default of 32000 to 64000, and Sonnet and Opus reach 128000.
  `haiku_thinking_tokens` (default 16000) is passed as `MAX_THINKING_TOKENS` for Haiku only,
  so thinking can no longer consume the whole output limit; other models size thinking from
  `--effort` and never receive it. A text-only LLM command (analyze, plan, and the others that
  consume the response as artifacts) whose response stops on `max_tokens` now fails with exit 1
  and a `FATAL ERROR - LLM OUTPUT TRUNCATED` block. The block names the limit, the thinking
  tokens spent, and the artifact that was cut, and gives the setting to change: the Haiku
  thinking budget, or `--effort` for other models. Previously the CLI's automatic continuation
  was joined to the cut-off text, and a model that restarted the artifact produced a
  duplicated `SEA_TRIALS.md` that surfaced as a spurious Commander blocker. Tool-using runs
  (`drydock build`) record the truncation in `logs/llm.jsonl` but are not failed by it.

- 2026-09-10: `DATABASE.md` now has a parsed, feature-owned persistence contract. Its named
  `FEATURE-<DOMAIN>-<NNN>` access patterns declare owner, read/write access, repository call,
  typed DTO input/output fields, and compatibility. Feature and screen Blueprints may cite only
  those operations through `## Database Interface`; Drydock rejects cross-owner calls and
  undeclared supplied or returned fields.

- 2026-09-10: Relational schema work now has a Blueprint-owned migration ledger at
  `blueprint/migrations/MIGRATION-<AccessPatternId>.md`. Records hold Alembic revision metadata,
  `upgrade`/`downgrade` snippets, and `planned`/`built`/`applied` state. A successful
  `DATABASE.md` build advances planned records to `built`.

### Changed

- 2026-09-13: `drydock refit <Target>` now normalizes external or raw ticket files, direct
  Blueprint edits, and Feature Blueprint HTML comments into typed `drydock_*` change tickets.
  It preserves upstream front matter, records unmatched inputs in `BLOCKERS.md`, attaches direct
  tickets to rebuilt work, and commits Target artifacts even when reconciliation fails. Source
  ticket processing is idempotent after its Manifest work becomes `incorporated`; deprecated
  `--sources` and `--relineage` routes are removed.

- 2026-09-13: DATABASE refit impact now compares the current named Access Pattern contract with
  the public contract snapshot stored in `MANIFEST.md`. A recorded applied Git commit is used only
  once to bootstrap Targets that predate the snapshot. Private persistence, schema, and migration
  changes rebuild the database owner only; a changed `rebuild` Access Pattern resets only its
  citing Features and dependents. Each normalized database change records a separate ticket-scoped
  migration ledger entry.

- 2026-09-12: `drydock build <Target>` now exits before any build runner executes when an
  applied Blueprint changed or disappeared. The error lists every stale applied-spec record and
  directs the operator to `drydock refit <Target>`; `--reset` cannot bypass reconciliation.

- 2026-09-12: `drydock refit <Target>` now treats direct Blueprint edits as the authoritative
  input for incremental rebuilding. It reconciles changed `ARCHITECTURE.md`, `DATABASE.md`, and
  `UI-GENERAL.md` files without requiring `blueprint/changes/TICKET-*.md` files, resets their
  affected Manifest closure to `pending`, and removes stale applied-spec provenance. Change
  tickets remain an optional additive-work path. `DATABASE.md` retains operation-level
  invalidation: the owner rebuilds, while only consumers of changed `rebuild` operations reset;
  Refit later records the applied public contract snapshot used to identify direct operation
  changes without a change ticket or a pre-authored migration record.

- 2026-09-11: `drydock diagnose --apply` records each amendment it applies in `DECISIONS.json` as
  a `low`, `recommended` decision titled `Applied without review: <summary>`, naming the changed
  file, the reason, and the report. It replaces an earlier declined proposal of the same change
  and carries no Commander answer, so it never reaches a Plan or Build prompt. Amendments
  confirmed at the prompt are not recorded.

- 2026-09-10: `drydock build` progress output is `key=value` and step-structured. Each block
  prints one `BLOCK <id>  name="…"  calls_max=N` header with its `story=` and `gates=` lines, then
  one `[call N/M]  kind=initial|resume|repair(i/n)  llm=<provider>/<model>` step per LLM call
  (`escalated=yes` on an escalated final repair), with that call's `fixing=`, `result=  rc=
  execution=`, and `acceptance=P/T  failed=  skipped=  disputed=` lines indented beneath it.
  Failed criteria carry `(passed/total)` case tallies. The provider `Completed …` line is no
  longer printed during a build; `result=` replaces it. Repair-loop stops print
  `STOP  reason=kit-fault|stall`, and the per-block outcome line is
  `DONE|FAILED  story=|feature=<id>  state=<state>  execution=<id>  elapsed=<wall time>`, where
  `elapsed=` is the build unit's total wall time (`12.3s`, `4m12s`, `1h02m03s`).

- 2026-09-10: `drydock diagnose` terminal output is restructured for reading and approval. A
  `DRYDOCK DIAGNOSE · <Target>` masthead carries the verdict; each section (Root Cause, Details,
  Commander Feedback Requested, Repair Proposal, Not Offered, Missing Evidence, Report, Outcome) is
  titled by a rule and wrapped to the terminal (at most 100 columns) without splitting `code`
  spans. Details lists evidence first and groups `Not a defect:` bullets under `Not defects`. Each
  amendment prompt now shows the file, the `+N -M` size, the reason, and the unified diff itself
  (cut at 60 lines; the report keeps it whole) before `Apply? [y/N]`. The outcome block reports the
  applied files, the reset Manifest blocks, and the Target commit once, and `Next: <command>` is
  the final line. Colour is used only on a terminal that supports it (`NO_COLOR` honoured);
  captured output is plain. Ladder times in the terminal, `DIAGNOSE_<stamp>.md`, and
  `DIAGNOSE_<stamp>.html` are now local time rather than UTC. `target_git.commit_target` accepts
  `quiet=True` for callers that report the commit themselves.

- 2026-09-10: `drydock diagnose` repairs Blueprints. The report has four sections — Root Cause,
  Details (evidence plus `Not a defect:` wreckage), Commander Feedback Requested (next steps drawn
  from `BLOCKERS.md` and `DECISIONS.json`), and Repair Proposal — under prompt contract
  `diagnose_report` v2. Repairs are verified unified diffs against the Blueprints implemented by
  `blocked/questions` and `closed/failed` Manifest blocks (read in full, at most six), plus the
  Compass files and `MANIFEST.md`; imported sources, change tickets, and `*_compact.md`
  derivatives are rejected. An applied Blueprint repair deletes the Blueprint's stale
  `_compact.md`, resets its consuming blocks and their dependency closure to `pending` through
  `refit.reset_blueprint_consumers` (the reset `drydock refit` drift reconciliation now shares),
  and names `drydock build <Target>` as the next step. Applied repairs are committed to the Target
  repository as `Apply drydock diagnose repairs: <summaries>`. No change ticket is written. Amendment
  `File:` paths now keep directory prefixes such as `blueprint/`.

- 2026-09-10: `drydock diagnose` now prints its findings to the terminal, followed by the
  `DIAGNOSE_<stamp>.md` and `.html` paths; previously it printed only the paths. The duplicate
  copyright line after the masthead is removed.

- 2026-09-10: `drydock refit` now scopes an unapplied `rebuild` database migration to Manifest
  stories whose Blueprint `## Database Interface` cites the affected access pattern, then resets
  only their dependency closure. The DATABASE owner story is rebuilt without using it as a broad
  cascade seed; `data` and `unchanged` records leave consumers intact until a consumer-sensitivity
  policy is introduced.

### Fixed

- 2026-09-15: `drydock diagnose --apply` receives complete decision evidence and current
  execution state, repairs acceptance defects under delegated Commander authority, prints
  repair diffs, and reports unresolved stalls as failure. Acceptance repairs preserve check
  identities and must parse and compile before application; corrected malformed-check gates
  retire before affected consumers rebuild. Routine repairs remain report annotations;
  consequential decisions enter non-blocking QuarterDeck review. Pending review no longer
  gates stories. `helpers/build_loop.sh` and `helpers/drydock_runner.sh` recover unfinished
  Targets stalled before build and stop when diagnosis fails to restore progress.

- 2026-09-14: `drydock score llm` now reports provider cache-write input tokens separately and
  includes them in `Input` and `Total`. Claude's `cache_creation_input_tokens` previously appeared
  in durable execution evidence but was omitted from the score, materially understating
  lifecycle usage for cache-miss-heavy runs.

- 2026-09-13: `drydock plan` now retains a topology repair whose otherwise valid delimited
  artifact is surrounded by model narration, then verifies its exact artifact set and complete
  declaration before continuing. Previously the repair was discarded and Plan reported the
  original topology defect even when the model had corrected it. `plan_create` V38 also states
  that feature assembly stories implement one Stage 2 Blueprint and may not leave `implements:`
  empty.

- 2026-09-13: `DATABASE.md` no longer accepts model-authored programmatic assertions. Drydock
  now parses its Markdown SQLite table declarations, renders idempotent DDL, and verifies a fresh
  store creates every declared table and column and accepts a connection before Plan succeeds.
  This removes unattainable assertions that opened an unrelated temporary database without
  invoking the built application's migrations. Runtime package authorization now requires a
  Target environment or dependency manifest; only test-scoped packages may use Drydock's active
  interpreter as an execution fallback.

- 2026-09-13: `drydock plan` now enforces one file per `implements:` before Stage 2 starts. A
  story listing several files (`implements: SCREEN-X.md, FEATURE-Y.md`) was frozen as a single
  unauthorable filename, so every Stage 2 batch that reached it was rejected as `output changed
  frozen or deferred work` and the plan stalled. `verify_graph` now reports a
  `multi-specification` defect and counts each listed file toward `shared-specification`. The
  Stage 1 declaration repair now covers every work-graph defect as well as coverage. For a
  one-specification defect, its prompt tells the model to split the story, where it had
  previously told the model to preserve the assignment. A graph defect the repair does not
  correct fails the plan as `plan topology rejected` before any Stage 2 call. A rejected
  Stage 2 pass no longer leaves earlier artifacts from the same response in the accumulator,
  and the rejection now names the artifact and the reason (frozen, already accepted,
  undeclared, or deferred). `plan_create` V35 states that `implements:` is never a list.

- 2026-09-12: `drydock diagnose` now reads the Target's recorded `ERRORS.md` before calling an
  LLM. A deterministic failure classification — including provider rate, session, or usage limits;
  provider, context/token, execution-environment, and execution-security failures — prints its
  recorded required action and exits 1 without a second model call. The Marina Haiku build helper
  now aborts on its first failed `drydock build`; it no longer runs `diagnose --apply`, suppresses
  failure with `true`, or retries an unavailable provider.

- 2026-09-10: `drydock build` and `drydock plan` now treat test-scoped Python acceptance
  dependencies as automatically authorized hermetic test-environment inputs, not Commander
  authorization decisions.
  Existing per-check test-package decisions are archived during gate synchronization, releasing
  their affected stories without QuarterDeck action. Missing project-local submodules discovered
  during acceptance now remain implementation failures instead of being misclassified as external
  package authorization requests. Runtime packages and external executables remain governed.

- 2026-09-10: Codex repository-security rejections now classify as a non-retryable local
  execution-policy failure. They do not trigger an advisory diagnosis call, and `drydock status
  <Target> --ready` stops an automatic build loop until the local condition is corrected.

- 2026-09-10: `drydock build` now passes Codex's non-repository override when launching the
  isolated build agent. Builds invoked for a newly created target directory no longer fail before
  the agent starts because that directory has not yet been initialized as a Git repository.

- 2026-08-30: Drydock's recorded project state is now resolved at milestone granularity — INIT,
  ANALYZE, PLAN, BUILD, SCORE — with supersession named explicitly in
  `project_status.SUPERSEDES` rather than inferred from ladder position. A passing
  `PLAN REPAIRED` retires a failed `PLAN CREATED` and a passing `BUILT` retires a failed
  `BUILDING`, so `drydock status`, `drydock score report`, and `drydock diagnose` no longer
  report a failure the project already recovered from. A passing `SCORE BUILD` deliberately does
  not retire a failed `SCORE AC`: the build report is observational and reports on different
  work than the acceptance gate. A passing `SCORE RELEASE` remains the terminal gate over the
  scores beneath it, and an earlier milestone failure that was never answered still stands as the
  lifecycle frontier however far the project later advanced.

- 2026-08-23: A `drydock uat` proof-kit run whose recorded `PROJECT_STATUS.jsonl` has a passing
  `SCORE RELEASE` now displays terminal `PROJECT COMPLETE`, rather than the lower-level `BUILT`
  metadata state. The top badge reads `DRYDOCK UAT` and that project status; Project also links
  the final `SHA256SUMS` integrity verification.
- 2026-08-23: `drydock uat` proof-kit run reports now identify the project from recorded
  `METADATA.md` (`Project`, `Short description`, `Status`) instead of presenting the UAT run's
  pass/fail result as project state. They no longer display `Verdict` or `Ran`; Decisions is a
  dedicated report tab and the primary run artifacts are part of the Project section.
- 2026-08-23: The Error tab in a `drydock uat` proof kit now contains only nonempty captured
  `stderr` logs, each headed by its filename. Captured `stdout` remains available only from its
  lifecycle row in Steps.
- 2026-08-23: `drydock score build <Target>` is now an observational report. Missing evidence
  and unverified Build Blocks remain visible in its output but no longer produce a failing exit
  code, alter `PROJECT_STATUS.jsonl`, or rewrite `SCORECARD.md`; `score ac` and `score release`
  remain the acceptance and release gates.
- 2026-08-23: `drydock uat` now ends each project with a terminal verdict banner, its
  `METADATA.md` description, and absolute paths to the UAT report, proof kit, checksums, evidence,
  and generated Target. The terminal summary no longer prints advisory score exit codes or UAT-kit
  checkpoint chatter.
- 2026-08-23: `drydock build status` now treats `closed/implemented` as completed rather than
  suggesting a nonexistent verification step. A completed one-story computed Build Block renders
  as one compact line; the aggregate still distinguishes built-but-unverified work from governed
  verification.
- 2026-08-23: `drydock plan verify` now requires a declared non-candidate probe for every
  statically recoverable staged-runner selector and rejects a missing, malformed, failed, or
  zero-case selection before build. `drydock plan repair` retains a selector repair only after
  the same probe succeeds with a nonzero count. A dynamic selector remains advisory-only at plan
  time and is contained by the build-time zero-case `UNVERIFIED` backstop.
- 2026-08-23: A completed acceptance criterion that reports an authoritative zero-case tally now
  settles `UNVERIFIED` rather than either a false pass or an unrecoverable product failure. Build
  repair and regression sweeps exclude it, and a resumed story supported only by such criteria
  closes `implemented`, never `verified`. This prevents an empty corpus selection from consuming
  repair calls or stopping the build.
- 2026-08-22: `BLUEPRINTS_CONTRACT.md`'s oracle rule now covers reconstructed non-string
  expectations (a rebuilt path compared against one the code under test computes itself), not
  only re-typed string literals, with a worked example. Planning previously authored
  `run_conformance.CORPUS == sources / "jq.test"` against a harness whose `CORPUS` is an
  absolute, resolved path — a criterion no implementation could satisfy.
- 2026-08-22: `acceptance.retyped_expectations` (and the `plan verify` / `validate_specification`
  warnings and build-time `binding`/`DISPUTED` classification that read it) now also flags a path
  rebuilt with the pathlib join operator and compared for equality against an attribute read off
  another object — the shape above. Previously only re-typed string literals were detected, so
  this criterion settled `FAIL` and burned the block's whole repair budget instead of `DISPUTED`.
- 2026-08-22: A fused acceptance boundary — two criteria emitted under one `=== AC <id> ===`
  opener, closed with the *second* criterion's id and never given its own opener — is now
  repaired deterministically at plan-generation time and, for a Blueprint already on disk, by
  `drydock plan repair`'s container path with no model call. Previously this shape reached the
  LLM-based container repair on every attempt and failed identically every time: the model
  reliably renamed the wrong closer but never inserted the missing opener, so no number of
  retries fixed it.
- 2026-08-22: Plan generation's validation-defect artifact-repair pass now groups repair calls by
  which validator found the defect, then chunks each group at the same batch size Stage 2
  authoring already uses (5 files), instead of citing every file a systemic defect touches in one
  unbounded call. A single systemic mistake spanning dozens of files previously produced one
  oversized repair prompt carrying every file's full original body; under that load the model
  silently dropped content (`## Guardrails`, the header table) it was explicitly told to preserve.
- 2026-08-22: `drydock uat resume <Project> --stage verify` (and `--from verify`) is accepted; the
  argument's choice list had omitted the `verify` stage. Passing a step number to `--stage`/`--from`
  now names `--from-step <n>` instead of a bare "invalid choice" error.

### Changed

- 2026-08-22: `drydock uat --help` drops its long-form mechanism prose (kit layout, workspace
  isolation, streaming, scoring); it keeps only the command-form usage lines and per-flag help.

### Added

- 2026-09-09: `docs/posts/devlog_2026-09-09.md` publishes the first Drydock development log,
  covering the SQLAlchemy/Alembic persistence boundary and `drydock diagnose`, with the reasoning
  behind each. It follows `Rigging/BRANDING_POSTS.md` and renders through
  `drydock publish --theme slate` to `docs/posts/devlog_2026-09-09.html`.

- 2026-09-09: Python Targets with relational `DATABASE.md` now require `sqlalchemy.md` and
  `alembic.md` in `TECHNOLOGY_STACK.md`. QuarterDeck rejects stack approval until both Rigging
  selections are present, and `drydock plan` blocks before authoring when either is absent.
  SQLAlchemy repository/DTO boundaries and Alembic revision discipline are distributed as Rigging;
  `drydock refit --sources` now classifies persistence changes as `unchanged`, `data`, or
  `rebuild` rather than treating every internal migration as a downstream rebuild.

- 2026-08-30: `drydock diagnose [<Target>] [--run <stamp>] [--apply] [--no-apply]` explains why a
  Target's latest run stopped and proposes durable corrections. It prints a stage ladder derived
  from `PROJECT_STATUS.jsonl` and a failure classification taken from the recorded stop before any
  model call, so the deterministic account costs nothing. It then makes exactly one LLM call and
  writes a diagnosis to `targets/<Target>/DIAGNOSE_<stamp>.md`: break
  point, reason, the failures that are wreckage rather than defects, open blockers and blocking
  decisions, cited evidence, and a table of local log paths with SHA-256 digests drawn from
  `logs/llm.jsonl` and `logs/history.jsonl`. The report is self-contained: a reader who never saw
  the run can repair the defect from it. Amendments are unified diffs against `COMPASS.md`,
  `PLAN_COMPASS.md`, `ANALYZE_COMPASS.md`, or `MANIFEST.md`, each verified to apply before the
  operator is asked, then confirmed one at a time; `--apply` applies all without prompting and
  `--no-apply` records them as `recommended` decisions in `DECISIONS.json`. A malformed model
  answer still writes the report, marked `MALFORMED`, with the raw text preserved. Every exit
  names the next command to run. The report is written in two surfaces beside each other:
  `DIAGNOSE_<stamp>.md` for pasting into a ticket or handing to another agent, and
  `DIAGNOSE_<stamp>.html` for reading, sharing `drydock score report`'s letterhead, verdict
  stamp, tab strip, and table styling while remaining a separate artifact. Both sit in the
  Target root beside `SCORECARD.md`.

- 2026-08-23: `helpers/diagnose-uat.sh <Target>` runs a bounded, read-only adversarial diagnosis
  of the latest failed archived UAT run, while `helpers/diagnose.sh <Target>` diagnoses the latest
  failed non-UAT command recorded for a Target. Both use subscription-authenticated Codex and
  Claude CLIs with explicit model and reasoning-effort overrides, persist independent analyses,
  review rounds, and a consensus report, and do not alter product or Blueprint evidence.
- 2026-08-22: `drydock uat status <Project>` now lists every recorded step of the run, in the
  same numbered form `drydock uat <Project> --steps` prints, so the operator can read the exact
  `--from-step <n>` argument off the status output without a separate command.
- 2026-08-22: `drydock uat <Project> --stage verify [--run <run-id>]` resumes an existing UAT
  workspace at the Plan Verify → Repair → Verify gate. It reuses the existing Blueprint and
  Manifest, skips Plan generation, and enters Build only after the gate passes.
- 2026-08-22: `drydock plan verify` now reads the executable contract of a staged Python
  acceptance runner when a literal `subprocess` command invokes it. An option whose parsed value
  is proven to reach `re.compile` rejects an invalid literal pattern before build; `drydock plan
  repair` receives that defect and retains a repair only after the same contract re-verifies.
  This prevents a malformed runner selector from consuming build-repair calls or being reported
  as a product acceptance failure.
- 2026-08-20: The main specification and Quick Start now state the complete Target lifecycle:
  initialize, import, analyze, QuarterDeck review, plan verification and repair, iterative build,
  completion check, and scoring. Their compact Bash examples identify the review points and state
  that this is the build order `drydock uat` executes, including its refit-and-rebuild path for
  declared source updates.
- 2026-08-20: `drydock score <Target>` summarizes the score family in one screen. It reports the
  workflow state the Target is in, then one row per score sub-verb — `spec`, `ac`, `build`,
  `release`, `report` — naming when each last ran, the exit code it returned, and the artifact
  it writes with that file's modification time; the acceptance row additionally tallies the
  recorded Soundings board. It closes by naming the scores that have not been run. The invocation
  reads only: it is not journaled to `logs/history.jsonl` and does not checkpoint the Target's
  Git store. Previously a bare `drydock score <Target>` was a usage error, and the receipt
  counted any such invocation as an `ac` exit code.

### Changed

- 2026-08-22: `drydock plan verify` classifies an unreadable Programmatic Acceptance section as
  a `bad-container` defect. `drydock plan repair` makes one constrained LLM attempt to repair
  that file's AC delimiters, retains the output only when the container parses and every
  non-delimiter line is byte-equivalent, and otherwise restores the original file.
- 2026-08-22: `drydock uat <Project>` now marks every child command as unattended. Analyze and
  Plan receive an explicit policy to resolve ambiguity from governed fixture inputs, persist the
  selected system choice, and emit no Commander questions, questionnaires, blockers, or open
  decision records. Model-emitted Analyze questions and blockers are discarded defensively; a
  malformed acceptance criterion becomes a material recommended repair decision instead of an
  open blocking question.
- 2026-08-21: `SCORE RELEASE` is now the terminal `PROJECT_STATUS.jsonl` state and the sole
  passing release condition. `drydock score report` no longer records the synthetic
  `FINALIZED` state. A passing release score supersedes earlier recoverable failures in the
  Target's lifecycle frontier, so `drydock score`, the receipt, and the Commander's Chair report
  the release rather than an obsolete `PLAN CREATED` failure. The receipt headline now states
  lifecycle progress — red before `BUILT`, amber from `BUILT` through scoring, green only for a
  passing release — and labels a clean `PLAN CREATED` state as `PLAN APPROVED`. Its duplicated
  Scores tab is replaced with Verification, and the Overview provides relative links to the
  delivered code and Target workspace.
- 2026-08-21: `drydock build --help` now prints one concise command description and one option
  list. It omits repeated command examples and configuration-setting commands while retaining
  each build option and its default.
- 2026-08-21: `drydock plan repair <Target>` now repairs advisory-only acceptance criteria when
  invoked directly. The repair prompt distinguishes criteria that cannot run from named
  measurement improvements; it still makes one surgical attempt per file and re-verifies before
  retaining a write.
- 2026-08-21: `drydock score ac <Target>` now prints `Running AC <n>/<total>: <id>` before each
  Programmatic Acceptance criterion begins. Long deterministic corpus slices therefore show
  bounded live progress while preserving the existing consolidated verdict report and
  `SOUNDINGS.md` output.

- 2026-08-21: `drydock status <Target> --check` now reports every executable Manifest block by
  its current state (`21 closed/implemented`, `2 pending`) instead of a `verified/total` fraction.
  The completion exit contract is unchanged: only `closed/verified` work yields `COMPLETE`.
- 2026-08-20: The `drydock score report` receipt Overview now renders the same score summary as
  `drydock score <Target>`: every score command's last run, result, and output artifact. Receipt
  assembly now resolves a command's Target from its operands rather than the legacy journal
  `target` field, which recorded a score sub-verb for some older score commands and omitted them
  from the receipt.
- 2026-08-20: The `drydock score report` Workflow table now renders all eleven legitimate
  lifecycle states. States not held in `PROJECT_STATUS.jsonl` appear as `NOT ESTABLISHED`, with
  no timestamp or command, rather than being omitted; the receipt therefore shows why an
  otherwise all-pass table remains incomplete and distinguishes an unrun gate from a failure.
- 2026-08-20: `PROJECT_STATUS.jsonl` voids a workflow state only when the artifact it was
  verified against has been re-authored. Previously any recording voided every state above it on
  the ladder, so re-running a passing verification silently deleted the passing states above it:
  a second `drydock score ac` removed `SCORE BUILD`, `SCORE RELEASE`, and `FINALIZED` without
  touching any evidence, and `drydock score` then reported three passing scores as `voided`.
  Voiding is now a property of the command. `ANALYZED`, `PLAN CREATED`, `PLAN REPAIRED`,
  `BUILDING`, and `BUILT` void everything above them, pass or fail, because the command ran and
  rewrote the tree. `INITIALIZED` and `IMPORTED` void nothing — creating a Target and reading
  sources into it invalidate no later verification. The acceptance and score states void nothing
  either: a verification that fails on rerun invalidates itself alone, and the states above it
  keep whatever standing they had. `drydock refit` voids every state above `PLAN REPAIRED` when
  it conforms a ticket or resets a drifted Blueprint, which it previously did not record at all.
- 2026-08-20: `drydock plan verify` now records a workflow state when it fails, and still records
  nothing when it passes. A clean verify says only that the plan already standing is sound, which
  is not a new fact about the project; a failed one is, so it fails the plan rung the Target holds
  — `PLAN REPAIRED` when the plan was repaired, otherwise `PLAN CREATED` — with the defect count
  as the detail. It voids nothing, having authored nothing. Previously a repair that exited 0 and
  still left criteria unrunnable left `PLAN CREATED` or `PLAN REPAIRED` standing as passed, so the
  state machine reported a sound plan an operator's workflow had already aborted on.
- 2026-08-20: States are no longer mutually exclusive, so the `PROJECT_STATUS.jsonl` summary row,
  `drydock score`, the `drydock score report` receipt, and the Commander's Chair lifecycle strip
  now name the *standing* state: the lowest failed rung when one exists, otherwise the furthest
  rung reached. A failed rung outranks the passing states recorded above it, because the workflow
  runs bottom-up and stops there. Optional rungs (`PLAN REPAIRED`, `BUILDING`) no longer have to
  be present for the rungs above them to count.
- 2026-08-20: The `drydock score report` receipt renders the plan of record instead of indexing
  it. The `PLAN` tab was a table of file names, byte counts, and `open` links to generated viewer
  pages; it is now one tab per artifact — `Manifest`, `Scorecard`, `Analysis`, `Metadata`,
  `Compass`, `Build Compass`, `Stack`, `Sea Trials`, `Soundings` — each showing the artifact
  itself, with the hashed `Workspace` inventory kept as the last tab. The Manifest and Scorecard
  are drawn by the QuarterDeck's own renderers, so a receipt shows the same block board and
  verdict board the Commander's Chair does, in the receipt's typography; the remaining documents
  are rendered Markdown. A tab appears only when the Target wrote that artifact.
- 2026-08-20: The receipt now carries the Target's `blueprint/`, including imported `sources/`.
  Every Manifest block names the specification it implements and the sources it was given as
  context, and a receipt that shows the plan without carrying what the plan cites makes a claim
  its reader cannot check. Build caches (`__pycache__`, `node_modules`, `.venv`) are excluded
  from every copied subtree, as dot entries already were. The delivered application is still
  named rather than copied.
- 2026-08-20: A Target repository checkpoint now recovers from a stale Git lock instead of
  failing permanently. When a git invocation against `targets/<Target>` reports `Unable to
  create '<path>.lock': File exists`, Drydock deletes that lock, prints `Target - cleared stale
  git lock <name>`, and retries the invocation once. A Target repository is written only by
  Drydock, one command at a time, so a lock left behind means an earlier command was killed
  before it could unlink one — a routine outcome on a Windows-mounted workspace that previously
  aborted every later command against that Target until the file was removed by hand. Each
  command that writes to a Target continues to produce exactly one checkpoint commit at the end
  of the invocation; the redundant mid-command commits in `drydock refit --sources` and Compass
  `drydock import` are removed, leaving only the import lineage stamp, which must commit early
  because a lineage record names the commit that introduced a source version.
- 2026-08-20: The `drydock score report` receipt is pared down to a page an operator can host
  and keep in version control. It no longer copies in the delivered application, the
  Blueprint, the provider wire transcripts (`*.raw.jsonl`), the assembled prompts
  (`*.prompt.md`), or any dot directory. Previously it carried all of them, and publishing a
  receipt for a Target whose build directory still held a receipt from the pre-`drydock_receipt`
  layout copied that receipt in as delivered code: one jq run produced a 278 MB directory, of
  which 139 MB was a stale nested receipt, 43 MB was wire transcripts, 19 MB was prompts that
  re-injected the specification and Blueprint once per block, and much of the rest was one
  generated HTML viewer per copied file. The same run now publishes at roughly 2 MB. The
  receipt carries the readable evidence — command transcripts, model output, the `.llm.log`,
  and the `history.jsonl` and `llm.jsonl` slices the page is rendered from — plus the Target's
  top-level artifacts with its `evidence/` and `QuarterDeck/` subtrees, and it links
  `QuarterDeck/commanders_chair.html` from the plan panel. The `OUTPUT` and `INPUT` tabs are
  gone, the delivered code is named by its build directory in the run facts rather than copied,
  and the LLM table drops its prompt and raw-transcript columns. Everything omitted stays where
  the run wrote it in the Target's own `logs/`; every file the page links is still carried and
  hashed in `SHA256SUMS`.
- 2026-08-20: `METADATA.md` is now the sole Target identity record. QuarterDeck persists
  `discovery-identity.json` answers for `display_name` and `short_description` to
  `METADATA.md`, then reloads the questionnaire from those persisted values; Analyze likewise
  refreshes an existing identity questionnaire from metadata. Identity questionnaires are no
  longer copied into `DECISIONS.json` or injected as planning decisions. Every Drydock or
  QuarterDeck metadata mutation uses one atomic replacement, increments `version` once per
  effective write, and records an ISO-8601 UTC `updated` timestamp.
- 2026-08-20: Workflow state is a state machine in `PROJECT_STATUS.jsonl`, replacing the
  append-only `PROJECT_STATUS.md` journal. A Target now holds one row per workflow state it
  currently stands in, in ladder order, followed by one summary row naming the state the
  project is in — readable with `tail -1`. Recording any state voids every state below it on
  the ladder, whether the attempt passed or failed: starting a build un-finalizes the project,
  re-running `drydock score ac` voids `SCORE BUILD`, `SCORE RELEASE`, and `FINALIZED`, and a
  failed `drydock build` voids the scores that ran before it. Previously every attempt was
  appended forever and the state was re-derived by ranking labels by ladder position, so a
  Target accumulated hundreds of records, re-running a mid-ladder command left stale downstream
  states standing, and a project whose newest evidence was a rescore still reported
  `FINALIZED`. `project_status.current_state` is the single reducer. The hand-rolled markdown
  parser is gone, taking with it the single-line escaping constraint on `detail`. Each row
  carries an `attempts` count so the receipt still reports repeated attempts without retaining
  a journal; the count resets when the state is voided. `PROJECT_STATUS.md` is not read and is
  not migrated: there is no format to convert from, because a journal of every attempt cannot
  be reduced to the one state a Target holds without inventing an ordering it never recorded.
- 2026-08-20: The Commander's Chair carries a lifecycle strip naming the state the project is
  in, its verdict, when it was recorded, and how many attempts it took, above the full
  eleven-state ladder with held states marked. It sits below the BIG ERRORS and RUNNING
  panels and is omitted for a Target that has recorded no state. The Chair previously showed
  only `get_build_state`'s four-way artifact projection (init, analyzed, planned, building),
  which cannot distinguish a built project from a scored or finalized one. That projection
  still drives which phase view renders; the strip reports the recorded machine beside it.
- 2026-08-20: The `drydock score report` receipt renders the state machine and nothing else.
  The workflow ladder is one row per row of `PROJECT_STATUS.jsonl`, and the header states the
  one state the project is in rather than re-deriving how far the run got. The receipt
  previously merged a second ladder inferred from `logs/history.jsonl` exit codes, graded it
  with its own reducer, and appended a `FINALIZED` row that existed only in the rendered page —
  so the document could claim a state the Target did not hold, and the header and ladder could
  disagree. `FINALIZED` is now recorded to the machine before the page renders, still earned
  only by a ladder that failed nothing and reached `SCORE BUILD`, and `drydock score report`
  prints the resulting state. An acceptance board on disk that contradicts a passing
  `LLM ACCEPTANCE CHECKS OK` corrects the machine — voiding the scores above it — instead of
  correcting the rendered row. `drydock score report`, `score build`, and `score release` are
  additionally journaled under the Target they name; they were recorded under `report`,
  `build`, and `release` as though those were Target names, which kept them out of their own
  Target's history and out of the receipt's command list.
- 2026-08-20: The repair ladder in `drydock score build` reports what each pass settled instead
  of whether it closed its block. Every pass that did not close was labelled `failed`, so a
  block that verified on repair 5 printed five failures above one success, and a pass overturned
  by a governed gate or the regression sweep printed `failed` beside `2/2 AC` — a contradiction
  on its face. A pass that is not the block's last now reads `incomplete`; the last pass carries
  the block's verdict, `built` or `failed`. Block evidence additionally records `reason:` on any
  pass that did not close, naming the gate, sweep, or acceptance failure that overturned it, and
  the ladder prints that reason beneath the row. Evidence written before this change parses
  unchanged and simply carries no reason.

- 2026-08-20: `drydock score report` stamps the lifecycle a Target recorded rather than the
  presence of one artifact. A finished project whose acceptance board was never written was
  stamped `UNPROVEN` — jq, with every Manifest story `closed/implemented` and 537 of 537
  conformance cases passing, read as not accepted. The receipt now leads with a workflow
  ladder: one row per lifecycle state actually attempted (`INITIALIZED`, `IMPORTED`,
  `ANALYZED`, `PLAN CREATED`, `PLAN REPAIRED`, `BUILDING`, `BUILT`,
  `LLM ACCEPTANCE CHECKS OK`, `SCORE BUILD`, `SCORE RELEASE`, `FINALIZED`), each with its
  result, the command that established it, and a local timestamp. A state never attempted is
  absent — it is no longer rendered as a failed claim. The stamp is red when any state's last
  attempt failed, amber `IN PROGRESS` when everything recorded passed but the project has not
  been built, scored, and published, and green `Accepted` only then. A usage error or deferred
  command (exit 2) establishes no state and is kept off the ladder entirely.

  Every lifecycle command now records its own outcome in `PROJECT_STATUS.md` in the Target
  directory, append-only, so reattempts stay visible and a command that knows more than its
  exit code — a build that exits 0 with stalled blocks — says so. Recording is a pure side
  effect: it never alters a command's exit code. Targets built before the file existed still
  get a ladder, derived from the command journal.

  The receipt itself moves out of the delivered application to
  `targets/<Target>/drydock_receipt/`, since it documents the delivery rather than forming
  part of it, and carries a frozen copy of the delivered code so the directory stays
  self-contained. It is sealed with `SHA256SUMS` like a UAT kit, and dot directories — `.git`
  above all — are no longer inventoried or hashed. Navigation is two tiers,
  `OVERVIEW | BUILD | PLAN | OUTPUT | INPUT` over per-panel strips, each strip scoped to its
  own tab group so sibling strips no longer blank one another. The commands table drops the
  model-log column, names the model each command drove, labels a rerun with which attempt it
  was while keeping the earlier attempts and their results, and states every time in the
  reader's local zone.

### Fixed

- 2026-08-21: Programmatic Acceptance now recognizes `Gate:` as criterion metadata alongside
  `Intent:`, `Suite:`, and `Requires:`. Planned criteria therefore execute their Python proof
  body without evaluating a `Gate: story-id` declaration as a Python annotation. Previously
  every gated criterion raised `NameError` before reaching the Target, was recorded
  `UNVERIFIED`, and could leave a build appearing complete without having exercised its declared
  acceptance checks.

- 2026-08-20: The `drydock score report` receipt no longer reports a failure a later rerun
  cleared. The `Error` tab quoted the last nonzero exit in the journal regardless of what
  followed it, so a `drydock score release` that failed and was rerun clean minutes later still
  opened the receipt with the failed attempt's transcript, and the `Every recorded command
  exited clean` check still failed. A nonzero exit is now outstanding only when no later
  invocation of the same command exited 0; options are ignored when matching, so a rerun that
  changed provider or model counts as the same step, and a `--help` invocation clears nothing.
  Status queries (`drydock status`, `drydock <verb> status`) are excluded entirely — their exit
  code reports the Target's state, not a fault. With no outstanding failure the `Error` tab is
  not rendered at all, and the commands check reads `every one either exited 0 or was rerun
  clean`. Every attempt remains in the `Commands` table with its own result and rerun label.

- 2026-08-20: The QuarterDeck's scorecard board reads the acceptance table `drydock score` writes
  today. It located the criterion and verdict columns by position and required six of them, so
  the current five-column `ID | Type | Criterion | Verdict | Observed` table rendered nothing:
  every finalized Target showed an empty verdict board on the Commander's Chair. The columns are
  now found by header name, the gate line falls back from `Completion gate:` to `Verdict:`, and
  `MET` and `PASSED` are recognized as holding alongside `PASS` and `HELD`.
- 2026-08-20: The QuarterDeck's story board no longer reports a completed plan as pending. The
  state-to-badge table had no entry for `closed/implemented` — a block that built and closed with
  no governed acceptance command covering it — so every such block fell through to a `pending`
  badge captioned with its own raw state name. `closed/implemented` now reads `built`, and
  `blocked/questions` reads `blocked`.

### Added

- 2026-08-18: The acceptance harness reports how much of a suite passed, so the build's repair
  loop can see progress inside a criterion that is still red. A criterion answers one yes-or-no
  question: a jq story that went from 22 to 123 of 282 conformance cases passing reported the
  same failure both times, and the loop stopped it as a stall with four of its seven calls
  unspent. `acceptance_runner.py` now searches the failing frame — the parsed report, the output
  the criterion captured — for a pass/fail tally in any of the common dialects (`{"pass": 123,
  "fail": 159}`, `123 passed, 159 failed`, `pass=123 fail=159`) and prints it in a fenced
  `--- drydock: progress ---` block. `build_run` reads that block in preference to scraping
  printed text, `failure_detail` shows the counts beside the failed assertion so the repair pass
  is told how far off it is, and the existing subcase-progress comparison then governs the stall
  decision. The detection is retroactive: it requires nothing of the criterion, so Blueprints
  already on disk are measured without re-planning.

  The authoring side is instructed as well. `BLUEPRINTS_CONTRACT.md` requires a suite-driving
  criterion to print its counts before asserting, including when it asserts on a parsed report
  rather than on text. `plan verify` raises a non-fatal advisory — rolled up to one line when it
  holds across a plan — for a criterion that captures a program's output and prints none of it,
  and `plan repair` is permitted to add the missing `print` and is given the file's advisories
  alongside the defect it was already called for, so an advisory never buys a model call of its
  own.

- 2026-08-18: A UAT kit may declare `metadata` in `uat.json`, naming a `METADATA.md` seeded over
  the scaffold `drydock init` writes and before `import`. `analyze` backfills `stack`,
  `display_name`, and `short_description` only when they are blank, so a kit that declares them
  fixes the Target's identity for the whole run rather than accepting whatever the model proposed.
  Discovery rejects a kit `METADATA.md` whose `name` is not the Target's, or that populates a
  run-owned field (`version`, `build_state`, `build_sub_state`, `last_analyzed`, `last_planned`,
  `last_built`, `build_dir`) — a stale lifecycle value would tell later commands the run is
  further along than it is, and a `build_dir` would redirect the build out of the run's own build
  root. The jq kit ships `inputs/METADATA.md`.

- 2026-08-17: `drydock plan verify` and `drydock plan repair` close the gap between detecting an
  unrunnable acceptance criterion and doing something about it. `plan verify` is deterministic,
  read-only, and free: it parses every criterion in `blueprint/` and exits non-zero when one
  cannot execute — a missing import, an undefined name, a syntax error — the class of fault that
  raises `NameError` in the criterion's own frame, settles UNVERIFIED, and spends a story's whole
  repair budget on code that was already correct. `plan repair` makes one LLM pass over exactly
  those criteria, splicing whole `=== AC id ===` blocks back over the ones they replace and
  reverting any file that fails to re-parse; it repairs mechanics only and never touches what a
  criterion asserts. One attempt, then it reports what is still broken rather than retrying. The
  intended workflow pays for the model only when it is needed:
  `drydock plan verify <Target> || drydock plan repair <Target>`. `drydock uat` runs that sequence
  after `plan` and halts the run at the plan when criteria remain unrunnable, instead of building
  over them. A build agent that reports the specification is at fault — it has no write authority
  over `blueprint/` — now routes the operator to `plan repair` rather than to another build pass.
  `drydock plan` gains sub-verbs and a verb menu in `--help`; options continue to work before or
  after the Target.

- 2026-08-17: `STORY_GUIDANCE.json` is a Target-root artifact naming the stories planning must
  produce, with an optional gate command for each and a `provenance` field that carries the
  authority. `commander` entries are supplied as a kit input before `analyze`, are binding —
  `plan` preserves their ids verbatim and shapes each story around the scope its gate exercises —
  and their gates are governed oracles that can close a story `closed/verified`. `plan` entries
  are derived by `analyze` when the imported material states its own build breakdown; they are
  recorded as evidence and their gates are ordinary repairable criteria, because an oracle the
  model wrote proves nothing about the code the same model wrote. `analyze` re-derives its own
  entries each run and never displaces a Commander entry. The resolved set is rendered into
  `ANALYSIS.md` as a `## Story Guidance` section, which QuarterDeck surfaces as a tab.

- 2026-08-17: A UAT kit declares its own `COMPASS.md` as a lifecycle input. `uat.json` accepts
  `"compass": "inputs/COMPASS.md"`, validated at discovery to carry the three Compass body
  sections and to contain no HTML comment — `analyze` reads any comment as an unfilled template
  and would silently replace the file — and seeded into the Target after `init` beside the frozen
  Sea Trials and technology stack. The Compass is the first artifact `analyze`, `plan`, and every
  build step read, so a kit that authors it declares its governing rules as an input rather than
  letting `analyze` compose them from whichever imported source a model classified as intent.
  `analyze` preserves a populated Compass and normalizes only the Drydock-owned Build Write
  Guardrail into it. The `jq` kit now ships one, carrying the harness invocation contract, the
  definition of its terminal story, and the scope rule for every other story.

- 2026-08-17: `STOP_NOW.md` is a Target-level halt semaphore. A lifecycle stage that reaches a
  terminal failure records the stage, the reason, and the time at the Target root, and the stages
  that follow refuse by reading it rather than by re-deriving a verdict from an exit code they did
  not observe — several Drydock commands exit non-zero as ordinary state signals. The first
  declaration wins and is never overwritten, so a stopped run preserves its first causal failure
  instead of the last incidental one. `drydock.stop_condition` exposes `write_stop`, `read_stop`,
  and `clear_stop`.

- 2026-08-16: `drydock uat` carries answered decisions forward and publishes every decision on the
  report. A run's `DECISIONS.json` is copied to its `inputs/` directory at completion, and the next
  run of the same project re-enters the decisions a human answered — `commander_direction` only, so
  Drydock's own `system_choice` proposals are re-derived each run rather than cached. UAT runs are
  therefore not clean-room: a question settled once stays settled, which is the point. Both report
  surfaces now show them: a run's page carries a `Decisions` section above the run detail, listing
  each decision's id, origin, severity, status, title, system choice, and commander direction; the
  project page carries a `Decisions` section, above `Inputs` and `Project`, counting the decisions
  each run recorded and how many remain recommended. The project page's `Inputs` section is now
  labelled with what it holds. `DECISIONS.json` was already sealed into each run but was reachable
  only four directories deep inside the workspace mirror, with nothing linking to it — an
  unattended run has no operator at the keyboard, so it is the only review surface there is.

### Changed

- 2026-08-17: `COMPASS.md` gains a normative `## Verification Protocol` section, and the Blueprint
  artifact repair pass now carries the Compass sections that bind artifact authorship —
  `## Constraints`, `## Guardrails`, and `## Verification Protocol` — quoted rather than
  summarized. The repair prompt instructs the model to add a missing assertion while previously
  supplying only the validation defect and the artifact bodies, so a repair pass authored
  assertions against rules it had never been shown. The observed failure: a repair pass added an
  acceptance criterion invoking a staged conformance harness without the environment variable the
  project's Compass requires of every invocation, making the criterion false under every possible
  implementation, which parked its story at `blocked/questions` and left the Manifest with no
  buildable frontier. The section is normative and is the place to state which story may invoke a
  supplied harness, what every invocation must supply, and which exit codes mean a harness fault
  rather than a product verdict — a rule stated only in prose elsewhere in the Compass does not
  reach a repair pass. A Target with no Compass, or a Compass declaring none of these sections,
  produces no Compass block.

- 2026-08-17: `ACCEPTANCE.json` now carries only `full`, the whole-project release gate. The
  per-story `stages` map moved to `STORY_GUIDANCE.json`, whose subject is the story list rather
  than acceptance; `AcceptanceContract.stages` is now `story_gates` and `stage_for` is
  `story_gate_for`. A Target or kit still declaring `stages` keeps working — the retired key is
  read as Commander-provenance guidance — and `uat.json` accepts `acceptance.story_guidance`.
  The rename also removes a collision: `plan create` already used "stage" for its own internal
  phases.

- 2026-08-17: Planning guidance for an authoritative test suite now requires intermediate slices
  to **execute**. Previously every non-terminal invocation was confined to the runner's list or
  dry-run mode, which enumerates cases without running any, so a slice criterion passed before its
  story's code existed and steered no repair. A story that owns behavior the suite covers now
  gates on its own slice, scoped by the runner's selector to the cases that story implements and
  executing them; the slices together cover the corpus, with overlap expected and gaps treated as
  unchecked work. Only the terminal story runs the whole suite, and list mode remains correct for
  a pure harness staging story, which implements none of the behavior under test.

- 2026-08-17: Plan rejects two acceptance-criteria defects deterministically instead of reporting
  them afterwards. A criterion that invokes a staged asset without a variable that asset declares
  required, and a criterion on a non-terminal story that executes the authoritative suite runner
  outside its list or dry-run mode, now raise `CriteriaDefect` from plan validation. That routes
  the owning specification into the existing artifact repair loop, which re-emits only the cited
  file and re-validates, bounded by `continue_attempts`. When the repair budget is spent the plan
  is still written: validation re-runs with the criteria gate cleared and the defect falls back to
  the pre-existing blocking decision that parks its story, so several accepted batches of correct
  planning are never discarded over one bad snippet. The environment defect was previously a
  blocking decision that `--override` waived on every unattended run; the scope defect was
  detected nowhere.

- 2026-08-17: A Target has exactly one Compass. Imported material routed to the Compass
  disposition by the Analysis is no longer appended to a Commander-authored `COMPASS.md`;
  `compass_sources.mark_compass_authored` records the authorship and `promote_imported_sources`
  honors it. The Source Roles table is model-written, so a model that disagrees with the author's
  own table writes `compass` where the author wrote `context` — which is how the jq kit's
  instructions became a second set of governing rules appended after the first.

- 2026-08-17: A UAT run stops at a failed build instead of scoring one. The build stage declares a
  stop condition when a build pass exits non-zero with work still on the frontier, or when the
  pass bound is exhausted, and the refit, test, and all three scoring stages no longer run. The
  run records `failed` rather than `degraded`. Scoring a build that stopped part way grades the
  absence of the entry point the last stories deliver and publishes a number that invites acting
  on it; the useful artifact is the failing block's evidence, not a release verdict over a
  partial tree. `build_to_completion` is renamed `build_until_no_work_remains`, which describes
  what the loop does — it runs build passes until `status --ready` reports nothing left.

- 2026-08-17: The planning contract defines the terminal story by position rather than by name.
  `BLUEPRINTS_CONTRACT.md` and `plan_create.md` now state that the terminal story is the last
  story in the build order — the one every other story is a transitive dependency of — decided by
  resolving `depends`, never by a story's name, `type`, or `kind`. A story that stages the test
  assets runs first and is never terminal. The same contracts close the gap that left a staging
  story with no legal criterion: it is gated in the runner's list or dry-run mode, which
  enumerates the suite without executing a case, and every staged-asset invocation in any story
  and any mode supplies the environment variables the asset declares required, by extending the
  inherited environment.

- 2026-08-17: A build step whose agent interrupted its own verification command is repairable
  rather than terminal. `target verification interrupted by build agent` now buys repair passes
  like any other agent-reported failure: the build directory holds the work, the declared criteria
  still name the gate, and the interruption is a statement about that command's scope, not about
  the product. The classification previously closed a block on its first pass with its whole repair
  budget unspent — a `jq` step with three green scoped criteria closed `failed` after one call of a
  possible seven. The `build` prompt is now explicit that a staged authoritative suite is run only
  through the invocation this step's acceptance criteria declare: a `Suite: scoped` criterion is the
  whole of the step's obligation to that suite, and running the suite's unscoped entry point is a
  later step's gate executed early against a partial capability.

- 2026-08-16: A UAT receipt now links one LLM activity log per lifecycle step instead of a row of
  numbered links. `drydock uat --report` joins every model call a step made, in execution order,
  into `evidence/commands/<step>.llm.log` under a banner naming the call position, command,
  provider, model, and execution identifier, and the step table links that single file beside the
  step's stdout and stderr. The joined logs are published evidence: they are inventoried, hashed
  into `SHA256SUMS` and `evidence/manifest.json`, and rendered through the kit's HTML viewer.
  Logs for steps a resume superseded are deleted on rebuild rather than accumulating. Per-step
  attribution is unchanged — it still comes from the execution identifiers each command records —
  so a planning step that drives lineage attribution continues to own those calls.

### Fixed

- 2026-08-19: An exhausted provider quota now names itself and stops the run cleanly instead of
  failing as an anonymous non-zero exit. Codex reports a refused turn as its own stream event
  (`{"type": "error", ...}` / `{"type": "turn.failed", ...}`); `llm._provider_error` read only the
  Claude-shaped terminal `result` record, so the provider's own explanation — "You've hit your
  usage limit … try again at …" — was written to the raw transcript and discarded everywhere
  else. The build printed `rc=1` with the generic detail "The provider process exited non-zero",
  the evidence file recorded the same, and the standoff diagnosis then spent a second call
  against the same exhausted quota and returned nothing. `_provider_error` now reads the
  stream-level error events, and the rate-limit classifier recognizes `usage limit` and `quota`
  alongside `rate limit` and `session limit`. The failure surfaces as the existing
  `FATAL ERROR - PROVIDER RATE LIMIT` block carrying the provider's message and reset time,
  `build_run` classifies it `provider rate limit`, and `diagnose.should_diagnose` blocks the
  doomed second call. The Claude path is held to the same contract: a refused turn carrying no
  `api_error_status` is still classified as a rate limit from its message ("monthly spend limit",
  "usage limit reached"), and an `allowed` quota window — which Claude reports on every healthy
  call — is no longer offered as the cause of an unrelated non-zero exit.

- 2026-08-17: A UAT run whose Manifest was unbuildable on arrival now halts at the build stage
  instead of reporting a clean run and crashing below it. `drydock status <Target> --ready`
  returns the same non-zero code for a Target that finished and one whose stories are all parked
  at `blocked/questions` behind blocking `DECISIONS.json` records, so the harness read an empty
  frontier before the first build pass as a completed build. It now confirms that reading with
  `drydock status <Target> --check` — 0 complete, 1 incomplete, 2 blocked — and stops the run
  with `STOP_NOW.md` naming the decisions to answer unless the Target is genuinely complete. A
  resumed stage that arrives with its work already done still passes. `drydock uat` also creates
  the `build/<Target>` application root when it lays out the run directory, so a build that wrote
  nothing fails its scoring command on the evidence rather than raising `FileNotFoundError` out
  of the run and destroying `result.json` and every measurement below it. Command semantics are
  unchanged; the fix is in the harness workflow.

- 2026-08-17: `drydock uat --report` no longer degrades toward unusable as runs accumulate. The
  kit file inventory resolved the real path of every ancestor directory of every file, on every
  rebuild, and did so even when no directories were being skipped — tens of thousands of
  `realpath` calls per report on a kit of a few thousand files, which on a DrvFs or network mount
  turned a report into a multi-minute stall. Skipped directories are now matched by prefix
  against a root resolved once.

- 2026-08-16: An acceptance criterion that invokes a staged source asset without the environment
  that asset requires is now supplied that environment at build time, so the criterion produces a
  verdict instead of consuming the repair budget. Detection at plan time reports the defect but
  does not stop it reaching a builder — `drydock uat` plans with `--override`, where the blocking
  decision is recorded rather than enforced — and the criterion is unsatisfiable by any build: a
  repair pass may not rewrite a criterion, and staged assets are restored before grading. `build`
  now reads each block's criteria against the staged assets before its first LLM call and injects
  the missing variable into the criterion's own environment for that grading only, taking the
  value from the asset's documented usage line and, failing that, from a criterion in the same
  Blueprint that invokes the same asset correctly. The Blueprint and the staged asset are
  unchanged; every injection is recorded in `DECISIONS.json` as a `recommended` decision naming
  the criterion, asset, variable, value, and the source of the value, and is re-derived on every
  build so a repaired Blueprint simply stops producing them. A gap no source can answer, or one
  behind a closed `env=` dict no upstream assignment can reach, settles the criterion UNVERIFIED
  and records the decision without a choice. In the observed `jq` run, five of ten `Suite: scoped`
  criteria omitted `JQ` — the other five supplied it, from the same prompt in the same run — and
  the first to execute burned three LLM calls, failed its block, left blocks 6 through 11 unbuilt,
  and was reported as a product defect.

- 2026-08-16: A story whose every criterion settled UNVERIFIED now closes `closed/implemented`
  rather than `closed/verified`. Nothing measured the built code, so the story is not verified;
  the product may be correct and the criteria broken, so it is not a failure either. The Manifest
  records an advisory naming the condition. Previously a single-criterion conformance story whose
  criterion never ran closed green, which would have released a project with its conformance suite
  never executed.

- 2026-08-16: `drydock uat` no longer charges an UNVERIFIED assertion to the product as well as to
  the harness. The run record derived `failed` as `total - passed`, which includes unverified, so
  one assertion that never ran was counted once as `harness_defects` and again as
  `product_defects`. The run record also now carries `release_verdict`, the release gate's own
  PASSED/FAILED/ERROR result, which `acceptance_status` is derived from and does not preserve.

- 2026-08-16: An acceptance criterion that invokes a staged source asset without the environment
  that asset declares required is now detected at plan time instead of failing a build block. The
  new `drydock.acceptance_env` module reads each asset under `blueprint/sources/` for variables it
  states are required — an "is not set" / "must be set" / "is required" sentence, an `Environment:`
  entry marked required, or a documented usage line that assigns the variable in front of the
  asset's own command — then parses every emitted criterion and reports any `subprocess` call that
  names the asset without supplying the variable through `env=` or `os.environ`. `plan` writes the
  specification as authored, reports the defect as a warning, and raises it as a blocking decision
  against the owning story, matching how a criterion that does not compile is handled; a call whose
  environment cannot be read statically is treated as satisfied, so a sound story is never blocked
  on a guess. The origin is fixed with it: the worked `Suite: scoped` example in
  `prompts/BLUEPRINTS_CONTRACT.md` now carries `env={**os.environ, ...}`, where previously it
  modelled a bare `subprocess.run` while prose forty lines below required the variable. In the
  observed `jq` run, ten criteria copied the example and the first to execute exited on the
  conformance runner's own usage code, which no implementation could have changed.

- 2026-08-16: A Blueprint specification whose acceptance container cannot be read no longer
  discards the work around it. An unclosed `=== AC <id> ===` block that `plan`'s terminator repair
  declines to close — its body does not tokenize, so no boundary is inferable — used to raise out
  of an advisory declaration pass in `_validate_plan_output` and out of
  `project_plan_requirement_decisions`, throwing away a complete generated plan (in the observed
  `jq` run, six accepted batches and ten LLM calls) over one criterion. Both readers now degrade
  the file to zero criteria; the defect is already reported as a plan warning and as a blocking
  decision against the story that owns it, so the criterion gates nothing and nothing else stops.
  The same degradation applies at execution time, where `build`, `drydock score acceptance`, and
  `score_target` previously raised on the file that `plan` had written: each now warns and
  continues. The warning is mandatory by construction — the shared readers `acceptance_checks_from_text`
  and `acceptance_checks_from_file` take a required `defects` collector, so criteria cannot be
  dropped silently, and `AcReport` carries a `defects` tuple rendered above the board. `drydock
  validate` still fails hard on the file, and the terminator repair is unchanged: it will not
  insert a boundary into a body that does not tokenize.

- 2026-08-16: A blank line between an acceptance criterion's declarations no longer discards them.
  `=== AC ===` metadata parsing ended the declaration run at the first blank line, so a criterion
  that spaced `Intent:` away from `Suite:` and `Requires:` lost both into the proof body: it drew
  the story execution budget instead of the suite budget, declared none of its tooling to
  `project_plan_requirement_decisions`, and — because `Suite: full` is itself valid Python — was
  reported by `drydock status` as a snippet reading undefined globals named after its own
  directives. The run now ends at the first line that is not a recognized declaration. Criteria
  whose first statement is an annotated assignment are unaffected, and a blank line preceding the
  first statement stays in the proof body. Recovering the declarations means a criterion's tooling
  requirements are now gated as designed, so a plan may raise an authorization decision where the
  requirement was previously invisible.

- 2026-08-16: `drydock status` reports open blocking decisions. The Review line read only
  `BLOCKERS.md` and the questionnaire directory, so a target with an unanswered blocking entry in
  `DECISIONS.json` — the record that gates its story at build — printed `No blockers`. It now
  prints `<n> open blocking decisions`. Phase selection is unchanged: only `BLOCKERS.md` routes a
  target back to Arrange, so a planned target holding a blocking decision stays in Implement rather
  than being directed to edit a file that does not exist.

### Added

- 2026-08-16: A block is now swept against everything earlier blocks proved. After a block's own
  criteria go green, `drydock build` re-runs the accumulated proven set; a criterion that was green
  when the previous block finished and is red now is a regression attributable to this block,
  because nothing else ran in between. The block fails with `acceptance regression: <check-ids>`,
  and the repair pass is given a `### Regression — fix this first` section naming what it broke.
  A clean sweep says nothing to the model and costs no prompt context — previously proven criteria
  are never injected unless one of them goes red. This closes the gap that let Toml delete its
  decoder's argument guard at block 3 and ship eight further blocks before final scoring noticed.

- 2026-08-16: A failed acceptance criterion reports the values it observed. Criteria now execute
  through `drydock/acceptance_runner.py`, which prints the operands of the failing line before the
  traceback, so `assert result.returncode != 0` is reported alongside
  `result = CompletedProcess(returncode=0, stdout='…')` rather than as a bare `AssertionError`.
  The failure block also quotes the criterion's own source with the raising line marked. Values
  and source flow to every consumer of `failure_detail`: `drydock score ac`, block evidence, and
  the build-run repair feedback.

- 2026-08-16: `drydock score ac` reports proof coverage. After the per-criterion board it states
  how many criteria are evidence — green here and observed red before the work that turned them
  green — and lists every `PREPASSED` and integrity-demoted `UNVERIFIED` criterion with the story
  that owns it. It changes no exit code and no build prompt: a criterion measuring a deliverable
  that legitimately already existed is indistinguishable from a vacuous one, and only the author
  can tell which.

- 2026-08-15: A UAT run can be resumed at a recorded step instead of a stage name. `drydock uat
  <Project> --steps` prints the last run's numbered steps with the stage each one resumes into, and
  `drydock uat <Project> --from-step <n>` re-enters the run at the stage that owns step `n`,
  stating the translation before it runs. A stage remains the atomic entry unit, so a step
  belonging to `init` is refused with a pointer to a fresh run; `--from-step` and `--stage` are
  mutually exclusive and both accept `--run`.

- 2026-08-15: A nonzero `drydock score ac`, `drydock score build`, `drydock score release`, and
  `drydock build` now names its cause on stderr as well as stdout: the failing criterion or block,
  its owner and Blueprint file, and the assertion summary. The graded report on stdout is
  unchanged. An empty error stream beside a nonzero exit is now a defect rather than the norm, so a
  harness or CI step that captured only stderr is told why the command failed.

### Changed

- 2026-08-16: Baseline-green (`prepassed`) is recorded only for criteria owned by the stories a
  block is building. A criterion carried in from an earlier block is green because that block
  proved it, which is the opposite of the claim `prepassed` makes; recording it inflated the count
  and would have flagged the entire proven set once the regression sweep began observing it.

- 2026-08-15: UAT proof kits report `drydock status` steps as states rather than grades. A status
  row's Result column carries the state the command printed — `READY TO BUILD`, `NOT READY`,
  `BUILD COMPLETE`, `INCOMPLETE` — with no pass/fail styling and no `EXIT n` stamp, and shows
  nothing when the invocation printed no headline. The same rendering applies to the build receipt.

- 2026-08-15: The proof kit's Error tab quotes every step that exited nonzero, in run order and
  with the error stream first, instead of only the first and last. A failing step that wrote
  nothing to stderr is called out as such rather than rendered blank.

- 2026-08-15: A UAT run records the LLM execution identifiers each lifecycle command produced, and
  the proof kit joins model transcripts to steps with those identifiers. The previous association
  was reconstructed by matching `Calling <provider>/<model>` banners in captured stdout, which
  attached nothing to `drydock build` — the command that makes most of a run's calls and prints no
  banner. Runs recorded before the field still fall back to banner matching. Kit selection also
  now resolves to the directory spelling on disk, so a case-insensitive filesystem no longer
  records paths the report cannot state relative to the kit.

- 2026-08-15: Every `drydock uat` invocation verifies that each selected `uat/<Kit>/` directory is
  an independent Git repository, initializes it when absent, and commits all pending kit changes
  before exit, including report rebuilds, resumed stages, failures, and usage exits reached after
  kit selection. Target Git stores used during execution are removed from `runs/` before staging,
  and stale gitlinks are expanded into ordinary tracked run files.

- 2026-08-15: Every Target workspace is now initialized as its own quiet Git store. Existing
  Targets are upgraded before their next Target command so `drydock refit` always has repository
  history available for diffing, and each command checkpoints pending Target changes on
  completion. Successful setup and commit operations emit one stable summary line each; Git's
  implementation output remains captured and failures are reported through Drydock's error
  contract.

- 2026-08-15: The shipped `/drydock-uat <Target>` skill loads the current versioned
  `prompts/uat_diagnostic.md` contract at invocation time and diagnoses the latest completed run
  without rerunning it or editing evidence. The prompt treats incorrect Sea Trials and acceptance
  criteria as specification contamination and traces governed criteria through planning,
  implementation, and acceptance evidence before blaming generated code or the model. `drydock
  init` installs the skill for Claude Code and Codex alongside `/refit` and `/apply-refit`.

- 2026-08-15: The bounds governing an acceptance run are configuration rather than constants.
  `capture_output_limit` (default 8 MB), `repair_attempts` (default 6), and `repair_stall_limit`
  (default 2) join the existing `sandbox_mem_limit` as `drydock config` keys, readable from
  `DRYDOCK_CAPTURE_OUTPUT_LIMIT`, `DRYDOCK_REPAIR_ATTEMPTS`, and `DRYDOCK_REPAIR_STALL_LIMIT`.
  `drydock build` and `drydock uat` both accept `--repair-attempts`, `--repair-stall-limit`,
  `--capture-output-limit`, and `--sandbox-mem-limit`, in that precedence: flag, environment,
  config file, shipped default. `repair_attempts` and `repair_stall_limit` were previously
  unreachable module constants, so a target that converged slowly could not be given a longer
  budget without editing the source. An unset `--repair-attempts` is now distinct from one set to
  the default value, and the echoed running command names only flags the operator actually typed.

### Fixed

- 2026-08-16: A dropped `=== END AC <id> ===` terminator no longer discards a whole plan.
  `drydock plan` closes an acceptance container whose terminator the model omitted when the
  boundary is decidable — an opener directly followed by another opener, or a trailing opener at
  the end of an artifact block — and reports each repair as a planning warning. The boundary is
  accepted only when the candidate body tokenizes, so an `=== AC ... ===` line embedded in a
  triple-quoted string (which a target that processes Drydock's own markup writes legitimately)
  still raises rather than splitting a criterion silently. A mismatched end id, a stray end
  marker, and a duplicate id remain hard errors. Output that already pairs strictly is not
  touched. Previously a single omitted terminator failed post-output validation and rolled the
  run back: a `jq` run lost ten LLM calls, six accepted batches, and 944k input tokens, writing
  nothing. A plan validation failure now also names every execution that contributed to a merged
  Stage 2 block set, instead of naming only the call that opened the plan.

- 2026-08-16: A backslash escape in an acceptance criterion is reported against the criterion
  that contains it rather than as an unattributable `<acceptance>:5: SyntaxWarning` on stderr.
  `acceptance.escape_defects` captures the compiler's advisory and `drydock plan` renders it as
  `FEATURE-X.md [check-id] line 5: invalid escape sequence '\(' — write the backslash as a raw
  string (r"...") or double it`. The criterion is not gated and not rewritten: CPython preserves
  the bytes, so a jq or regex proof written this way runs and proves what it claims. Every
  `ast.parse`, `compile`, and `symtable` call over criterion text now suppresses the duplicate
  console warning, which previously re-emitted on every parsing pass because compile-time syntax
  warnings carry a NULL registry. `prompts/BLUEPRINTS_CONTRACT.md` (V13) states the escaping rule
  and that the end marker is mandatory.

- 2026-08-15: `drydock score ac` preserves an acceptance observation already classified as
  `UNVERIFIED` instead of relabeling every non-passing process as `FAIL`. Blueprint validation now
  rejects acceptance scripts that read unresolved standalone globals, such as `sys` without an
  import, before build or scoring can execute them. Runtime exception attribution remains the
  fallback for defects static validation cannot establish, with its exception categories loaded
  from the packaged `Rigging/acceptance_failure_taxonomy.json`; Drydock never injects imports or
  otherwise rewrites governed assertions.

- 2026-08-15: `drydock status` writes every verdict to stdout. `--check` (`COMPLETE`,
  `INCOMPLETE`, `BLOCKED`) and `--ready` (`READY TO BUILD`, `BUILD COMPLETE`, `NOT READY`) both
  reported some outcomes on stderr, so a build loop reading stderr as a failure signal saw a
  successful status report as an error. The exit code carries the verdict — `--check` exits 0, 1,
  or 2; `--ready` exits 0 while a build can advance — and stderr now means only that a command
  failed. UAT evidence now preserves each model execution's `.llm.log`, and UAT/build receipt LLM
  tables link it beside the prompt, output, and provider transcript. UAT lifecycle command rows
  also associate every recorded call banner with its `.llm.log`, rendering `stdout`, `stderr`, and
  `llm` links together even when one command made multiple model calls.

- 2026-08-15: Token and cost accounting no longer prints to a command's stdout. An LLM call's
  `elapsed`/`cached`/`uncached`/`out`/`tps` detail line, and the per-block `tokens:` line
  `drydock build` echoed, are written to that execution's `<stem>.llm.log` alone; the console keeps
  the call banner and the `Completed <provider>/<model> rc=<n>` headline, which are progress. A
  command transcript is therefore the command's own output, and accounting is read as accounting.
  `drydock score report` gained an `llm` column joining each recorded call's activity log to the
  command that made it, so every receipt page showing `stdout` and `stderr` also links where the
  accounting went.

- 2026-08-15: A governed acceptance gate can no longer end the process grading it. `run_gate`
  captured child output with `subprocess.run(capture_output=True)` and applied none of the bounds a
  build-time acceptance check already got, so a target that emitted without end was held whole in
  memory: a jq build missing an upstream `"Repeat string result too long"` guard emitted 2.1 GB on
  one line, and `drydock score release` was killed by the kernel at 14.7 GB resident after the
  build itself had passed the same command under a 4 GB ceiling. Gates now run through
  `drydock/child_sandbox.py`, which both paths share, so the address-space ceiling and the new
  output ceiling apply identically wherever Drydock hands control to the code under test. Output
  past the ceiling is discarded rather than buffered, the child's process group is killed, and the
  truncated head is kept as evidence. Exceeding the ceiling is classified `FAIL`, not `ERROR`: a
  product that emits without end is a defective product, and calling it a kit fault would excuse
  the build from a failure it caused.

- 2026-08-15: `drydock score report <Target>` publishes the receipt `drydock uat --report` produced
  for UAT fixtures, for any real Target. It writes `index.html`, `result.json`, and a styled viewer
  for every artifact to `$DRYDOCK_BUILD_DIRECTORY/<Target>/drydock/`, and copies the evidence the
  page links: the Target's slice of `logs/` — command transcripts, assembled prompts, model output,
  provider transcripts, and the `history.jsonl` and `llm.jsonl` records for the run — plus the whole
  Target workspace. The delivered application is inventoried in place, one level above the report,
  rather than duplicated inside itself. The run reported is the Target's latest: everything recorded
  since its most recent `drydock init`.

  The verdict inverts the UAT rule. A UAT run passes when the harness worked, so a product failure
  Drydock reported correctly is a UAT pass; a build receipt stamps `PASSED` only when the product
  met its acceptance criteria, `FAILED` on any failed criterion, and `UNPROVEN` when no acceptance
  board is recorded. `UNVERIFIED` criteria are counted and named but do not fail the run, matching
  `drydock score ac`. The receipt states five claims — acceptance criteria, build blocks, acceptance
  score, release score, and clean command exits — each with the artifact that settles it, and never
  renders an unsettled claim as a pass. No `SHA256SUMS` is written: digests exist so a third party
  can verify a published kit independently, which a receipt in the operator's own build tree is not
  for. The command reads only; it executes no proof, calls no model, and rescores nothing, so a
  stale acceptance board is reported as stale rather than silently refreshed.

  Command execution is now joinable to the files it wrote. `logs/history.jsonl` records `stamp` (the
  millisecond timestamp its transcript and every LLM evidence file are named from), `transcript`,
  `argv`, and `elapsed_ms` alongside the existing minute-resolution `time`; records written before
  those fields still parse, and are joined to their transcript by minute and command name where that
  is unambiguous. Report rendering shared by both commands — page chrome, inventory trees, artifact
  viewers, receipt tables, and path portability — moved to `src/drydock/report_render.py`;
  `uat_report.py` keeps the UAT verdict rule and its kit layout, and its output is unchanged.

### Changed

- 2026-08-15: Every UAT kit is now graded by a staged, Commander-owned scoring entry point.
  `discover_fixtures` requires each `uat/<Kit>/uat.json` to declare `acceptance.full`, and
  `test_command` defaults to it when omitted, since the two are the same command by construction.
  `uat/CommonMark/` and `uat/ReadingList/` previously declared no governed gate at all, so
  `score release` ran no oracle and graded them on the LLM's judgement alone — and a criterion the
  grader cannot settle is `MANUAL`, which never blocks. That is how a CommonMark run with four of
  sixteen stories built recorded `verdict: PASSED`. Both kits now stage `sources/full_test.sh`
  alongside Toml and jq: CommonMark's drives the unfiltered 655-example conformance suite against
  the delivered `./commonmark` and rejects the runner's `exit(failed + errored)` status when a
  multiple of 256 failures would truncate to zero; ReadingList's dispatches to the `bin/test.sh`
  its source prose makes a product requirement and fails loudly when it is absent. The CommonMark
  build instructions and `st-001` now name the supplied harness as read-only and hash-verified
  rather than instructing the build to author its own.

- 2026-08-15: `drydock uat` no longer puts a partial build to final validation. When a build stage
  ends degraded, the run skips both the terminal `status --check` completion record and the
  fixture's scoring command, records `test not run: the build did not complete`, and reports
  acceptance as `NOT_RUN` instead of `FAIL`. The scoring command is the terminal story's
  deliverable, so running it against a build that stopped early measured the absent harness and
  recorded it as a product failure. Partial views — `status --ready`, `build status`, and the
  per-stage status snapshots — are unaffected, and `score ac`, `score build`, and `score release`
  still run over the partial tree.

- 2026-08-15: `drydock status` no longer creates or checkpoints a Target's Git store. A query must
  not mutate what it reports on, and the store's setup and commit summary lines were being written
  onto the machine-readable stdout that `status --check` and `status --ready` hand to a calling
  script, ahead of the `COMPLETE:`/`INCOMPLETE:` token.

- 2026-08-15: A failed acceptance criterion now reports why it failed everywhere it is reported.
  `drydock score acceptance` previously printed the last line of the check's traceback, which for
  `assert result.returncode == 0` is the bare word `AssertionError` — a symbol naming no defect,
  and one that reads as an internal Drydock fault — while the check's own tally on stdout was
  discarded. Both the build report and the score report now render one bounded block per failure:
  the assertion that failed, the process exit code, the exception with its message, and the last
  twelve lines of what the check itself printed. `SOUNDINGS.md` keeps a one-line cell, now the
  recovered assertion rather than an exception name. A bare exception is never presented alone.

- 2026-08-15: Acceptance attributes a criterion that dies below its own frame to the criterion
  rather than to the build. A check that hands `subprocess.run` an `int` in its argv raises
  `TypeError` several standard-library frames down without the built code running at all;
  attribution previously required the deepest frame to be the check, so such a criterion was
  graded a product failure, consumed the whole repair budget, and closed its block `closed/failed`
  with no implementation able to reopen it. A traceback whose frames are the check and the
  standard library, with none inside the build tree, is now a `malformed check` — reported,
  terminal, and never charged to the build. One frame in the built tree still makes it a genuine
  red, and a `FileNotFoundError` reading a deliverable that does not exist yet remains the
  expected red baseline.

- 2026-08-15: `drydock status <Target> --check` names the blocks that failed in its one-line
  reason (`1 closed/failed; failed: block-references`) instead of reporting a bare count.

- 2026-08-15: UAT report pages no longer link empty artifacts or generate viewer pages for them.
  An empty stdout beside a failed command sent the reader to a page reading "This file is empty."
  while the explanation sat in the sibling stderr; empty files stay inventoried and are marked
  `empty`. The recorded failure excerpt now quotes the first stage that exited non-zero as well as
  the last, since later failures are usually consequences of the first.

- 2026-08-15: `prompts/uat_diagnostic.md` (V3) replaces its one-paragraph diagnosis with five
  fixed sections — Verdict, Root Cause, Consequences, Reporting Defects, Recommended Actions — in
  single-line bullets targeting 250 words, so a diagnosis separates the causal defect from its
  downstream effects and states where the run's own evidence failed to explain itself.

- 2026-08-15: Scoring commands no longer echo Codex's shell command and exit-event stream to the
  operator console. The raw LLM artifact retains those provider events as execution evidence;
  normal output keeps call status, quiet-run heartbeats, and the rendered scoring result.

- 2026-08-15: Programmatic acceptance no longer rejects a newly generated Python Target solely
  because it has no `.venv`. Acceptance prefers the Target `.venv` when present and otherwise
  executes through the active Python interpreter already running Drydock. Strict Target runs
  still replace `PYTHONPATH`, preventing repository-local Drydock modules from leaking into the
  check. Dependency availability is inventoried from the same selected interpreter. This repairs
  UAT builds whose generated `pyproject.toml` was tested successfully before Drydock reclassified
  every acceptance criterion as `UNVERIFIED` with `Target Python project has no .venv`.

- 2026-08-15: UAT run and project reports replace the five-step verification guide and four-item
  limitation statement with a compact `RUN SUMMARY` linking the input specification, delivered
  code, and external test results, followed by two `RUN NOTES`. A nonzero `drydock status` exit is
  rendered as its neutral `EXIT <code>` state signal rather than `FAIL <code>`; an unmet Target
  completion receipt claim is `UNPROVEN`, because `drydock status --check` did not itself fail.

- 2026-08-14: A programmatic acceptance criterion's execution budget now follows what it executes
  rather than only what it declared. A criterion that launches a staged runner under `sources/`
  is suite-bound whether or not its author wrote a `Suite:` marker, and draws
  `SUITE_TIMEOUT_SECONDS` instead of the story budget; detection requires the staged path to
  appear in the arguments of a process launch, so reading or stat-ing a staged file remains
  bounded work. The story budget rises from 60s to 120s. A timeout no longer asserts a cause it
  cannot establish: a suite-bound kill reports that the staged runner did not finish and that a
  hung case, a slow suite, and a loaded host are indistinguishable, while a story kill still
  names a non-terminating loop as the first thing to look for. The repair-feedback heading
  likewise states the resource fact and defers to each check's own error instead of declaring
  that the code does not terminate on some input. The prior behavior failed a jq build whose
  delivery criterion shells out to a 550-case conformance suite that completes in 50s: it drew
  the 60s story budget, was killed under load, and was reported as a non-terminating loop in the
  product, which routed the block to an unrepairable kit fault after one call.

- 2026-08-14: `drydock plan` now receives Commander-owned `ACCEPTANCE.json` as read-only planning
  context, so governed stage boundaries can shape the story topology instead of being compared
  only after implementation. Stable analyzed identifiers from Manifest `covers:` take precedence
  over generated story ids during stage-gate lookup; existing story-id contracts remain valid.
  The Plan authoring contract also states at the point of AC generation that every delimited
  acceptance block is a standalone script and must repeat every import it uses, including
  `import subprocess` in each block that calls `subprocess.run`. Plan deterministically inserts
  that standard-library import when a generated AC reads the qualified `subprocess` name without
  binding it locally, and reports the normalization; it does not reinstate general undefined-name
  prediction.

- 2026-08-14: A UAT report leads with a receipt instead of an evidence index. The run receipt
  (`runs/<id>/index.html` and its `README.md`) and the project page (`index.html`) now open with
  six fixed claims — lifecycle completed, external conformance suite passed, target completion
  check passed, acceptance score passed, release score passed, integrity verification passed —
  each carrying the recorded outcome that decided it and a link to the artifact that proves it.
  A claim the run never recorded renders `UNPROVEN`, never as a pass, and a passing run whose
  receipt is incomplete states the shortfall in its verdict line rather than letting `PASSED`
  imply the unproven claims. Below the receipt the report states run provenance (Drydock
  version and commit, provider, model, platform, Python, elapsed time, LLM calls, token use,
  build passes, repair budget, conformance result), a five-step guided path that a reader
  without Drydock installed can walk in five minutes — specification, Blueprint and Manifest,
  delivered code, external test result, `sha256sum -c SHA256SUMS` — and an explicit statement of
  what one run does not prove. Command tables, LLM executions, and the file inventory follow as
  supporting detail. The project page summarizes the newest run specifically and links it by run
  id. Every receipt link is emitted only when the artifact exists on disk.

- 2026-08-14: LLM run telemetry is no longer written to stderr. The call banner, the prompt
  breakdown, and the token accounting line (`Completed CODEX/gpt-5.6-luna (plan) rc=0
  elapsed=1m 21.4s cached=... uncached=... out=...`) describe a healthy execution, so they now
  print on stdout — which also means the command transcript keeps them — and each execution
  records its own copy in `logs/<stamp>_<target>_<command>_<provider>.llm.log`, created only
  when a line is written. Fatal provider errors, authentication failures, and rate-limit blocks
  stay on stderr. The consequence for diagnostics is that a `.stderr.log` next to a command or
  an execution now indicates that something went wrong, rather than that an LLM was called: on
  a clean UAT run the per-stage stderr capture closes empty and `index.html` renders a dash.
  The provider's own stderr is unchanged and still lands in `<stamp>...stderr.log`.

- 2026-08-14: A UAT proof kit publishes each LLM transcript once. A run drives a Drydock
  workspace, so every assembled prompt, provider transcript, and model output existed twice on
  disk — under `evidence/` and again under `workspace/logs/` — and the kit inventoried both trees
  whole, rendering a separate HTML viewer for each copy. `evidence/` is now the canonical home:
  a workspace file whose digest matches an evidence artifact is withheld from the inventory, no
  viewer is written for it, and `index.html` does not link it. Withheld paths are listed in a
  generated per-run `.gitignore`, and the artifact links the run recorded against its own
  workspace are remapped onto the published copy, so no receipt link addresses a file the kit
  held back. Duplication is decided on the digest rather than a suffix list; empty files are
  exempt, because every empty file shares one digest and "this command wrote no stderr" is a fact
  worth keeping. `workspace/targets/` is unaffected — the Blueprint, Manifest, and Target
  artifacts have no evidence twin and remain the record of what the run built. On the recorded
  CommonMark run this takes the kit from 50 MB to 38 MB on disk and 26 MB committed, with 393
  links resolving and none pointing at an ignored path.

- 2026-08-14: `drydock score release` grades the finished tree by observing it, and the verdict
  vocabulary collapses to three words. A run is `PASSED`, `FAILED`, or `ERROR`; a criterion is
  `MET`, `NOT MET`, or `MANUAL`. `PENDING MANUAL VERIFICATION` is retired: it was doing two
  unrelated jobs — a criterion no machine can ever settle, and a project that is not built yet —
  and one word for both is how a finished, correct project came to be reported as though it had
  open questions. The first is `MANUAL`, which attests and never blocks; the second is `NOT MET`,
  because an unbuilt criterion gets an F. `NOT MET` still requires the grader to have looked and
  to cite what it saw, so a verdict with no citation degrades to `MANUAL` rather than failing a
  build nobody examined.

  Score no longer reads what the build recorded. An assertion that passed at block 3 is a
  statement about the tree as it stood at block 3, so AC outcomes, block states, and the Manifest
  are history and reach no verdict. The governed gate is executed rather than inherited, every
  `Command:` a trial names is run against the final tree, and the grader is handed the build
  directory with tools so it can read the source and write an **ephemeral probe** for behavior no
  command covers. Probes live in `.drydock-probe/` inside the build tree and are deleted after
  grading whether or not the grader tidied up. The console prints the whole listing — every
  criterion and what was observed of it — and `evidence/score-release.json` moves to schema
  version 5 with `verdict`, `verdict_line`, `statement`, and `observations`. `SCORECARD.md` is now
  a release scorecard rather than a completion gate. Exit codes are unchanged: `PASSED` exits 0,
  `FAILED` and `ERROR` exit 1, with the two distinguished in the record — UAT now reads the
  recorded verdict instead of the exit code, so a run Drydock could not grade is an execution
  fault rather than a product failure.

- 2026-08-14: Sea Trials are referenced by nothing. `Sea Trials:` proof tags on Programmatic
  Acceptance blocks, `Verification:` as a mechanism selector, and the plan-time coverage gates are
  all retired: plan no longer validates `accepts:` targets, proof-tag targets, or that required
  trials are covered, and neither scorer looks up a criterion's verdict from which assertion
  claimed it. `accepts:` survives as human-readable traceability that gates nothing.

  What this closes: ReadingList run `20260814.001652` built a complete, correct product and was
  refused five times because `plan` and `score release` read the same coverage contract
  differently — `plan` accepted an `accepts:` field *or* a proof tag, `score` counted proof tags
  only. Every blocked criterion carried a grader rationale asserting it was met beside an evidence
  line reading `no code-bound proof references this criterion`. A grammar with two readers has one
  of them wrong.

### Added

- 2026-08-13: Artifact blocks carry an invariant closing boundary.
  `=== BEGIN ARTIFACT <name> ===` … `=== END ARTIFACT ===` is now the emitted form in
  `analyze`, `plan`, `document generate`, `survey import`, and `import compass`. The artifact name
  is typed once, at the open; the close is a constant token with nothing to recall and nothing to
  collide with, which is MIME multipart discipline. Both parsers accept the named form
  (`=== NAME ===` … `=== END NAME ===`) unchanged, so no recorded response stops parsing, and the
  `=== AC <id> ===` proof containers are deliberately excluded — there the id in both markers is a
  real checksum binding a criterion to its identity.

  The failure this prevents: a Toml `analyze` run died because the model closed `COMPASS.md` with
  `=== END COMPASS ===`. The only artifact that closed wrongly was the only one whose first
  heading restated its filename stem, twenty-five lines above the close. Any artifact whose
  content restates its filename is exposed to the same collision, and the close delimiter was the
  one place the protocol asked the model to reproduce a variable from memory.

### Fixed

- 2026-08-14: `drydock status <Target> --ready` checks the actual buildable frontier instead of
  deriving readiness from verification completeness. A Target whose stories are terminal
  `closed/implemented` but not `closed/verified` now stops the build loop immediately rather than
  issuing empty builds until UAT exhausts its pass budget. `status --check` remains the separate,
  read-only verification-completeness check; UAT records that result without using it to gate
  final-tree release scoring.

- 2026-08-13: The `plan` repair prompts state the artifact grammar instead of demonstrating a
  different one. Both repair prompts are assembled in Python rather than under `prompts/`, so the
  invariant-boundary migration never reached them: each asked for a "fully paired block" without
  saying what one looks like, then supplied the original body inside `<original-topology>` or
  `<original-artifact name="…">` tags. The model mirrored the only syntax it was shown. In Toml
  run `20260813.234757` a topology coverage repair the model performed correctly was discarded
  unread — twice — and `drydock plan` refused the run on `DECODER-002`, the analyzed story the
  discarded repair had covered, after Stage 2 had authored ten Blueprints against the declaration
  already known to be defective.

  `artifact_blocks` now owns the emission contract (`artifact_open`, `wrap_artifact`,
  `emission_contract_lines`), rendered from the delimiter constants so no prompt hand-types a
  boundary, and both repair prompts supply their input wrapped in the same grammar they ask for.
  A single `_read_repair_blocks` replaces the two independent readers in the coverage and
  continuation repair loops. The XML fallback survives as recovery for replies already in flight
  and additionally accepts `<NAME>…</NAME>` for filename-shaped names, refusing a reply that mixes
  forms. A repair Drydock cannot use is now reported with its reason rather than silently
  returning the uncorrected declaration on four separate paths.

- 2026-08-13: Every check that reasons over raw artifact delimiters now reads both boundary
  grammars. Adopting the invariant close taught the two parsers a second grammar but left five
  callers counting named `=== END <name> ===` lines, and the invariant close carries no name to
  count: `drydock plan` read an undamaged Stage 1 response as wholly unpaired, discarded the
  topology it had just parsed, and died `KeyError: 'TOPOLOGY.md'` in the continuation loop
  (Toml run `20260813.231738`). The same blindness made `plan_shape.check_delimiters` report
  every artifact unclosed and every close an orphan, and made `plan conform` silently find no
  spec in a well-formed response.

  Pairing is now computed once, positionally, by `artifact_blocks.pair_artifact_delimiters`, and
  shared by `planning_session` and `plan_shape`; it mirrors the parser's own recovery rules, so a
  structural check can no longer disagree with what the parser extracted. The duplicate delimiter
  regexes in `plan_shape` are deleted, and `plan conform` extracts through the shared parser
  rather than a name-backreferencing regex that the invariant close cannot satisfy.

- 2026-08-13: A malformed artifact block no longer discards the artifacts beside it. Both the
  `analyze`-path parser (`artifact_blocks`) and the `plan`-path parser (`planning_session`) now
  reject per artifact: a block whose name is not allowed, or whose boundaries could not be
  resolved, is dropped by name with its reason, and the command proceeds on what it did accept.
  Callers state which artifacts they require — `analyze` requires `ANALYSIS.md`, `document
  generate` requires its four standard sections — so a missing required artifact is still fatal,
  but it now fails naming the artifact rather than naming a block the model never opened. Only a
  response from which nothing survived is rejected whole. Four of twenty recorded UAT runs died
  this way, one of them discarding nineteen Blueprints and eight LLM calls over a single
  malformed block.

- 2026-08-13: A closing delimiter that names the wrong artifact is read as a close, not as a new
  block. Both parsers recognise the close by position — a name-mismatched close whose successor is
  another delimiter, or the end of the response, terminates the open block — and report the name
  disagreement naming both markers. A mismatched close whose successor is real content is still
  read as the boundary the model transposed. The names are never fuzzy-matched: the close's name
  is a checksum on the open, and matching them loosely would discard the property that makes an
  unclosed container detectable at all. Previously the parser invented a block named after the
  marker, then failed the allow-list on a name the model never opened, producing a diagnostic that
  pointed at the wrong artifact.

- 2026-08-13: A UAT fixture declares the verdict it expects. `uat.json` accepts
  `"expect": {"verdict": "PASSED|PENDING|FAILED|ERROR"}`, defaulting to `PASSED`, and every
  shipped kit declares one. `result.json` gains `expected_verdict` and `observed_verdict`, and a
  kit's `status` is now a comparison of the two rather than a copy of the observed one: a fixture
  carrying a known product defect that Drydock correctly reports as `FAILED` is a UAT pass. The
  observed verdict folds the run's two existing status views — an infrastructure fault is `ERROR`
  and never satisfies an expected `FAILED`, because a run that could not execute has said nothing
  about the product. This changes what `drydock uat` measures: it asks whether Drydock reached the
  correct conclusion about the fixture, not whether the fixture project passed. Eight recorded runs
  of a fixture with a real defect produced no signal about Drydock at all, because each read as
  Drydock failing.

- 2026-08-13: A story acceptance criterion binds only to an oracle it could not have invented.
  `acceptance.retyped_expectations` reads each criterion's AST and reports every expected string
  literal the author typed a second time rather than deriving; `ProgrammaticAcceptance.binding` is
  false when any exists. A binding criterion that misses its expectation fails its block as
  before. A non-binding one settles `DISPUTED` — run, graded, reported on the console, in the
  attempt summary, and in `score ac` — and is charged to nothing. Legal expected values are a
  staged suite's exit status, a status code, a value the criterion supplied as input, and an
  identifier-shaped contract token such as `"integer"` or `"application/json"`; illegal ones carry
  something that must be escaped correctly twice, once building the input and once stating the
  expectation.

  The failure this addresses is the dominant one in UAT. A criterion supplied the TOML literal
  string `'C:\\Users\\nodejs'`, whose backslashes a literal string preserves verbatim, then
  asserted the decoded value equalled `r"C:\Users\nodejs"`. The decoder was correct; the
  criterion was wrong; nothing downstream could tell which. That run cost 2.1M tokens and ended
  `degraded`. The adjacent basic-string assertion in the same criterion was re-typed too and
  happened to be right, which is the shape of the problem: a coin flip per assertion. Measured
  against the stored fixtures the rule admits 24 of 25 Toml criteria and 29 of 33 CommonMark
  criteria; the five it holds back are the one that failed wrongly and four renderer transforms
  whose output cannot be derived from their input and which a staged conformance suite already
  covers.

### Changed

- 2026-08-13: Drydock's own bookkeeping no longer blocks a release. `score` and `score release`
  report a dirty build directory, a missing Git code identity, and stale applied Blueprint
  specifications as warnings rather than blockers. The case that settled it: a run passed all 8
  Sea Trials and all 26 programmatic assertions, then failed the release with
  `BLOCKER: Build directory has uncommitted changes` — the uncommitted change being an SQLite
  file the project's own test suite created when Drydock ran it. Drydock ran the tests, the tests
  wrote a file, and Drydock refused the release because a file was present. The governing rule: a
  gate may only block on a fault domain it can distinguish, and a dirty worktree cannot
  distinguish a defective product from tidy housekeeping. Operators who relied on `score release`
  failing on an uncommitted build tree now read that condition from the warnings.

- 2026-08-13: The minimum-assertion gate is deleted. A story declaring a programmatic surface no
  longer has to carry at least two `=== AC ===` criteria, and `_MIN_ASSERTIONS_PER_STORY`, its
  imported-suite exemption, and the bare-`- None.` emission failure go with it. Quantity is not a
  gate: forcing a story to reach a count makes the model author criteria it has no oracle for, and
  every invented criterion is a fresh chance to predict an expected value wrongly. The Toml
  evidence is exact — 15 suite-bound criteria all passed, and 10 hand-authored criteria covering
  nothing the conformance suite did not already cover supplied 100% of the failures. Coverage is
  measured by an authoritative suite or by the project's own test suite, graded at the Sea Trials
  level. `drydock plan` no longer fails on a Blueprint whose acceptance section is empty.

- 2026-08-13: The release grader may reason toward `PASS` and may not reason toward `FAIL`.
  `prompts/score_release.md` (V5) states the asymmetric evidence rule: absence of evidence is
  `INCONCLUSIVE`, never `FAIL`, and a `FAIL` must cite a specific artifact that exhibits the
  failure. The guardrail special case is removed — a prohibition is judged by the same rules as
  any other criterion — along with the instruction never to infer that a guardrail held and the
  stale claim that `UNPROVEN` "fails the gate exactly as a breach does", which stopped being true
  when unproven guardrails became manual-verification attestations. That instruction was
  observably biasing the grader: a recorded run's rationale was a verbatim restatement of it.

- 2026-08-13: The authoring contract addresses tests to two destinations.
  `prompts/BLUEPRINTS_CONTRACT.md` (V12) separates story AC — few, gating, authored before the
  code exists, so every expectation in one is a prediction — from the project's own test suite,
  authored beside the finished code, where expectations are observed and coverage is unbounded.
  Patterns 1, 4, 6, 9, and 10 govern AC blocks; patterns 2, 3, 5, 7, and 8 are stated as suite
  discipline. The contract now also states what each criterion is worth — blocking, consultative,
  advisory, or void — so an author can aim: a hand-typed expectation does not merely risk being
  wrong, it demotes the criterion to advisory and leaves the story with no gate at all.
  `prompts/build.md` (V6) gains the matching obligation to grow the project's suite as it writes
  the code, including test isolation, so a test run leaves no residue in the build directory.

- 2026-08-11: A criterion that raises `TypeError` in its own frame reports UNVERIFIED and is not
  charged to the build. `TypeError` joins `NameError`, `SyntaxError`, and their neighbors in
  the malformed category now stored in `Rigging/acceptance_failure_taxonomy.json`: a criterion
  that dies on argument passing never reached the code under test, so grading it FAIL closed a
  block that no implementation could reopen. A build measures pass and fail verdicts; an exception
  in the harness is charged to the harness, stated by id in the block evidence and the build
  summary. Attribution remains by traceback frame — the same `TypeError` raised inside the built
  code is still a genuine red. The known trade: a `TypeError` a correct implementation would have
  avoided also stops gating, visibly rather than silently.

- 2026-08-12: Sea Trials are the sole input to the completion gate. `score` and `score release`
  report unclosed Manifest work as a warning instead of a blocker, so a release whose every
  required Sea Trial passes completes even when a story sits at `closed/failed` or `pending`.
  Both modules already documented this contract — "story acceptance is reported, never an input
  to the release decision" — while `blockers.append("Manifest work is not closed/verified: ...")`
  contradicted it, making a per-story acceptance criterion a release gate transitively: a failed
  criterion closes its story `closed/failed`, which failed the release. A TOML run passed all four
  required Sea Trials and the full external toml-test suite (205 valid, 474 invalid, 0 failed) and
  still scored `INCOMPLETE`, because one generated criterion asserted the wrong JSON shape and took
  four stories down with it. The backstop that Manifest closure stood in for — a contract satisfied
  by work nobody did — remains a blocker and tests the contract directly: a required Sea Trial with
  no implementation or proof coverage fails the gate. `drydock status --check` is unchanged and
  still reports the terminal pipeline state from Manifest closure, so the build loop continues to
  stop on unclosed work.

- 2026-08-13: Governed acceptance commands decide block and release state. `ACCEPTANCE.json` in
  the Target root declares a `full` gate and optional per-story `stages`, each an argv array
  Drydock executes directly. It is Commander-owned; no LLM-assisted command writes it, and
  `drydock uat` seeds it from the fixture's `acceptance` block so UAT and ordinary operation
  consume one target-level contract rather than diverging.

  This exists because authority cannot be inferred from an artifact the model wrote. The same
  model authors the criterion, its input, its expected value, and the code meant to satisfy them;
  when they disagree, nothing recovers which is wrong. A criterion declaring `Suite:` or naming a
  path under `sources/` proves nothing, because a model can type either string. So the oracle now
  comes from data outside the model-authored artifact, and Drydock runs the argv rather than
  inspecting a wrapper the model generated.

  Precedence: a governed gate outranks a model-authored criterion, and a model-authored criterion
  outranks nothing at all. Where a stage gate covers a story its verdict is the verdict and the
  criteria are diagnostic — the console reports criteria that stayed red where the gate passed,
  against the criteria rather than the product. Where no gate covers the story, a binding
  criterion is still the only evidence available and still fails the block; discarding it would
  leave a project without a conformance suite, which is most projects, with no failure signal at
  all. A story finishing under a declared contract but outside its coverage closes `implemented`
  rather than `closed/verified`, with an advisory saying so, because "verified" is a claim about
  an oracle. That distinction is drawn only for a project that has opted into governance.

  The gates run inside the repair loop, on every attempt, and their output is fed to the next
  agent call. A gate that reported only after the budget was spent would drive no repair at all —
  the block would simply fail with every pass unused — so a red gate is classified repairable and
  is the signal the loop steers by.

  `build_plan.FINISHED_STATES` lets `implemented` satisfy a dependency, so an ungoverned story no
  longer stalls the blocks behind it. Gate execution is classified three ways and the distinction
  is load-bearing: exit zero is a product PASS, a non-zero exit from a command that ran is a
  product FAIL, and an absent executable, timeout, signal, or unusable build directory is ERROR —
  evidence about the kit, never charged to the build. Each result records argv, exit code, stdout,
  stderr, duration, timeout classification, and a digest of the built tree, so a verdict names the
  artifact and the command that produced it. `drydock score release` runs the `full` gate and
  records it in `evidence/score-release.json`.

  The Toml fixture declares six stage slices of the installed toml-test suite plus
  `sh sources/full_test.sh` as the release gate, and stages a `stage_test.sh` that builds the
  decoder and runs one slice.

- 2026-08-13: `drydock uat` reports `execution_status` and `acceptance_status` separately, and the
  headline status passes only when both do. A product test failure is not an infrastructure
  error, but an infrastructure error must still stop a run reading as a pass — which a single
  status derived from the final command's exit code allowed whenever an orchestration failure or
  a skipped stage was followed by a weak command that happened to exit zero.

- 2026-08-13: An acceptance criterion that cannot execute no longer discards the plan. A single
  criterion that failed to compile raised `SpecificationError` from `drydock plan`, throwing away
  every Blueprint and Manifest artifact the run had produced — five LLM calls of correct work lost
  to one bad snippet, with no way to restart from where the run stood. The criterion was never
  dangerous: it raises in its own frame, which the runtime classifier reads as a malformed check
  and settles UNVERIFIED, so it gates nothing and costs its story nothing.

  The plan is now written, the defect leads the warning list, and each one becomes a blocking
  `DECISIONS.json` record against the owning story. `severity: blocking` gives both modes what
  they need from one mechanism: interactively the operator is asked whether the criterion is
  salvageable before that story builds, and under `--override` the run proceeds with the record
  intact for review. Bad stories and bad Sea Trials are outside Drydock's control; a bad
  acceptance criterion is generated by a command Drydock runs against a contract Drydock owns, so
  a pipeline that cannot process one cleanly is a pipeline defect rather than a modelling
  accident.

- 2026-08-13: `closed/implemented` joins the Manifest state vocabulary for a story whose work
  finished with no governed command able to judge it. It is terminal and satisfies a dependency,
  so an ungoverned story does not stall the blocks behind it, and it renders as `[unverified]`
  rather than `[done]`. The existing `implemented` state was not reused: it is a mid-flow state in
  the child-`ac` taxonomy meaning "built, acceptance not yet run", where a dependent must *not*
  build on it, and conflating "not verified yet" with "nothing will ever verify this" broke
  dependency scheduling in both directions. `drydock status --check` still counts only
  `closed/verified` toward completion, because runnability and completion are different
  questions.

### Removed

- 2026-08-13: The acceptance prediction layer is deleted — 2664 lines. Six analyzers in
  `proof_integrity.py` predicted from a criterion's text that it would fail: mis-authored
  literals, unbound names, shell escapes, swallowed output, runner-tally vocabulary, and
  staged-script invocation. Each was added in response to one observed failure, the space of bad
  assertions is not enumerable, and every entry carried its own false-positive rate against
  legitimate snippets. Two had already been retracted after they began failing fixtures that had
  passed for weeks; accumulating the rest is how the fixtures degraded. Removed with them: the
  plan-time authoring and staged-setup fatals, the unbounded-suite and zero-skipped fatals, the
  build-time quarantine and its advisory Manifest finding, and the `validate specification`
  advisories, which now report the one surviving authoring signal instead. Vacuity analysis
  (`analyze_proof`) and the compile gate survive: the first only withholds credit rather than
  assigning blame, and the second asks whether a criterion parses, which is a fact about the file
  rather than a judgement about the assertion.

- 2026-08-13: `drydock score release` and `drydock build score` no longer compute a technical
  score. The seven model-emitted 0..100 dimensions, their average, the `< 80` and `< 60`
  completion blockers, and the `_coverage_penalty` discount are gone, along with the `score` and
  `dimensions` fields on `BuildScoreResult`, the `technical_score` key in the evidence record
  (`schema_version` 4), and the "Technical quality" table in `SCORECARD.md`. The gate is now every
  required Sea Trial's verdict and nothing else, so a project satisfying every criterion its
  Commander wrote can no longer be refused by an opinion — or by a different opinion on the next
  run. A release gate has to be reproducible. The model still judges `evidence` and `llm`
  criteria, which are the criteria that genuinely need judgement; `proof` and `measurement`
  criteria remain deterministic. This also removes the divergence in which `score release` applied
  a hardcoded rubric while `build score` resolved the `SEA_TRIALS.md` policy block.

- 2026-08-13: An agent's `AC_BROKEN` claim no longer terminates the repair loop. A criterion
  reaches the point of failing only when its oracle is derivable, so the agent's claim that the
  criterion is at fault is the less likely explanation, and a build in which the party under test
  can end its own examination is not a gate. The claim is still detected and reported as
  "recorded, not accepted"; the loop keeps its budget and stops on the ordinary stall rule.

### Fixed

- 2026-08-13: A governed acceptance gate exiting 2 is a kit fault, not a product failure.
  `run_gate` classified every non-zero exit as `FAIL`, so a gate script reporting a usage error —
  an unset variable, a bad argument, a conformance harness that is not the version the run named —
  was recorded as the product failing a test that never ran. Exit 2 now classifies as `ERROR`
  alongside an absent executable, a timeout, and a signal: it does not block, it is never charged
  to the build, and `score release` reports it as `Governed acceptance gate could not run` rather
  than `failed`. This follows `diff` and `grep`, where 1 is a legitimate negative answer and 2 is
  trouble, and it is the contract Drydock's own commands already state. A Commander-supplied
  command that means something else by 2 is now read as a kit fault, which is the safe direction:
  a kit fault never fails a release.

- 2026-08-13: The Toml UAT fixture's conformance harness runs. `sources/run_conformance.sh` probed
  the suite's identity with `toml-test -version`, which is not a flag the harness accepts: it
  printed general help, exit 0, and the version guard compared that help text against the expected
  `v2.2.0` and refused to run. The probe now uses the `version` subcommand, as
  `setup_harness.sh` already did. Every governed gate in the fixture routes through this script,
  so the failure surfaced as three failed layout acceptance criteria, `test` exiting 2, and a
  release blocked on `full: FAIL (exit 2)` — none of which concerned the decoder under test. The
  guard itself is unchanged: a harness that is genuinely the wrong version is still refused.

- 2026-08-12: A missing project-local executable in a pre-build acceptance observation no longer
  parks a finished story on an unanswerable authorization. `_MISSING_EXECUTABLE_RE` in
  `acceptance_requirements` excluded `/` from its capture but not the newline, so stderr naming a
  relative path — the artifact under construction, absent by definition before the build — forced
  the engine to backtrack past its own quotes and capture the following traceback as the tool
  name. `discover_missing_requirement` returned `AcceptanceRequirement("executable", <traceback
  text>, "test")`, which `record_requirement_decision` persisted as a blocking `DECISIONS.json`
  record; `synchronize_manifest_question_gates` then re-asserted that gate on every later pass and
  dragged the story back to `blocked/questions` from `closed/verified`, after the repair pass had
  driven both its checks green. A CommonMark run finished 655 of 655 conformance examples and its
  sole project acceptance criterion, then scored `INCOMPLETE` on `Manifest work is not
  closed/verified: block-quotes`. The capture is now confined to the failing line and
  `discover_missing_requirement` returns a requirement only for a bare command token, applying the
  rule `visible_external_usage` already used for declared commands: an executable starting with
  `.` or `/` is project-local, not external tooling a Commander must authorize. A genuine missing
  tool is still discovered and still blocks.

- 2026-08-11: `drydock plan` integrity validation reads acceptance criteria in the format the
  planning prompt mandates. `planning_session._acceptance_status` counted Markdown ` ```python `
  fences, which the delimited `=== AC <id> ===` container replaced, so every story scored zero or
  one criterion however many it actually carried and `plan` failed its own `Plan integrity check`
  with `N Programmatic Acceptance assertion(s)` on output that satisfied its own template — a
  CommonMark run wrote 10 of 10 Blueprints carrying 2 to 5 criteria each and was rejected at the
  gate. Every plan-time inspection of acceptance content now goes through
  `acceptance.parse_programmatic_acceptance_text`, the same authority the build engine executes,
  via a single `_acceptance_checks` helper: the criterion count, the imported-suite exemption
  (`_drives_external_suite`), and the unbounded-suite gate (`_invokes_unbounded_test_suite`).
  The unbounded-suite gate now judges one parsed criterion at a time against its own `Suite:`
  declaration instead of guessing scope from a line window, which had misread any proof body
  containing a fence or a heading. A test asserts the shipped `BLUEPRINTS_CONTRACT.md` example
  clears the validator's own `_MIN_ASSERTIONS_PER_STORY` minimum.
- 2026-08-11: A truncated diagnostic states what it hid. `errors._safe_detail` cut at a character
  offset, so an integrity failure enumerating one finding per story ended mid-word and gave no
  indication that further findings existed. The cut now lands on a line boundary and appends
  `… (N more lines truncated)`. The criterion-count message also names the specification files it
  measured rather than referring to "its implemented spec(s)".
- 2026-08-11: `drydock plan` no longer rejects every Blueprint batch that carries an acceptance
  criterion. The `=== AC <id> ===` proof block introduced with the delimited-criterion container
  reuses the `=== NAME ===` line grammar the artifact envelope already used for whole files, and
  the envelope parsers are flat — so a nested proof delimiter was read as an artifact boundary,
  orphaning its `=== END AC <id> ===` marker and failing the batch as `Rejected: malformed
  artifact response`. Because `BLUEPRINTS_CONTRACT.md` instructs the model to place criteria
  inside the Blueprint, every batch for every project failed deterministically and no retry
  budget could recover: a CommonMark run accepted `TOPOLOGY.md`, then rejected all three Stage 2
  passes with 0 of 19 Blueprints written. The envelope grammar now reserves the `AC` namespace
  via `artifact_blocks.RESERVED_BLOCK_NAMESPACE`, applied to every envelope pattern in
  `artifact_blocks`, `planning_session`, and `refit`; an artifact is a file, and no file is named
  `AC something`. A test parses the worked example out of the packaged `BLUEPRINTS_CONTRACT.md`
  and asserts it round-trips as one artifact holding two criteria, so the format the prompt
  mandates and the format the parser accepts can no longer drift apart. The guard covers every
  envelope pattern, not only the two that parse the response: `_HEADER_ANYWHERE_RE` decides
  whether a parsed body absorbed another artifact, and `plan_shape` measures response shape, so
  a Blueprint could parse cleanly and still be discarded as damaged. The reserved-namespace
  pattern absorbs an optional `END` itself, because a pattern spelling the end marker as
  `(?:END )?` backtracks that group to empty and otherwise matches `=== END AC <id> ===` under
  the name `END AC <id>`.

### Changed

- 2026-08-14: `drydock build` and `drydock uat` now use one repair policy per build block: six
  repair passes after the initial call, with one flat pass tolerated and two consecutive passes
  without deterministic acceptance progress ending the block. Interactive builds no longer stop
  earlier or carry a smaller repair budget than UAT runs.
- 2026-08-11: A UAT report states when the run happened in local time. The per-kit `README.md` and
  the aggregate summary carry a `Ran:` window rendered from `environment.started_at` /
  `finished_at` in the reader's timezone, alongside the UTC run id. A run id alone reads hours
  away from the wall clock the operator watched the run on, which made a report impossible to
  match to a session by eye.
- 2026-08-11: A build block's repair loop is bounded by progress rather than by a fixed call
  count. A pass that raises the deterministic acceptance score — a newly green criterion, or a
  non-regressing case tally that improves — earns another pass; consecutive passes that move
  nothing end the block. `config.max_consecutive_stalls()` is 1 interactively, so the first flat
  pass still ends a block, and 2 under `drydock uat`, where a single flat pass is often noise
  between two productive ones. This replaces `repair_through_stall()`, under which a UAT ignored
  stalls entirely and always spent its whole budget. The stall count is now the only behavior
  `DRYDOCK_UAT` changes inside the repair loop; no error class is suppressed for UAT that would
  gate interactively, and a test enforces that `is_uat_run()` has no other consumer.
- 2026-08-11: `drydock uat` allows a block 6 repairs, up from the interactive default of 3, and
  accepts `--repair-attempts` to change it. The bound is per build block, not per story: the
  repair loop runs once per `BuildUnit`. The previous fixed budget cut off converging work — in
  the CommonMark UAT, block 3 went 3/8 → 4/8 → 4/8 → 6/8 criteria and 83 → 101 → 109 → 126
  conformance cases across four calls without one stalled pass, exhausted its budget while still
  climbing, and left blocks 4 and 5 unbuilt because the build frontier is strict Manifest order.
  `full_test.sh` was therefore never written and the run's own test command failed to open it,
  so the conformance measurement the UAT exists to produce was never taken.
- 2026-08-11: A repair loop stops when every failing criterion is a kit fault — malformed check,
  absent declared tool, unavailable acceptance environment, exhausted memory or time — and names
  the ids. A repair pass rewrites the implementation, never the criterion or the machine it runs
  on, so these can never be driven green and the budget spent on them was always wasted.
  `acceptance.TERMINAL_FAILURE_PREFIXES` and `is_terminal_check_failure()` hold the
  classification beside the prefixes they name.
- 2026-08-11: A block that passes its acceptance only after more than four calls reports a
  `sizing:` advisory naming the block and its call count. Repeated repair to reach green is a
  decomposition signal about the Manifest rather than a build failure, so it is reported and
  never gated.
- 2026-08-11: Programmatic Acceptance criteria are authored in explicitly delimited
  `=== AC <id> === … === END AC <id> ===` blocks, replacing the inferred Markdown boundaries.
  The previous container extracted criteria with a non-greedy ` ```python ` regex, so a proof
  body containing a Markdown fence truncated at the inner fence and discarded the criterion
  after it; the fragment then raised `SyntaxError` in its own frame, which classifies as a
  malformed check, settles UNVERIFIED, and costs the story nothing — the criterion stopped
  gating and its story still closed verified. The criterion id now lives in the delimiter rather
  than being slugified from a nearby heading, declarations are the leading `Key: value` lines,
  and the body runs verbatim to the end marker, so a fence, a `##` line, a `###` line, or a
  `Requires:` line inside a string is inert. Blocks are scanned document-wide, so a `##` line in
  a proof can no longer close the `## Programmatic Acceptance` section. An unterminated block, a
  mismatched end id, a stray end marker, and a duplicate id are hard errors. The Markdown form
  still parses, so Blueprints authored before this change keep working. `BLUEPRINTS_CONTRACT.md`
  states the new form.
- 2026-08-11: `drydock score ac` reports a fourth verdict, `~ PREPASSED`, for a criterion that
  runs green but was also green at its block's baseline — before that block's code existed. Such
  a criterion has not shown that the story's work is what satisfies it; in the CommonMark UAT
  four of them (`leaf-blocks`, `containers`, `character-line-endings`, `character-insecure`)
  selected no conformance examples, exited zero, and printed `✓ PASS`, making the reported score
  12/28 where the proven score was 8/28. The build records its per-block baseline to
  `evidence/prepassed-acceptance.json` because only the build takes a baseline. It is reported
  and never gated: a criterion that exercises nothing and one measuring a deliverable that
  legitimately already existed are indistinguishable from the baseline alone, so failing on it
  would break correct builds. `PREPASSED` does not affect the exit code.
- 2026-08-11: A Programmatic Acceptance criterion that does not compile now fails
  `drydock validate` and `drydock plan` instead of warning. Whether a criterion is Python is a
  fact about the file, in the same class as a container parse error, and it is deliberately
  separate from the unsatisfiability analyzers, which stay advisory because they predict that a
  well-formed assertion cannot pass and that prediction carries a false-positive rate.
- 2026-08-11: `group_blocks` bounds a build block by the number of acceptance criteria it owes
  as well as by assembled token cost, capped at `DEFAULT_BLOCK_ACCEPTANCE_LIMIT` (5). Cost alone
  is a poor proxy for how much a block has to prove: the cheapest merge on offer is often two
  stories that each carry a full conformance section. In the CommonMark UAT that merged leaf
  blocks (4 criteria) with containers-and-lists (4) into one block owing 8 against a flat repair
  budget of 3; it reached 6, stopped third of five, and starved every block behind it, so the
  run produced no `full_test.sh` and every downstream verification step failed as a consequence.
  A story whose own criteria exceed the ceiling still builds as its own block — a marker, never
  a refusal — matching the existing `limit_tokens` behavior. Previously observed block shapes
  are unchanged.
- 2026-08-11: Imported source material reaches a prompt byte-for-byte. `prompt_chunks` sliced
  files at raw character offsets, cutting 15 of 17 chunk boundaries in `spec.txt` mid-line and
  delivering each severed line as two unrelated lines in two separately fenced blocks; the
  fenced-part builders in `prompt_assembly` called `.rstrip()`, destroying trailing spaces that
  are a CommonMark hard line break; and they emitted a fixed three-backtick fence against a file
  carrying 1427 lines that open with three or more backticks, including 655 thirty-two-backtick
  example openers that closed the wrapper early. Chunking now splits on existing line
  boundaries, and a fence is always longer than the longest backtick run in the body. Content
  without a three-backtick run still gets exactly three, so existing prompts — and their cache
  prefixes — are unchanged.
- 2026-08-10: UAT lifecycle inputs are explicit and reproducible. Kits may declare `sea_trials`
  and `technology_stack` paths in `uat.json`; discovery applies the same containment and existence
  checks as source/update paths, validates both artifacts before a run, seeds them after `init`,
  and preserves them under each run's `inputs/` proof bundle. Undeclared root filenames are no
  longer discovered implicitly, so omission delegates artifact generation to `analyze`. The three
  shipped kits now keep both declarations under `inputs/`, and generated reports inventory and
  link that bundle. CommonMark now has one blocking, deterministic project criterion: the complete
  supplied conformance suite, run by `sh full_test.sh`, must exit successfully.

- 2026-08-10: Every artifact a UAT report links is reached through a styled viewer instead of raw
  text. A report previously handed the reader off to the browser's own rendering the moment they
  opened a log, a transcript, or a Markdown document. `build_case_kit` and `write_kit_index` now
  generate a viewer page per linked text artifact under `view/`, mirroring the artifact's path,
  sharing one generated `assets/kit.css`: Markdown is rendered, anything else is shown as source,
  and each viewer links its raw file and the report it came from. Rendering is done by a new
  dependency-free `drydock.markdown_render`, which supports headings, fenced code, GitHub tables,
  nested lists, block quotes, rules, and inline markup, and keeps consecutive `Field: value` lines
  on their own lines so Drydock's typed artifacts survive rendering. `view/` and `assets/` are
  generated output: excluded from `SHA256SUMS` and the evidence manifest, and replaced on every
  rebuild. A published kit grows by roughly the size of its text artifacts.

- 2026-08-10: A UAT kit's `index.html` is a project page, and every completed run refreshes it.
  The kit landing page previously listed only the runs and hardcoded links to `README.md` and
  `uat.json`. It now inventories the governed documents actually present at the kit root
  (`SEA_TRIALS.md`, `TECHNOLOGY_STACK.md`, `USER_NOTES.md`, `LICENSE`, and any other kit file,
  excluding dotfiles), lists the `sources/` and `updates/` bundles with sizes, and links the newest
  run above the run table. A kit only ever links what it ships, so the page stays valid when
  published as its own repository. `drydock uat` now calls the new
  `uat_report.write_kit_index(<kit>)` after each run, so a run appears on its project page without
  a separate `drydock uat --report`; `--report` still rebuilds every run receipt and the page.

- 2026-08-10: An unproven project guardrail qualifies a release instead of failing it.
  `drydock score release` and `drydock build score` previously blocked completion on a guardrail
  whose verdict was `UNPROVEN`, conflating "evidence showed the prohibition violated" with
  "no evidence settled it either way". Only `BREACHED` blocks now. An unproven guardrail is
  reported as an attestation — a named check a human owes before release — and the gate reports
  a third state, `COMPLETE — MANUAL VERIFICATION REQUIRED`, exiting 0. Both scorers emit a new
  `attestations` list and `qualified` flag in `evidence/score-release.json` and
  `evidence/build-score.json` (`schema_version` 2 → 3), `SCORECARD.md` gains a
  `## Manual verification required` section, and the CLI prints `ATTESTATION REQUIRED:` lines
  distinct from `BLOCKER:`. `drydock uat` harvests the list from the Target's score evidence into
  `result.json` and renders it in the run `README.md` and `index.html`; run status is unchanged,
  because an unproven prohibition was never a failure of the run. Related: `score release` no
  longer counts a proof-verified guardrail toward required implementation/proof coverage, which
  restores the rule that guardrails require no story or proof reference. Guardrails are now
  graded on what their author claimed about them: `Verification: evidence` or `llm` declares the
  prohibition unprovable and carries no weight in `acceptance_criteria_coverage`, while
  `Verification: proof` or `measurement` declares it provable and is graded like any other
  assertion, so leaving it unbound scores as model opinion until a Programmatic Acceptance
  `Sea Trials:` reference reaches it. The motivating case was a ReadingList UAT run that built and
  tested clean, passed 27 of 27 acceptance criteria, and was failed at the release gate solely
  because no acceptance check declared `Sea Trials: st-003`.

- 2026-08-10: A story whose acceptance criteria were quarantined closes `closed/failed`, not
  `closed/verified`. Quarantine excludes a criterion from grading so no repair call is spent on
  something no implementation can satisfy, but the criterion was *removed*, not satisfied —
  closing the story verified counted it toward `manifest.verified`, which release scoring gates
  on, so a Blueprint defect could buy a release for a story nothing verified. The story now
  carries a `UNVERIFIED: acceptance criterion defective: <ids>` finding naming the Blueprint as
  the defect rather than the implementation, and the step result fails to match. `--ungate` does
  not recognise the marker: it records an operator decision to release a real red, while this
  one records a defect only a Blueprint repair can clear. `drydock uat` no longer runs its
  refit stages after a degraded build — a refit over a terminal partial build measures nothing,
  and its required steps could raise and rewrite the run as `failed`, destroying the degraded
  verdict. The staged-asset invocation rules moved from `prompts/plan_create.md` to
  `prompts/BLUEPRINTS_CONTRACT.md` so every prompt that authors or rewrites Programmatic
  Acceptance carries them.

- 2026-08-10: Three further classes of unsatisfiable acceptance criterion are caught
  statically, closing the defect family that failed the Toml UAT build on five consecutive
  runs. `proof_integrity.analyze_invocation` reports an `env=` dict literal carrying no
  `**os.environ` unpacking: it replaces the child environment rather than extending it, so the
  check runs with no `PATH` and grades a missing tool. A new `analyze_staged_invocation` reads
  the staged asset a criterion invokes, extracts the environment variables the asset's own
  unset-guard exits on, and reports a call that omits one — the requirement comes from the
  script, not from configuration, so the rule holds for any harness the Analysis stages. A new
  `analyze_shell_escapes` reports `printf '%s'` handed arguments containing `\n`: the format
  copies its argument verbatim, so the program under test is graded on input the author never
  wrote. `plan` strips all three, and `plan_create.md` now states the staged-asset invocation
  contract so fewer are authored in the first place.

- 2026-08-10: An unsatisfiable acceptance criterion is quarantined at build time rather than
  refusing the build. `build` previously raised `SpecificationError` and exited 1 on the first
  such criterion, which is unrecoverable in an unattended run: a repair pass may not rewrite a
  staged acceptance asset, so every rerun failed identically. The criterion is now excluded
  from the graded set, named on the console and in the failure report under `quarantined:`,
  and carried on the step result as `quarantined_acceptance`. A criterion that proved nothing
  no longer fails the block that owns it, and a Blueprint defect is no longer reported as an
  implementation defect.

- 2026-08-10: `drydock uat` continues past a failed build and reports the run as `degraded`
  instead of aborting it. A build that exhausts its repair budget has reached a terminal
  state, and the partial application, the scores over it, and the test command's verdict are
  the only record of how far Drydock got — discarding them lost the measurement the run
  exists to take. `UATResult` gains a `degraded` tuple naming each stage that fell short;
  `result.json`, the run receipt, and the kit index render `DEGRADED` as its own verdict,
  neither a pass nor a failure. A clean build whose test command fails is still a failed run,
  and its scores now run before the verdict is recorded.

- 2026-08-10: `proof_integrity.analyze_output_assertions` now reads the regular-expression form
  of an output assertion, not only `in` / `not in` comparisons. Its own remediation advice
  recommends rewriting a pinned tally as `re.search(r"\b0\s+failed\b", result.stdout)`, which
  moved the assertion into a call none of the existing rules could see. Two defects are caught
  in that form: a pinned nonzero count (`re.search(r"\b205\s+passed\b", ...)`) is reported as a
  hardcoded tally, and requiring a count of errors, skips or warnings in captured stdout
  alongside an exit-status assertion is reported as a *speculative tally* — only passes and
  failures are reliably tallied, and a runner with none of the others prints no such line at
  all, so `re.search(r"\b0\s+errors?\b", ...)` is false on a clean run. Both are fatal: planning
  strips the criterion and a build against an already-authored one refuses to start.
  `prompts/BLUEPRINTS_CONTRACT.md` no longer instructs the planner to require zero errors on a
  scoped suite or zero skips on the terminal full suite; the failure count is the only tally an
  assertion may require.

- 2026-08-10: A programmatic-acceptance failure report carries the output the check printed.
  The Block → Story → AC chain stated the failing assertion and the exit code but not the
  runner's own account of the run, so a reader could not distinguish a broken assertion from
  broken code without opening the evidence file. Up to twelve lines of captured stdout now
  follow the assertion under `observed output:`. The terminal renderer for a post-LLM failure
  also stops reflowing indented lines, which had been splitting the failing assertion across
  two lines mid-regex.

- 2026-08-09: Every surface that reports token usage — the per-call console line, the
  `drydock build` report table and its totals, the UAT run summary, and the UAT receipt —
  states `cached` and `uncached` instead of a total input with a cached subset. That is the
  split providers bill, so the two numbers a reader cares about no longer have to be derived
  by subtraction. Cache-hit rate and the Claude cache-write figure are unchanged.

- 2026-08-09: A UAT run identifier is now `20260809.204459` (UTC, to the second) rather than
  `20260809T204459.901240Z`. Two runs of one kit cannot start within the same second, so the
  microseconds bought nothing and cost legibility. Run ordering compares identifier digits, so
  directories written under the retired format still sort chronologically beside new ones and
  `--run` continues to accept them.

- 2026-08-09: The UAT receipt files the run's evidence as four directory trees — Build,
  Evidence, Sources, Workspace — one per directory a run writes, with paths stated relative to
  the kit (`runs/<run-id>/…`) and unprocessed output (`evidence/provider_raw/`,
  `evidence/prompt_outputs/`, `workspace/logs/`, `*.raw.jsonl`) marked `raw`. The workspace is
  now inventoried whole rather than only the Target subtree, so `SHA256SUMS` covers what the
  run actually left behind. Digests moved out of the page and stay in `SHA256SUMS`. A command
  or LLM result renders as an `OK` or `FAIL <code>` stamp instead of a printed exit code, the
  header names the directory the build delivered into, and the kit register carries the model
  each run used.

- 2026-08-09: The Toml UAT kit ships its scoring entry point instead of asking the build agent to
  transcribe it. `sources/full_test.sh` is a declared kit source, staged and hash-verified like the
  conformance harness it invokes, and `uat.json` scores with `sh sources/full_test.sh`. Staged
  assets land under the build directory's fixed `sources/` root, which is why the path moved off
  the application root. The kit loses an entire LLM block, the "path corrections are the only
  permitted edit" escape hatch, and the surface on which a build could weaken its own score — a
  modified entry point is now restored before grading rather than caught by review. The kit's
  Definition of Done no longer asserts absolute case totals (`210 valid, 499 invalid`, stale against
  the 205/474 the installed suite supplies); it requires every supplied case to pass with zero
  failed, errored, and skipped. `drydock uat` also asserts that a kit declaring a `sources/` scoring
  command ships that asset. The CommonMark kit keeps an agent-authored `full_test.sh`: its command
  names the program the build chooses, so it cannot be a static asset.

- 2026-08-09: `drydock uat --report` renders the run receipt (`uat/<kit>/runs/<run>/index.html`
  and the kit landing page) as a printed acceptance report rather than a web page: a white
  monospaced sheet with the Drydock mark inlined as a data URI, an APPROVED or REJECTED verdict
  stamp keyed to the recorded status, and the evidence filed into tabs — Steps, Error, LLM, Code,
  Sources, Blueprint. The Error tab appears only when a command exited nonzero, the LLM tab only
  when the run recorded an execution, and command logs are no longer inventoried a second time
  under their own table. A captured stream is linked only when it holds bytes, so an empty
  `stderr` renders as a dash: `stderr` carries provider progress on successful commands and its
  existence never implied a failure. Every evidence link opens in a new tab. Rendering only —
  the inventory, `SHA256SUMS`, and `result.json` contracts are unchanged, and an old run can be
  re-rendered in place.

### Added

- 2026-08-09: A build agent can end its own repair budget with an `AC_BROKEN: <check-id>` line
  when a declared acceptance criterion cannot pass however the code is written. Staged acceptance
  assets are restored before grading, so the agent is structurally unable to repair a broken
  assertion; without an escape hatch it spends every remaining call re-failing identically. The
  token is read from the response independently of `RESULT`, because the case that motivates it —
  correct code failed by a wrong assertion — is one the agent may legitimately report as `SUCCESS`.
  An unrecognized or absent id claims every currently failing check; a check that passed cannot be
  claimed. Drydock stops with `stop_reason` "acceptance criterion reported defective" and directs
  the operator to the assertion's source specification. The pre-existing prose inference remains as
  a fallback, now also reading `BLOCKERS` and recognizing "always fails", "cannot be satisfied",
  and "incorrectly reject".

- 2026-08-09: `proof_integrity.analyze_output_assertions` rejects an acceptance snippet that
  asserts a literal never appears in a command's captured output when that literal is tally
  vocabulary (`failed`, `error`, `skipped`, `warning`, and inflections). A test runner prints
  `N passed, M failed` on a clean run, so `assert "failed" not in result.stdout.lower()` is false
  on correct code and no implementation can move it. These fail `drydock validate` and are dropped
  as unsatisfiable before a build spends a repair pass. A substring assertion on any other literal
  beside an exit-status assertion warns instead: the exit status is already the verdict, and the
  substring models an output format the author may never have observed. Assertions tracked through
  a binding (`out = result.stdout`) are covered; a substring check that is the proof's only gate is
  left alone.

- 2026-08-09: `drydock uat --stage <stage>` resumes an existing run instead of starting a new one,
  re-entering the lifecycle at `import`, `analyze`, `plan`, `build`, `refit`, `test`, or `score`.
  A run directory already owns its Drydock workspace and build tree, so a lifecycle that failed
  late is retried without paying for the earlier LLM passes again. The newest run of each selected
  kit is resumed by default; `--run <run-id>` selects an older one and requires `--stage`. Resuming
  past `import` leaves the source bundle as the prior attempt left it, evidence log numbering
  continues past the existing files rather than overwriting them, and the earlier attempt's
  commands are carried into `result.json`. A resumed run records `resumed_from` and its receipt
  states the re-entry stage rather than claiming every command exited `0`, because a resumed run
  reuses prior state and is not a clean-room measurement. Each stage declares the Target artifact
  it consumes, so a resume into a stage the prior attempt never reached fails immediately with the
  missing artifact and the stage that produces it — `--stage build` after a failed `plan` reports
  the absent `MANIFEST.md` and directs the operator to `--stage plan` rather than running a status
  check and a completion gate to discover the same thing.

- 2026-08-09: A UAT fixture declares its own technology stack by shipping a `TECHNOLOGY_STACK.md`
  in its fixture directory. `drydock uat` seeds that file into the Target between `init` and
  `analyze`; because `analyze` never overwrites an existing Technology Stack, the declaration
  becomes the decision of record and `plan` reads it as the sole stack authority. The stack is
  configuration rather than a command-line argument — there is no `--stack` flag. Fixture
  discovery validates the declaration against the Rigging catalog and fails with exit `2` on an
  unknown Rigging filename or an empty table, so a typo surfaces before the run spends tokens. A
  fixture with no such file behaves exactly as before and lets `analyze` propose the stack.

- 2026-08-08: `drydock uat` now emits a self-contained, verifiable proof kit for every run. Each
  project case gains an `index.html` receipt that links every lifecycle command to its own captured
  stdout and stderr, quotes the failing stage's output verbatim, and tabulates each LLM execution
  beside the exact prompt, model output, and raw provider transcript that produced it. A run-level
  `index.html` states the aggregate verdict and links to each case. `SHA256SUMS` covers the
  delivered code, imported sources, Blueprint, command logs, and LLM evidence, so a checked-in kit
  is validated with `sha256sum -c SHA256SUMS`. The verdict is derived from recorded exit codes, so
  a failed lifecycle renders as `FAILED` and cannot present as a clean run.
- 2026-08-08: `drydock uat --report [<run>|all]` rebuilds the proof kit for a completed run without
  re-executing it, which also backfills receipts for runs recorded before this capability existed.

### Changed

- 2026-08-09: `drydock uat` streams each child command's output to the console as it is produced
  instead of reporting one stage name per step. The runner replaced `subprocess.run(capture_output)`
  with a `Popen` tee: raw bytes go to the evidence log unaltered while decoded text reaches the
  terminal on every read, so a run that takes minutes per step shows progress rather than silence.
  Child output is reproduced faithfully — carriage-return redraws and lines without a trailing
  newline pass through, since the `│` (stdout) / `!` (stderr) gutter is inserted only at a line
  start. Each step is framed by a header carrying the kit, stage, argv, and wall clock, and a
  footer carrying the exit code and elapsed time; the run ends with the per-kit summary that was
  previously written but never displayed. Children run with `PYTHONUNBUFFERED=1` so pipe buffering
  cannot withhold output until exit. `--quiet` restores the previous stage-name-only reporting.
  Evidence content is unchanged either way.

- 2026-08-09: The TOML conformance fixture is a Go project. Its `TECHNOLOGY_STACK.md` names
  `go.md` and `common.md`; `full_test.sh` compiles `./cmd/toml-decoder` as a step distinct from
  scoring, so a compilation failure and a conformance failure are separable in the evidence; and
  `run_conformance.sh` now requires `DECODER` instead of defaulting to a Python command, which
  removes the implementation language from the scoring instrument. The Go toolchain was already a
  prerequisite because the upstream `toml-test` harness is written in Go, so the deliverable and
  the instrument now share one toolchain. `Rigging/stack/go.md` sets Go 1.22 as a hard floor with
  a verification snippet and instructs the builder to stop and report a blocker rather than
  degrade the code to compile on an older toolchain; 1.22 changed loop-variable scoping, so an
  older compiler changes behavior silently rather than failing to build.
- 2026-08-08: UAT reports are portable. `result.json`, `summary.json`, and `SUMMARY.md` now record
  paths relative to the run or case directory instead of the generating machine's absolute paths,
  and `evidence/manifest.json` carries the artifact inventory and run provenance. Each result
  records the Drydock version, repository commit, provider, model, effort, Python version, platform,
  and start and finish timestamps. Regenerable `__pycache__` and tooling caches are pruned before a
  kit is inventoried, so a run directory can be committed to another repository as delivered
  evidence.

### Removed

- 2026-08-08: Deleted the last executable remnants of the Blueprint Markdown question surface. The
  Build Compass no longer parses `## Questions` sections or renders per-question "Save answer"
  controls, so the compass step card presents a Blueprint source editor directly instead of hiding
  it behind a question group that only appeared for documents containing questions. The retired
  `POST /api/build-question/answer` and `POST /api/plan-feedback` endpoints, which returned HTTP 410
  since the `DECISIONS.json` cutover, are gone along with their request models and client scripts;
  callers must use the `DECISIONS.json` endpoints. The `drydock.questions` and
  `drydock.plan_feedback` modules, whose only remaining consumers were that dead renderer and their
  own tests, are removed. `drydock.question_gates` — which projects blocking `DECISIONS.json`
  records onto Manifest story states — is unaffected.

### Fixed

- 2026-08-10: `sha256sum -c SHA256SUMS` verifies a UAT run receipt cleanly. `build_case_kit`
  rewrote `evidence/manifest.json` after taking its checksum, so verification reported that one
  file `FAILED` on every kit Drydock has published. The manifest is now written before the
  inventory is sealed and re-hashed afterwards, and it no longer lists its own digest among its
  artifacts — a file cannot index itself.

- 2026-08-09: A build step whose observed file delta is empty no longer skips acceptance grading
  when the block declares Programmatic Acceptance. `_written_files` compares content hashes, so a
  step that rewrites an already-correct deliverable with identical bytes reported zero changes and
  was classified `no build files written` — a terminal status that short-circuited the acceptance
  run, which in turn discarded the agent's `AC_BROKEN` report, the one signal that ends a repair
  loop against a criterion nothing can satisfy. The classification is now advisory whenever the
  block has criteria to measure: the deterministic gate decides, and a defective-criterion claim
  stops the loop on the first call instead of consuming the budget behind a misleading cause. With
  no criteria, an agent that changed nothing still fails terminally. Observed on `drydock uat Toml`,
  where a correct decoder and a correct scoring script were reported as an unpersisted artifact.

- 2026-08-09: `proof_integrity.analyze_output_assertions` now also rejects the positive form of the
  tally defect: an acceptance snippet requiring an exact runner tally to appear in captured stdout,
  such as `assert "valid tests: 210 passed, 0 failed" in result.stdout`. The case count belongs to
  the installed suite rather than to the specification, and runners column-align their summaries
  (`valid tests: 205 passed,  0 failed` carries two spaces), so the literal is false on correct code
  as soon as either drifts, for two independent reasons. The defect is fatal: `drydock validate`
  reports it, planning strips the criterion, and a build refuses to start rather than spend its
  repair budget on it. Only a literal carrying a tally is rejected — an ordinary required substring,
  the same literal asserted against stderr, and a whitespace-tolerant regular expression are all
  left alone. `prompts/BLUEPRINTS_CONTRACT.md` now teaches `re.search(r"\b0\s+failed\b", ...)` in
  place of `assert "0 failed" in result.stdout`.

- 2026-08-09: The Programmatic Acceptance declaration gate no longer treats the POSIX shell and the
  Python interpreter as undeclared external tooling. `visible_external_usage` flagged every literal
  `subprocess` executable, so a conformance check that shelled out through `sh` failed planning with
  `undeclared executable=sh` even though `shutil.which` would have authorized it instantly. `sh`,
  `bash`, `env`, `python`, and `python3` are now baseline substrate and require no `Requires:`
  declaration; every other executable still must be declared and Commander-authorized.

- 2026-08-09: Build-asset staging is now closed over what the staged files reference. Previously
  only the sources the Analysis marked `stage` reached `<build_dir>/sources/`, so a conformance
  harness whose declared dependency was classified `prompt-only` arrived on disk without the
  installer it shells out to, and the build failed at its first story with a missing input.
  `declared_build_assets` now scans each staged file for the names of its non-Markdown siblings
  and stages the transitive closure, enforcing in code the rule `prompts/analyze.md` had asked of
  the model. Markdown remains prompt material and is never staged. Scoring inherits the closure
  unchanged, since staging and score-time verification read the same declaration.

- 2026-08-09: The build prompt now names the files present on disk in the build directory. The
  staged set was computed but never surfaced, leaving the agent to infer its own working directory
  from imported prose; an agent that read "the imported source files are placed in a `sources/`
  subdirectory" reported its own fenced Markdown context as missing inputs and halted. Both the
  per-story and per-block prompts carry a `Files on disk in the build directory` block listing the
  staged paths and stating that every other file named in the prompt is context, not a missing
  input. The block is omitted when nothing is staged.

- 2026-08-09: `drydock uat` now spends the full `--repair-attempts` budget on a block whose
  acceptance score stops improving. Interactively, one repair pass that moves no acceptance
  criterion still ends the block — the operator should not pay for a model that is spinning — but
  a UAT measures what Drydock delivers at the full budget, and a fixture that would converge on a
  later call was being scored as a methodology failure. `drydock uat` marks every child command
  with `DRYDOCK_UAT`; the build reports the flat pass on the console and continues rather than
  recording a stop reason. A criterion the agent reports as defective remains terminal in both
  modes, because staged acceptance assets are restored before grading and no later pass can move
  it.

- 2026-08-08: Plan integrity now rejects `Suite: scoped` Programmatic Acceptance that requires
  `0 skipped`. A scoped conformance invocation deliberately excludes tests owned by other stories;
  only the terminal `Suite: full` story may use zero skipped as whole-suite completion evidence.

- 2026-08-07: Restored a green verification run. The test suite still asserted the Blueprint
  Markdown question surface retired on 2026-08-02, so 27 tests described behavior that no longer
  existed; gate, authorization, build-decision, and Commander-guidance coverage is now expressed
  against `DECISIONS.json`, and the Sea Trials question projection is asserted as retired. Three
  further CI-only failures are closed: `pyproject.toml` declares `pythonpath = ["."]` so tests that
  import sibling test helpers work under `uv run`, the `logs/` replay fixture consumed by the
  MANIFEST parser test moved to `tests/fixtures/` because `logs/` is not committed, and
  `validation/bin/*.sh` carry the executable bit in Git so `validation/bin/run_validation.sh` finds
  its case scripts on a clean checkout.

### Changed

- 2026-08-07: GitHub Actions verification now uses one Ubuntu/Python 3.12 job instead of repeating
  the full suite across three Python versions and two operating systems. The single job retains
  lint, formatting, tests, and clean wheel installation checks while removing unenforced coverage
  collection and the slow Windows compatibility matrix from every push and pull request.

### Added

- 2026-08-08: `drydock uat` now writes a per-fixture `evidence/` bundle on both successful and
  failed runs. It preserves every lifecycle command's stdout and stderr, copies LLM prompts,
  prompt outputs, provider-raw transcripts, and `llm.jsonl`, and indexes those artifacts with
  relative paths, byte counts, and SHA-256 hashes in `evidence/manifest.json`. The lifecycle also
  captures `build status <Target>`, `status <Target>`, and workspace-wide `status` views after
  planning, refitting, and each completed build stage so the evidence shows state transitions as
  well as command outcomes.

- 2026-08-08: UAT fixtures can declare fixture-local source files and a deterministic post-build
  `test_command` in `uat.json`. Fixtures now declare a nonempty source bundle and ordered updates
  explicitly instead of relying on `spec_N.md` filename semantics. Drydock assembles a flat,
  isolated import root so nested fixture organization cannot alter the build's `sources/<basename>`
  contract; updates replace that staged source before the real `import --update` and refit flow.
  The CommonMark fixture carries its complete upstream conformance kit and gates the completed
  application by running `sh full_test.sh` from its root. Vendored UAT inputs are excluded from
  Drydock's Ruff scope so project lint does not rewrite or impose local style on upstream test kits.

- 2026-08-07: `drydock uat [<Project>]` runs known project fixtures as isolated, timestamped,
  unattended builds using one configured model and provider. Ordered `tests/uat/<Project>/spec_N.md`
  inputs exercise both the initial lifecycle and subsequent `import --update` → `refit --sources`
  incremental rebuilds; the first fixture is ReadingList, derived from the prior helper scripts.
  Each run preserves child-command transcripts and emits Markdown/JSON summaries with wall time,
  LLM time, token/cache usage, build-pass counts, and advisory `score ac`, `score build`, and
  `score release` results. Score failures are reported but do not mask whether the build lifecycle
  itself completed.

- 2026-08-07: `drydock plan --override` and `drydock build --override` waive the gates that wait
  on a human answer — unanswered Analyze questionnaire decisions marked `required_before_plan`,
  blocking `DECISIONS.json` records that park a story at `blocked/questions`, and acceptance
  prerequisites awaiting Commander authorization. Each waiver is recorded rather than skipped: the
  command prints an `OVERRIDE SUMMARY` naming every bypassed gate, and the Target's `METADATA.md`
  gains `override: true` and `override_waivers: <n>` so a waived run cannot later be mistaken for
  a governed one. A blocked analysis (`BLOCKERS.md`, `Quality: Blocked`) is deliberately not
  waivable, because on a source the author controls that verdict is a regression signal about the
  source rather than an interruption. The flag takes no sub-options; a selectable severity list
  would make the flag itself part of the test surface. Note that an override build may reach for
  an undeclared external prerequisite and is therefore not hermetic.

- 2026-08-07: `drydock config env [<Target>]` prints resolved paths as shell `KEY=value`
  assignments for `eval "$(drydock config env <Target>)"` — `DRYDOCK_WORKSPACE`,
  `DRYDOCK_TARGETS_ROOT`, `DRYDOCK_BUILD_DIRECTORY`, and, when a Target is named,
  `DRYDOCK_TARGET`, `DRYDOCK_TARGET_DIR`, and `DRYDOCK_TARGET_BUILD_DIR`. The Target need not
  exist, so a driver that clears and regenerates one can learn its paths first. Like
  `status --check/--ready`, the output is masthead-free; values are shell-quoted.

- 2026-08-07: `helpers/autotest_ReadingList.sh` drives the full pipeline unattended as a
  pre-release regression build: it clears the Target and build directory, runs
  init → import → analyze → plan → build with `--override`, loops `build` under a
  `status --ready` guard with a pass cap, and asserts completion with `status --check`. It
  hardcodes no paths, taking them from `config env`, so a copy covers another Target.

- 2026-08-07: `drydock status console` reports how the current terminal was classified — platform,
  stream encoding, `TERM`, console host, resolved glyph tier, colour — and prints a sample line of
  every tier past the tier wrapper, so a terminal that cannot render a glyph shows it. One command
  and one screenshot now diagnose any icon complaint.

- 2026-08-07: `drydock --glyphs <emoji|text|ascii|auto>` and `DRYDOCK_GLYPHS` override console
  detection by naming a tier. `--ascii` and `--unicode` remain as aliases for the bottom and top
  tiers. An override replaces the terminal heuristic but never the encoding limit: forcing emoji
  onto a `cp437` stream would reintroduce the `UnicodeEncodeError` the detection exists to prevent.

- 2026-08-06: `LINEAGE.json` at the Target root records which source version produced which work.
  The unit is a *source version*, not a parsed fragment of prose: import copies the file and lets
  git record it, so a version is a `(content hash, commit)` pair and a delta is a git diff. A
  version stays `pending` until `plan` or `refit` consumes it, and consumption appends the
  requirements found and the stories they became without rewriting any earlier version — the
  versioned history that previously did not exist, because refit overwrote the prior hash on
  success. Requirements point at Manifest story ids and never at Blueprints, since stories already
  carry `implements`. Each version also records the `METADATA.md` release identifier.

- 2026-08-06: `drydock refit <Target> --relineage` rebuilds `LINEAGE.json` for a Target that
  predates it. The deterministic half replays every source version from the Target's git history
  with its commit and date; the judgement half attributes existing Manifest stories to the
  requirements they implement, as a closed-set match. A story matching no requirement is recorded
  `origin: plan` and left unattached rather than failing — planning legitimately invents
  foundational work no sentence asked for. Requires a Target git repository and says so plainly
  when one is absent.

### Fixed

- 2026-08-07: Status icons and shell markers now render correctly on terminals that previously
  showed boxes or escape sequences. Four defects, each independently sufficient to break output:
  the MSYS/MinGW rule was gated on `isatty()`, which is false for a Git Bash terminal under a
  native Windows Python, so the rule never fired for the host it was written for; console output
  defaulted to its richest form on any unrecognized terminal, and a UTF-8 encoding is not evidence
  of an emoji font, so unknown hosts got glyphs they could not draw; an auto-detected downgrade was
  never published to the environment, so subprocesses and the LLM runner rendered differently from
  their parent; and ANSI colour was written whenever stdout was a terminal, which prints a literal
  `←[32m` on a Windows console without virtual terminal processing enabled.

  Output is now resolved to the richest of three tiers the terminal is *known* to support — `emoji`
  (`✅`), `text` (`✓`, the default for any unrecognized host), or `ascii` (`v`) — capped by what the
  stream's encoding can carry. Nearly every glyph Drydock prints is a single-width symbol that
  survives at the `text` tier, so the icons stay.

- 2026-08-07: Subprocess output is decoded as UTF-8 rather than as the system locale encoding.
  `text=True` without `encoding=` decodes with `cp1252` on Windows and `ascii` under `LANG=C`, so a
  streamed LLM transcript containing any non-ASCII character arrived as mojibake or raised
  `UnicodeDecodeError` — before any console handling could apply. Fixed at every call site, with a
  contract test that fails if a new one omits it.

- 2026-08-06: Standoff diagnosis no longer calls an LLM for deterministic operating-system
  exceptions. Missing files, denied permissions, incorrect path types, existing destinations, and
  related `OSError` failures now return their direct error immediately; unexpected programming
  exceptions and opaque post-LLM failures remain eligible for diagnosis.

- 2026-08-06: Three defects that together made a source change silently vanish between
  `import --update` and the Manifest. `refit --relineage` marked every version it replayed from git
  `consumed`, but `import --update` commits the snapshot it imports, so a version awaiting a refit
  sat in history and relineage claimed it had produced work it never produced; replay now preserves
  the pending state the existing `LINEAGE.json` records, and only genuinely unknown versions
  default to consumed. `refit --sources` injected the compact Blueprint into the routing prompt
  while validating amended section names against the authored Blueprint — the compact form is a
  prose digest carrying no headings, so an `amending` story could only invent a heading and fail
  the whole refit with `Ticket amends sections absent from <Blueprint>`; the authored headings are
  now injected as a `sections` attribute the model copies from. Routed stories land in a new
  computed block, and `refit --sources` did not update the Manifest `blocks:` count, leaving the
  Manifest it had just written unloadable with `Manifest blocks count does not match computed
  blocks`; the count is now recomputed before save.

- 2026-08-06: `drydock refit --sources` now runs. It resolved a changed source to Blueprints
  through `MANIFEST.md` `source_lineage.files[].blueprints`, whose only writer attributed a source
  to a Blueprint when the Blueprint text literally contained the source filename — something no
  LLM-authored Blueprint does. The field was empty on every Target, so the command always failed
  with `Changed source has no lineage candidate Blueprint`. Routing is now one LLM call that
  decomposes the diff into stories seated on existing Blueprints, symmetric with planning:
  `plan` decomposes the whole source, `refit --sources` decomposes what changed. Every gate runs
  before the first write — unknown Blueprint, unknown or cyclic dependency, unrouted requirement —
  and any later failure restores the Manifest, the lineage record, and `blueprint/changes/`, then
  prints the commit to recover from. A requirement that seats on no existing Blueprint fails with
  `replan required`; refit never creates a Blueprint.

- 2026-08-06: A change ticket no longer claims authority over its whole parent Blueprint. Every
  ticket previously declared `Supersedes: <parent>` and "governs in case of conflict", so a
  one-sentence addition superseded assertions it never mentioned and that had already been proven.
  Tickets now carry `Scope`: `additive` supersedes nothing and leaves every parent assertion in
  force, `amending` supersedes only the sections listed under `## Amended Sections`, each
  validated against the parent so a ticket cannot amend a section that does not exist.

### Changed

- 2026-08-06: Both refit paths write one ticket format,
  `blueprint/changes/TICKET-NNN-{Name}.md` with `Version`, `Description`, `Amends`, `Depends On`,
  `Scope`, `Origin`, `Created` and `Stories`. `refit --sources` previously invented an undocumented
  `<Blueprint>_refit_N.md` table that appeared nowhere in `BLUEPRINTS_CONTRACT.md`; `build`
  consumed both only through the Manifest `implements:` field, so the divergence went unnoticed.
  The development workflow (machine-authored from a diff) and the production workflow
  (human-authored through an enterprise change process) now emit and consume the same artifact.
  The `Stories` row is load-bearing: `drydock refit` reprocesses every ticket on every run, and
  without the declared ids the model invents new ones and stories are duplicated rather than
  replaced in place. A ticket's `Depends On` remains computed from the parent Blueprint — inherited
  edges are never routed by the model. Stories gain optional `origin:` and `created:` fields.

- 2026-08-06: `refit --sources` reports blast radius from the existing `provides:`/`consumes:`
  edges, with no LLM. A change to a foundational story's *contract* lists the downstream stories
  that consume it, records them under `## Downstream Impact` in the ticket, and proceeds — the
  classification is model judgement and is not stable between runs, so the Commander decides
  whether to rebuild or defer. Deleting a provision another live story still consumes blocks
  before any file is written, because no ticket can repair a build that no longer has the service
  it uses. Source-driven refit also refuses non-text sources rather than routing a contentless
  delta.

- 2026-08-06: Retired two legacy lineage stores. `blueprint/sources/.drydock-import` is absorbed
  into the `LINEAGE.json` import record, keeping its rule against narrowing a directory root to a
  single file. `MANIFEST.md` `source_lineage:` is read once for migration and then removed, with
  its broken `blueprints` list discarded and reported. Migration runs at most once per Target and
  succeeds with neither file present. `import --update` no longer opens the Manifest at all, so it
  works on a Target that has not been planned. All Target git invocation moves behind
  `target_git`; the lineage commit sha is stamped by a follow-up commit rather than an amend,
  because amending would rewrite the very commit the record points at.

- 2026-08-06: QuarterDeck items that require a Commander answer can now be approved as proposed.
  Discovery questionnaires and the Technology Stack carry an `Approve` action in the page header;
  approving a questionnaire sets its state to `approved` without requiring answers, and approving
  the Technology Stack writes a dated `**Approved:**` marker into `TECHNOLOGY_STACK.md`. Editing
  an approved item never revokes the approval, and `approved` counts as a closed questionnaire
  state everywhere open questionnaires are counted (Analyze summary, Commanders Chair). The
  Technology Stack now also flies the sidebar action icon — red `✗` until approved, green `✓`
  after — so an unreviewed stack is as visible as an unanswered questionnaire.

### Fixed

- 2026-08-06: Programmatic Acceptance validation now caches installed Python distribution
  metadata, Target environment package inventories, dependency manifests, Technology Stack text,
  and parsed Blueprint acceptance for the duration of a Drydock workflow. Target package
  inventory is explicitly invalidated after `uv sync --locked`; `DECISIONS.json` remains
  live-read. This removes repeated high-latency metadata and specification traversal during Plan,
  Build, and Score, particularly on Windows-mounted filesystems under WSL.

- 2026-08-06: Text-only LLM-assisted commands no longer run with a writable codex sandbox.
  `llm.run_prompt(allow_tools=False)` suppressed tools on the `claude` path only; the `codex`
  branch never consulted the flag and ran with the configured sandbox, which defaults to
  `danger-full-access`. Commands that are contractually text-in/text-out — `rigging compact` among
  them — therefore had full filesystem and git write access to the invoking repository, and were
  observed editing their own output file, committing the result, and returning a narrative summary
  that the module then wrote over the file the model had just written. `allow_tools=False` now
  forces `--sandbox read-only` for codex, overriding `DRYDOCK_CODEX_SANDBOX`, the configuration
  file, and the `--codex-sandbox` flag, so the floor cannot be configured off. The forced path
  skips `_preflight_codex_sandbox`, which rejects `read-only` on Linux hosts lacking
  `codex-linux-sandbox`; codex enforces `read-only` natively and needs no helper. `drydock build`
  is unaffected — it passes `allow_tools=True` and keeps its configured sandbox and preflight.

- 2026-08-06: Corrected the SQLite connection-ownership pattern in the Rigging stack guidance.
  `stack/persistence.md` §1 previously prescribed a `Database` that opened one
  `sqlite3.Connection` in `__init__` and passed it to every table class. A `sqlite3.Connection`
  is bound to its creating thread, so generated web applications built the connection on the main
  thread during `create_app()` and raised
  `sqlite3.ProgrammingError: SQLite objects created in a thread can only be used in that same
  thread` on the first request. Single-threaded unit suites never exercised the failure, so
  affected builds completed green and 500'd on first use. The guidance now requires one
  connection per thread held in a `threading.local()` and owned by `Database`; table classes
  receive a connect provider rather than a connection. `stack/sqlite.md` gains a Threads section
  naming `check_same_thread=False` as a non-fix, and `stack/flask.md` records that objects
  constructed in `create_app()` are shared across request threads. Compacts regenerated.
  Applications generated before this change need the same correction applied to their persistence
  module.

- 2026-08-04: `drydock import <Target> --update` now runs. `<Source>` is optional and rejected
  outright with `--update`, which refreshes from the root recorded in
  `blueprint/sources/.drydock-import`. Importers no longer narrow that recorded root: importing a
  single file out of a directory that was already imported keeps the directory as the refresh
  root, so `--update` stops reporting every sibling as a deletion. Snapshot comparison now uses
  the shared visible-source enumeration, so `.gitkeep` and other hidden bookkeeping never register
  as an added or deleted source.

### Changed

- 2026-08-03: `drydock build --ungate` releases prior programmatic acceptance failures as
  explicitly `UNVERIFIED` Manifest nodes and continues with the next buildable step; execution,
  dependency, and provider failures remain gated.

- 2026-08-02: Retired Blueprint and Sea Trials Markdown question sections. Plan, Build,
  acceptance authorization, and QuarterDeck Commander review now use `DECISIONS.json`; unanswered
  blocking decisions gate only their affected stories.

- 2026-08-02: `drydock build` no longer gates on the managed Build Write Guardrail in the
  human-editable `COMPASS.md`; Analyze and Compass creation continue to inject the guardrail.

- 2026-08-02: Plan and Build now govern external Programmatic Acceptance tooling through typed
  `Requires:` declarations and story-local Commander authorization questions. Commander answers
  become durable Target guidance, undeclared build-time prerequisites block without spending a
  repair attempt, and Python/uv acceptance executes through the Target `.venv` with locked uv
  provisioning instead of Drydock's interpreter.

- 2026-08-02: `drydock plan` resumes a planning response that ran out of output budget instead of
  discarding it. A deterministic score measures the artifacts returned against the run's own
  `TOPOLOGY.md` declaration, and continuation passes append a bounded instruction to the unchanged
  prompt prefix so the cached input is not re-billed. The loop stops when the accepted count stops
  increasing or the attempt cap is reached, and reports the score as numbers. Accepted stories are
  frozen; a continuation pass may still split a pending one. `--continue-attempts <n>` (default 3,
  `0` disables).

- 2026-08-01: `drydock score spec <Target>` independently inventories imported raw sources,
  extracts only cited Markdown facts in bounded subscription-authenticated LLM passes, and writes
  an advisory deterministic conformance report to `SPECIFICATION_SCORECARD.md` before Analyze.

- 2026-08-01: `drydock plan` recovers artifact responses whose opening delimiters were transposed
  onto the `=== END NAME ===` line, and accepts a byte-identical repeat of an artifact instead of
  discarding the run. Duplicate blocks with conflicting content, and delimiters appearing inside a
  parsed body, remain contract failures.

- 2026-08-01: `drydock plan` is restructured around authorship versus verification. The model
  authors the four jobs requiring judgment — specification content, programmatic acceptance
  alongside it, conflict resolution by precedence, and questions — and declares each story's type,
  phase, relationships, and stack. Drydock now owns the deterministic remainder in
  `plan_graph`, `plan_topology`, `plan_shape`, and `plan_stack`: graph verification, ordering,
  block grouping, builder/consumer stack-mode assignment, and output-contract shape checking. The
  Manifest becomes a list of stories typed `foundational`, `service`, or `feature`; `spike` and
  `ac` are retired as node types, acceptance becomes a field the story owns, and `Phase` moves out
  of the Blueprint header into the Manifest. Blocks replace feature grouping as the context
  optimization, never crossing a phase, topology type, or stack. Story sizing is a
  single-build-pass token ceiling and the ~100-story cap is removed. A phase/edge two-topology
  disagreement is now a deterministic error instead of a silent defect. The single-build-pass
  size limit is a target, not a gate: over-target stories and blocks are measured, marked in the
  Manifest, reported as warnings, and planned as-is, because an irreducible specification makes
  every story implementing against it over target by construction.
- 2026-08-01: `drydock plan create` asks the model for a `TOPOLOGY.md` declaration instead of a
  finished `MANIFEST.md`. The declaration has no way to express a position, so the model cannot
  assert an order it has not computed; Drydock verifies the declared graph, orders it, packs it
  into blocks, and serializes the Manifest itself. The declaration is transient and never reaches
  the Blueprint. The reuse and Spec Kit prompts continue to emit `MANIFEST.md` directly.
- 2026-07-31: Analyze now acts as the Team Lead/Product Owner completeness session, records
  Commander expectations as assertions, and emits an ASCII-safe crew handoff. Plan receives every
  readable imported source and treats Analyze's story map as a proposal: governed Markdown is
  authored from unconstrained source material, while non-Markdown assets are projected byte-for-byte
  without modifying source provenance. Structural validation enforces one specification per story
  and one owner per specification; preview and execution grouping both separate screen work from
  feature/service work. Blueprint decisions carry Low, Material, or Blocking severity, with only
  Blocking questions gating work. Commander answer revisions persist as replan history, and the
  Shipyard Crew can report bounded implementation decisions into only the owning Blueprint. MSYS,
  MinGW, and Cygwin terminals default to ASCII-safe output so status glyphs remain legible.
- 2026-07-31: `drydock run quarterdeck` accepts an optional Target and defaults to the most
  recently updated initialized Target in the configured workspace.
- 2026-07-30: `TECHNOLOGY_STACK.md` replaces the stack questionnaire as the technology decision of
  record. It maps each technology to the Rigging file governing it, or to none, so a target can
  name technologies Rigging does not document. `drydock analyze` proposes it once and never
  overwrites it; `drydock plan` reads it to assign per-story `stack:` guidance; QuarterDeck edits
  it as rows with a Rigging selector seeded by name similarity. The technology stack no longer
  gates planning, and `plan` resolves an input disagreement by a stated precedence order instead of
  deferring to the Commander. An answered `discovery-stack.json` migrates into rows on first use
  and is archived.

### Fixed

- 2026-07-30: QuarterDeck questionnaires are durable Commander-owned input. Answers survive every
  re-run of `drydock analyze` and feed the analysis as authoritative decisions alongside
  `drydock plan`; only the Commander edits them, in the QuarterDeck. Concurrent autosaves no
  longer corrupt a questionnaire file.
- 2026-07-30: `drydock plan` challenges a model-declared product conflict once before deferring.
  A recovered artifact batch proceeds through normal validation; a confirmed conflict is recorded
  in `ERRORS.md`, appears as pending BIG ERRORS and in the Commander's Chair, and prints its full
  diagnostic, required action, and execution evidence. `PLAN_COMPASS.md` remains human-owned.
- 2026-07-30: `drydock analyze` now surfaces incompatible definitions across imported sources as
  required QuarterDeck questionnaire decisions. `drydock plan` refuses before invoking an LLM
  while any such decision remains unanswered, preventing late post-LLM conflict failures.
- 2026-07-30: Console output no longer fails with `UnicodeEncodeError` on a terminal that cannot
  encode Drydock's glyphs. Every command detects the console encoding and renders ASCII when
  needed. `--ascii` and `--unicode` override the detection.

- 2026-07-29: `drydock plan` accepts a wildcard source citation in `ANALYSIS.md`
  (`sources/FEATURE-CATALOG-*.md`), expanding it against the imported source material instead of
  demanding a file named after the fragment before the `*`.
- 2026-07-29: Imported prose content is always read. A Markdown or text source is never withheld as
  generated or minified — a withheld specification is a lost story — and a large one is chunked
  rather than summarized. Withholding now applies only to code and data artifacts, judged on line
  structure (one machine-scale line holding most of the file) rather than aggregate newline
  density, which had misclassified ordinary hand-written specifications.
- 2026-07-29: `drydock analyze` warns when any imported file's content was not read, naming each
  file and the reason. Command warnings print on stdout so they appear in the run log; sent to
  stderr they were absent from every transcript.

### Changed

- 2026-07-29: Sea Trials EARS conformance is now a derived `Notation: ears | other` label on every
  criterion rather than an enforced requirement. `Pattern` is optional and never a parse error,
  plain-English criteria are fully valid, and both notations are explained to the judge at scoring
  time. Removes the `drydock analyze` EARS repair pass and the `drydock score release` wording
  gate; the pattern shapes now accept a proper-noun system name.

## [0.1.4] — Unreleased

### Added

- 2026-07-27: `drydock plan` now reports the exact location and a JSON-escaped, 100-character
  preview when a model emits text outside otherwise complete artifact blocks. A batch with no
  structural or plan-integrity defect may use the already-enabled standoff-diagnosis call as a
  narrow semantic waiver: exact approval discards only trivial transition text and resumes the
  original transaction; rejection, malformed judgment, disabled diagnosis, artifact-like text, or
  more than 100 outside characters remains fail-closed and writes no Blueprint or Manifest
  artifacts. The waiver and original plan retain separate execution evidence.

- 2026-07-26: Reasoning effort is controllable across the command surface. `--effort
  <low|medium|high|xhigh|max>` is an invocation-wide override accepted by every command, and
  `drydock config set drydock_effort <level>` sets the standing default. Precedence is the flag,
  then a prompt's declared `effort:`, then the configured level, then the provider's own default.
  The level maps onto what the selected provider and model actually serve: claude takes the ladder
  as-is, codex receives it as `model_reasoning_effort`, with `xhigh` reserved for the codex-max
  model family and clamped to `high` elsewhere. Every rejection names the offending value and lists
  the valid levels.

- 2026-07-26: `drydock score drydock` runs an adversarial self-assessment of Drydock itself. It
  takes no Target: the subject is the Drydock source checkout. Intent is derived from
  `docs/Drydock_Specification.md`, and the methodology is attacked against Agile story
  decomposition, Test Driven Development acceptance, context economy, and governance, including
  coverage gaps for project types Drydock has not been exercised on. The command changes no code —
  it writes ranked feature files, each decomposed into Agile stories with TDD acceptance criteria
  and an implementation plan, to `docs/drydock_planning/`, with an `INDEX.md` ranking every feature
  by impact and complexity. The assessment defaults to the highest available model rather than the
  configured build model, and a previous plan is archived rather than overwritten.

- 2026-07-26: A Programmatic Acceptance check that fails inside its own snippet is now rejected
  rather than built against. Every check runs as its own script in its own process, so a check
  reading a name a sibling check bound raises `NameError` on every run and no implementation can
  turn it green. `drydock validate` and `drydock build` reject an unparseable snippet, and a
  snippet reading an unbound name, before any LLM pass is spent; at runtime such a failure is
  classified `malformed check` rather than reported as a missed assertion. `drydock validate`
  additionally warns when a check captures a test runner's output and never prints it, which
  reduces a failure to a bare assertion with no tally and no failing cases. A failing check now
  prints both of its output streams to the console, and a failed Definition of Done line is
  marked `[!!]` so it cannot be misread as a ticked checkbox.

- 2026-07-25: Programmatic Acceptance runs under a bounded address space in its own process
  group, configured by `drydock config set sandbox_mem_limit <MB>` (default 4096; `0` lifts the
  bound, and JVM or Go toolchains generally need it raised). Built code that allocates
  without bound or never terminates is stopped by the kernel in seconds instead of driving the
  host into swap for the whole timeout window, and the timeout now reaps the check's whole
  process tree rather than orphaning a runaway grandchild. A resource kill is reported as
  `exhausted memory` / `timed out` rather than as a missed assertion, and the repair pass leads
  with that fact so it fixes the non-terminating code instead of tuning output.

- 2026-07-23: The Commander's Chair now publishes a prominent `RUNNING` notice with the command
  and UTC start time while `drydock analyze`, `drydock plan`, or `drydock build` executes, then
  regenerates its terminal state on every exit path. Its new Logs and Run History tabs are live
  QuarterDeck views: Python rereads the workspace log inventory and the active Target's filtered,
  newest-first `logs/history.jsonl` records on every request.
- 2026-07-23: Build repair loop. When a build block fails a deterministic gate in a repairable way —
  a Programmatic Acceptance miss or a surviving agent-reported failure — `drydock build` feeds the
  failure diagnostics back and re-runs the same block against the persisted partial work, iterating
  it toward green rather than restarting. Terminal failures (token or context limit, missing
  sandbox, provider error, dependency-legitimacy block, staged-asset tamper, no files written) never
  loop. The `--repair-attempts <n>` flag sets the budget (default `3`, `0` disables). Repair
  continues only when passing ACs grow without regression or stable ACs show non-regressing
  per-criterion case progress. Feature repair grades verified sibling ACs as regression gates and
  reopens a sibling whose behavior regresses. Normal console output and evidence report each
  attempt's AC and case totals. Model escalation is opt-in and applies only to the final attempt,
  via `--escalate-model` or the `drydock_build_escalate_model` configuration key (unset by default).
- 2026-07-22: Standoff diagnosis. When a command fails in a way its author cannot interpret — a
  post-LLM failure such as `no build files written`, or an unclassified exception — Drydock stops,
  states that a major error has occurred, and has the selected provider and model diagnose it. The
  result is one `CAUSE` line and up to three `DO` lines, printed and appended to the Target's
  `ERRORS.md`. Deterministic failures never trigger it: usage errors, provider authentication and
  rate-limit blocks, and any classification that already carries its own remediation are answered
  without an LLM call. Validation findings now state their own fix instead — a blank
  `short_description` names the file to edit and the command that fills it. `--no-diagnose` and the
  `diagnose` configuration key disable the feature.

### Changed

- 2026-07-28: Normal `drydock build` output identifies the block, active stories, verified sibling
  regression gates, LLM call number, repair position, model, and current failing AC case totals
  before every provider call. Acceptance summaries use one-based call numbering. Suite acceptance
  permits an authoritative exact passed count or a count derived from authoritative suite data;
  runner success remains mandatory.

- 2026-07-24: Every log file is named `<stamp>_<Target>_<command>[_<provider>].<extension>`. The
  stamp is a readable UTC instant, `20260725.004228.288Z`, replacing `20260725T004228288279Z`, and
  `execution_id` shares it. An LLM-assisted command's transcript names the provider in force — the
  `--llm-provider` override when given, otherwise the configured default — so the transcript and
  the evidence files beneath it share one stem; a deterministic command such as `drydock status`,
  `drydock validate`, `drydock build status`, or `drydock score ac` names no provider, because none
  runs. `drydock build`, `drydock status`, `drydock score`, and `drydock document` resolve their
  Target from their operand list, which also fills the Target field they previously left blank in
  `logs/history.jsonl` and directs a standoff diagnosis at that Target's workspace instead of the
  working directory. Drydock no longer leaves empty log files: a transcript that captured no output
  and an unused LLM `.stderr.log` are both discarded on close, and `llm.jsonl` omits the `stderr`
  artifact path when there is no such file.
- 2026-07-23: Drydock no longer creates command or LLM execution `.debug.log` files. The global
  `--debug` option, accepted before or after the command, prints internal Python and LLM execution
  diagnostics to the console for the current invocation. Normal command transcripts and
  reproducible LLM evidence artifacts remain unchanged.

- 2026-07-23: Drydock command logging now writes one timestamped plain-text `.log` containing
  stdout for every command, including report commands such as `drydock status`. The shared rotating
  `run.log` files and redundant `events.jsonl` telemetry are retired; the LLM execution index is
  named `llm.jsonl`.

- 2026-07-23: `drydock build` treats a build agent's self-declared failure as advisory, not
  authoritative. When the agent still wrote files and the block carries Programmatic Acceptance
  criteria, Drydock runs the deterministic gate and lets the measured result decide the outcome —
  so an agent can no longer fail a block whose own acceptance criteria it met by editorializing
  about work outside that block's definition of done. The self-report is recorded in evidence under
  `## Agent self-report (advisory)`, distinct from the measured `## Post-build programmatic
  acceptance`. Blocks with no acceptance criteria, and hard execution failures (sandbox, token
  limit, non-zero exit, empty output), remain terminal.

- 2026-07-23: A failed `drydock build` now commits the build directory so the generated artifact is
  preserved for inspection, diagnosis, and the next rebuild instead of lingering as fragile
  uncommitted state that later asset staging can wipe. The commit subject carries a `[FAILED]`
  marker.

- 2026-07-22: Unsatisfiable Programmatic Acceptance assertions are rejected before they cost a
  build. A mis-authored expectation — most often a raw string literal carrying `\n`, which is a
  backslash and a letter rather than a newline — cannot be satisfied by any correct
  implementation, so the step burned a full agent cycle and closed `failed` against working code.
  `drydock validate` now fails on the defect and `drydock build` blocks before the agent runs,
  naming the Blueprint file and check to repair. Acceptance snippets also execute from a real file
  instead of `python -c`, so a failing assertion appears verbatim in evidence rather than as a
  bare `File "<string>", line 3`. The plan prompt contracts state the authoring rule.

- 2026-07-22: `drydock build` now stages declared build assets into the build directory. Analyze
  classifies every imported source with a build disposition; a source marked `stage` is placed at
  `sources/<name>` in the build directory, copied from the immutable import. Previously the
  disposition was parsed and discarded, so an imported test kit never reached the build tree —
  and because acceptance runs there, build agents authored substitutes to satisfy existence
  assertions and then graded themselves against them. Staged assets are digest-checked: a step
  that rewrites one fails and the asset is restored, and `drydock score` reports substitution as a
  release blocker without altering the artifact under judgment.
- 2026-07-24: "corpus" is retired throughout. The imported source body is now **source material**
  (`drydock.source_material`, `SourceMaterialFile`, `discover_source_material`) and the conformance
  concept is the **test suite**. The legacy `Corpus:` acceptance marker is removed; a full-suite
  gate declares `Suite: full`. The Plan integrity gate now rejects any non-terminal story that runs
  the whole test suite without `Suite: full`, and the Blueprint prompts direct a harness staging
  story to bound its run with the runner's `--pattern`/`--number` selector.
- 2026-07-22: a deterministic conformance test suite can now gate delivery. `SEA_TRIALS.md`
  measurement criteria accept `Extract:`, a regex capturing the measured value from a harness's
  own stdout, so a harness that reports in human-readable text and exits non-zero on failures is
  measurable without a project-authored wrapper. A single terminal verification story may gate on
  the complete suite by declaring `Suite: full` in its Programmatic Acceptance heading block;
  story acceptance remains bounded by default. A Sea Trial `Command:` containing an unresolved
  `<placeholder>` is now rejected rather than silently never running.

- 2026-07-17: reworked scoring to match the specification. `drydock score release` is now an
  LLM-assisted release gate that judges the project criteria in `SEA_TRIALS.md` and writes
  `SCORECARD.md` (prompt contract `prompts/score_release.md`); deterministic proofs, measurements,
  and guardrails still settle mechanically and feed the model. `drydock score ac` remains
  deterministic and is now the sole writer of `SOUNDINGS.md` — `analyze` and `plan` no longer create
  it, so a project has no Soundings until it is scored. The Commander's Chair renders a Scorecard
  section with per-criterion checkmarks.
- 2026-07-17: retired the Ship's Log feature, removed the `drydock shipslog` command and related
  repository tooling, and made `CHANGELOG.md` the only maintained high-level project history.
- 2026-07-17: aligned `drydock document` with its specification by making generated `DOC-*` output
  authoritative for configured sections only, tightening the prompt against invented content, and
  removing stale repository references to non-Target sample acceptance artifacts.
- `drydock import --format compass` now normalizes the intent document into the canonical
  COMPASS.md format with an LLM pass at import time (prompt contract
  `prompts/import_compass.md`), preserving the Commander's vocabulary. It is the only import form
  that runs an LLM and honors `--llm-provider` and `--model`. The written COMPASS.md is final and
  Commander-owned; an existing COMPASS.md is preserved unless `--force` is given, and
  `drydock analyze` no longer performs deferred normalization for compass imports.

## [0.1.1] — 2026-07-08

### Added

- Drydock Blueprint Methodology vocabulary across the product specification, documentation, and CLI.
- Sole authoritative product specification at `docs/Drydock_Specification.md`.
- Project foundation: single-sourced version, packaging metadata and classifiers, `py.typed` marker.
- Continuous integration (GitHub Actions) across Python 3.11–3.13 on Linux and Windows, with a wheel
  build and installed-CLI smoke test.
- Static type checking (mypy) and coverage reporting (pytest-cov).
- `pre-commit` configuration (whitespace, YAML/TOML, and ruff hooks).
- `nox` sessions for lint, type, tests, and build.
- Contributor guide and this changelog.
- `drydock rigging compact` — the first LLM-assisted command and general compaction entry point —
  with a versioned prompt contract (`prompts/<command>_<subcommand>.md` + required YAML frontmatter).
- Canonical product specification packaged in the wheel at
  `drydock/resources/docs/Drydock_Specification.md`.

### Changed

- Renamed the `INTENT.md` Typed Specification file and `INTENT` FileType to `COMPASS.md` /
  `COMPASS`, the `## Intent` body section to `## Compass`, and the `BUILD_PLAN_INTENT.md` planning
  inventory to `BUILD_PLAN_COMPASS.md`. "Compass" is the nautical term for the product's
  direction-setting document.
- Renamed the `drydock iterate` command to `drydock refit`, aligning the verb with the canonical
  SAIL Loop "Refit" concept. The `<BOTH|BLUEPRINT|TGT>` modes are unchanged.
- Replaced the public `drydock log` commands and shared target-project capture rules with the
  Drydock-only agent process in `AGENTS.md` and repository-local `bin/ships_log.py`.
- Renamed the public Blueprint root contract to `BLUEPRINT_DIRECTORY` and `blueprint_directory`;
  legacy specification-directory names remain accepted as deprecated migration aliases.
- Renamed the public CLI project argument from `<Spec>` to `<Blueprint>` and the iterate-side mode
  from `SPEC` to `BLUEPRINT`; `SPEC` remains accepted as a deprecated migration alias.

### Known Limitations

- This is an alpha release. Command contracts and Typed Specification contracts may change during
  the `0.x` series.
- LLM-assisted commands require an authenticated local `claude` or `codex` CLI.

## [0.1.0] — Unreleased

### Added

- Installable `drydock` CLI with `config`, `init`, and `validate` commands.
- Subscription-authenticated LLM execution foundation.
- Source-tree launchers and packaged Rigging resources.

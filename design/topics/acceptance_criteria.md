# MEMORY: acceptance_criteria

| Field | Value |
|---|---|
| Version | 2026-10-15 V1 |
| Description | How a Programmatic Acceptance criterion is recorded, classified, run, repaired, and counted during staged builds. |
| Route | acceptance_criteria |
| Modules | `acceptance.py`, `acceptance_status.py`, `ac_repair.py`, `proof_integrity.py`, `status.py`, `build_run.py` |
| Prompts | `diagnose_ac_repair.md` |
| Tests | `tests/test_acceptance*.py`, `tests/test_ac_repair.py` |
| Governs | [build](../commands/build.md), [score](../commands/score.md), [plan](../commands/plan.md), [diagnose](../commands/diagnose.md), [status](../commands/status.md) |
| Pending spec | 0 |
| Pending impl | 1 |

## Intent

How a Programmatic Acceptance criterion is recorded, classified, run, repaired, and counted during
staged builds. A criterion is evidence only when it binds to the product, was red before the build,
and measured something; everything else is reported, not charged.

## Guardrails

- None.

## Details

`2026-10-26` · Staged selection probes share their executable validator between source-aware
planning admission and `plan verify`; a rejected expression can be reauthored inside the bounded
artifact repair loop before serialization and lineage. Mechanical repair preserves its narrower
scope. Recovery routing is shared with execution so authoring faults recommend replanning.
The probe contract explicitly names supported literal arguments and canonical abspath; runtime
f-strings are not evaluated to prove selection. Prompt examples use supported path forms.

`2026-10-25` · Ordered-oracle and process-readiness checks live in
`acceptance_oracle.py` and run at admission and verification without executing proofs. Ordered
rows are checked only when the declared keys, projected columns, and fixture values are statically
resolvable; unsupported expressions remain unjudged. Immediate spawn-only liveness checks are
rejected narrowly, not treated as a general proof of correct readiness. UAT receipts describe
outcomes without automatically assigning product/harness ownership. OutcomeTally uses the same undetermined-ownership field in its serialized counts; the old
product/harness aliases are removed rather than retaining contradictory terminology.


`2026-10-24` · Native Go `not-run` is `VALID product-missing` at baseline, extending
`c6a910f`'s absent-file rule. Skip and unavailable retain `ERROR environment`; post-build
not-run stays UNVERIFIED and cannot pass. A real temporary Go module regression observes the
missing test, runs it unverified, writes the required test, and observes a pass through the same
acceptance executor. Repair feedback summarizes excluded criteria after actionable diagnostics;
receipts count unverified results outside the graded PASS/FAIL denominator. CSV success-fixture
authoring uses a serializer and preserves the declared parser contract, including quoting rules.

`2026-10-24` · Build grades declared criteria after a successful provider call even when the
agent reports failure with no file changes; verification-only steps may report SUCCESS without
edits. Prepassed and governed attribution rules remain unchanged. Evidence distinguishes bypassed
grading from failed assertions. Static exit checks follow a local helper's single directly
returned runner tuple only when every caller asserts its exit, and reject an exit rebound before
assertion. See the build and plan Memory Files for the supported helper boundary.

`2026-10-24` · Staged corpus probes recognize section/selection options and options whose
parsed values feed `re.compile`, rather than treating the first option as a selector.
Program and corpus-path arguments remain in the probe's complete argv. A canonical,
unmodified `import os` permits syntactic resolution of `os.path.abspath("literal-path")`
against the criterion working directory, including argv bound to a module variable; no criterion
expression is evaluated and the proof text is unchanged. Other unresolved arguments fail as
`unresolved-probe-arguments`, naming their one-based runner-argument positions. `plan repair`
reports these unchanged without a model call: declaration edits cannot repair body expressions.
`Probe Count: json` counts JSON array items, including zero for `[]`; JSON arrays/objects are rejected under `lines`. Probe repair
receives only the implicated runner source, preserves non-probe metadata, code and assertions,
and changes listing flags/count formats for `probe-failed`; `empty-selection` retains scoped
selector repair. `BLUEPRINTS_CONTRACT.md` requires flags and protocols the supplied runner
implements. This revises `51a9c2b`; the master specification is unchanged.

### Rules

`2026-10-24` · **An assembled expectation binds unless its typed text is escapable.** The text
typed into an f-string, a `+` concatenation, a `%` template, or a `.format` receiver follows the
literal rule: plain text binds, and a backslash other than `\"`, a carriage return, non-ASCII
text, or a `!r`/`!a` conversion marks it re-typed. A reconstructed `/` path is still re-typed.
This revises the 2026-10-12 Binding rule for assembled strings. Cost when broken: FxRates
`20261024.164835` demoted `body["mean"] == f"{mean:.6f}"`, a source-mandated mean computed from
the seeded rates, to non-binding, so a wrong mean could never fail the build.

`2026-10-24` · **A string calculation compared with a literal is not an assembled expectation.**
For either operand order of `==` or `!=`, the literal supplies the expected bytes and retains
the existing escaping and citation checks; the computed string is not flagged as a second
expectation. Each adjacent pair in a chained comparison is judged separately. An assembled
string compared with a nonliteral still follows the existing binding rule. This revises the
assembled-expression classifier retained by `b7ea20b`; it does not establish product coverage.
Empty-tree passes remain `PREBUILD_PASSES` and cannot verify a story. Cost when broken:
DrydockStats `20261024.155305` reports `f'{usd:.4f}'` as retyped while missing the actual
problem: the criterion tests Python rather than Go.

`2026-10-24` · **Citation validation distinguishes binding expectations from re-typed literals.**
Every declared `Cite:` resolves inside `sources/`. Verbatim matching applies only when the
criterion has re-typed expectations; numeric exit codes and plain ASCII expectations already
bind and do not need literal derivation. This does not establish semantic support for an
already-binding expectation. Citation repair receives only its referenced source files with
one-based line numbers and changes only the existing `Cite:` declaration. Other proof and metadata
changes, removed citations, and still-invalid citations are rejected per criterion. Missing
source evidence yields `REPAIR_IMPOSSIBLE`. This revises `2af2661` alongside `b7ea20b`.
A criterion may cite several ranges, one `Cite:` line each. Every range must resolve, and the
cited text is their concatenation. The declaration is the run of consecutive `Cite:` lines, so
repair may rewrite, add, or drop ranges within it.
Cost when broken: DupFind `20261024.080843` rejects two runnable criteria even with correct
citation ranges, then asks a source-free repair prompt to infer missing source lines. FxRates
`20261024.155325` refuses two-line citations in verify, then rejects their correct repair.

`2026-10-24` · **The acceptance harness owns one rollback transaction per criterion.** The
DATABASE step emits runtime catalog/count probes, applies schema, verifies declared columns, keys,
constraints and indexes, and records `evidence/persistence-verification.json`. Later acceptance
runs verify without applying DDL and refuse a missing or incompatible store. `acceptance.py` sets
`DRYDOCK_ACCEPTANCE_TRANSACTION=1`. The shipped runner removes it from the environment, calls
`persistence.db.begin_acceptance_transaction()` before the criterion, and
`end_acceptance_transaction()` after it. Every `Database` the process opens then shares one pinned
connection per store (keyed by resolved path or DSN) inside `BEGIN`, serialized by a lock across
request threads, with each operation in a savepoint. `close()` and leaving `rollback_session()` are
no-ops, and driver access and schema SQL are refused. A rollback failure fails the criterion. A
crash commits nothing. Outside the harness (project pytest suites), `db_session()` rolls back its
own scope and `committed_session()` autocommits. Plan rejects recognized DSN mutations, schema
calls, and a criterion that both imports `persistence` and launches a process (`subprocess`,
`os.system`/`popen`/`exec*`/`spawn*`, `asyncio` subprocess). Go keeps `OpenSession(ctx, dsn)`
rollback scopes and owned committed records. Cost when broken: setup rolled back before the request
it seeds (FxRates `20261024.051856`: six HTTP criteria 404 against a correct product), shared
residue, or criteria testing an unprovisioned store.


`2026-10-19` · Native Go statuses survive the outer executor. Skip, not-run and unavailable are UNVERIFIED; compilation errors and native failures remain failures with distinct error text. The outer process group timeout terminates descendants. Breaking this rule counts a skipped test as proof.

`2026-10-12` · **Records.** `SOUNDINGS.md` (from `score ac`) is the per-criterion ledger: id,
Blueprint, result (`PASS`, `FAIL`, `UNVERIFIED`, `PREPASSED`), evidence, time, plus Binding,
Baseline, Previously Passed, Last Block columns read by name. Node state lives in `MANIFEST.md`.
`BUILD_LINEAGE.jsonl` holds one receipt per attempt (`acceptance`, `pre_acceptance`,
`regressed_checks`, `swept`). `evidence/acceptance-status.json` holds each criterion's status,
error code, and code digest.

`2026-10-12` · **A status holds only while its code digest matches.** The pre-build observation
classifies each criterion: pass → `PREBUILD_PASSES` (or `ALWAYS_PASSES` when vacuous); malformed →
`ERROR malformed`; skipped/unverified → `ERROR environment`; missing product → `VALID
product-missing`; other red → `VALID baseline-red`. Timeout and memory stay `VALID`. A resumed
baseline never records `PREBUILD_PASSES`. *Broken:* an edited criterion inherits a stale verdict.

`2026-10-20` · **An absent path at baseline is product-missing.** A pre-build observation that is unverified because the criterion's own frame raised `FileNotFoundError` records `VALID product-missing`, not `ERROR environment`, so the criterion runs after the build; a file still absent then reports `UNVERIFIED`. A declared package absent from the environment stays `ERROR environment`. *Broken:* a criterion reading a deliverable its story creates is excluded from every post-build run and never verifies.

`2026-10-12` · **Vacuity is decided from source only.** Constant branches, code after
`return`/`raise`, swallowing `try` bodies, and `suppress(...)` are pruned; undetermined means live.

`2026-10-12` · **The empty-tree baseline runs without the product.** Criteria run in a temp
directory with staged assets and no `.venv`. Empty pass → `PREBUILD_PASSES empty-tree` (runs, never
verifies); empty red but current green → `VALID existing-behavior`. *Broken:* a criterion satisfied
by an earlier block verifies a story that did nothing.

`2026-10-12` · **Terminal statuses are excluded, not retried.** `ALWAYS_PASSES`, `ERROR`,
`UNFIXABLE`, and `FLAKY` (rerun passes with an identical tree) skip later runs and report
`UNVERIFIED` with an `excluded check:` reason. `PREBUILD_PASSES` still runs. *Broken:* a criterion
that measures nothing counts as evidence.

`2026-10-12` · **Binding.** A criterion is non-binding when it compares against a re-typed or
assembled string not supplied as input. Printable ASCII text with newlines and tabs, whose only
backslash is an escaped quote `\"`, binds as a deterministic known answer (`2026-10-21`; was
identifier-shaped tokens only). Another backslash, a carriage return, or non-ASCII text still
marks a re-typed value. A literal found verbatim at its `Cite: sources/<file>:<line>` counts as
derived, and a bad citation is a `bad-citation` plan defect. *Broken (2026-10-21):* LayersTesting
`20261021.195808` demoted seven known-answer CSV criteria to non-binding. A non-binding miss settles
`DISPUTED`: reported, never charged, never repair feedback, never a regression or progress.

`2026-10-12` · **A story verifies only on its own binding criterion that passed and was red before
the build.** Otherwise `closed/implemented` with `UNEXAMINED`, `NON_BINDING`, or `PREPASSED`
finding. A governed gate decides its own stories. *Broken:* a story verified by a criterion that
measured nothing.

`2026-10-12` · **Build loop per block.** Baseline, build, acceptance. A binding `FAIL` fails the
block and is repairable; terminal-prefix failures alone stop it. Progress is a strict superset of
passed ids or a per-case tally gain over binding criteria; two flat passes stop. A green block
sweeps every criterion of every finished block (`2026-10-13`). *Broken:* regressions from earlier
passes go unseen.

`2026-10-25` · **A case tally counts the cases a check selected.** `acceptance.case_tally` takes the
denominator as `total - skip` from the harness `cases:` line, so a scoped suite that reports its
unselected corpus as `skip` reads `248/286`, not `248/655`, and a filter that selects nothing reads
`0/0` and settles UNVERIFIED. Shared by `build` and `score ac`.

`2026-10-12` · **AC repair is deterministic in selection and validated in memory.** `malformed` and
`DISPUTED` criteria are selected; terminal ones never. One call per run with the AC, fault, spec
text, and numbered sources — never product source or output. A repair keeps its id, must bind, must
not be vacuous, and must run `VALID` on the empty baseline; else the criterion becomes `UNFIXABLE`.
*Broken:* criteria fitted to product output, or an endless loop.

`2026-10-12` · **Completion.** `status --check` is `RETRYABLE` while any criterion is `DISPUTED`;
`UNFIXABLE` is clean. The outer loop (`Lifecycle.build`, driven by `drydock run builder`; see
[lifecycle](lifecycle.md)) owns sequencing: build, then `diagnose --apply`, until `status --check`
passes.

`2026-07-23` · **A deterministic definition of done is the complete suite, never a sample.** A
whole-project suite sits on the block that completes the capability (`Suite: full`) and is mirrored
into Sea Trials; running it as a story criterion is required, not an error. *Broken:* a sampled
suite verified a broken build.

`2026-10-18` · The Python execution harness is shipped in its language bundle. Go native tests run through the staged `drydock_go.run_test` helper inside the existing AC container; skipped and absent tests cannot pass. Cost when broken: valid language resources are omitted or acceptance evidence is misclassified.

`2026-10-22` · Go CLI criteria run through the staged `drydock_go.cli_runner(*args, package=None, input=None)`, which builds the single `./cmd/<name>` main package once with `go build -o` and returns `(exit_code, stdout, stderr)` from the binary. A failed build reports `execution-error`, an absent toolchain `unavailable`. Cost when broken: `go run` rewrites every non-zero exit to 1, so exit-status criteria fail a correct product or pass a wrong one.

`2026-10-26` · **One Target declares one TestClient transport.** `plan verify` reports
`test-transport` on each criterion declaring `python-package=httpx` when any criterion declares
`httpx2` (`acceptance_requirements.transport_conflicts`); plan repair replaces only that
`Requires:` line. A uniform `httpx` Target (older selected stack) passes. A post-provisioning
prerequisite failure (`unavailable_requirement_detail`) names each missing requirement once, its
declaring criteria, and an installed alternative transport. Test-scope packages stay
auto-authorized (`a86fe78`); authorization does not install them — only `uv sync --locked`
provisions, so a test package absent from the Target manifest still fails the block. Cost when
broken: FxRates `20261026.153843` block-3 failed before any criterion ran, and diagnosis
inverted the fix to `httpx`.

### Mechanism

See the build-loop and completion rules. Removing a criterion id is rejected; `FLAKY`,
`ALWAYS_PASSES`, and `UNFIXABLE` are never retried.

### Spec divergence

- The specification does not describe criterion statuses, binding, or AC repair.

## Decisions

### Criteria use the provisioned store with rollback or owned committed state
`2026-10-22` · `spec:approved` · `impl:implemented`

Ed selected default autocommit plus explicit rollback scopes for same-connection database
criteria. This supersedes the proposed SETUP/CHECK/TEARDOWN marker grammar: Python context
managers and Go deferred cleanup own the lifecycle. Cross-connection and durability criteria use
owned committed records and recover from interrupted setup/cleanup; no fresh stores or resets.

### Reject a dishonest or missing full suite at plan (conformance gate)
`2026-07-23` · `spec:approved` · `impl:unimplemented`

When a Blueprint imports an authoritative deterministic suite, plan integrity rejects a criterion
that declares `Suite: full` but samples it (`--pattern`, `--number`, slices, hardcoded subsets,
file-exists stubs), and rejects a plan where no story carries it. Deferred because detecting
"suite present" and sampling risks false positives.

## Questions

2. **What counts as sampling?** The heuristic boundary between a sampled or stubbed suite and a
   genuine full run, in `proof_integrity` or the plan gate.
3. **Residue observation is deferred (UAT gates §35).** Reporting files a criterion leaves in the
   build tree is diagnostic only and noisy; revisit if SETUP/TEARDOWN does not stop self-poisoning.
4. **Criterion isolation:** resolved 2026-10-22 by rollback scopes and owned committed records.

## Actions

- `2026-10-24` · CommonMark `20261024.233753`: bounded literal-abspath resolution and
  unresolved-argument repair routing are verified locally in `test_acceptance.py` and
  `test_plan_repair.py`; Ed's later run must pass all scoped probes without the same failure.
  The earlier selector/JSON/runner-context defects are fixed in this run; delimiter generation
  remains open in `design/skills/ddk-uat.md`.

- `2026-10-24` · Go criteria are not under the harness transaction: `drydock_go` runs native tests
  in a separate process, so Go keeps `OpenSession` scopes and owned committed records. Decide
  whether Go gets an equivalent harness-owned transaction.
- `2026-10-24` · Re-run `drydock rigging compact` for `sqlite.md`, `postgres.md` and
  `persistence.md`; their compacts are stale and builds fall back to the full files.

## Working Notes

Not in scope yet: how the planner authors criteria and maps them to stories; governed gates from
`ACCEPTANCE.json` (see [build](../commands/build.md)).

# MEMORY: stabilization

| Field | Value |
|---|---|
| Version | 2026-10-26 V6 |
| Description | Bounded UAT stabilization plan with historical proposal dispositions, truthful verdicts, state ownership and a frozen ten-kit release gate. |
| Modules | `acceptance_oracle.py`, `planning_session.py`, `build_state.py`, `build_run.py`, `diagnose.py` |
| Prompts | `uat_diagnostic.md`, `build.md`, `BLUEPRINTS_CONTRACT.md` |
| Tests | `tests/test_acceptance_oracle.py`, `tests/test_build_state.py`, `tests/test_build_run.py`, `tests/test_plan_reliability.py` |
| Governs | [plan](../commands/plan.md), [build](../commands/build.md), [diagnose](../commands/diagnose.md) |

## Intent

Make approved requirements and resource ownership observable before implementation, and make
repeat failures reproducible without rebuilding ten complete projects after each correction.
The release gate remains Ed's ten-project UAT matrix.

## Guardrails

- `2026-10-26` · Ed approves proactive rules for proved constraints; unproved cases remain
  uncertainty. Static uncertainty never authorizes new rounding, changed expected values,
  broader permissions or weakened gates.
- `2026-10-26` · The assistant owns assumptions review and evidence collection; Ed supplies
  unresolved product decisions. Skipping the review can silently replace the approved goal.
- `2026-10-26` · No agent runs or mutates UAT evidence. Ed runs the release matrix. Local tests
  use private temporary resources and fake provider replies; live subscription calls require
  the authorization applicable to that experiment.

## Details

### Current contract

| Concern | Contract |
|---|---|
| Authority | Approved intent defines correctness; implementation establishes observed behavior. |
| Review owner | Assistant reads current contracts and states invariants, owners, uncertainties and falsifying tests before editing. |
| Validation | Proved violations block; proved allowed behavior proceeds; unsupported inference stays unknown. |
| Mutable state | Every resource has an owner, scope, permitted mutations, cleanup and failure action. |
| Recovery | Preserve evidence and data; route recovery to the owner; never silently overwrite possible concurrent writes. |
| Proof | Deterministic regressions precede the fixed ten-kit release matrix; any separately authorized live experiment supplements them. |
| Execution | S1–S6 are deterministic audit/delivery slices inside Ed’s manual run → /ddk-uat diagnosis → authorized repair → review → rerun workflow. |
| Limit | Passing AC establishes measured behavior only; source coverage, oracle correctness and real product binding must also be established. Local tests do not prove live model convergence. |

### Previously implemented technical slice

These are recorded mechanisms from earlier work, not verification of the next candidate.

- Decimal provenance is advisory. Exact numeric tokens embedded in supplied fixture text are
  recognized without format-specific parsers; unknown provenance cannot trigger artifact repair.
  This does not prove an arbitrary derived formula or rounded expectation correct.
- SQLite agent calls receive a new schema-provisioned disposable store through both database
  environment variables. Existing application rows do not become the agent's test baseline.
- For a managed SQLite store inside the build tree, Drydock keeps a private pre-call SQLite
  backup and checks main-file/WAL fingerprints after the call, including exceptional exits.
  Detected changes stop the block and retain the backup. No automatic restore overwrites data.
- External SQLite DSNs are replaced for the agent's tests without reading or backing up the
  external store. PostgreSQL isolation is not implemented by this mechanism. Neither mechanism
  is an OS sandbox against arbitrary tools with full filesystem access.
- Per-test isolation within one agent call remains a project-fixture responsibility; the current
  store is fresh per call, not per individual pytest test. Processes and ports are not isolated
  by a database copy. These are explicit remaining stabilization work.
- Persistence failures identify the DATABASE owner, preserve recovery evidence and use a managed
  state phase; the inline model diagnostician does not replace their deterministic recovery.
- `/ddk-uat` prints Assumptions Review after Verdict. Default invocation diagnoses; explicit
  repair authorization permits the requested code work under repository rules.

### State inventory — implement only represented, reproduced gaps

This is the resource catalogue. S2 records which rows are represented in the release matrix,
which protections exist and which gaps block those paths; unrepresented adapters stay deferred.

| State | Scope and isolation | Owner / required verification |
|---|---|---|
| Imported sources, scoring assets, Blueprints | Immutable during Build; compare hashes, reject unauthorized changes. | Import/Plan; existing staged-asset guard, extend coverage for all governed files. |
| Generated framework code and schema/provenance | Regenerate only through the owning lifecycle step. | DATABASE/foundation; verify fingerprints and ownership before/after calls. |
| Application DBs, files, uploads, object storage | Fixture-owned test namespace, schema and seed; preserve canonical state. | Store owner; SQLite call isolation implemented, per-test and remote adapters pending. |
| Configuration and secrets | Task-local config; preserve operator values; redact evidence. | Config/runtime; existing `.env` materialization rule is not a universal write guard. |
| Dependency manifests, locks, environments | Target-local manifests/environment; immutable version resolution during comparison. | Language foundation; existing parent-workspace guard plus environment regression. |
| Git/worktrees and applied-spec provenance | Private worktree or explicit mutation set; preserve unrelated edits and accepted work. | Target Git/build lineage; verify before/after, never reset unrelated changes. |
| Locks, journals, counters, lifecycle state | Run-scoped identities; owner-only transitions; idempotent resume and failure cleanup. | Orchestrator; test interrupted and repeated operations. |
| Processes, sockets, ports | Owned process groups, dynamic ports, bounded readiness, checked termination. | Executor/service fixture; no surviving child or occupied test port after completion. |
| Caches, temporary files, environment/CWD | Task-specific directories and child environment; restore parent state. | Executor/test harness; cold/warm reruns must agree on required behavior. |
| Network, queues, remote stores and credentials | Stub by default; explicitly authorized namespace for real integration. | Service adapter; no unowned resource creation or destructive remote cleanup. |

### Small frozen regression cases

Preserve one minimal case for each demonstrated failure class, plus a successful nearby case.
Do not preserve an entire build or make every test rerun a model. Reuse existing fixtures where
they already express the contract. Proposed location for new cases:
`tests/fixtures/regressions/<capability>/<case>/` with a small `case.json` index.

| Preserve | Required content |
|---|---|
| Case identity | Stable id, command/stage, originating run/commit, affected contract, expected disposition and reason. |
| Approved basis | Small source excerpt and relevant current contract; original source SHA-256 for traceability. |
| Command inputs | Only the consumed Compass/stack/topology/Blueprint/criteria/config fields, with portable paths. |
| Model boundary | Relevant original reply and bad/repaired candidate; tests inject replies without model calls. |
| Runtime fixture | Minimal real product interface, staged runner, small corpus and schema/seed sufficient to reproduce. |
| Expected result | Exit code, defect/advisory class, story ownership, preserved coverage and resource mutations. |
| Recovery behavior | Correct owner, data preservation, next legal stage, unchanged prior accepted work. |
| Reproduction metadata | Framework revision, prompt versions/hashes, language/tool versions, dependency locks and test invocation. |

Never freeze credentials, live operator DBs, private `.env`, provider homes, `.venv`, caches,
compiled dependencies, entire raw transcripts or timestamps as semantic expectations. Preserve a
schema and synthetic seed instead of a business-data database. Normalize paths and run ids.
Generated model output is an input to a regression, not an authority overriding the source.

Initial cases to index: serialized decimal round trip and incorrect normalization; probe
declarations/static arguments; provider/consumer ordering; rollback versus cross-connection
tests; deleted managed store and surviving backup; missing-store owner recovery; malformed
artifact retry; missing transport/tool prerequisites; interrupted execution and resume; valid
replan preserving already accepted work. These cover failure classes across projects.

### Historical stabilization assessment and scope (superseded by review correction)

`2026-10-26` · Review baseline: `7586152` (`Make stabilization plan implementation-ready`),
clean working tree. The approach is sound: establish contracts, reproduce failures without model
calls, correct the owning boundary, then validate one candidate with Ed's ten-kit matrix. V2's
weaknesses were an unbounded resource-hardening gate, insufficient attention to truthful closure
and release evidence, and no disposition of the July proposals. This revision bounds the release
scope and inserts those missing proofs. It changes the implementation plan, not product behavior.

The request in this session is to review and update the plan. Execution begins when Ed requests
implementation; the plan itself does not grant new permissions. During execution, complete
ordinary implementation, verification and local commits without phase-by-phase approval.

**Release scope:** existing supported command paths and the capabilities required by the current
ten-kit matrix. Fix demonstrated contract violations and shared mechanisms that cause them. Do
not implement every historical feature or every possible resource adapter. A missing declaration
is uncertainty, not proof that a Target has no state or that a dependency does not exist.

**Priority:** P0 data/evidence preservation and false verification; P1 recurring planning,
execution, repair and recovery failures; P2 diagnostics and bounded performance defects. A P2
item becomes a release blocker only when it violates an approved contract or prevents assessment.
Record lower-priority unrelated work; keep it outside the candidate.

### Historical proposal disposition

Read [July assessment](../../docs/drydock_planning/INDEX.md) and its twelve feature documents,
plus the earlier [archived assessment](../../docs/drydock_planning/archive/20260726-224601/INDEX.md)
and its thirteen proposals. These are generated assessments, not approved requirements or current
implementation evidence. DDF ids change meanings between assessments; identify proposals by
path/title, never id alone. Keep the originals unchanged. Each row below has an execution home;
"audit" means inspect current code and tests before deciding whether a defect remains.

| July proposal (file number in `docs/drydock_planning/`) | Disposition for stabilization |
|---|---|
| [01 — proof execution](../../docs/drydock_planning/FEATURE-01-declare-and-enforce-a-proof-execution-contract.md) | Retain setup/readiness, isolated state, timeout, teardown and truthful executed/unexecuted evidence in WP1/WP3. Reuse current outcome vocabulary; do not copy the proposed new heading syntax or status enum. |
| [02 — staged/resumable planning](../../docs/drydock_planning/FEATURE-02-split-plan-creation-into-a-skeleton-pass-and-resumable-per-f.md) | Current topology, continuation and bounded artifact repair already address parts of this. Audit preservation and interruption in WP2/WP4; do not replace the planner or introduce old `--file`/`--continue` proposals by assumption. |
| [03 — interface grammar](../../docs/drydock_planning/FEATURE-03-typed-interface-point-grammar-for-provides-consumes-and-acce.md) | Retain exact declared provider/consumer ordering and source-defined stages in WP2. Current graph matches declared strings; retain legal external inputs. Defer namespaced grammar and new `CONTRACT` type. |
| [04 — derived evidence](../../docs/drydock_planning/FEATURE-04-derive-build-evidence-from-the-build-directory-rather-than-f.md) | Retain measured changes, command outcomes and independent gate facts in WP1. Reject the blanket empty-diff failure and automatic restoration rules: verification-only steps and concurrent writes are valid current cases. |
| [05 — RED/vacuity](../../docs/drydock_planning/FEATURE-05-enforce-red-before-green-and-widen-the-vacuity-taxonomy.md) | Retain conservative proof-integrity checks and honest pre/post reporting in WP1. Do not reinstate a blocking prepass or blacklist `isinstance`, existence or indirect calls without proving a contract violation. |
| [06 — context budget](../../docs/drydock_planning/FEATURE-06-compute-and-enforce-a-per-block-context-budget-at-plan-time.md) | Audit measured size/grouping and actual provider-limit classification in WP2/WP4. Current over-target markers are advisory; defer a new hard budget, Manifest fields and split CLI. |
| [07 — refit reconciliation](../../docs/drydock_planning/FEATURE-07-give-refit-tickets-executable-acceptance-and-reconcile-them.md) | Regress the existing UAT refit path and its evidence in WP4. Defer automatic parent-spec rewriting, archival and new drift semantics. |
| [08 — one story gate](../../docs/drydock_planning/FEATURE-08-collapse-the-double-acceptance-gate-into-one-executable-stor.md) | Audit current acceptance references and persisted story states in WP1/WP2. Current governed `ACCEPTANCE.json` authority supersedes the proposal that generated Blueprint proofs alone verify every story. |
| [09 — enforcement claims](../../docs/drydock_planning/FEATURE-09-bind-every-prompt-enforcement-claim-to-a-named-validator-and.md) | Retain claim → enforcer → negative/positive test mapping in WP0/WP4. Use a small evidence table; defer a universal invariant registry and sentence-scanning CLI. |
| [10 — negative/auth paths](../../docs/drydock_planning/FEATURE-10-obligate-negative-path-and-authorization-acceptance.md) | Retain negative tests required by approved sources for represented capabilities. Defer `SECURITY`, `Auth`/`Roles` headers and inferred universal authorization requirements. |
| [11 — prompt I/O](../../docs/drydock_planning/FEATURE-11-validate-prompt-frontmatter-against-the-artifact-i-o-matrix.md) | Audit actual injected inputs, prompt registry and source/wheel parity in WP2/WP4/WP5. Header presence alone proves no injection. Defer similarity thresholds and new prompt-validation CLI. |
| [12 — brownfield baseline](../../docs/drydock_planning/FEATURE-12-add-a-baseline-mode-so-drydock-can-plan-against-code-that-al.md) | Defer baseline import/verify modes and reset flags. Preserve existing accepted work and valid no-op execution in WP1/WP4. |

Additional archived proposals: deterministic plan admission/repair belongs in WP2; required
negative/guardrail evidence is audited against current Sea Trials policy in WP1, without restoring
retired `Required`/`Consequence` semantics; Python/Go runtime availability belongs in WP1/WP5,
without inventing a runtime plugin system; compact provenance belongs in WP2; bounded repeated
build attempts belong in WP4. New `POLICY` types and fleet assertions remain deferred. Archive
recommendations overlapping the twelve rows receive the same disposition.

Current-code anchors that invalidate a wholesale July implementation:
`plan_graph.interface_dependency_defects` validates reachable declared providers;
`plan_graph.measure_stories` explicitly marks excess size without refusal;
`build_run._snapshot_files` measures file changes; `build_run.build_target` distinguishes governed
gates from model criteria; `proof_integrity.py` records why speculative analyzers were removed;
`lifecycle.Policy` bounds build passes; `rigging_compact._is_stale` has both mtime and source
SHA handling. These establish mechanisms, not complete protection. In particular, compaction's
mtime fast path still needs a changed-content/newer-derivative regression before calling freshness
proved. Existing code and tests must be re-read at implementation time.

### Historical WP0 baseline and finding matrix

`2026-10-26` · Initial state: HEAD `32a35ff`, clean tree. `.venv` Python 3.12.13, editable
`drydock` 0.8.0 from `src/`, pytest-xdist 3.8.0, hatchling importable, `uv.lock` present. Ruff
0.15.2 is not in `.venv`; it resolves from `~/.local/bin`, and `bin/test.sh` lints `.` rather than
`src/ tests/`. No gate was run: WP0 changes no code. Candidate identity is not yet established.

UAT-access audit: pytest collects no test that reads published `uat/`. `tests/uat_corpus.py`
`_regenerate`, run only as `python tests/uat_corpus.py`, globs `uat/*/runs/*` read-only (F21).

Ledger inventory (`design/skills/ddk-uat.md`, 198 rows): 34 `fixed`, 93 `unverified`, 55 `open`,
16 `recurred`. Every open/recurred row maps to one finding below; `unverified` rows stay with
their fixes and close only on Ed's evidence. Rows are cited as Kit run (FX FxRates, RL
ReadingList, LT LayersTesting, CM CommonMark, DF DupFind, CS CsvStat, DS DrydockStats, JQ jq).
Status: **covered** local regression exists, needs candidate rerun · **open** no fix ·
**confirmed** open defect re-read in current code · **undetermined** cause not established.
Ed verification is pending for every row. WP references below are historical; the execution
queue below supplies the current order and scope.

| Id | P | Requirement → earliest owner | Ledger evidence | Status | WP |
|---|---|---|---|---|---|
| F01 | P0 | Console, Manifest and status report the persisted per-story state → `build_run`/`cli`/`plan_repair` | RL 1022.195456 (console verified vs implemented); FX 1026.011843 (unrun criteria read verified); DS 1026.011913 (stale plan error after repair); FX 1024.051856 (`AC_BROKEN` not printed) | RL row covered (`build_run.py:4566` per-block state); others open | WP1 |
| F02 | P0 | An unexecuted or undeclared-tool check never becomes PASS → acceptance/`plan_graph` | DS 1026.011913, CM 1026.173709 (undeclared `executable`); FX 1026.011843 | open; unavailable-prerequisite regression exists | WP1 |
| F03 | P0 | Generated project tests never write the canonical store → language testing adapter | FX 1026.173232 (`cli_runner` against application DSN) | per-call isolation covered (`938021a`); per-test open | WP3 |
| F04 | P0 | Acceptance runs against a schema-provisioned store; schema evidence is deterministic → `database_apply`/`plan_verify` | RL 1022.195456 ×2; LT 1020.145335; RL 1022.220045 (recurred `9a71e69`) | open/recurred | WP3/WP1 |
| F05 | P0 | Build agents never mutate Drydock's own manifests → executor environment | FX 1024.073528 (recurred, `39e4e10`; `test_llm.py:774`) | covered, recurred once; needs proof | WP3 |
| F06 | P1 | In-plan criteria gate equals terminal `plan verify` → `planning_session.kinded_criteria_defects` | LT 1021.235036; JQ 1021.020003; FX 1024.015228 | `0ab6649` claims parity; audit | WP2 |
| F07 | P1 | Checked-call analysis accepts caller-asserted helpers → `harness_exits`/`acceptance` | CS 1025.001433 (recurred `1688130`); DS 1026.011913 ×2 | open | WP2 |
| F08 | P1 | Malformed artifacts recover within budget with a targeted, differing retry → `artifact_blocks`/`planning_session` | FX 1024.172824, DF 1024.183232 ×2, CM 1026.173709; recurred: LT 1021.173113, CM 1024.231239/233753, FX 1025.014047/184822/200850/230142 | provider defect recorded; recovery covered by `56a363c`/`683c3ee`; audit | WP2/WP4 |
| F09 | P1 | Unattended refusals are refuted correctly and stalls state why → `plan_blocked._refutation`, stall detail | LT 1022.121722 (recurred); FX 1023.234755 ×3 | open | WP4 |
| F10 | P1 | DATABASE authoring defects get exact corrective feedback → `database_contract` | FX 1024.162029/172824 (recurred), FX 1025.184822 ×3; LT 1025.160726 ×2; LT 1020.132808 | partly covered (`f63494c`); audit | WP2 |
| F11 | P1 | Topology covers every analyzed id with a legal owner; stacks have foundations → `plan_topology`/`plan_graph` | FX 1024.183153, 1025.014047 (recurred), 1025.192942, 1025.230142 (recurred), 1026.011843 | open | WP2 |
| F12 | P1 | Build receives governed source context → `build.py` context roots | FX 1026.011843 block-3 | confirmed: `build.py:138-139` roots omit `blueprint/sources/` | WP2 |
| F13 | P1 | Repair loop measures regression, stalls on no progress, keeps attempt history, routes next step → `build_run`/`cli` | RL 1022.231143 ×2 (constant `BUILD_FAILURE_HINT`, confirmed `build_run.py:165`); CM 1025.023211 ×4; DS 1026.011913 | open | WP4 |
| F14 | P1 | `plan repair` handles every authored criterion form and keeps the model's reason → `plan_repair` | DF 1024.183232 ×3 | open | WP2/WP4 |
| F15 | deferred | Parsed policy fields promise only implemented effects → `gate_policy`/`sea_trials` | FX 1026.011843 (`Consequence` parsed, `fold` ignores) | Scoring/policy changes excluded by Ed for this pass | deferred |
| F16 | P2 | Diagnostics name the failing span, assertion and ids → `output_format`/`cli`/`lineage_attribution` | RL 1023.022430; FX 1024.070101; LT 1020.161323; DF 1024.183232 (comma-only `stories=` split, confirmed `lineage_attribution.py:117`) | open | WP4 |
| F17 | P2 | Provider auth/quota stops are classified as provider stops → `llm` | LT 1021.141704; CS 1024.221659 | open | WP4 |
| F18 | P1 | Refit pending-source and no-frontier stop are truthful → `refit`/`uat` | RL 1014.031551 ×2 | undetermined / open | WP4 |
| F19 | — | Causes not established | LT 1020.132808, 1020.161323; RL 1014.040547 | undetermined; needs Ed-requested evidence | — |
| F20 | P2 | Plan artifact names and citations satisfy validation → `planning_session`/`validate_specification` | RL 1022.195456 (`VERIFICATION.md`); DF 1024.080843 | open | WP2 |
| F21 | P2 | No repository script reads published `uat/` implicitly → `tests/uat_corpus.py` | WP0 audit | open; not run | WP5 |
| F22 | P0 | Represented stores have tested isolation → `AgentStore`, Go harness | PostgreSQL pass-through (WP3.6); Go criteria outside harness transaction (`acceptance_criteria.md` Action) | PostgreSQL excluded by Ed; Go database gap requires an actually represented path, not merely a Go kit | S2 / deferred |
| F23 | P1 | Stale compacts never reach assembly → `rigging_compact._is_stale` | `acceptance_criteria.md` Action (stale `sqlite`/`postgres`/`persistence` compacts) | open; mtime fast path unproved | WP2 |

Capability profiles, inferred from ledger text only (unconfirmed; `uat/` not read):

| Kit | Language | Interfaces | Store | Conformance/grader |
|---|---|---|---|---|
| FxRates | Python | CLI, FastAPI HTTP | SQLite | grader, `sh` |
| ReadingList | Python | HTTP app server | SQLite | refit, `import --update` |
| LayersTesting | Python | CLI | SQLite inferred; Ed confirms PostgreSQL is not used | grader |
| CommonMark | Python | library | none seen | spec corpus, `sh` |
| CsvStat, DupFind | Go | CLI | none seen | grader |
| DrydockStats | Go/Python unclear | CLI | none seen | grader, `sh` |
| jq, Quakes | unclear | unclear | unclear | corpus (jq) |
| Toml | not established here | not established here | not established here | Ed confirms kit membership |

### Review correction — 2026-10-26

Retain the existing implementation and regression work. Replace the broad WP1–WP4 audit gate
with six ordered delivery slices. The plan is a completion queue, not an instruction to implement
all 23 historical finding groups. PostgreSQL and scoring changes are outside this pass.

Ed uses a manual stabilization loop: run one kit, invoke `/ddk-uat` on the failure, authorize
repairs as appropriate, review the work, then rerun. This plan does not require adopting
`drydock run builder`, enabling automatic diagnosis, or removing that review stage. Build's
existing internal repair loop remains a subsystem to audit when exercised by a kit.

Ed may revise kit sources between runs. Record each run's source revision and distinguish changed
requirements from framework regressions. Freeze inputs for a comparison and final evidence;
source revisions do not automatically reopen unrelated framework fixes.

### Confirmed ten-kit matrix and current reported progress

Ed supplied this output from `drydock report uat_summary` on 2026-10-26 (30-day window).
`Y` is a reported success in that window; `—` is a blank in the supplied summary, not proof of
failure or that the provider was never tested. These are historical results, not verification of
one current candidate. The report was not rerun and published evidence was not inspected.

| Kit | Claude | Codex |
|---|---|---|
| CommonMark | Y | — |
| CsvStat | Y | Y |
| DrydockStats | Y | Y |
| DupFind | Y | Y |
| FxRates | — | — |
| LayersTesting | — | Y |
| Quakes | Y | Y |
| ReadingList | Y | Y |
| Toml | Y | Y |
| jq | — | — |

Prioritize FxRates and jq (no reported success), then CommonMark's outstanding path; preserve the
working kits as regression controls. The two report columns do not establish a new requirement
for all twenty kit/provider combinations to pass. Record which provider/model produced each
confirming result; do not silently generalize success to other providers.

### Database scope and initialization

PostgreSQL remains an intended supported backend. Ed excludes PostgreSQL installation and live
PostgreSQL testing from this stabilization effort. Preserve its adapter and shared SQL contracts;
use existing deterministic checks where relevant to changed code. SQLite is the exercised backend.
Record PostgreSQL runtime/isolation as unverified; SQLite success is not PostgreSQL test evidence.
Do not add a PostgreSQL test gate or remove support to close this plan.

There is no missing `METADATA.md` blocker. `drydock init` writes it and initializes the Target's
Git repository (`init_target.py:118`, [init memory](../commands/init.md)); plain `git init` alone
does not write it. The former unknown tenth kit was a catalogue question, now resolved as Toml,
not a missing Target file. A real initialization failure, if encountered, belongs to Init and
must be reproduced there rather than treated as information Ed must supply.

### Layered acceptance and TDD audit checklist

Use this checklist within S1–S4. Prefer deterministic parsing, validation and execution wherever
the contract permits it; use source review for semantic claims a tool cannot establish. Existing
passing checks close audit items without a rewrite. Each unchecked item gets a named owner and
proof, not a new blanket release prohibition. No new framework or universal AC schema is required.

| Layer | Required checks | Owner / proof |
|---|---|---|
| 1. Requirements | Every required behavior has an AC or explicit non-executable review; each AC traces to approved source; no initial/update leakage or invented requirements. | Analyze/Plan; source-to-AC coverage and semantic review. |
| 2. Oracle | Expected values, ordering, tolerances and error behavior follow source; fixtures satisfy preconditions; asserted outputs are independent of the implementation being judged. | Plan/AC; small known-correct and deliberately wrong examples; unknown semantics stay uncertain. |
| 3. Executability | Names/imports, declared tools, runner arguments, nonempty selection, schema and readiness are valid; admission and terminal verification agree. | Plan/Verify/foundations; deterministic rejection plus a valid neighbor. |
| 4. Delivery | Each block's AC requires only available capabilities; source prerequisites reach the graph; later integration criteria retain full coverage. | Plan/Build; temporary whole-plan regression, serialized graph and computed blocks. |
| 5. Isolation | Test setup is reproducible; independent connections/subprocesses use the intended store; cleanup preserves canonical data and earlier accepted work. | DATABASE/executor; sentinel, repeated-run and failure-path tests. |
| 6. Measurement | Checks exercise the real product, execute the intended cases and assert meaningful outcomes; unavailable/skipped/zero-case work is never PASS; overlapping suites are not double-counted. | Acceptance/Build/Status; actual executor results agree with stored and displayed states. |
| 7. Repair and closure | Reproduce → identify owner → add failing regression → fix → pass the regression and affected neighbors → review → Ed reruns; preserve the accepted behavior set. | Owning command memory and /ddk-uat ledger; fix commit plus later affected-stage evidence. |

- [ ] For each active finding, record source requirement, AC/check identity, fixture/input revision,
  expected result, observed result and failure owner before changing behavior.
- [ ] For a framework defect, make the local regression fail for the diagnosed reason before the
  correction; make it pass afterward. Reuse an existing reproducer when sufficient.
- [ ] For generated products, retain baseline observations and existing governed verification rules.
  An already-correct/no-op step need not be forced red; do not reintroduce a universal RED gate.
- [ ] A failed assertion is an observation, not automatic proof that product code is wrong. Route
  faulty oracles to their source/authoring owner, execution failures to the adapter/environment,
  and correct-AC failures to implementation. Model prose alone cannot invalidate an AC.
- [ ] Do not weaken assertions, reduce selected coverage, change expectations, or increase budgets
  just to get green. Correct a proved bad criterion against approved intent and retain its history;
  Ed owns governed kit edits. Revalidate affected downstream evidence after such a change.
- [ ] Stop a local repair at its existing budget or when evidence cannot distinguish causes. Keep
  the failure and missing proof visible for Ed's review; do not launch a new unattended outer loop.
- [ ] Finish only when required behavior is covered, applicable AC actually pass, protected state
  survives, and no reproduced in-scope defect remains. Unmeasured behavior remains unverified.

### Manual diagnosis, repair and review handoff

1. Ed runs the selected kit and chooses the failure/run to inspect.
2. `/ddk-uat` reads the relevant memories, ledger and preserved evidence; classifies the earliest
   cause and distinguishes source, AC, framework, product, provider and environment ownership.
3. A diagnosis alone updates the ledger. An explicit repair request authorizes the coherent local
   fix, regression, memory/changelog and commit; do not ask again for that same authorized work.
4. Return a compact review packet: cause and evidence, changed files/commit, tests and outcomes,
   residual uncertainty, and the exact condition/affected stage to check next. Ed reviews it.
5. Ed reruns. A locally passing fix stays `unverified` in the ledger until a later clean affected
   stage supports `fixed`; recurrence revisits the existing fix instead of adding another layer.

The skill reports material findings once and puts durable detail in memory/ledger. Source review
and deterministic checks remain thorough even when the chat report is short. This plan revision
also updates the repository skill and its versioned diagnostic prompt for that handoff.

### Review findings

1. **Scope is still expandable.** WP3 includes remote resources, secrets, process ownership,
   hard kills, parallel workers and universal per-test adapters without evidence that all are
   needed by these kits. Retain the catalogue as deferred risk inventory; require implementation
   only for a reproduced violation on an active path.
2. **Historical rows are mistaken for current defects.** F06/F08/F13 mix implemented fixes,
   unresolved causes and live proof. `0ab6649` already supplies a complete synthetic planning
   correction/exhaustion test. Repeat that test before editing its mechanism.
3. **The central planning risk needs a distinct proof.** CommonMark's latest failure involved
   unsupported probe expressions, already addressed locally. Its omitted block-before-inline
   sequencing is a separate authoring problem. `interface_dependency_defects` checks declared
   relationships; it cannot discover a source dependency omitted from both `consumes` and
   `depends`. Prompt instructions alone do not prove delivery of the intended stages.
4. **Internal repair needs connected proof.** Existing tests cover case progress, skipped
   measurement, losses and feedback. Connect exercised internal behaviors through a bounded
   multi-block regression. This does not replace Ed’s manual diagnosis/review/rerun loop.
5. **F22 conflates language and storage.** PostgreSQL is not tested in this effort. Go CLI
   coverage does not prove a Go database path exists. Defer PostgreSQL; require Go database isolation only if represented
   and unsafe. Keep the demonstrated SQLite boundary in scope.
6. **F02 overstates its evidence.** An undeclared-tool warning is not itself proof of a false PASS.
   Test execution outcomes separately from declaration quality. Keep unexecuted checks unverified;
   do not promote every warning into a new gate.
7. **F13 needs path-specific reproduction.** The generic `BUILD_FAILURE_HINT` is consumed by
   `cli.py`, but `_failed_story_recovery_commands` also supplies owner-specific recovery. Reproduce
   the contradictory rendered output before replacing recovery behavior.
8. **F23 names the wrong function.** Current freshness is `rigging_compact._is_stale`, with an
   mtime fast path. Test changed source bytes under equal/older timestamps through the actual
   assembly consumer, not just the compaction helper.
9. **Memory coverage exists.** `design/commands/` has the command memories and linked topic
   contracts. Its coverage test checks presence, format and indexing; it does not establish that
   recorded behavior is correct or that every open action blocks this release.

### Execution boundaries

Repository rules continue to apply: Ed alone runs UAT; agents neither inspect published `uat/`
without his request nor write or run Git there. Audit test paths before execution; stop an unsafe
verification and continue independent safe work. Use temporary resources and fake providers;
no live calls or API spending are authorized by this plan. The master specification requires
block-specific permission. Preserve unrelated work, sources and canonical data; stage task files
only and commit locally without pushing. Detection and backups do not establish confinement;
never restore over concurrent changes. An unavailable or failed required check leaves its gate open.

### Execution queue

Read the owning command memory's Current contract, Intent, Guardrails and relevant linked topics
before each slice. State authority, permitted mutations, invariants and the falsifying test.
Update Details and Actions in the same commit as an implementation change. Never rewrite
Intent/Guardrails/Decisions merely to match code. Preserve the existing ledger's historical rows.

| Order | Deliverable | Findings | Completion proof |
|---|---|---|---|
| S1 | Truthful execution and closure | F01/F02; existing F13 reporting paths | One table connects actual execution, criterion outcomes, persisted story states, console and `status`; fake success/no-run/partial/failure and valid verification-only cases agree. |
| S2 | Existing SQLite and workspace protection | F03/F04/F05; represented part of F22 | Through build orchestration, provider children receive a provisioned disposable DSN; canonical sentinel and parent manifests survive success/failure; two project tests cannot contaminate each other. Keep canonical acceptance's separate lifecycle. |
| S3 | Source-complete incremental planning | F06/F08/F10/F11/F12; relevant F07/F14/F23 | Complete temporary Target: source instructions reach the consumed prompts; stage dependencies and scoped criteria permit incremental delivery; invalid probes receive bounded authoring correction; exhaustion remains unbuildable. |
| S4 | Internal build recovery and manual review handoff | F13; reproduced F09/F17/F18 | Multi-block synthetic scenario: partial gains, unmeasured call, regression, recovery, exhaustion and resume; earlier accepted work survives; per-check denominators and attempt history remain truthful; next command belongs to the failing owner. |
| S5 | Local candidate | F21 and local gate failures | Audited full deterministic suite, lint, formatting and package smoke pass on one identifiable code revision. No published-UAT access or live provider calls. |
| S6 | Ed’s manual run/review/rerun confirmation | FxRates, jq, outstanding CommonMark path; working-kit controls and final matrix | Ed runs each kit, reviews /ddk-uat findings and authorized repairs, then reruns. Retain confirmed results and exact candidate/input/provider identity; synthetic tests do not prove live convergence. |

S1 and S2 protect evidence and data first. S3 and S4 address the actual planning/build convergence
risk; they must not be postponed behind unrepresented resource hardening. Do not implement F12
alone and declare planning stable: verify source consumption and the resulting staged work.

Use existing regression fixtures and fake runners. Add a fixture index only if multiple cases
need it; a new fixture framework is not a deliverable. Each new negative test needs a valid
neighbor so fixes do not reject previously working kits.

#### Specific S3/S4 test contracts

- Source context: a temporary `blueprint/sources/INSTRUCTIONS.md` appears with provenance in the
  consumed build prompt. Cover explicit `sources/...` references, basename lookup, collisions,
  missing files and read-only source preservation; decide precedence from current source contracts.
- Planning: use a small parser/transformation source with prerequisite stages, an independent
  sibling and a final conformance story. Verify source instructions reach topology authoring;
  declared provider/consumer omissions are rejected; valid dependencies survive serialization,
  verification and grouping; independent work still groups. No CommonMark-specific graph rule.
- A fake response containing the correct dependencies proves execution of those dependencies,
  not that a real model reliably authors them. Ed's CommonMark/jq plan inspection closes that gap.
- Corpus selection: preserve exact selected IDs/counts and runner arguments; empty selection,
  unresolved expressions and unsupported protocols cannot masquerade as measured success.
- Iteration: use per-check case identity where available, otherwise per-check counts with an
  explicit limit on what they prove. Never sum overlapping full/scoped suites. A skipped grade
  changes neither measured progress nor flat-pass history. Real regression gets first repair
  priority; budgets terminate. Do not invent automatic rollback or change budgets to obtain PASS.
- Resume: retain previous attempt evidence and accepted blocks; compare only measurements with
  the same criterion/input identity. Kit edits invalidate affected comparisons, not unrelated fixes.

### Finding disposition and closure

The F01–F23 inventory remains historical traceability. Before changing a finding, record exactly
one current disposition: reproduced blocker; locally covered awaiting live proof; uncertainty
awaiting a named observation; or deferred outside this candidate. A historical `open`/`recurred`
ledger status alone does not require another code change.

For each implementation slice maintain one row:

`finding | owning memory | current repro | regression node | fix commit | local result | live proof`

- F15 (scoring/policy) is deferred by Ed's scope instruction; do not change scoring or gates.
- F16/F20 remain optional diagnostics unless reproduced as preventing the active workflow.
- F19 remains uncertainty; it cannot hold all implementation until historical evidence is read.
- F21 prevents the unsafe script from being used; its existence does not prohibit independent
  audited tests. Any repair must eliminate implicit reads of published evidence.
- F22 PostgreSQL is deferred. Go database isolation remains conditional on actual capability use.
- F23 requires a current consumed-staleness reproduction; avoid a broad compaction redesign.

A new blocker enters this queue only with a violated approved contract, current reproduction,
owner and closure test. Repeated warnings, recovered envelopes and provider stops must remain
visible, but do not automatically expand implementation scope. Preserve the existing clean-run
standard for proved defects; do not call recovered defects fixed without affected-stage proof.

### Verification and finish line

During implementation, run focused local regressions for each coherent slice and commit locally.
Do not rerun all kits for every patch. After the final local slice, run repository gates once;
rerun affected checks after any correction. Record exact commands, interpreter, results and SHA.
Resolve Ruff's actual executable path instead of prescribing the absent `.venv/bin/ruff`.

Ed continues the manual kit-run → `/ddk-uat` → authorized repair → review → rerun workflow.
Prioritize FxRates/jq and the outstanding CommonMark path using the supplied matrix. When Plan
is the failing owner, first establish buildable stage dependencies and executable AC; a repeated
Build against the same unbuildable plan is not useful evidence. No new operator command is required.

All ten kit names are known and `METADATA.md` is initialization-owned; neither blocks S1–S5.
The final release record identifies the candidate, chosen input revision and provider/model for
each kit. Freeze each kit's inputs for its confirming run. Source edits invalidate affected
comparisons; implementation edits require affected local/development reruns and final matrix
confirmation. Keep existing release semantics; this pass neither redesigns scoring nor invents
a twenty-cell provider gate.

Completion has two distinct states:

1. **Implementation complete:** S1–S5 pass; no reproduced in-scope blocker remains; remaining live
   proof and deferred capabilities are listed explicitly.
2. **Release verified:** S6 supplies the required live evidence on the final candidate. A live
   failure is reduced to a regression and repaired at its owner; it does not reopen the whole plan.

## Decisions

- `2026-10-26` · Ed approves concise current contracts, assistant-owned assumptions review and
  explicit guardrails; unproved intermediate cases remain uncertainty.

## Questions

- None. The workflow, ten kit names, database-testing scope and review ownership are resolved.
  Ask only if a future diagnosis exposes conflicting source intent or a material unresolved decision.

## Actions

- `2026-10-26` · Execute S1–S4 in order, reusing existing regressions and changing only reproduced
  in-scope defects. Each slice closes on its stated proof, owning-memory update and local commit.
- `2026-10-26` · Complete S5 local gates and record one candidate identity. Historical test
  results do not close this gate.
- `2026-10-26` · S6: Ed continues kit execution, /ddk-uat diagnosis, repair review and reruns,
  prioritizing FxRates/jq and outstanding CommonMark evidence. Close on the final ten-kit record
  with exact inputs/provider/candidate; historical Y cells alone do not close this action.

## Working Notes

- `2026-10-26` · Review baseline `fae8250`. Read command/topic memories, current code, regression
  tests and the design ledger; no published `uat/` evidence inspected and no UAT executed.
  Review changes the delivery plan, not runtime behavior or historical verification outcomes.
- `2026-10-26` · Review verification at `fae8250`: `.venv/bin/python -m pytest -q
  -p no:cacheprovider` over `tests/test_design_coverage.py`, `tests/test_plan_reliability.py`
  and `tests/test_build_state.py`: 76 passed (72.01 s). Python bytecode disabled, `.venv/bin`
  first on PATH, temporary resources under `/home/barlo/drydock-review-test-proof`.
  This verifies existing narrow coverage, not S1–S5 completion or live model convergence.
- `2026-10-26` · Ed clarified the manual review loop and supplied all ten kit names/results.
  V6 restores structured deterministic audit checklists, makes AC correctness/coverage central,
  and distinguishes excluded PostgreSQL testing from preserving backend support.
- `2026-10-26` · V6/skill verification: design coverage, prompt loading/headers and skill
  provisioning checks: 97 passed. Skill validator passes; wheel builds and its diagnostic prompt
  matches source V9 byte-for-byte. Claude/Codex resolve the same repository skill 1.4.0.
  Diff checks pass. No live diagnosis/model call or UAT was run; runtime stabilization remains open.

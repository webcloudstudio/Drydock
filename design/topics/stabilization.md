# MEMORY: stabilization

| Field | Value |
|---|---|
| Version | 2026-10-26 V7 |
| Description | Bounded UAT stabilization plan with historical proposal dispositions, truthful verdicts, state ownership and Target-independent verification. |
| Modules | `acceptance_oracle.py`, `planning_session.py`, `build_state.py`, `build_run.py`, `diagnose.py` |
| Prompts | `uat_diagnostic.md`, `build.md`, `BLUEPRINTS_CONTRACT.md` |
| Tests | `tests/test_acceptance_oracle.py`, `tests/test_build_state.py`, `tests/test_build_run.py`, `tests/test_plan_reliability.py` |
| Governs | [plan](../commands/plan.md), [build](../commands/build.md), [diagnose](../commands/diagnose.md) |

## Intent

Make approved requirements and resource ownership observable before implementation, and make
repeat failures reproducible without rebuilding complete projects after each correction.
Apply the same acceptance and repair contracts to any Target selected by Ed.

## Guardrails

- `2026-10-26` · Ed approves proactive rules for proved constraints; unproved cases remain
  uncertainty. Static uncertainty never authorizes new rounding, changed expected values,
  broader permissions or weakened gates.
- `2026-10-26` · The assistant owns assumptions review and evidence collection; Ed supplies
  unresolved product decisions. Skipping the review can silently replace the approved goal.
- `2026-10-26` · No agent runs or mutates UAT evidence. Ed selects and runs live validation. Local tests
  use private temporary resources and fake provider replies; live subscription calls require
  the authorization applicable to that experiment.

## Details

### Current contract

`2026-10-27` · AgentStore retains the fingerprint fast path; on change it compares a consistent SQLite backup with the pre-call backup, including schema, rows, rowids and relevant metadata. Concurrent physical changes or unreadable comparisons fail closed. WAL-only checkpoint activity can proceed without restore. This remains detection, not an OS sandbox.


| Concern | Contract |
|---|---|
| Authority | Approved intent defines correctness; implementation establishes observed behavior. |
| Review owner | Assistant reads current contracts and states invariants, owners, uncertainties and falsifying tests before editing. |
| Validation | Proved violations block; proved allowed behavior proceeds; unsupported inference stays unknown. |
| Mutable state | Every resource has an owner, scope, permitted mutations, cleanup and failure action. |
| Recovery | Preserve evidence and data; route recovery to the owner; never silently overwrite possible concurrent writes. |
| Proof | Deterministic regressions precede Ed-selected live validation; any separately authorized live experiment supplements them. |
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

This is the resource catalogue. S2 records which rows are exercised by the affected command paths,
which protections exist and which gaps block those paths; unrepresented adapters stay deferred.

| State | Scope and isolation | Owner / required verification |
|---|---|---|
| Imported sources, scoring assets, Blueprints | Immutable during Build; compare hashes, reject unauthorized changes. | Import/Plan; existing staged-asset guard, extend coverage for all governed files. |
| Generated framework code and schema/provenance | Regenerate only through the owning lifecycle step. | DATABASE/foundation; verify fingerprints and ownership before/after calls. |
| Application DBs, files, uploads, object storage | Fixture-owned test namespace, schema and seed; preserve canonical state. | Store owner; SQLite call and per-test (pytest) isolation implemented, remote adapters pending. |
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
calls, correct the owning boundary, then validate the candidate on Ed-selected Targets. V2's
weaknesses were an unbounded resource-hardening gate, insufficient attention to truthful closure
and release evidence, and no disposition of the July proposals. This revision bounds the release
scope and inserts those missing proofs. It changes the implementation plan, not product behavior.

The request in this session is to review and update the plan. Execution begins when Ed requests
implementation; the plan itself does not grant new permissions. During execution, complete
ordinary implementation, verification and local commits without phase-by-phase approval.

**Release scope:** existing supported command paths and the capabilities exercised by the
affected Targets. Fix demonstrated contract violations and shared mechanisms that cause them. Do
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

### Plan authority and Target independence

This file is the implementation handoff: scope, invariants, audit checklist, work order, finding
closure and unfinished actions are recorded here. The linked command/topic memories remain the
authority for their individual contracts; implementation work updates those owners as needed.
No chat-only instruction or temporary review draft is required to continue.

Drydock can operate on any Target. Do not keep a kit roster, provider pass matrix, fixed Target
count or named-Target priority queue in this plan. Ed chooses live runs; historical finding
citations below identify where a generic defect was observed, not the allowed project set.

`/ddk-uat` maintains one diagnosis memory per Target, created only when diagnosing that Target:
`design/skills/ddk-uat/targets/<Target>.md`. Resolve the actual Target and memory filename with
case-aware directory checks before reading or writing. The skill memory defines resolution,
format and update rules. The existing central ledger is historical evidence, not a new roster.
### Database scope and initialization

PostgreSQL remains an intended supported backend. Ed excludes PostgreSQL installation and live
PostgreSQL testing from this stabilization effort. Preserve its adapter and shared SQL contracts;
use existing deterministic checks where relevant to changed code. SQLite is the exercised backend.
Record PostgreSQL runtime/isolation as unverified; SQLite success is not PostgreSQL test evidence.
Do not add a PostgreSQL test gate or remove support to close this plan.

There is no missing `METADATA.md` blocker. `drydock init` writes it and initializes the Target's
Git repository (`init_target.py:118`, [init memory](../commands/init.md)); plain `git init` alone
does not write it. There is no catalogue prerequisite. A real initialization failure, if
encountered, belongs to Init and
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
| 7. Repair and closure | Reproduce → identify owner → add failing regression → fix → pass the regression and affected neighbors → review → Ed reruns; preserve the accepted behavior set. | Owning command memory and Target diagnosis memory; fix commit plus later affected-stage evidence. |

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
2. `/ddk-uat` reads the relevant memories, Target diagnosis history and preserved evidence; classifies the earliest
   cause and distinguishes source, AC, framework, product, provider and environment ownership.
3. A diagnosis alone updates its Target diagnosis memory and index link. An explicit repair request authorizes the coherent local
   fix, regression, memory/changelog and commit; do not ask again for that same authorized work.
4. Return a compact review packet: cause and evidence, changed files/commit, tests and outcomes,
   residual uncertainty, and the exact condition/affected stage to check next. Ed reviews it.
5. Ed reruns. A locally passing fix stays `unverified` in the Target diagnosis memory until a later clean affected
   stage supports `fixed`; recurrence revisits the existing fix instead of adding another layer.

The skill reports material findings once and puts durable detail in the Target diagnosis memory. Source review
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
| S6 | Ed’s manual run/review/rerun confirmation | Any Ed-selected Target exercising affected capabilities | Ed runs the Target, reviews /ddk-uat findings and authorized repairs, then reruns. Retain exact candidate/input/provider identity; synthetic tests do not prove live convergence. |

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
  verification and grouping; independent work still groups. No Target-specific graph rule.
- A fake response containing the correct dependencies proves execution of those dependencies,
  not that a real model reliably authors them. Ed's affected-stage live validation closes that gap.
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

Ed continues the manual Target-run → `/ddk-uat` → authorized repair → review → rerun workflow.
When Plan is the failing owner, first establish buildable stage dependencies and executable AC;
a repeated Build against the same unbuildable plan is not useful evidence. No new operator
command, Target list, `METADATA.md` question or provider matrix is required.

Record candidate, input revision and provider/model with each confirming run in that Target's
diagnosis memory. Source edits invalidate affected comparisons; implementation edits require
affected local checks and appropriate live confirmation. Preserve existing release semantics
without inventing a fixed-count project/provider gate. No finite test set proves all possible
projects; close the demonstrated generic defects and report the actual validation limits.

Completion has two distinct states:

1. **Implementation complete:** S1–S5 pass; no reproduced in-scope blocker remains; remaining live
   proof and deferred capabilities are listed explicitly.
2. **Release verified:** S6 supplies the required live evidence on the final candidate. A live
   failure is reduced to a regression and repaired at its owner; it does not reopen the whole plan.

### Slice ledger

`finding | owning memory | current repro | regression node | fix commit | local result | live proof`

| Finding | Owner | Current repro | Regression | Fix | Local | Live |
|---|---|---|---|---|---|---|
| F02 absent result read as PASS | build | executor returning no result closed story `closed/verified` | `test_build_truthful_closure.py` `[no-run]`, `test_absent_results_are_reported_as_not_executed` | 0338ebe | fail before, pass after | pending |
| F01 `AC_BROKEN` line dropped | build | `_stream_build_summary` filtered the line | `test_cli.py` `test_stream_build_summary_shows_llm_scope_and_acceptance_only` | 0338ebe | pass | pending |
| F01 stale plan error after repair | plan | `_settle_plan_state` left `plan verify` error | `test_build_truthful_closure.py` `test_a_buildable_repair_retires_only_the_plan_verify_error` | 0338ebe | pass | pending |
| F03 project tests share call store | build | committed writes leak between tests in one call | `test_build_state.py` `test_two_project_tests_in_one_agent_call_cannot_contaminate_each_other`, falsifier `test_without_the_plugin_the_same_tests_collide` | 93acdf6 | pass | pending |
| F03/F04 provider failure path | build | none reproduced | `test_provider_failure_without_mutation_keeps_canonical_and_discards_snapshot`; build-level `test_agent_store_writes_are_isolated_and_deletion_stops_with_owner_recovery` | — | pass | pending |
| F05 parent manifests | build/llm | none reproduced; existing guard | `test_llm.py` `test_agent_registration_in_an_enclosing_uv_workspace_is_restored_and_fails` | 39e4e10 | pass | pending |
| F12 source brief missing from build | build | bare `INSTRUCTIONS.md` reported missing context | `test_build_source_context.py` (5) | 81e185d | fail before, pass after | pending |
| F23 mtime overrides changed sha | rigging | changed source older than compact read fresh | `test_rigging_compact.py` `test_changed_source_older_than_its_compact_is_stale` | 81e185d | fail before, pass after | pending |
| F07 projected helper exit | acceptance/plan | `return code, out` helper rejected | `test_harness_exits.py` projected-helper tests | 81e185d | fail before, pass after | pending |
| F14 undelimited / impossible reason | plan | empty-body model call; reason dropped | `test_plan_repair.py` two tests | 81e185d | fail before, pass after | pending |
| F06/F08 probe correction, exhaustion | plan | none; 0ab6649 regression rerun | `test_plan_reliability.py` `test_complete_plan_reauthors_probe_before_persisting_and_can_repeat` | 0ab6649 | pass | pending |
| S3 source → topology, staged deps | plan | none reproduced | `test_source_instructions_reach_topology_and_authoring_prompts`, `test_staged_dependencies_survive_serialization_verification_and_grouping` | — | pass | pending |
| F11 unfounded runtime stack | plan | warning only; causal link unproved | — | — | uncertainty; see Questions | pending |
| F10 DATABASE feedback | plan | not re-reproduced | existing `f63494c` coverage | — | audit only | pending |
| F13 regression-led repair label | build | `agent-reported` printed after a measured regression | `test_build_recovery_scenario.py` | d6cbf16 | fail before, pass after | pending |
| F13 dispute routing / owner recovery | build/cli | not reproduced; record and banner agree | `test_a_defect_claim_is_recorded_and_does_not_stop_the_loop` (banner), scenario recovery | — | pass | pending |
| F17 provider stop identifiers | llm | `usage_limit_reached` unclassified | `test_process_stop.py` parametrized classifier | d6cbf16 | fail before, pass after | pending |
| F09 unattended refusal | plan | not reproduced; `plan_blocked._refutation` unattended policy present | existing | — | audit only | pending |
| F18 refit pending source | refit/uat | undetermined; needs Ed-requested evidence | — | — | uncertainty | pending |
| F21 implicit `uat/` read | tests | `iter_live_runs` defaulted to repo `uat/` | `test_gate_policy_replay.py` `test_corpus_regeneration_reads_only_an_explicit_root` | ef68b55 | pass | — |
| F22 Go database / PostgreSQL | — | not represented / excluded | — | — | deferred | — |
| F01 state/console/status agreement | build/status | none reproduced beyond F02 | `test_execution_outcomes_manifest_console_and_status_agree` (5 rows) | — | pass | pending |

## Decisions

- `2026-10-26` · Ed approves concise current contracts, assistant-owned assumptions review and
  explicit guardrails; unproved intermediate cases remain uncertainty.

## Questions

- `2026-10-26` · F11: should a non-foundational first user of a stack with a runtime Foundation
  Contract (FastAPI `app_server/testing.py`) be a fatal topology defect routed to topology repair,
  instead of today's `unfounded-stack` warning? Evidence: FxRates `20261026.011843` row (no
  FastAPI foundation story; 10 criteria `ModuleNotFoundError`); `plan_graph.assign_stack_modes`
  already gives that story builder mode, so fatality is not proved to fix the run. Closes on Ed's
  decision; unchanged until then.

## Actions

- `2026-10-26` · S1–S4 *Closed 2026-10-26*: `0338ebe`, `93acdf6`, `81e185d`, `d6cbf16`; see Slice ledger.
- `2026-10-26` · S5 *Closed 2026-10-26*: candidate is `ef68b55`. See Working Notes.
- `2026-10-26` · Deferred, not reproduced or excluded: F09 audit, F10 audit, F11 (Question),
  F15 scoring, F16/F20 diagnostics, F18/F19 undetermined, F22 PostgreSQL/Go database. Each
  closes on a current reproduction with owner and regression, per Finding disposition.
- `2026-10-26` · S6: Ed selects Targets, reviews /ddk-uat diagnosis/repairs and reruns affected
  stages. Close each finding on later clean evidence with exact input/provider/candidate identity
  in its Target diagnosis memory; historical success alone does not verify a new fix.

## Working Notes

- `2026-10-26` · Review baseline `fae8250`. Read command/topic memories, current code, regression
  tests and the design ledger; no published `uat/` evidence inspected and no UAT executed.
  Review changes the delivery plan, not runtime behavior or historical verification outcomes.
- `2026-10-26` · Review verification at `fae8250`: `.venv/bin/python -m pytest -q
  -p no:cacheprovider` over `tests/test_design_coverage.py`, `tests/test_plan_reliability.py`
  and `tests/test_build_state.py`: 76 passed (72.01 s). Python bytecode disabled, `.venv/bin`
  first on PATH, temporary resources under `/home/barlo/drydock-review-test-proof`.
  This verifies existing narrow coverage, not S1–S5 completion or live model convergence.
- `2026-10-26` · Ed clarified the manual review loop.
  V6 restores structured deterministic audit checklists, makes AC correctness/coverage central,
  and distinguishes excluded PostgreSQL testing from preserving backend support.
- `2026-10-26` · V6/skill verification: design coverage, prompt loading/headers and skill
  provisioning checks: 97 passed. Skill validator passes; wheel builds and its diagnostic prompt
  matches source V9 byte-for-byte. Claude/Codex resolve the same repository skill 1.4.0.
  Diff checks pass. No live diagnosis/model call or UAT was run; runtime stabilization remains open.
- `2026-10-26` · V7 removes the mistakenly imposed kit roster, provider matrix and fixed-count
  validation gate. Ed confirms one diagnosis memory per Target with actual filename/case checks.
  Plan preparation is complete; S1–S6 implementation/live proof remains open as listed above.
- `2026-10-26` · V7 / prompt V10 / skill 1.5.0 verification: 97 focused tests pass; skill
  validation and wheel build pass; packaged diagnostic prompt matches source. No Target memory
  was precreated and no UAT or live provider was invoked.
- `2026-10-26` · S5 gates on the candidate: `.venv/bin/python -m pytest -p no:randomly -n auto -q`
  4608 passed, 2 skipped (1116 s, Python 3.12.13); `ruff check src/ tests/` and `ruff format
  --check src/ tests/` pass (`~/.local/bin/ruff` 0.15.2); `hatchling build -t wheel` plus a
  clean-venv install runs `drydock --help` and ships `pytest_store_isolation.py`. A run overlapped
  by a second suite showed two planning-probe failures that pass alone and under xdist: shared
  temporary resources between concurrent suites, not a candidate defect. No UAT, published `uat/`
  access or live provider call. S6 (Ed's live runs) remains open.

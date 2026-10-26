# MEMORY: stabilization

| Field | Value |
|---|---|
| Version | 2026-10-26 V3 |
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
| Execution | This revision plans the work; an execution request starts WP0 and prioritized release slices, each verified and committed locally. |
| Limit | Passing deterministic tests does not establish model convergence or undeclared semantic dependencies. |

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

### State inventory to complete

This is the resource catalogue. WP0/WP3 mark which rows are represented in the release matrix,
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

### Stabilization assessment and scope

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
`lifecycle.Policy` bounds build passes; `rigging_compact._fresh_sibling` has both mtime and source
SHA handling. These establish mechanisms, not complete protection. In particular, compaction's
mtime fast path still needs a changed-content/newer-derivative regression before calling freshness
proved. Existing code and tests must be re-read at implementation time.

### Execution contract

Before each slice, record the approved behavior, owner, allowed mutations, invariants, observed
facts, uncertainty, falsifying test and valid neighbor. Read the owning command/topic contracts,
source, prompts and tests. Extend an existing mechanism before introducing another. A successful
recovery remains evidence of a generating defect when that defect is proved.

#### Fixed boundaries

- Never invoke `drydock uat` in any form. Never write, stage or run Git inside `uat/`; inspect
  published evidence only when Ed requests it. Use the design ledger and synthetic fixtures here.
- Never edit `docs/Drydock_Specification.md` without block-specific authorization. Record any
  disagreement in the owning Memory File; a historical proposal does not resolve it.
- No live model/provider calls, API-key generation, charges or full project builds in deterministic
  verification. Any bounded live experiment needs applicable explicit authorization.
- Use the checkout and private temporary resources outside `uat/`. Preserve unrelated work,
  imported sources, governed acceptance, canonical data and previously accepted implementation.
  Stage only task files; inspect every staged diff; commit locally; do not push.
- Prove test paths before running them. A script/test that reaches published `uat/` is a defect:
  report it and stop that verification. Synthetic UAT orchestration tests use fake children and
  temporary kit roots; they never execute the UAT command.
- Detection, prevention and recovery are separate claims. Hashes and prompts do not sandbox
  arbitrary agent tools. Never automatically restore over changed data or reset a worktree.
- An unavailable, hanging or failed required check keeps its gate open. Record command, cause,
  owner and rerun; continue independent work, but do not advance the release candidate as passed.

#### WP0 — freeze scope and map evidence

1. Record HEAD, clean/dirty paths, Python/interpreter, dependency/lock state, test/lint/package
   availability and installed/source package identity. Candidate identity is the eventual final
   verified commit, not the initial HEAD. Preserve the initial state for comparison.
2. Read build, plan, diagnose, uat, score, acceptance-criteria, foundations, lifecycle and `/ddk-uat`
   memories plus affected linked topics. Reconcile documented and implemented contracts explicitly.
3. Create one finding table here: id, priority, source requirement, earliest failing owner/stage,
   evidence/commit, minimal reproduction, negative test, valid neighbor, fix commit, local result,
   affected kit capabilities and Ed verification status. Separate a proved defect from uncertainty.
   Map all open/recurred ledger findings; do not limit the inventory to the latest two incidents.
4. Seed the map with decimal normalization, unresolved probes, omitted source ordering, canonical
   test writes/deletion/recovery, false verified closure after unavailable tooling, missing source
   context, malformed artifact recovery, and console/persisted-state disagreement. Reuse existing
   tests; classify an existing fix as locally covered, needing proof, or recurred before rewriting.
5. Map the ten-kit capability profiles from authorized non-evidence configuration or Ed-provided
   data. Missing profiles do not block independent tests, but the matrix must be complete before
   release. Do not inspect `uat/` to obtain them without Ed's request.

**Exit:** bounded release backlog, capability/resource matrix, existing regression links and
explicit missing tests. Every item has an owner and closure proof. Counts from earlier commits
are historical evidence; they are not the new candidate's baseline.

#### WP1 — make execution, closure and verdict evidence truthful (P0)

1. Establish the current truth table from build/score/UAT contracts. For each path, assert child
   return code, provider outcome, declared/selected/executed check counts, criterion outcomes,
   governed-gate outcome, per-story persisted state, console state and release receipt agree.
   Preserve separate dimensions; a provider success is not successful verification.
2. Cover provider success with failed/absent acceptance setup, missing transport/tool, zero-case
   selection, malformed/unreadable criteria, skipped/timeout checks, partial governed coverage,
   mixed covered/uncovered siblings, and a valid verification-only/no-diff step. An unexecuted
   check never becomes PASS; no governed proof never becomes governed verification. Preserve
   existing legal `implemented` versus `verified`, prepassed and diagnostic-only classifications.
3. Separate assertion failure from diagnosed defect ownership. Source-backed Sea Trials and
   governed acceptance retain their current authority. No static uncertainty, missing proof or
   model-authored criterion silently becomes a product defect or a new release prohibition.
4. Regress score/release/receipt behavior using synthetic evidence and fake graders: malformed
   output, unknown/missing/duplicate trials, grader failure, legitimate advisory and actual governed
   failure. Retired policy fields must not promise effects the runtime ignores; record conflicts
   without silently reviving old gate rules. Never weaken an existing gate to make a kit pass.
5. Retain deterministic measured file/command facts separately from model narrative. Verify
   missing/false `FILES CHANGED`, tracked/untracked changes and no-op success. An empty diff alone
   does not determine correctness. Repair prompts may change implementation, not governed oracles.

**Exit:** truth-table regressions pass; all represented no-run/partial/failure paths retain truthful
states and owner-specific causes. Locally fixed ledger rows remain `unverified` pending Ed's run.

#### WP2 — prevent recurring plan and oracle defects (P1)

1. Preserve decimal text from serialized CSV/JSON/XML fixtures. Cover exact source values,
   unknown provenance, derived expressions and source-backed contradiction; no new rounding,
   quantization or normalization. Advisory remains visible and never triggers semantic repair.
2. Retain admission/verify parity for supported probe arguments, empty selection, executable tools,
   scoped/full suites, required foundation interfaces and dependency paths. Give every rejection a
   valid neighbor. Unknown/external dependencies stay legal where current contracts allow them;
   omitted source-defined stages require authoring feedback, not guessed domain edges.
3. Exercise a complete synthetic plan with injected outputs: initial defect, bounded correction,
   corrected admission, revalidation, exhaustion and recovery recommendation. Existing legal work
   survives malformed/truncated output. Repeating mechanical repair never substitutes for source
   authoring. Do not merely test the same helper through two wrappers.
4. Prove consumed source/context exists in the assembled prompt with correct path/provenance;
   foundation/provider first use precedes consumers; stack/runtime/test transport selections agree.
   Preserve source-required incremental delivery even when the graph permits grouping.
5. Audit compact freshness against changed bytes with unchanged timestamps and a newer stale
   derivative. If stale content can reach assembly, repair the existing freshness mechanism and
   use full source or the supported explicit recovery; do not add an unrequested model call.
6. Regress current size accounting, deduplication and grouping at the configured target. Keep
   advisory oversize behavior. Distinguish a target estimate from an actual provider context limit;
   no new hard ceiling or public schema is authorized by the July recommendation.

**Exit:** complete synthetic authoring/verify regressions pass and repeat with stable semantic
outputs; defects route to their earliest legal owner without rewriting approved requirements.

#### WP3 — protect represented state and isolate generated tests (P0/P1)

1. Complete the state inventory for actual release paths. For each resource record owner, scope,
   mutation entry points, protection level (prevented/detected/recoverable/unsupported), enforcing
   code, negative/positive test and residual risk. An unrepresented remote service is deferred;
   a represented destructive path cannot be released on a prompt promise.
2. First deliver the demonstrated SQLite path. Keep per-agent-call isolation and private backups;
   verify deletion, modification, WAL writes, provider exception, failed provisioning, missing
   canonical store, concurrent writer and backup access/ignore behavior. Never overwrite current
   data; provisioning an empty DB is not recovery. Preserve DATABASE-owner routing.
3. Enforce per-test isolation through the existing generated foundation/testing adapter for the
   selected language and runner. Use a temporary file/namespace when independent connections or
   subprocesses are required; rollback of one connection does not isolate another. Do not prescribe
   pytest for Go or invent a universal fixture protocol. Test two cases writing the same key,
   cross-connection access, assertion/collection failure, supported parallel workers and two runs
   against a canonical sentinel. Update templates and prompts with the enforcing code.
4. Trace governed acceptance separately: preserve its canonical schema-verification and
   rollback/committed lifecycle. Disposable development-test DSNs must not silently redirect the
   independent gate away from the application being assessed.
5. For represented file, config, Git, environment and process paths, verify authorized mutations,
   unchanged governed inputs/unrelated work, child-only environment, owned scratch cleanup,
   secret redaction, bounded readiness/timeout and termination of owned children. Port allocation
   must avoid a bind/release race where the harness owns the listener; no promise that every
   sequential check receives a different numeric port.
6. PostgreSQL remains a declared product capability, but `AgentStore` currently passes it through
   without isolation. Mark this gap explicitly. If a release path uses it, deliver and test the
   narrow namespace/fixture adapter or stop unsafe test execution before the agent call and report
   the unsupported case. If unrepresented, record the limitation outside this candidate; do not
   claim universal DB isolation or disable unrelated supported commands.

**Exit:** represented mutable resources have tested protection and recovery; no canonical-data
mutation is disguised as test cleanup. Unsupported cases and confinement limits are explicit.
Hard-kill cleanup uses owned leftovers and next-run reclamation where teardown cannot execute;
never promise `finally` runs after an unobservable process kill.

#### WP4 — bound recovery and align prompts with enforcement (P1)

1. Use fake children to cover lifecycle plan/verify/repair/build/refit/test/score sequencing,
   standing blockers, provider limit, actual context limit, timeout, repeated no-progress calls,
   restart and interruption at persistence/journal boundaries. Inspect current bounds before adding
   counters. Keep UAT `diagnose_attempts=0`; changing that policy is Ed's existing open decision,
   not a prerequisite for this stabilization pass.
2. Prove retry budgets terminate in the supported lifecycle and cannot accidentally reset inside
   its loop. Record any separate manual-invocation limit; do not silently invent a durable global
   budget, automatic model escalation or a new reopen command.
3. Recovery identifies owner/stage, preserved evidence, safe prerequisite and next legal command.
   Preserve accepted work on replan/resume; deterministic persistence/provider failures must not
   be overwritten by model prose or spend a diagnosis call to restate known facts.
4. For each changed prompt claim, map source contract → assembled input → enforcing function →
   negative and positive regression. Label authoring advice as such. Prompt string/header tests
   supplement execution tests; they do not prove isolation, repair, injection or cleanup.
5. Keep the diagnosis loop concise: Assumptions Review, cause/uncertainty, upstream owner, proof
   and authorized repair. Audit relevant prompt/contract conflicts without expanding the master
   specification or copying a growing prohibition catalogue across prompts.

**Exit:** represented failure/recovery paths terminate, preserve evidence and accepted work, and
report the next actionable stage consistently. Enforcement claims have executable evidence.

#### WP5 — verify and freeze the candidate

1. Audit selected tests, fixtures and entry points for published-UAT access and live subprocesses
   before running. Use the declared environment with its interpreter first on PATH. Run focused
   tests per slice; repeat state-sensitive cases cold/warm, including failure and interruption,
   comparing semantic results rather than timestamps, temporary names or nondeterministic bytes.
2. Run required repository gates after the final slice: full deterministic suite, lint, formatting
   and package build/smoke. Inspect `bin/test.sh` before using it. Install/extract the built wheel
   in a private temporary directory; verify imports, prompts, Rigging and resource versions match
   source. No dependency download or live provider is part of the smoke test.
3. Record command, environment, exit code, counts and revision for each gate. All required gates
   must pass before candidate freeze; an unavailable gate is an open action, not an exception
   that converts a partial run into release readiness.
4. Inspect diff/status/staged contents, record remaining limitations and commit verified slices.
   Identify the final candidate commit/package/config and capability coverage. Any subsequent
   implementation change invalidates affected proof and produces a new candidate identity.

**Exit:** one identifiable candidate passes every required local gate. Required unsupported or
unverified release capabilities remain blockers; deliberately deferred features are listed apart.

#### WP6 — Ed's release matrix and closure

1. Ed pins candidate commit, package digest/install location, Python/tool versions, provider/model
   and settings, source/kit revisions, acceptance inputs and dependency resolution. The ten kits
   run against that candidate without implementation edits. No bulk/resume syntax is invented;
   derive actual operator commands from the current CLI before handoff.
2. Record each kit's planning, build, acceptance, recovery and isolation observations separately.
   Model convergence is established here, not by fake-runner tests. Preserve release gates and
   record proved defective warnings/recovered errors as well as terminal failures; expected
   advisories and static uncertainty alone do not establish an unclean run.
3. After Ed supplies results and requests evidence inspection, diagnose the earliest cause and
   minimize any new failure into a local regression before changing code. Update ledger Fix and
   Outcome under its rules; only clean affected-stage evidence verifies a fix.
4. A changed candidate reruns affected local gates and the ten-kit matrix before release closure.
   A failure with a named follow-up is a useful handoff, not a passed release or completed plan.

**Exit:** all ten kits satisfy the existing release contract on one frozen candidate; every
release-blocking finding is closed by evidence. Otherwise keep the release open with a named
owner, minimal reproduction and next slice. Deterministic success never substitutes for UAT.

### Continuation and progress record

Execute WP0 first, then prioritize P0 items across WP1/WP3 before P1 slices. WP2, WP3 and WP4
may proceed independently once their owners/inputs are mapped; do not postpone verdict integrity
until universal resource hardening is complete. Finish WP1–WP4 release scope before WP5/WP6.
After each slice update the finding table, owning Memories, Actions and changelog as applicable,
then commit. No repeated approval is needed for ordinary work in an authorized execution session.

| Work package | Status at this planning revision | Closure evidence |
|---|---|---|
| WP0 | Open | Baseline/proposal review recorded; complete finding and capability matrix still required. |
| WP1 | Open | Existing snapshot/governed-gate mechanisms and unavailable-prerequisite regression found; truth table not audited. |
| WP2 | Partial, historical local coverage | `0ab6649` planning/probe/dependency fixes and decimal regressions exist; candidate rerun and remaining audits required. |
| WP3 | Partial, historical local coverage | `938021a` / `tests/test_build_state.py`; per-test isolation and remaining represented-state proofs open. |
| WP4 | Partial, historical mechanisms | Lifecycle budgets and recovery exist; interruption/loop/claim coverage audit open. |
| WP5 | Open | No implementation-candidate gate run in this documentation session. |
| WP6 | Ed-owned, open | No UAT execution or published evidence inspection in this session. |

Suggested commands after the WP5 safety audit (implementation session, from the checkout):

```bash
PATH="$PWD/.venv/bin:$PATH" .venv/bin/python -m pytest -q -n auto tests/test_acceptance_oracle.py tests/test_build_state.py tests/test_plan_reliability.py tests/test_build_run.py tests/test_diagnose.py
PATH="$PWD/.venv/bin:$PATH" .venv/bin/python -m pytest -q -n auto
.venv/bin/ruff check src/ tests/
.venv/bin/ruff format --check src/ tests/
.venv/bin/python -m hatchling build
```

## Decisions

- `2026-10-26` · Ed approves concise current contracts, assistant-owned assumptions review and
  explicit guardrails; unproved intermediate cases remain uncertainty.

## Questions

- None.

## Actions

- `2026-10-26` · Execute WP0's complete finding/capability matrix when Ed requests implementation;
  review baseline `7586152` and historical proposal dispositions above. Closes with owned,
  prioritized release findings and explicit deferred scope.
- `2026-10-26` · WP1–WP4 implementation/proof remain open: truthful verdicts, recurring plan
  defects, generated per-test isolation, represented state protection and bounded recovery.
  Existing regression files/commits above are starting evidence, not completion of these packages.
- `2026-10-26` · WP5 requires passing local candidate gates; WP6 requires Ed's complete frozen
  ten-kit matrix. No historical test count, unavailable check or named follow-up closes either.

## Working Notes

- None.

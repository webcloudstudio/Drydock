# MEMORY: stabilization

| Field | Value |
|---|---|
| Version | 2026-10-26 V2 |
| Description | Self-implementing work plan for explicit contracts, tested state ownership and reusable regressions before the ten-kit release gate. |
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
| Proof | Unit/command regressions precede bounded live experiments, which precede the fixed ten-kit release matrix. |
| Execution | When Ed asks to execute this plan, the assistant proceeds through ordered work packages, commits verified slices, and stops only at named safety boundaries or unresolved product decisions. |
| Limit | Passing deterministic tests does not establish model convergence or undeclared semantic dependencies. |

### Completed technical slice

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

### Self-implementing stabilization plan

This section is an execution contract for the next implementation session, not a proposal to
discuss. Ed's request to create this plan authorizes the implementing agent to complete the
reversible code, prompt, test, README, changelog and Memory File work below, run local deterministic
verification, and commit each coherent slice. Do not stop after writing a task list or ask Ed to
approve ordinary implementation choices. Ask only if approved requirements conflict or a material
product decision cannot be derived from the current contracts. Record unresolved technical cases
as uncertainty and continue independent work.

The executor owns the assumptions review: read this Current contract and all linked command/topic
memories, inspect the relevant source and existing tests, then record the approved goal, state
owners, mutations, known facts, uncertain claims and falsifying tests before each capability slice.
Treat only proved violations of explicit contracts as defects. A proved allowed behavior proceeds;
everything else remains uncertainty. Never change expected product semantics to silence a checker.

#### Fixed boundaries

- Never run, resume, report or mutate `drydock uat`; never write, stage or run git under `uat/`.
  Ed runs the ten-kit matrix. Do not read its evidence unless Ed requests it for that session.
- Never edit `docs/Drydock_Specification.md` without separate block-specific authorization.
- Do not make live provider/model calls, use API-key generation, incur metered charges, or start a
  full project build as a substitute for deterministic regressions. Use injected/fake runners.
  A later bounded live command experiment requires its own explicit authorization.
- Work only in the repository checkout and synthetic temporary directories outside `uat/`.
  Preserve unrelated working-tree edits. Commit only task files and inspect the staged diff.
- Keep each phase small and independently verifiable. After a phase passes, update its tests,
  owning Memory Files, this topic's Actions, and `CHANGELOG.md`, then commit locally. Do not push.
- If a check cannot run because its tool is unavailable or hangs, record the exact command and
  condition, use an available equivalent only if it proves the same property, and continue other
  independent phases. Never report an unrun check as passing.

#### Work package 0 — establish the candidate and evidence map

1. Record `git status`, HEAD, Python version, dependency lock state and available test/lint/package
   tools. Preserve pre-existing edits. Identify the candidate revision for this stabilization run.
2. Read Current contracts, Guardrails, Intent and relevant dated entries in this topic and the
   build, plan, diagnose, acceptance-criteria, foundations and `/ddk-uat` Memory Files. Read the
   corresponding prompts, implementations and tests before changing them.
3. Build an evidence map from the existing FxRates and CommonMark design-ledger findings already
   recorded here. Include: serialized decimal false positive and normalization regression;
   unresolved dynamic probe arguments and verify/repair routing; provider/consumer ordering;
   generated project tests writing to canonical persistence; managed SQLite deletion and wrong
   owner recovery; and provider-success/state-verification phase confusion. Link each finding to
   its current regression test or mark the missing regression. Do not inspect UAT data.
4. Reuse existing test fixtures first. Create `tests/fixtures/regressions/<case-id>/` only for
   inputs that existing Python tests cannot preserve clearly. Each added case must have a small
   `case.json` with stable id, contract, source hash/excerpt, consumed inputs, expected disposition,
   expected state mutations, recovery owner, reproduction command and relevant prompt/tool
   versions. Use synthetic data and injected model output; never freeze credentials, live DBs,
   provider homes, caches, virtual environments, full transcripts or timestamps as semantics.

**Exit:** every known ledger finding maps to a test or an explicit missing-test task; baseline
tool availability and unrelated edits are recorded. A full project or live model is not required.

#### Work package 1 — make oracle and plan admission semantics durable

1. Retain the current behavior that exact numeric text in a serialized fixture does not trigger a
   false defect and unknown decimal provenance is advisory. Add/retain table-driven regressions
   for CSV, JSON and XML text, exact text preservation, a genuinely unsupported literal, a derived
   expression, and a contradictory source-backed expectation.
2. Prove the checker does not silently accept semantic correctness it cannot establish: advisory
   cases must remain visible; source contradictions must still block through the relevant explicit
   contract; no formatter or repair path may add precision, quantization, rounding or normalization.
3. Preserve probe admission and verify's shared static argument resolution, mechanical-versus-
   authoring repair classification, exact consumed-interface dependency checks, and owner-specific
   replan guidance. Add one valid neighbor for each rejected probe/order case.
4. Assert user-facing diagnostics name the actionable stage once and do not recommend repeating a
   repair command that cannot address the defect. Tests must inject provider output and prove no
   provider call occurs for a purely mechanical advisory or validation failure.

**Exit:** focused acceptance, planning-session and CLI tests pass twice; the same semantic outputs
and exit codes appear on both runs; no source requirement is weakened.

#### Work package 2 — isolate project tests within an agent call

1. Trace how generated projects select their database DSN, initialize schema, run pytest and clean
   up fixtures. Determine whether the project has one test process, subprocesses or parallel tests;
   do not infer isolation from the acceptance harness's rollback behavior.
2. Implement the narrowest common test-fixture contract that gives each test an isolated disposable
   store (or an isolated namespace/transaction where the database semantics require it), while
   keeping cross-connection behavior testable. Do not copy live business rows into test state.
3. Ensure fixture setup/teardown runs on pass, assertion failure, collection failure and process
   interruption where the harness can observe it. Use unique paths/namespaces; never delete or
   recreate the configured canonical store as cleanup.
4. Add regressions with at least two tests that write the same logical key, a cross-connection
   assertion, test failure cleanup, parallel execution if supported, and a pre/post canonical
   sentinel. Run the same case twice and prove unrelated rows and canonical bytes/state survive.
5. Update the build prompt and generated test guidance only after the fixture behavior is enforced
   and tested. A prompt prohibition alone does not satisfy this package.

**Exit:** generated project tests can exercise shared application behavior without cross-test data
leaks, and canonical configured data is unchanged on every success/failure path. If the supported
database cannot provide the required isolation, record the precise unsupported case and stop that
adapter; do not claim universal support.

#### Work package 3 — close local state ownership gaps

For every row in **State inventory to complete**, inspect the actual mutation paths and enforcement
code. Add a negative test before describing a guard as implemented. Deliver these slices in order:

1. **Managed SQLite lifecycle:** strengthen the existing per-call disposable store and pre-call
   snapshot tests for deletion, modification, WAL-only writes, provider exception, schema setup
   failure, missing canonical store, concurrent writer and backup permissions/ignore rules. Never
   restore automatically over changed state. Verify owner recovery does not suggest rebuilding a
   consumer block.
2. **Governed files, Git and manifests:** capture the authorized mutation set for an agent call;
   prove source inputs, unrelated user edits, dependency locks and previously accepted work remain
   unchanged. Test authorized implementation writes and reject unauthorized source/metadata
   changes. Do not reset a worktree to recover from a partial failure.
3. **Environment, CWD, temporary files and caches:** pass task-local child environments without
   mutating the parent; isolate working directories and scratch paths; redact secrets from stored
   evidence; prove cleanup on exceptional exit. Preserve caches only when their owner and reuse
   semantics are explicit.
4. **Processes, ports and services:** inventory subprocess creation and termination. Add owned
   process-group cleanup, dynamic port allocation and bounded readiness/termination tests where
   Drydock starts services. Prove no child survives failure or interruption and no fixed port is
   left occupied. Do not start a real service in tests unless it is local, temporary and bounded.
5. **External databases, queues, object stores and network:** default tests to fakes or isolated
   local namespaces. Add an adapter only where the configured service and cleanup contract are
   explicit. Never probe or delete an operator's remote resource to test isolation. Until an
   adapter is verified, fail closed before the model call when safe isolation is required and report
   the exact unsupported resource.
6. **Lifecycle locks, journals and resume:** test repeated invocation, interruption at each
   mutation boundary, recovery and resume. Keep accepted work and evidence; ensure a retry is
   idempotent and points to the earliest legal owner/stage.

If full OS-level confinement is unavailable, be precise: lifecycle snapshot/detection is evidence,
not prevention. Implement only protections the process boundary actually enforces. Add a residual
limit and owner-specific recovery instead of claiming that prompts or hashes sandbox arbitrary
child commands.

**Exit:** every state class is either protected by tested code or explicitly unsupported with a
fail-closed condition, owner, recovery and test. No resource is silently classified as isolated.

#### Work package 4 — harden prompt clarity and the diagnosis loop

1. Keep rules grouped by explicit authority, preconditions, allowed mutation, invariant, failure
   action and verification. Separate proactive rules for proved requirements from authoring advice;
   label intermediate cases as uncertain rather than silently turning them into policy.
2. For `build.md`, require reading current contracts and source before edits, preserving exact
   product semantics, using isolated test resources, reporting observed progress/results, and
   stopping on unsupported resource/state boundaries. Keep the model prompt concise; link shared
   state policy to the relevant contract instead of copying a growing rule catalogue everywhere.
3. For `uat_diagnostic.md` and `/ddk-uat`, keep investigation as default, repair authorization
   from an explicit repair request, and the assistant-owned Assumptions Review as a required report
   section. Ensure diagnosis distinguishes proved defect, allowed operation and uncertainty, and
   does not put routine assumptions work back on Ed.
4. Add prompt-header, prompt-structure and output-contract tests for each rule. Test that the
   diagnosis's deterministic state recovery cannot be overwritten by inline model prose.
5. Review wording for conflicts, duplicated rules, absolute claims unsupported by runtime
   enforcement, and conditions with no owner or test. Fix the source of each conflict and link
   related Memories; do not amend the master specification.

**Exit:** prompt/contract tests pass; every mandatory prompt rule names its source and enforcing
test or is labeled as authoring guidance with its enforcement limitation.

#### Work package 5 — reusable cross-project test suite and package proof

1. Keep regressions capability-based, not project-copy-based. For each of the ten release kits,
   later map its capability profile to these cases using an authorized kit manifest; do not duplicate
   entire generated Targets. If kit names or profiles are unavailable without UAT access, leave the
   mapping as Ed-owned input and finish all independent capability tests.
2. Run focused tests for every changed capability, then the full deterministic suite, lint,
   format check and package build/smoke. Use the repo's declared Python environment and commands.
   Record exact command, exit code and counts. If a command hangs, diagnose the cause and rerun a
   bounded, equivalent check; do not quietly omit it.
3. Repeat state-sensitive and semantic regression cases twice, including cold and warm temporary
   state. Inject deletion, concurrent modification, provider exception, malformed output and
   interruption. Compare contract-level results, not nondeterministic paths/timestamps.
4. Install/extract the built wheel in a clean temporary location and verify imports, prompt
   resources, headers and rules match the source package. Remove only the temporary build artifacts
   created by this task.
5. Review full diff, `git diff --check`, status, ignored/untracked files and the commit contents.
   Commit each coherent slice locally with a descriptive message and no attribution; never push.

**Exit:** all deterministic gates available in the repository pass, or each unavailable gate has a
recorded reason and a concrete rerun command. No live provider usage is part of this package.

#### Work package 6 — release handoff (Ed runs UAT)

1. Publish the candidate commit(s), supported compatibility matrix, passed checks, unresolved
   limitations and exact next commands in this Memory File and the completion report.
2. Before UAT, Ed pins one commit/package/config/provider setup. Ed runs the actual ten-kit matrix
   using supported CLI syntax. No implementation edits occur during that candidate's comparison.
3. For each result, classify planning, build, acceptance, recovery and resource-isolation status
   separately. Preserve existing acceptance gates. Uncertainty alone is not a defective warning;
   any proved contract violation or unexplained recovery prevents a clean release.
4. After Ed supplies results, the assistant reads only the requested evidence, updates the
   diagnosis ledger's Fix/Outcome fields, and closes a finding only after the affected stage proves
   the cause no longer recurs. A new code change reopens proof for its affected capabilities.

**Exit:** Ed's ten-kit matrix passes on one frozen candidate, or every failed kit has a minimal
reproducible case, a named owner and a specific next implementation slice. No local test result is
represented as UAT completion.

#### Continuation protocol

When an agent is asked to execute this plan, it must start with Work package 0, then continue to
the next unfinished package in order without asking for phase-by-phase approval. It may defer a
package only for an explicit external dependency, a safety boundary above, or a genuine unresolved
product decision; it must name the exact blocker and finish independent work. Keep this file's
Actions current after every committed slice. Do not mark the plan complete while any implementation
package, verification gate or Ed-owned release step remains.

Suggested local commands (from the checkout; none invokes UAT):

```bash
PATH="$PWD/.venv/bin:$PATH" .venv/bin/python -m pytest -q -n auto tests/test_acceptance_oracle.py tests/test_build_state.py tests/test_plan_reliability.py tests/test_build_run.py tests/test_diagnose.py
PATH="$PWD/.venv/bin:$PATH" .venv/bin/python -m pytest -q -n auto
ruff check src/ tests/
ruff format --check src/ tests/
.venv/bin/python -m hatchling build
```

UAT commands are run only by Ed, using the actual ten kit names and the supported CLI syntax;
do not invent a bulk flag or run an unverified resume against a stale generated plan.

## Decisions

- `2026-10-26` · Ed approves concise current contracts, assistant-owned assumptions review and
  explicit guardrails; unproved intermediate cases remain uncertainty.

## Questions

- None.

## Actions

- `2026-10-26` · The next execution starts at Work package 0 in the self-implementing plan above
  and continues in order without phase-by-phase approval. Code, prompt and test work is authorized;
  Ed retains the ten-kit UAT release gate.
- `2026-10-26` · Work packages 2–3 remain open: per-test fixture isolation, remaining local state
  ownership, and any explicitly supported remote-store adapters. Each state class needs a negative
  test or an explicit unsupported/fail-closed disposition.
- `2026-10-26` · Work packages 5–6 remain open: package/lint verification in a usable environment,
  then Ed's frozen ten-kit release matrix. The 490 focused tests do not close these gates.

## Working Notes

- None.

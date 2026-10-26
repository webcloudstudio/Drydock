# MEMORY: stabilization

| Field | Value |
|---|---|
| Version | 2026-10-26 V1 |
| Description | Stabilize Drydock through explicit contracts, bounded state ownership and reusable command-level regression cases before the ten-kit release gate. |
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

### Executable stabilization pass plan

1. **Establish the baseline — assistant, before further code changes.** Review this current
   contract and affected memory files; record goal, owners, assumptions and discriminating tests.
   Identify the candidate commit, package, prompt hashes, selected model/provider and dependency
   locks. Keep that revision fixed during each comparison. Exit: a concrete reproducible baseline.
2. **Complete the state inventory — assistant.** For each row above, map existing enforcing code
   and negative tests; mark gaps explicitly. Prioritize per-test store fixtures, remote-store
   isolation, escaped processes and mutable configuration. Exit: every resource is owned or
   explicitly deferred, with no claim that a prompt prohibition is runtime enforcement.
3. **Create a small regression index — assistant.** Select a minimal failing case and a valid
   neighboring case from each known failure class; use read-only evidence inspection when Ed
   authorizes it, then construct synthetic fixtures outside `uat/`. Map each of the ten kit ids
   to its capability cases. Exit: tests reproduce decisions and mutations without a live model.
4. **Run the cheap tiers — assistant.** Execute focused tests, the complete deterministic suite,
   lint, formatting and installed-package smoke; repeat affected cases twice and compare semantic
   results. Inject resource deletion, contradictory criteria, provider failure and interruption.
   Exit: no unexplained failures, changed or weakened gates, leaked resources or lost accepted work.
5. **Run a bounded live command experiment — explicitly authorized operator/assistant.** Choose
   one representative case per changed capability, copy its saved pre-command inputs to a private
   development Target outside `uat/`, use the subscription CLI adapter, and stop at the command
   boundary. Set a finite call/time budget and retain evidence. Exit: clean completion or one
   reproducible scoped defect; no automatic restart of import/analyze/full UAT after every failure.
6. **Freeze and execute release UAT — Ed.** Pin one candidate commit/package/config and run the
   ten required kits. Preserve each receipt, command streams, source/prompt hashes and failure
   classification. No framework edits during a running comparison. Exit: all ten complete with
   required acceptance, no unexplained recoveries, and no unresolved material defects. Label
   genuine static uncertainty separately from defective warnings.
7. **Close the evidence — assistant.** Compare each ledger finding with later affected-stage
   evidence; mark fixed only when the cause does not recur. Document the supported compatibility
   matrix and remaining limitations. A new implementation commit restarts the affected proof;
   the final release matrix belongs to a single candidate.

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

- `2026-10-26` · Execute phases 1–7 above for the release candidate after this technical slice;
  the ten-kit matrix is not replaced by local unit tests.
- `2026-10-26` · Complete per-test SQLite fixtures and an explicitly scoped PostgreSQL/remote
  store adapter; close only with repeated tests proving canonical state and unrelated rows survive.
- `2026-10-26` · Complete process/port/configuration ownership enforcement and the frozen case
  index; close with interruption/retry and cold/warm command regressions.

## Working Notes

- None.

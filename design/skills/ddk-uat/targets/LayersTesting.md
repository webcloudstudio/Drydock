# MEMORY: UAT LayersTesting

| Field | Value |
|---|---|
| Version | 2026-10-27 V3 |
| Description | LayersTesting UAT diagnosis and verification history. |
| Target | LayersTesting |
| Evidence root | /mnt/c/Users/barlo/projects/drydock/uat/LayersTesting |

## Intent

Preserve evidence-backed causes and verification status across LayersTesting runs.

## Guardrails

- `2026-10-26` · Ed owns UAT execution and published evidence. Diagnosis does not mutate evidence or generated Targets.
- `2026-10-26` · Implementation repairs require explicit authorization.

## Details

### Current contract

- Authority: [ddk-uat](../../ddk-uat.md), [plan](../../../commands/plan.md), [acceptance_criteria](../../../topics/acceptance_criteria.md), and kit `sources/INSTRUCTIONS.md`.
- Ordinary store criteria never directly replace DSNs or apply schema (`acceptance_store.store_setup_defects`). Configuration-only tests use harness-owned `drydock_acceptance.database_environment`; see the linked acceptance/plan contracts.
- Plan repair preserves criteria, coverage and behavioral assertions. Configuration fixture relocation may replace path operands while preserving precedence, prefix, unset/empty cases and error outcomes.
- Proof: later clean `04-plan` through `07-plan-verify-after-repair` evidence after any correction.

### LT-STORE-001 — source-required database-failure exits have no lifecycle-compatible criterion

- Run/stage: `20261027.013358`, `05-plan-verify` rc=1, `06-plan-repair` rc=1, `07-plan-verify-after-repair` rc=1. Terminal: "stopped at plan-repair: acceptance criteria still cannot run after one repair pass".
- Framework: Drydock 0.8.0, receipt commit `1b234d7`. Provider/model: `claude` / `claude-sonnet-5-5` (plan).
- Source: `sources/INSTRUCTIONS.md:120` exit 1 = "database unreachable, tables missing, file unreadable". `run.sh` never exercises exit 1. Analysis added SETUP-001/AC-001 "PostgreSQL DSN refused with exit 1" (`ANALYSIS.md:25,94,220`) as a SQLite-only stack decision.
- Contamination path: INSTRUCTIONS exit-1 row + ANALYSIS AC-001/CLI-002 → `FEATURE-OperationalFailures.md` criteria `operational-postgres-refused`, `operational-unreachable-database`, `operational-invalid-database-file`, `operational-usage-before-database`, each assigning `os.environ["DATABASE_URL"]`.
- Disposition: guard and repair behaved per contract (proved: `acceptance_store.py:55-57` matches the subscript assignment; repair is forbidden to delete or move coverage). The plan violated `plan_create.md:931`, but no authoring route exists for a source-required behavior that can only be observed by changing the configured store. Second occurrence of this class: central ledger row FxRates `20261024.030814` (resolved by a kit source edit).
- `operational-usage-before-database` is separable: `count extra` against the provisioned store still asserts exit 2, losing only the ordering proof.
- `operational-unreadable-load-file` uses the provisioned store and passed verify.
- Reproduction: `store_setup_defects(<AC body>)` on any of the four bodies returns the "configured database" defect. Not run against evidence; read-only.
- Fix `2026-10-26`: Ed directed a kit source edit (route a). PostgreSQL wording removed from `sources/INSTRUCTIONS.md`, `INSTRUCTIONS_go.md`, `INSTRUCTIONS_python.md` (Database section now SQLite-only) and `inputs/COMPASS.md` (network rule). Uncommitted in the kit; Ed commits kit history. The exit-1 row "database unreachable, tables missing" was then removed from the exit-1 row of all three variants (now "a file named on the command line cannot be read"), as for FxRates. Store connectivity remains proved by the DATABASE step.
- Outcome: unverified.

### LT-IFACE-001 — `## Database Interface` entries omit `- supplies:` (recovered)

- Run/stage: `20261027.013358`, `04-plan` warnings for `FEATURE-Count.md` and `FEATURE-Init.md`.
- Evidence: `evidence/prompt_outputs/20261027.014205.667Z_layerstesting_plan_claude.output.txt:464` `` - `FEATURE-LEDGER-003` — read: list accounts ordered by code - returns: ... `` with no `supplies:` clause. `database_contract._INTERFACE_RE` (`database_contract.py:32-36`) requires `supplies:`; `_INTERFACE_FORM` shows it. Module rewrote the section from DATABASE.md.
- Cause: model output deviates from the stated grammar for no-input reads. Rewrite recovered; downstream contamination not established (final sections read `- None — persistence is owned by DATABASE.md`, which is uncertain as a correct substitute for a feature that reads accounts).
- Outcome: unverified. Omitted empty field clauses are accepted by the framework repair recorded below; required fields and access grants remain checked.

### LT-RUNNER-001 — `runner-posix-syntax` uses undeclared `sh`

- Run/stage: `04-plan` warning on `FEATURE-TestRunner.md`. Criterion lacks a `Requires:` declaration. Advisory only; not investigated further.
- Outcome: open, undetermined severity.

### 20261027.030445 — recurrence and authorized framework repair

- Receipt: failed, execution ERROR, acceptance NOT_RUN; terminal plan-repair, rc=1.
  `04-plan` rc=0 writes draft/unbuildable; `05-plan-verify`, `06-plan-repair` and
  `07-plan-verify-after-repair` return 1. Cleanliness: not clean.
- Framework: 0.8.0, receipt `c0fdece828331c229d3e7fa0780816d6d04eba83`.
  Providers/models: Claude Haiku/Sonnet 5.5; repair Sonnet. Preserved source SHA256:
  `5fe5f2b8c018d49d6767f97136987b24127f9646c97098cc93f8879d1f0c5ccd`.
- LT-STORE-001 recurred: seven criteria directly change the DSN. Four configuration-selection
  criteria are explicitly supported by `blueprint/sources/INSTRUCTIONS.md:49-50`: URL optional
  prefix and precedence, PATH fallback, default `data/app.db`. SQLite is already selected;
  this is not PostgreSQL or connectivity provisioning failure. The remaining three test
  open-store/init/count failure behavior declared in their generated Blueprints; the source's
  exit-1 row now names unreadable command-line files, so the exact extra database-failure exit
  requirement is not established by that row. Future authoring must not invent required exits.
- Earliest mechanism: the same unconditional direct-environment guard rejects pure path
  resolution tests and ordinary CRUD store replacement. Creation forbids all changes; mechanical
  repair must retain the input/assertion but has no supported isolation fixture. The assembled
  `evidence/prompts/20261027.032524.151Z_layerstesting_plan-repair_claude.prompt.md`
  carries this contradiction; the matching output explicitly refuses all seven. Raising a
  budget or choosing another SQLite filename cannot satisfy the old contract.
- Fix: `33fb18b`. A harness-only context manager supplies disposable cwd
  and confined relative SQLite paths, unsets/sets empty variables correctly and restores state
  even on failure. It provisions no schema. Ordinary CRUD/direct DSN/schema guards remain.
  Creation/Blueprint/repair/full+compact persistence contracts document it, including permitted
  mechanical fixture relocation. Existing published criteria/evidence were not modified.
- LT-IFACE-001 recurred: raw `20261027.031011.284Z_layerstesting_plan_claude.output.txt:537-539`
  omits returns on delete citations; `:671-673` omits supplies on no-input list citations.
  DATABASE declares these shared (`Owner DATABASE.md`), so the old normalization replaced the
  entire consumer interface with None. It recovered syntax but discarded explicit dependencies.
  The reader now treats one omitted field clause as an empty claim while retaining every cited
  id; required-input/declared-field/access validation still applies. Both clauses with explicit
  empty `—` remain the authoring form. Fix: `33fb18b`.
- The third planning warning reports successful SQLite construction/connectivity for three
  tables; this is an expected observation, not a defect. No envelope repairs appear in the
  preserved provider contract records. LT-RUNNER-001 was not observed in this run.
- Verification: new regressions first failed against the previous code; configuration tests
  exercise actual acceptance subprocess import plus exceptional restoration, canonical bytes,
  traversal/absolute/remote-path rejection and direct-DSN guard retention. Parser regression
  replays both omitted-clause shapes. Read-only replay of the exact preserved raw output against
  its DATABASE.md retains and validates three init plus three count citations. Final verification
  is recorded below.
- Outcome for the two implemented causes: unverified pending Ed's clean affected-stage UAT.

### Local verification — 2026-10-27

- New regressions first failed against the previous implementation. Affected acceptance/build/
  repair/parser checks: 568 passed. Planning/parser/memory checks: 489 passed; final planning/
  handoff/prompt/memory checks: 484 passed. Final repair/isolation/ledger selection: 21 passed;
  the final complete new regression file passes all 11 tests after helper lint alignment.
- Full suite: 4,629 passed, 2 skipped, one shell smoke failure because its child selected system
  Python 3.10 (`datetime.UTC` unavailable). That exact smoke passes with the project's Python
  3.12 venv first on PATH. No product change or assertion weakening was needed for that failure.
- Repository lint, changed-file formatting and diff checks pass. Wheel build and isolated
  extracted-wheel execution pass; changed prompt/source/helper bytes match the wheel exactly.
- Published UAT files and generated products remain unchanged. Framework/prompt findings stay
  unverified until Ed's fresh affected-stage evidence; prompt compliance is not statically proved.

### 20261027.135355 — LT-EXIT-001: unchecked final reads; recovered

- Observed state: no `result.json`, evidence manifest or report index at diagnosis. Available
  command streams end with `06-plan-repair`: five repaired, zero outstanding. `04-plan` writes
  draft/unbuildable with rc=0; operator reports `05-plan-verify` rc=1. Final verdict/exit pending.
  Cleanliness: not clean, because defective criteria required repair.
- Provider/model: Claude Sonnet 5.5 for planning and repair; Haiku 5.5 for analyze.
  Framework reports 0.8.0; receipt commit and source revision are unknown without final receipt.
- Authority: imported `INSTRUCTIONS.md:65-70,121` requires atomic rejection of negative balances
  with exit 3. These five proofs exercise source intent; no specification contamination proved.
- Cause: original `FEATURE-NoNegativeBalance.md` omitted exit assertions on six final
  `account get` calls: one each in nonneg-load/post/amend/delete and two in nonneg-transfer.
  All rejection calls already asserted exit 3. `print(out, err)` was not causal; initial inspection
  of the already-repaired workspace misleadingly suggested a false positive, ruled out by the
  exact original bodies in `workspace/logs/20261027.141325.731Z_layerstesting_plan-repair_claude.prompt.md`.
- Deterministic read-only replay: strip the `Intent:` declaration before passing original code
  to `harness_exits.unchecked_calls`; it reports 42, 24, 30, 29, and 33/35 respectively after
  normalizing the leading blank line. Repaired workspace bodies all return `[]`. A valid neighbor
  with print between runner assignment and exit assertion also returns `[]`.
- Repair output adds six `assert code == 0` statements; existing product assertions remain.
  `06-plan-repair.stdout.log` records five repaired/zero outstanding; linked llm.jsonl records
  provider rc=0. This is observed recovery, not a framework fix or clean-run proof.
- Contributing admission gap: `planning_session.py:4127-4227` groups decidable authoring defects
  but never invokes `unchecked_calls`; `plan_verify.py:768` first reports this defect after
  serialization and lineage. Recommend sharing the existing guard with bounded artifact repair,
  with an omitted-final-read regression plus asserted/rebound neighbors. Do not relax the guard.
- The single SQLite construction/connectivity warning is an expected successful observation,
  unrelated to missing exit assertions. Available init/import/analyze streams show no other
  defective warning; complete envelope audit/final downstream outcome remains pending receipt.
- Fix: none applied in this diagnosis. Outcome: open (authoring/admission cause), recovered
  in this run by existing mechanical repair; no UAT execution or evidence mutation performed.

## Decisions

- None.

## Questions

- None.

## Actions

- `2026-10-27` · LT-EXIT-001 — share unchecked-call validation with pre-write artifact repair; close after authorized regression-backed repair and later clean affected-stage evidence. Final receipt for `20261027.135355` remains pending; inspect it before assigning an overall run verdict.

- `2026-10-26` · LT-STORE-001 — framework isolation repair is implemented (commit recorded in Details). Ed reruns from Plan; closes when configuration criteria use the harness fixture and verify/build cleanly. Preserve URL coverage rather than removing source requirements.
- `2026-10-26` · LT-IFACE-001 — omitted empty field clauses are accepted without losing shared citations; Ed verifies the next plan has no interface rewrite warnings.

## Working Notes

- None.

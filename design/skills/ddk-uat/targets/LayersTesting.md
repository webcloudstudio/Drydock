# MEMORY: UAT LayersTesting

| Field | Value |
|---|---|
| Version | 2026-10-26 V1 |
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
- Acceptance store lifecycle (`prompts/plan_create.md:929-933`): criteria never replace `DATABASE_URL`/`DATABASE_PATH`. Enforced by `acceptance_store.store_setup_defects` in `plan verify`.
- Plan repair may not delete a criterion, move coverage or change its assertion (`prompts/plan_repair.md:140-150`); such a fault ends in `REPAIR_IMPOSSIBLE`.
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
- Fix `2026-10-26`: Ed directed a kit source edit (route a). PostgreSQL wording removed from `sources/INSTRUCTIONS.md`, `INSTRUCTIONS_go.md`, `INSTRUCTIONS_python.md` (Database section now SQLite-only) and `inputs/COMPASS.md` (network rule). Uncommitted in the kit; Ed commits kit history. The exit-1 row "database unreachable" (`INSTRUCTIONS.md:120`) remains and can still regenerate `operational-unreachable-database` / `operational-invalid-database-file`.
- Outcome: unverified (postgres criteria); open (unreachable/invalid-store criteria).

### LT-IFACE-001 — `## Database Interface` entries omit `- supplies:` (recovered)

- Run/stage: `20261027.013358`, `04-plan` warnings for `FEATURE-Count.md` and `FEATURE-Init.md`.
- Evidence: `evidence/prompt_outputs/20261027.014205.667Z_layerstesting_plan_claude.output.txt:464` `` - `FEATURE-LEDGER-003` — read: list accounts ordered by code - returns: ... `` with no `supplies:` clause. `database_contract._INTERFACE_RE` (`database_contract.py:32-36`) requires `supplies:`; `_INTERFACE_FORM` shows it. Module rewrote the section from DATABASE.md.
- Cause: model output deviates from the stated grammar for no-input reads. Rewrite recovered; downstream contamination not established (final sections read `- None — persistence is owned by DATABASE.md`, which is uncertain as a correct substitute for a feature that reads accounts).
- Outcome: open. Candidate correction: accept an absent `supplies:` as empty in the parser, or state the empty form in the prompt; not yet decided.

### LT-RUNNER-001 — `runner-posix-syntax` uses undeclared `sh`

- Run/stage: `04-plan` warning on `FEATURE-TestRunner.md`. Criterion lacks a `Requires:` declaration. Advisory only; not investigated further.
- Outcome: open, undetermined severity.

## Decisions

- None.

## Questions

- `2026-10-26` · LT-STORE-001: remove "database unreachable" from the `INSTRUCTIONS.md:120` exit-1 row as in FxRates, or keep it and give Drydock an authoring route. Closes when Ed decides.

## Actions

- `2026-10-26` · LT-STORE-001 — implement the chosen route with a regression test; rerun `04-plan`..`07` on LayersTesting.
- `2026-10-26` · LT-IFACE-001 — decide parser vs prompt fix; regression test replaying `plan.output.txt:464`.

## Working Notes

- None.

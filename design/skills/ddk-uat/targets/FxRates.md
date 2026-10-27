# MEMORY: UAT FxRates

| Field | Value |
|---|---|
| Version | 2026-10-27 V1 |
| Description | FxRates source fidelity, grader lifecycle and managed-state diagnosis. |
| Target | FxRates |
| Evidence root | /mnt/c/Users/barlo/projects/drydock/uat/FxRates |

## Intent

Preserve evidence-backed diagnosis and the operator review handoff for FxRates.

## Guardrails

- `2026-10-27` · UAT and published evidence are owned by Ed; diagnosis never executes or mutates them.

## Details

### Current contract

Approved source intent governs generated criteria and implementation. See
[build](../../../commands/build.md), [foundations](../../../topics/foundations.md),
[uat](../../../commands/uat.md) and [diagnostic contract](../../ddk-uat.md).
Investigation writes only this memory and its index. Repairs require explicit authorization.
Managed state is preserved; a fingerprint alert does not establish logical data loss.

### Run 20261027.152427

Receipt: failed / execution ERROR / acceptance NOT_RUN; initial-build-1 exit 1;
24 built, 1 failed, block-16 accept-001-grader. Not clean. Framework receipt revision
c62f2e158c62b51800e7a80ad02746d14a40f381; claude haiku build / sonnet plan.
Source revision unknown independently of the receipt. All paths below are relative to the run.

**FX-001 — source-to-plan init contract conflict; open.**
`workspace/targets/FxRates/blueprint/sources/INSTRUCTIONS.md:22,67` explicitly specifies a
fresh grader database and init dropping/recreating rates. `sources/run.sh:27` unconditionally
sets DATABASE_URL to a new mktemp directory. Generated FEATURE-InitCommand.md:15-19 instead
requires DELETE through rates.delete_from_date against provisioned schema and forbids DDL.
Its acceptance seeds a pre-existing schema and never checks fresh-store init. This is a proved
source fidelity defect, not proof the supplied grader independently invented an unauthorized
scratch store. Ed now states the intended workflow is grading the working provisioned database;
that differs from the preserved kit brief and must be resolved at the governed input rather than
patching the application to satisfy the incompatible generated and imported contracts.
Execution 20261027.170854.522Z-c29cd1c4 returns provider rc=0 but reports grader 11/35;
its scratch-only schema probe reports 35/35, without a persisted implementation fix.
Evidence: evidence/prompt_outputs/20261027.170854.522Z_fxrates_build_claude.output.txt;
evidence/provider_raw matching stem; generated FEATURE-InitCommand.md; source brief/run.sh.
Deterministic proof to implement: source-contract comparison and fresh/unprovisioned versus
provisioned-store grader neighbor; never execute the published grader during diagnosis.
Drydock AgentStore separately provisions its disposable schema: this grader overrides that DSN.
Fix: none. Outcome: open. Spec divergence: generated Blueprint contradicts imported source;
master specification not edited.

**FX-002 — managed-state fingerprint alert; causal mechanism undetermined; open.**
Terminal gate is managed-state violation before deterministic acceptance, separate from FX-001.
Agent raw Bash explicitly opens sqlite3.connect('data/app.db') to inspect sqlite_master outside
its disposable DSN. It reports no tracked file changes, which does not cover ignored DB/WAL.
AgentStore compares SHA256 of main file and WAL, not logical SQLite content. Snapshot is
workspace/targets/FxRates/evidence/managed-state/sqlite-e5ov3t78/app.db.
Read-only immutable inspection of snapshot and current build/FxRates/data/app.db finds identical
sqlite_master definitions (rates plus three indexes) and zero rates rows in each. No logical
loss is established; immutable inspection excludes any still-live WAL contents. A WAL checkpoint
or journal lifecycle change remains a hypothesis, not a proved cause or permission to restore.
Deterministic proof needed: temporary WAL database, snapshot/fingerprint, agent-equivalent
read/close, logical comparison and deliberate committed-write/deletion neighbors. Inspect all
remaining sidecars read-only before any operator recovery decision. No automatic overwrite.
Fix: none. Outcome: open; prior 938021a detection/recovery is active but not cleanly verified.

**FX-003 — planning executable declarations; independent advisory; open.**
04-plan.stdout.log:115-118 reports two FEATURE-OfflineTestRun criteria without Requires
executable=sh. No evidence connects these warnings to FX-001 or FX-002. The third warning is
successful SQLite construction/connectivity information, not a defective recovery.
Fix: none. Outcome: open.

### Continuation

Verified from cli.py _uat_resume_selection and uat.py default_resume_stage:
`drydock uat resume FxRates --run 20261027.152427` resumes the failed lifecycle stage.
There is no --resume option. Explicit equivalent:
`drydock uat FxRates --run 20261027.152427 --stage build`.
Build block-16 is not UAT step 16. The recorded build command is UAT step 10;
resuming Build retains completed stories rather than restarting init/plan.
These commands are handoff syntax, not a claim that unresolved causes are repaired.

## Decisions

- None.

## Questions

- None.

## Actions

- `2026-10-27` · FX-001: reconcile Ed's provisioned-store grading intent with the governed kit
  brief/run.sh, then correct the earliest owning source/planning contract and regressions.
  Close after reviewed correction and clean affected-stage UAT evidence; no repair authorized
  or performed by this diagnosis.
- `2026-10-27` · FX-002: reproduce fingerprint change on a temporary WAL database and inspect
  preserved sidecar evidence before deciding whether any recovery is necessary. Close with
  discriminating regression and reviewed affected-stage UAT proof.
- `2026-10-27` · FX-003: correct missing sh declarations in planning authoring; close with
  static declaration proof and clean planning evidence.

## Working Notes

- None.

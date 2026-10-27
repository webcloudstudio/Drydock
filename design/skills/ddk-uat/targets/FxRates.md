# MEMORY: UAT FxRates

| Field | Value |
|---|---|
| Version | 2026-10-27 V2 |
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

### Authorized source repair — 2026-10-27

Ed explicitly authorized edits to the kit sources and supplied grader, then required a complete
fresh run because instructions changed. This exception permits kit input changes, not historical
run mutations. Changed kit files: sources/INSTRUCTIONS.md, bin/run.sh, README.md.
The brief assigns schema provisioning to DATABASE and defines init as deleting all rates through
the persistence interface, preserving schema. The grader preserves configured DSNs, resolves
DATABASE_URL then DATABASE_PATH then APP/data/app.db, and refuses missing stores/tables through
a read-only preflight. It creates no replacement store or schema. Its 35 checks and expected
answers are unchanged. Grading explicitly owns and resets the dedicated test store's rows;
agent grading uses the inherited Drydock-provisioned test store.

Verification uses only /tmp/fxrates-grader-check-vd9ry9n9: copied application code, a SQLite backup
of provisioned data, and the corrected copied grader. No UAT command or historical grader was
executed. Shell syntax and missing/empty-store negative checks pass without schema creation;
full grader passes 35/35 in each of three configurations: default path, sqlite:// DATABASE_URL
with a conflicting DATABASE_PATH, and DATABASE_PATH alone. The conflicting path is never created.
All 35 checks and expected answers are byte-identical to the preserved grader.
This verifies grader compatibility, not a clean newly planned UAT.

Kit commit blocked: git add reported pre-existing uat/FxRates/.git/index.lock; no lock was removed
or modified. Source repair is unverified by UAT, and remains uncommitted in the kit until the
owner resolves the lock. Root memory/changelog commit records this handoff separately.

FX-001 now has an implemented source correction (Outcome: unverified); a fresh import/analyze/
plan/build/score is required, never a resume of 20261027.152427. The old Continuation section
above documents syntax only and is superseded for this repair. Operator command:
`drydock uat FxRates --llm-provider claude --model haiku --plan-override-model sonnet`.

FX-002 remains undetermined, not evidence requiring database restoration. Canonical deletion
protection and testing against a provisioned isolated store are separate concerns. SQLite supports
WAL; physical bytes can change without changed rows. No Drydock mutation-gate change is made
within this source repair. The fresh grader no longer discards the inherited provisioned DSN.
A recurrence of the alert needs a logical-state versus physical-file reproduction, not blind
restoration. FX-003 is unchanged.

## Decisions

- None.

## Questions

- None.

## Actions

- `2026-10-27` · FX-001: reconcile Ed's provisioned-store grading intent with the governed kit
  brief/run.sh, then correct the earliest owning source/planning contract and regressions.
  Source correction implemented on 2026-10-27; close after the kit commit and clean fresh-run
  evidence. The existing kit index lock prevents committing the authorized input edits.
- `2026-10-27` · FX-002: reproduce fingerprint change on a temporary WAL database and inspect
  preserved sidecar evidence if the managed-state alert recurs; no restoration is currently justified. Close with
  discriminating regression and reviewed affected-stage UAT proof.
- `2026-10-27` · FX-003: correct missing sh declarations in planning authoring; close with
  static declaration proof and clean planning evidence.

## Working Notes

- None.

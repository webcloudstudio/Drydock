# MEMORY: UAT FxRates

| Field | Value |
|---|---|
| Version | 2026-10-27 V3 |
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

### Final explicit-initialization repair — 2026-10-27

Ed corrected the earlier provisioned-store workaround: init creates missing schema, and testing
on a fresh store is valid after initialization. This supersedes the earlier authorized repair
entry's preservation of the grader DSN and clearing of rates. Canonical authority is Ed's latest
instruction; no master specification block is edited. DATABASE generates the script/package;
Python persistence.initialize_database(dsn) applies only idempotent creation, returns an open
database, preserves existing rows/definitions, and resolves schema.sql independently of cwd.
Ordinary opens do not initialize. The generated creation path joins acceptance rollback;
ordinary arbitrary execute_script is still forbidden there.

Kit commit `abbbb22` changes sources/INSTRUCTIONS.md, bin/run.sh and README.md: fresh temporary
grader DSN, application init before load, no harness DDL, no canonical store mutation, temporary
store cleanup. All 35 check bodies and expected answers are unchanged. The former kit index lock
cleared without assistant intervention and the three-file commit succeeded.

The first three generated-initializer regressions fail before implementation with ImportError.
Focused verification: 175 passed, 1 skipped; includes initialization and acceptance rollback,
source prompt/header and memory checks. Six integration regressions cover fresh/repeat
preservation, cwd-independent script lookup, missing script and ordinary-open behavior,
canonical acceptance rollback, destructive SQL refusal before any script statement executes,
and scratch-fixture product initialization. The isolated fresh-store grader passes 35/35 with the generated initializer and a matching init
caller. Installed-wheel resource resolution, fresh/repeat initialization and packaged diagnostic prompt
V11 pass. Both wheel and sdist builds pass; the wheel is refreshed after final prompt wording.
Repository Ruff lint/format, skill validation and diff checks pass.
Full suite: 4,633 passed, 2 skipped, 4 failed in 953.07s. Three failures were the contract-example
test helper selecting the wrong fence/example; corrected to explicit markdown/acceptance-heading
selection with actual AC blocks, preserving all expected criteria/assertions. The fourth selected
system Python 3.10 in validation child scripts because the first invocation used the venv Python
without putting venv/bin on PATH. All four checks pass on the corrected targeted rerun (7.56s).
No full-suite rerun is claimed after those fixture/environment corrections. A copied application under /tmp uses the generated library
and an explicit init caller solely for compatibility verification; no application under runs/
is patched. Fix commits: `d8b82d0` (Drydock initializer/contracts and skill handoff), `abbbb22` (kit inputs).
Outcome: unverified until clean fresh UAT evidence.

The /ddk-uat prompt V11 and skill 1.6.0 now require concrete verified recommendations for the
separate implementation loop: observed failure/owner/evidence, exact file and behavior change,
invariants, regression/passing neighbor, and fresh-run/resume boundary. Unproved or low-value
ideas stay notes. Explicit repair authorization still requires completing the repair in the
active pass. This fixes the handoff failure demonstrated by this conversation.

### Run 20261027.190646 — 2026-10-27

Receipt: failed / ERROR / acceptance NOT_RUN; initial-build-1 exit 1, block-4
managed-state violation, not clean. Framework 9024185c80f14633e56d709968c8d86cfaaea238;
Claude haiku build, sonnet plan; source revision not independently established. Paths below
are relative to this run. This is the fresh run after d8b82d0 / kit abbbb22.

**FX-002 — managed-state fingerprint alert recurred; mechanism undetermined.** AgentStore
provisioned a disposable DSN and fingerprints the canonical SQLite main file and WAL. The
provider transcript for 20261027.193228.463Z-05a4d299 records an explicit
`sqlite3.connect('data/app.db')` and sqlite_master read, bypassing the supplied DSN; WAL
sidecars were present at the beginning of the call. The physical fingerprint changed before
acceptance; the pre-call logical backup is evidence/managed-state/sqlite-2rqgxlo6/app.db
under workspace/targets/FxRates. The exact write or checkpoint and logical difference are not
established. A separate temporary SQLite reproduction shows last-connection WAL checkpoint
changes main/WAL fingerprints while preserving the row; it does not prove this run's cause.
Prior 938021a detects physical changes, and this is a recurrence of the alert, not a proved
recurrence of a logical mutation. Do not restore or weaken detection on this evidence. Next
proof: compare consistent logical backups including any WAL without mutating published evidence,
and reproduce read/close with the same connection lifecycle; deliberate committed-write and
deletion neighbors must still stop. Fix: `eebf518` logical-state comparison and agent helper delivery. Outcome: unverified pending affected-stage UAT.

**FX-004 — inaccurate vacuous-criterion warning; reporting; open.** Plan stdout flags
FEATURE-LiveVisibility.md#live-load-visible-in-rates as passing when the endpoint does nothing
because the initial probe accepts 404. The same criterion requires `load` success and then
HTTP 200 with the expected date and rate, so an absent endpoint fails the final assertions.
No causal connection to the build stop. The warning generator is `acceptance.py` and `planning_session.py`; fix `eebf518` describes the assertion rather than claiming the whole criterion passes. UAT outcome unverified; accepting 404 before data exists is not itself a
proved defect. Plan verify independently warns dispatch-exit-codes hides output; no downstream
causal link established. Plan lineage corrected unknown story id cli-usage-placeholder-none;
its effect is undetermined and requires inspecting the attribution artifacts.

**Setup evidence.** DATABASE block-2 closed/implemented before block-4; generated root
`schema.sql`, persistence package, `initialize_database(dsn)`, and Drydock-managed disposable
store already exist. FEATURE-Init requires the product's init handler to call that initializer.
The agent reports 155 tests and nine criteria passing, but the managed-state gate prevented
Drydock from executing any of block-4's 12 post-call checks. Three init criteria require the
Drydock acceptance harness and the agent did not execute them verbatim. Thus agent self-report
is not independent acceptance proof. Previous FX-001 initializer repair remains unverified.
The provided grading harness is intentionally deferred until the application is complete.
Exact setup guidance alone cannot enforce filesystem isolation. The available evidence does
not prove that schema generation or provisioning was skipped.

## Decisions

- None.

## Questions

- None.

## Actions

- `2026-10-27` · FX-002 / FX-004: local fixes require clean affected-stage evidence in a new
  Ed-run UAT; the exact cause of the historical physical fingerprint change remains unknown.
  Inspect corrected lineage attribution separately if it affects a later stage.

- `2026-10-27` · FX-001: explicit initialization correction is implemented in kit commit
  `abbbb22` and Drydock initializer/contract repair `d8b82d0`. Outcome:
  unverified by UAT. Ed requires a fresh run; close on clean import/plan/build/scoring evidence
  using the new sources. No resume or historical evidence mutation is required.

## Working Notes

- FX-002 remains an unproved physical-fingerprint lead, not a verified repair recommendation or
  a prerequisite to a fresh run. The built store and snapshot have identical inspected schema
  and row counts; no data loss or need for restoration is established. A recurrence warrants a
  temporary logical-state-versus-file-state reproduction before recommending any gate change.
- FX-003's undeclared-sh advisory is retained as a low-value planning note. It did not cause the
  terminal failure and is not part of this repair queue.

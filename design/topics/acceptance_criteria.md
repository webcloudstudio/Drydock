# DESIGN: acceptance_criteria

| Field | Value |
|---|---|
| Version | 2026-10-15 V1 |
| Route | acceptance_criteria |
| Modules | `acceptance.py`, `acceptance_status.py`, `ac_repair.py`, `proof_integrity.py`, `status.py`, `build_run.py` |
| Prompts | `diagnose_ac_repair.md` |
| Tests | `tests/test_acceptance*.py`, `tests/test_ac_repair.py` |
| Governs | [build](../commands/build.md), [score](../commands/score.md), [plan](../commands/plan.md), [diagnose](../commands/diagnose.md), [status](../commands/status.md) |
| Pending spec | 0 |
| Pending impl | 0 |

## Behavior

### Purpose

How a Programmatic Acceptance criterion is recorded, classified, run, repaired, and counted during
staged builds. A criterion is evidence only when it binds to the product, was red before the build,
and measured something; everything else is reported, not charged.

### Rules

`2026-10-12` **Records.** The per-criterion ledger is the Target's `SOUNDINGS.md`, written by
`drydock score ac`: criterion id, Blueprint, intent, result (PASS, FAIL, UNVERIFIED, PREPASSED),
evidence, `verified_at`. Story and `ac` node state lives in `MANIFEST.md` (`pending`,
`blocked/questions`, `implemented`, `closed/implemented`, `closed/verified`, `closed/failed`).
`BUILD_LINEAGE.jsonl` is the execution log: one receipt per attempt carrying `acceptance`,
`pre_acceptance`, and `regressed_checks`, each result with `binding`, `passed`, and `error`.
`evidence/prepassed-acceptance.json` records criteria green before their block built.

`2026-10-12` **Status store.** `acceptance_status.py` owns `evidence/acceptance-status.json`
(replaced `prepassed-acceptance.json`): per criterion id, `status`, `error_code`, `code_sha256`,
`updated_at`, `detail`. `classify_baseline` maps the pre-build observation: pass → PREBUILD_PASSES
(or ALWAYS_PASSES when vacuous); malformed → ERROR `malformed`; skipped/unverified → ERROR
`environment`; import/file/command missing or unbuilt foundation → VALID `product-missing`; other
red → VALID `baseline-red`; "baseline unavailable" → nothing. Timeout and memory at baseline stay
VALID, because the baseline cannot tell a hang from an absent product. A status applies only while
its code digest matches. ALWAYS_PASSES, UNFIXABLE, FLAKY survive later baselines. A resumed
baseline never records PREBUILD_PASSES and otherwise fills gaps, replaces edited criteria, or
re-checks ERROR. Cost when broken: an edited criterion inherits a stale verdict, or a resumed block
is judged against its own partial work.

`2026-10-12` **FLAKY.** `_settle_flaky` reruns each binding, non-suite-bound FAIL once. FLAKY only
when the rerun passes and `_snapshot_files` is identical before the first run and after the rerun.
The result settles UNVERIFIED with the terminal `flaky check` prefix and records FLAKY.

`2026-10-12` **Exclusion.** `excluded_criteria` selects ALWAYS_PASSES, ERROR, UNFIXABLE, FLAKY
for the current code digest; `_run_valid_criteria` skips them in the post-build and resume runs and
returns each as UNVERIFIED with the terminal `excluded check: <STATUS> <code>` error, in
declaration order. PREBUILD_PASSES still runs (Q3). A FLAKY found mid-block joins the excluded set
for later attempts. Cost when broken: a criterion that cannot measure anything is counted as
evidence, or a valid criterion silently disappears from its story.

`2026-10-12` **Vacuity.** `proof_integrity._live_block` prunes only what the source decides:
constant `if`/`while` branches, statements after `return`/`raise`/`break`/`continue`, `try` bodies
whose AssertionError/Exception/BaseException/bare handler never re-raises, and `suppress(...)`
bodies. Undetermined means live. `classify_baseline` checks vacuity first, so ALWAYS_PASSES does
not depend on the baseline outcome.

`2026-10-12` **Empty-directory baseline.** `observe_empty_baseline` runs the block's criteria in a
temporary directory with only staged assets copied in and no `.venv` (an editable install would
leak the product), so the interpreter is Drydock's own. Empty pass → PREBUILD_PASSES `empty-tree`,
runs after the block, and counts as prepassed, so it never verifies (`2026-10-13`: running costs
nothing and can still catch a break). Empty red, current green → VALID `existing-behavior`,
runs, counts as prepassed for T5. No empty run → PREBUILD_PASSES `current-tree`, runs. A resumed
baseline skips `current-tree` and `existing-behavior` but records `empty-tree`. Cost when broken:
a criterion satisfied by an earlier block verifies a story that did nothing.

`2026-10-12` **AC repair.** `ac_repair.select_repairs` is deterministic: `malformed` when the
current-code status is ERROR `malformed`; `disputed` when the last lineage run of the criterion
was a non-binding miss and its current code is still non-binding; terminal statuses never. It is
the first step of `diagnose --apply` (`diagnose_command._ac_repair`) and spends nothing when
empty. `2026-10-13` The interactive default mode runs it too and confirms each verified repair; a
declined repair writes nothing and stays selected. One `diagnose_ac_repair` call; input is the AC block, fault, specification text, and
`sources/` numbered (files over 400 KB or non-text listed by name); `run_prompt` without tools in
the Blueprint directory. Each response block is validated in memory (the file parse cache keys on
mtime/size): same id, `_still_broken`, `citation_defect`, binding, not vacuous, then
`verify_repaired` runs the empty baseline and requires VALID (one retry on ERROR `environment`).
Kept → status VALID `repaired`, consumers reset via `reset_blueprint_consumers`, compacts deleted,
Target committed, exit 0 unless stalled. Rejected, impossible, or missing → original kept, status
UNFIXABLE. A failed call records nothing and falls through to the diagnosis. Cost when broken: a
criterion fitted to product output, or a loop that never ends on an unrepairable criterion.

`2026-10-12` **Completion gate.** `status.completion_check` is RETRYABLE while
`ac_repair.disputed_criteria` is non-empty, appending `disputed: <ids>` to a remaining-work
reason. UNFIXABLE is never selected, so it is clean. No cap: the loop script owns sequencing.

`2026-10-12` **Board.** `score ac` writes Binding (from the criterion code), Baseline (status and
error code), Previously Passed and Last Block (one read of `BUILD_LINEAGE.jsonl`, skipped results
excluded). `load_soundings` reads columns by name.

`2026-10-12` **Binding.** `acceptance.retyped_expectations` statically flags `==`/`!=` string
constants that are escapable and not supplied as input, and `/`-joined paths compared to a computed
attribute. A criterion with none is binding. A non-binding miss settles DISPUTED: reported, never
charged against the build.

`2026-10-12` **Assembled and cited expectations.** `_is_assembled_string` flags `JoinedStr`,
string `+`, string `%`, and `"...".format()` on either side of `==`/`!=`; the expression is exempt
only when its `ast.dump` matches an Assign value or call argument (`_supplied_expressions`). Every
assembled form is flagged regardless of fragment escapability, as decided. `Cite:` is resolved at
file parse (`_blueprint_root` finds the directory with `sources/`) into `cited_text`; the
`retyped_expectations` property drops literals found verbatim there. `citation_defect` makes a
non-resolving or non-matching citation a `bad-citation` plan defect. Cost when broken: a re-typed
value laundered through formatting or a fake citation becomes binding and fails correct products.

`2026-10-12` **Build loop per block.** Baseline run before the block builds (prepassed and vacuous
reported, not enforced). Build pass, then acceptance. Binding FAIL fails the block and is repairable.
Failure prefixes in `TERMINAL_FAILURE_PREFIXES` (malformed, timeout, memory, skipped, unverified)
are criterion faults and stop the loop when they are the only failures. Progress is a strict
superset of passed ids or a per-case tally gain. Two consecutive flat passes stop the block. Repair
feedback is appended to the block prompt. A green block runs a regression sweep over earlier
proven criteria. `2026-10-13` The swept set is the in-run proven set plus every criterion of every
FINISHED (`closed/verified`, `closed/implemented`) block, read from the Manifest at each unit;
`proven_green` is seeded from each criterion's last lineage outcome. Excluded statuses are not
swept. Blocks closed failed are not swept. The sweep's results are written to the attempt receipt
as `swept` and projected by `acceptance_history`. Cost when broken: the outer loop starts a new
build per pass, so an in-memory set alone sweeps nothing a previous pass delivered.

`2026-10-12` **Binding discipline.** A story verifies only on an own binding criterion that passed
and was not green before the build (ungoverned stories; a governed gate still decides its own).
Otherwise `closed/implemented` with one of three findings: `UNEXAMINED_FINDING` (no criterion ran),
`NON_BINDING_FINDING` (none binding), `PREPASSED_FINDING` (every binding pass was prepassed). A
resumed block takes its prepassed set from `prepassed-acceptance.json`, never from its own partial
tree, and does not re-record it. Progress (`_acceptance_progress`) compares binding criteria only,
over an identical executed set. DISPUTED misses never enter repair feedback, the resume seed, the
kit-fault stop test, or the regression sweep's regressed set (`_drives_repair`, `result.binding`).
Cost when broken: a story verified by a criterion that measured nothing, or a loop steered by a
possibly wrong expectation.

`2026-10-12` **Outer loop.** `drydock_build_loop.sh` alternates `drydock build` and
`drydock diagnose --apply` until `drydock status --check` passes. Cross-command feeding (for
example build verify into repair) is the loop's job, not a command's.

### Mechanism

See the **Build loop per block** and **Outer loop** rules above. Guardrails carried from the
working notes: repair changes a criterion under its existing id and removing an id is rejected;
FLAKY, ALWAYS_PASSES, and UNFIXABLE are terminal and never retried; cross-command sequencing stays
in `drydock_build_loop.sh`.

### Spec divergence

- The specification does not describe criterion statuses, binding discipline, or AC repair.

## Decisions

-

## Open Questions

-

## Working Notes

Not in scope yet: how the planner authors criteria and maps them to stories; governed gates from
`ACCEPTANCE.json` (see [build](../commands/build.md)).

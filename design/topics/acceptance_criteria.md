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
| Pending impl | 2 |

## Behavior

### Purpose

How a Programmatic Acceptance criterion is recorded, classified, run, repaired, and counted during
staged builds. A criterion is evidence only when it binds to the product, was red before the build,
and measured something; everything else is reported, not charged.

### Rules

`2026-10-19` · Native Go statuses survive the outer executor. Skip, not-run and unavailable are UNVERIFIED; compilation errors and native failures remain failures with distinct error text. The outer process group timeout terminates descendants. Breaking this rule counts a skipped test as proof.

`2026-10-12` · **Records.** `SOUNDINGS.md` (from `score ac`) is the per-criterion ledger: id,
Blueprint, result (`PASS`, `FAIL`, `UNVERIFIED`, `PREPASSED`), evidence, time, plus Binding,
Baseline, Previously Passed, Last Block columns read by name. Node state lives in `MANIFEST.md`.
`BUILD_LINEAGE.jsonl` holds one receipt per attempt (`acceptance`, `pre_acceptance`,
`regressed_checks`, `swept`). `evidence/acceptance-status.json` holds each criterion's status,
error code, and code digest.

`2026-10-12` · **A status holds only while its code digest matches.** The pre-build observation
classifies each criterion: pass → `PREBUILD_PASSES` (or `ALWAYS_PASSES` when vacuous); malformed →
`ERROR malformed`; skipped/unverified → `ERROR environment`; missing product → `VALID
product-missing`; other red → `VALID baseline-red`. Timeout and memory stay `VALID`. A resumed
baseline never records `PREBUILD_PASSES`. *Broken:* an edited criterion inherits a stale verdict.

`2026-10-12` · **Vacuity is decided from source only.** Constant branches, code after
`return`/`raise`, swallowing `try` bodies, and `suppress(...)` are pruned; undetermined means live.

`2026-10-12` · **The empty-tree baseline runs without the product.** Criteria run in a temp
directory with staged assets and no `.venv`. Empty pass → `PREBUILD_PASSES empty-tree` (runs, never
verifies); empty red but current green → `VALID existing-behavior`. *Broken:* a criterion satisfied
by an earlier block verifies a story that did nothing.

`2026-10-12` · **Terminal statuses are excluded, not retried.** `ALWAYS_PASSES`, `ERROR`,
`UNFIXABLE`, and `FLAKY` (rerun passes with an identical tree) skip later runs and report
`UNVERIFIED` with an `excluded check:` reason. `PREBUILD_PASSES` still runs. *Broken:* a criterion
that measures nothing counts as evidence.

`2026-10-12` · **Binding.** A criterion is non-binding when it compares against a re-typed or
assembled string not supplied as input; a literal found verbatim at its `Cite: sources/<file>:<line>`
counts as derived, and a bad citation is a `bad-citation` plan defect. A non-binding miss settles
`DISPUTED`: reported, never charged, never repair feedback, never a regression or progress.

`2026-10-12` · **A story verifies only on its own binding criterion that passed and was red before
the build.** Otherwise `closed/implemented` with `UNEXAMINED`, `NON_BINDING`, or `PREPASSED`
finding. A governed gate decides its own stories. *Broken:* a story verified by a criterion that
measured nothing.

`2026-10-12` · **Build loop per block.** Baseline, build, acceptance. A binding `FAIL` fails the
block and is repairable; terminal-prefix failures alone stop it. Progress is a strict superset of
passed ids or a per-case tally gain over binding criteria; two flat passes stop. A green block
sweeps every criterion of every finished block (`2026-10-13`). *Broken:* regressions from earlier
passes go unseen.

`2026-10-12` · **AC repair is deterministic in selection and validated in memory.** `malformed` and
`DISPUTED` criteria are selected; terminal ones never. One call per run with the AC, fault, spec
text, and numbered sources — never product source or output. A repair keeps its id, must bind, must
not be vacuous, and must run `VALID` on the empty baseline; else the criterion becomes `UNFIXABLE`.
*Broken:* criteria fitted to product output, or an endless loop.

`2026-10-12` · **Completion.** `status --check` is `RETRYABLE` while any criterion is `DISPUTED`;
`UNFIXABLE` is clean. The outer loop (`drydock_build_loop.sh`) owns sequencing: build, then
`diagnose --apply`, until `status --check` passes.

`2026-07-23` · **A deterministic definition of done is the complete suite, never a sample.** A
whole-project suite sits on the block that completes the capability (`Suite: full`) and is mirrored
into Sea Trials; running it as a story criterion is required, not an error. *Broken:* a sampled
suite verified a broken build.

`2026-10-18` · The Python execution harness is shipped in its language bundle. Go native tests run through the staged `drydock_go.run_test` helper inside the existing AC container; skipped and absent tests cannot pass. Cost when broken: valid language resources are omitted or acceptance evidence is misclassified.

### Mechanism

See the build-loop and completion rules. Removing a criterion id is rejected; `FLAKY`,
`ALWAYS_PASSES`, and `UNFIXABLE` are never retried.

### Spec divergence

- The specification does not describe criterion statuses, binding, or AC repair.

## Decisions

### Criteria acquire and release their own state (UAT gates §34)
`2026-08-14` · `spec:approved` · `impl:unimplemented`

A criterion arrives at whatever state exists, acquires what it needs, asserts about only what it
owns, and releases exactly that — idempotent, order-independent, against the real store. Sandboxing
and fresh stores were rejected: both hide the class and make schema defects unreachable. Grammar:

```text
=== AC <id> ===
=== SETUP ===      optional; acquire
=== CHECK ===      required; the verdict
=== TEARDOWN ===   optional; runs even after partial setup or a failed check
=== END AC <id> ===
```

Drydock renders the control flow per language (Python `try`/`finally`, Go `defer`); the model writes
phase bodies only. A teardown failure is a warning, never a verdict. An unsupported executable is
`UNVERIFIED`. Closes D-027 (a criterion that inserted rows and never removed them failed itself on
every rerun).

### Reject a dishonest or missing full suite at plan (conformance gate)
`2026-07-23` · `spec:approved` · `impl:unimplemented`

When a Blueprint imports an authoritative deterministic suite, plan integrity rejects a criterion
that declares `Suite: full` but samples it (`--pattern`, `--number`, slices, hardcoded subsets,
file-exists stubs), and rejects a plan where no story carries it. Deferred because detecting
"suite present" and sampling risks false positives.

## Open Questions

1. **Where do SETUP/TEARDOWN renderers live** — in the AC executor keyed by `Requires: executable`,
   or declared in stack guidance under `Rigging/`?
2. **What counts as sampling?** The heuristic boundary between a sampled or stubbed suite and a
   genuine full run, in `proof_integrity` or the plan gate.
3. **Residue observation is deferred (UAT gates §35).** Reporting files a criterion leaves in the
   build tree is diagnostic only and noisy; revisit if SETUP/TEARDOWN does not stop self-poisoning.

## Open Actions

-

## Working Notes

Not in scope yet: how the planner authors criteria and maps them to stories; governed gates from
`ACCEPTANCE.json` (see [build](../commands/build.md)).

# NOTES: UAT Gate Model — Acceptance, Epics, and Release

| Field | Value |
|-------|-------|
| Version | 2026-08-13 V10 |
| Route | uat |
| Status | Working notes — not canonical specification |
| Description | Theoretical pass over the whole UAT lifecycle: every gate that can stop a run, given a stable reference id, evidenced against all 18 recorded runs; then the proposed verdict, provenance, and exit model that replaces them. Part VII collapses the verdict model and severs the last coupling between Sea Trials and story acceptance. |
| Pending spec | 8 approved items — §27.3 Q1, §30.3, §30.4, §34, §35, §36, §37, §38 |
| Pending impl | 3 unimplemented sections — §27.3 Q1 (P-3a), §34, §35 |

---

## Goal

**Make `drydock uat` converge, so Drydock can be released.**

A UAT run must end in a verdict that is *about the product* — and must reach that verdict whether
the product is good, bad, or partly unverifiable. Today it usually ends in a verdict about
Drydock: a gate fired, a criterion was malformed, a batch was discarded, a directory was dirty.
Two of eighteen recorded runs produced a usable answer.

Three properties define done:

1. **A run finishes.** Every independent branch builds; a failure stops what depends on it and
   nothing else. One run reports every defect it can observe, not the first one.
2. **The verdict is the user's, not the model's.** Project acceptance comes from Sea Trials, which
   trace to user-authored intent. Story acceptance criteria guide the build and never reach the
   release verdict.
3. **Drydock can only fail a project by exhibiting a failure.** Absence of evidence yields
   *pending manual verification*, never *failed*. Drydock's own bookkeeping never fails anything.

The measurable target: the 18 recorded runs, replayed through the new fold, produce the verdict
each *should* have produced — and ReadingList `20260813.160121` reports `PASSED: 7 of 7`.

---

## Start Here (after a `/clear`)

**Read:** §1.3 (the problem), §12 (the two paths), **Part VII (§34–§41), which is the current
model and supersedes most of Parts II–III**, and §26 (what to build). That is ~250 lines and
sufficient to begin. The rest is evidence.

**Settled, do not relitigate:** Q1 and Q2 in §27.3; the eight resolutions in §27.1; the three calls
in §27.2. All three fixture `SEA_TRIALS.md` files are already correct (`185b55a`).

**Build next — Part VII (§40 carries its order). ReadingList `20260814.001652` is the first run
in the record to reach `score release` with a correct, complete product, and it was refused by
Drydock's own bookkeeping in a new way (§39). Part VII is the response and is the current
model.** §26 item 3.1a, the per-branch stall (§27.3 Q1), remains scheduled behind it.
Part VI records the transport work that got a run this far.
Phase 0 and Phase 1 are **done and committed**; §31 records what landed. §30's three delimiter
layers — recovery, containment, prevention — landed in `299b702`, and §32 records the regression
that produced and the shared-pairing fix that closed it (`b7ce19e`). §33 records the third
instance of the same class: the two repair prompts assembled in Python never adopted the grammar,
and discarded two correct repairs. Four consecutive runs died in the transport layer without
observing the product; **re-run Toml before building anything.** **Read Part VI first.**

**Phases 2–5 of §26 still wait for the measurement Phase 0 produces**, except the narrow half of
2.4, which landed as §29.

**All evidence is in `uat/`.** 18 runs across three fixtures, with prompts, provider output, and
evidence trees. There is no other source, and every claim in this file is checkable there. Runs
were produced by materially different software, so their *evidence* replays but their *lifecycle*
does not (§16.1).

---

**§1–§11 are analysis. §12–§25 are the proposed model. §26–§28 are the handoff**, approved in
discussion 2026-08-13.
Part I is the gate inventory, Part II the verdict model, Part III provenance and exit semantics,
Part IV the two-destination test model, Part V the consolidated order.
**§23 corrects D-011 and UC-008 in Part I. §26 supersedes §17. §27 supersedes §10, §18, §22, §25.**
Nothing here authorizes an edit to `docs/Drydock_Specification.md`; §28 records where the model
would diverge from it.

Companion file: `notes/notes_uat.md` holds the 2026-08-10 diagnosis and the Sea Trials redesign.
**Its gate inventory is superseded** (§"Gate inventory after simplification" listed four gates; the
real count is 31), and its "TDD patterns for story unit tests" section is superseded by §24. Its
diagnosis and Sea Trials redesign stand.

---

## 1. Problem Statement

### 1.1 What was believed

"`drydock uat` fails because the LLM writes bad acceptance criteria."

### 1.2 What the 18 recorded runs actually show

`uat/*/runs/*/result.json`, 2026-08-08 through 2026-08-13:

| Fixture | Runs | Passed | Terminal stage of the failures |
|---|---|---|---|
| Toml | 8 | **0** | build (8) |
| CommonMark | 8 | 1 | plan (3), build (4) |
| ReadingList | 2 | 1 | score (1) |
| **Total** | **18** | **2 (11%)** | |

Grouped by *what kind of thing* stopped the run:

| Class | Runs | Example |
|---|---|---|
| Model artifact rejected in transport | 3 | `Rejected: malformed artifact response`, 0/19 blueprints accepted |
| Drydock structural gate rejected a correct product | 1 | `Build directory has uncommitted changes` |
| Story AC oracle wrong, product correct | ~4 | `strings-escape-boundaries` re-typed `r"C:\Users\nodejs"` |
| Product genuinely defective | ~4 | Toml U+3000 via `strings.TrimSpace` |
| Build did not converge in the pass budget | 6 | `initial-build-1 exited 1`, degraded |

**At most a quarter of the failures were the thing being fixed all week.** The single most recent
run — ReadingList `20260813.160121`, with every fix from this week in it — failed for a reason
outside the AC system entirely (D-014, below).

### 1.3 The actual problem statement

Drydock has **31 independent ways to stop a run**, spread across seven stages, authored at
different times against different theories of what "done" means, sharing no vocabulary, no
severity scale, and no common notion of who is at fault. A run must clear all 31. At a per-gate
false-rejection rate of only 5%, the expected pass rate is 0.95³¹ ≈ 20% — which is within noise of
the observed 11%.

The failure is not any one gate. **It is the absence of a gate model.** Each gate was added
correctly, in response to a real observed defect, by someone who could not see the other thirty.

Three structural consequences follow, and all three are visible in the run record:

- **G1 — Every gate is fatal by default.** There are three severities in use (fatal / degraded /
  warning) but no rule assigning one, so authors default to fatal. `_integrity_check` alone holds
  12 `fatal.append` sites and 8 `warnings.append` sites, and the split between them is historical.
- **G2 — Fault is not attributed.** A gate says "this run stops". It does not say whether the
  product is wrong, the criterion is wrong, the kit is broken, or Drydock is wrong. Every one of
  those needs a different response, and the operator gets the same message.
- **G3 — Rejection is atomic at the wrong granularity.** One malformed artifact in a batch of 19
  discards all 19 (`planning_session.py:3421-3436`). One story that cannot close stalls every
  dependent block (`build_run.py:3561`). The blast radius of a local defect is the whole run.

---

## 2. Reference Scheme

Stable ids so a future defect can be filed against a gate rather than a line number.

- **`G-<STAGE>-<NN>`** — a gate. Stage ∈ `INIT` `IMP` `ANA` `PLAN` `BUILD` `REFIT` `TEST` `SCORE`.
- **`D-<NNN>`** — an observed defect, with the run that evidences it.
- **`UC-<NNN>`** — a use case a gate must admit without complaint.
- **`P-<N>`** — a principle the gate model asserts.

Ids are append-only. A retired gate keeps its id and is marked *retired*, so a future run log
naming `G-PLAN-07` stays readable.

---

## 3. The Lifecycle, Step by Step

`STAGES = ("init", "import", "analyze", "plan", "build", "refit", "test", "score")`
— `uat.py:43`. UAT runs each in order in one workspace under `uat/<Fixture>/runs/<id>/`.

### 3.1 `init` — `G-INIT-*`

Creates `targets/<T>/`, seeds `METADATA.md`, stages the fixture's Commander inputs
(`TECHNOLOGY_STACK.md`, `SEA_TRIALS.md`, `ACCEPTANCE.json`) from `uat/<F>/inputs/`.

| Id | Gate | Severity | Fault |
|---|---|---|---|
| G-INIT-01 | Target directory resolvable under `$DRYDOCK_WORKSPACE/targets/` | fatal | operator |
| G-INIT-02 | Fixture declaration parses (`uat.json`) | fatal | Drydock kit |

No LLM. Has never failed in the record.

### 3.2 `import` — `G-IMP-*`

Copies user sources into `blueprint/sources/` read-only.

| Id | Gate | Severity | Fault |
|---|---|---|---|
| G-IMP-01 | Source paths exist and are readable | fatal | operator |
| G-IMP-02 | Staged assets recorded for later tamper detection | fatal | Drydock kit |

No LLM. Has never failed in the record.

### 3.3 `analyze` — `G-ANA-*`

One LLM pass. Authors `ANALYSIS.md`, `SOUNDINGS.md`, and — **unless a Commander
`SEA_TRIALS.md` is present** — the project acceptance criteria.

| Id | Gate | Severity | Fault |
|---|---|---|---|
| G-ANA-01 | Model response parses as delimited artifacts | fatal | model |
| G-ANA-02 | `SEA_TRIALS.md` parses as a typed table with a policy block | fatal | model |
| G-ANA-03 | Commander `SEA_TRIALS.md`, if present, is used verbatim and never overwritten | fatal | Drydock kit |

All three fixtures now ship a frozen Commander `SEA_TRIALS.md`, so G-ANA-02 is dormant in UAT and
live only for real Targets. **This is the one place the exam-authorship defect was fully closed.**

### 3.4 `plan` — `G-PLAN-*` — *the highest-loss stage*

Two LLM stages. Stage 1 emits the topology (`MANIFEST.md`). Stage 2 emits Blueprint
specifications in batches, each carrying `=== AC <id> ===` containers. Then `_integrity_check`
(`planning_session.py:1952`) runs 12 fatal checks over the whole plan.

**Transport gates** — these fire before anything is read:

| Id | Gate | Severity | Fault | Code |
|---|---|---|---|---|
| G-PLAN-01 | Response is non-empty | fatal after N stalls | model | `:3409` |
| G-PLAN-02 | Response parses as strict delimited blocks | **whole batch discarded** | model | `:3421` |
| G-PLAN-03 | Batch contains at least one Blueprint artifact | batch discarded | model | `:3437` |

**Topology gates:**

| Id | Gate | Severity | Fault | Code |
|---|---|---|---|---|
| G-PLAN-04 | Every `depends` names a known block | fatal | model | `_integrity_check` |
| G-PLAN-05 | Dependency graph is acyclic | fatal | model | |
| G-PLAN-06 | Every `parent` names a known block of a legal type | fatal | model | |
| G-PLAN-07 | A story implements exactly one spec | fatal | model | `:2016` |
| G-PLAN-08 | Implemented spec file exists | fatal | model | `:2024` |
| G-PLAN-09 | No spec is implemented by two stories | fatal | model | `:2080` |

**Acceptance-authoring gates** — the contested set:

| Id | Gate | Severity | Fault | Code |
|---|---|---|---|---|
| G-PLAN-10 | A SCREEN's AC literally calls every route it declares | fatal | model | `:2054` |
| G-PLAN-11 | A FEATURE's AC names every route it declares | warning | model | `:2060` |
| G-PLAN-12 | **A story with a programmatic surface carries ≥ 2 AC** | fatal | model | `:2065`, `_MIN_ASSERTIONS_PER_STORY = 2` |
| G-PLAN-13 | Every `accepts:` names a known Sea Trial | fatal | model | `:2097` |
| G-PLAN-14 | Every `Sea Trials:` proof tag names a known trial | fatal | model | `:2105` |
| G-PLAN-15 | Required Sea Trials have implementation/proof coverage | fatal | model | `:2115` |
| G-PLAN-16 | Malformed AC (does not compile, or unclosed container) | **blocking DECISION** | model | `malformed_acceptance_decisions()` |
| G-PLAN-17 | AC re-types an expected literal → non-binding | **advisory** | model | `retyped_expectations` |

G-PLAN-16 and G-PLAN-17 are this week's work. Everything above them predates it.

*Retired this week:* `G-PLAN-18` tooling authorization (`validate_declared_external_usage`);
`G-PLAN-19` … `G-PLAN-24`, the six `proof_integrity` text analyzers; `G-PLAN-25`
`_deterministic_acceptance_setup_defects`; `G-PLAN-26` unbounded-suite fatals.

### 3.5 `build` — `G-BUILD-*`

Per Manifest block in topological order. Each block gets an LLM pass, then up to
`repair_attempts` (default 3, `build_run.py:2060`) repair passes. UAT drives the whole stage in up
to `DEFAULT_MAX_BUILD_PASSES = 25` invocations (`uat.py:30`).

Per attempt, in order:

| Id | Gate | Severity | Fault | Code |
|---|---|---|---|---|
| G-BUILD-01 | Model response parses as delimited artifacts | repairable | model | |
| G-BUILD-02 | Question gates — no unanswered blocking DECISION on this story | block held | Commander | `:2951` |
| G-BUILD-03 | Python dependency manifest gate | repairable | model | `:2755` |
| G-BUILD-04 | Governed stage gate from `ACCEPTANCE.json` | **repairable, then fatal to the block** | product | `:3041` |
| G-BUILD-05 | Binding story AC (R1-legal oracle) | repairable, then `closed/failed` | product | `failed_checks` |
| G-BUILD-06 | Non-binding story AC (re-typed literal) | `DISPUTED`, never blocks | criterion | `disputed_checks` |
| G-BUILD-07 | Applied specs not stale | fatal | Drydock kit | `:875` |
| G-BUILD-08 | Block reaches a FINISHED state before dependents build | **stalls all dependents** | product | `:3561` |

Terminal block states after this week: `closed/verified` (gate PASS), `closed/failed` (gate FAIL
or binding AC failure), `closed/implemented` (gate ERROR, or no gate where a contract exists —
carries `UNGOVERNED_FINDING`).

*Retired this week:* `G-BUILD-09` `_quarantine_unsatisfiable_acceptance`; `G-BUILD-10` the
`AC_BROKEN` early terminal; `G-BUILD-11` the prose-defect early terminal.

### 3.6 `refit` — `G-REFIT-*`

A second requirements pass: import an update, re-plan the delta, build again. Re-enters
`G-PLAN-*` and `G-BUILD-*` wholesale — **it has no gates of its own**, and inherits every plan
gate a second time.

| Id | Gate | Severity | Fault |
|---|---|---|---|
| G-REFIT-01 | Skipped entirely when the run is already degraded (`uat.py:942`) | — | — |

### 3.7 `test` — `G-TEST-*`

Runs the fixture's declared `test_command` against the build tree.

| Id | Gate | Severity | Fault |
|---|---|---|---|
| G-TEST-01 | Test command exits zero | degraded, not fatal | product |

**G-TEST-01 has a side effect that is itself a defect — see D-014.**

### 3.8 `score` — `G-SCORE-*`

Three commands: `score acceptance`, `score build-report`, `score release`. Only `release` gates.
`score_release` at `score.py:300`.

| Id | Gate | Severity | Fault | Code |
|---|---|---|---|---|
| G-SCORE-01 | Governed `full` gate from `ACCEPTANCE.json` passes | blocker | product | `:342` |
| G-SCORE-02 | Governed `full` gate could run at all | blocker | kit | `:345` |
| G-SCORE-03 | Applied Blueprint specs are not stale | blocker | Drydock kit | `:359` |
| G-SCORE-04 | Build directory has a usable Git code identity | blocker | Drydock kit | `:364` |
| G-SCORE-05 | **Build directory has no uncommitted changes** | blocker | Drydock kit | `:366` |
| G-SCORE-06 | `SEA_TRIALS.md` has no unresolved QUESTIONS | blocker | Commander | `:368` |
| G-SCORE-07 | No staged build asset was modified | blocker | product | `:375` |
| G-SCORE-08 | No unknown Sea Trial references | blocker | model | `:419` |
| G-SCORE-09 | Required Sea Trials have implementation/proof coverage | blocker | model | `:430` |
| G-SCORE-10 | No guardrail is BREACHED | blocker | product | `:563` |
| G-SCORE-11 | Every required Sea Trial verdict is PASS | blocker | product | `:571` |
| G-SCORE-12 | Guardrail UNPROVEN | **attestation, never blocks** | — | `:565` |
| G-SCORE-13 | Manifest work not `closed/verified` | **warning, never blocks** | — | `:349` |

G-SCORE-12 and G-SCORE-13 are correctly non-blocking and are the model the rest should follow.

**Only three of these thirteen ask whether the product works** (G-SCORE-01, G-SCORE-10,
G-SCORE-11). Four ask whether Drydock's own bookkeeping is tidy.

---

## 4. Defect Catalog

Every distinct failure mode in the 18 runs. `status` is as of 2026-08-13.

| Id | Defect | Gate | Evidence | Status |
|---|---|---|---|---|
| D-001 | Story AC re-types an expected literal and is wrong; product correct | G-BUILD-05 | Toml `20260813.084830`, `strings-escape-boundaries` | fixed — G-PLAN-17 makes it non-binding |
| D-002 | Malformed AC raises `SpecificationError` and discards the whole plan | G-PLAN-16 | multiple | fixed — becomes a blocking DECISION |
| D-003 | `proof_integrity` blacklist grows without bound; two analyzers retracted | G-PLAN-19…24 | `ef53688`, `d91d66b` | fixed — deleted, 2664 lines |
| D-004 | Release gate averages seven LLM-invented dimensions and blocks under 80 | G-SCORE-* | all pre-`20260813` runs | fixed — rubric deleted |
| D-005 | UNPROVEN guardrail treated as breach | G-SCORE-12 | `78f9233` | fixed — attestation |
| D-006 | `analyze` writes the exam it is graded on | G-ANA-03 | all pre-`20260810` runs | fixed — frozen Commander file |
| D-007 | Assertion that never reached the code counted as product failure | G-BUILD-05 | pervasive | fixed — UNVERIFIED |
| D-008 | One malformed artifact discards a batch of 19 blueprints | G-PLAN-02 | CommonMark `20260811.184523`, `.215210` | fixed — per-artifact rejection, §30.3, `299b702` |
| D-009 | Assertion-count minimum forces the model to author AC it has no oracle for | G-PLAN-12 | CommonMark `20260811.215210` — killed 8 LLM calls in | **open** |
| D-010 | A story that will not close stalls every dependent block | G-BUILD-08 | Toml, all 8 runs | **open by design — see §6.4** |
| D-011 | ~~Toml parser accepts U+3000 as whitespace~~ **RETRACTED — see §23.1.** The 126 valid-case failures are unbuilt work, not a parser bug | G-BUILD-08 | Toml `20260813.084830` | folded into D-010 |
| D-012 | Sea Trial `st-001` carries no `Command:`; release resolves through model proof tags | G-SCORE-09 | Toml fixture | **open** |
| D-013 | `ACCEPTANCE.json` stage keys are model-chosen slugs; a rename silently unbinds the gate | G-BUILD-04 | not yet observed | **open — latent** |
| D-014 | **`test` creates `instance/reading_list.sqlite3`; `score release` then blocks the build as dirty** | G-TEST-01 → G-SCORE-05 | ReadingList `20260813.160121` | **open — see below** |
| D-015 | Build does not converge inside the pass budget; recorded as `degraded` with no attribution | G-BUILD-08 | 6 runs | **open** |
| D-021 | A governed gate exiting 2 — a usage error, meaning it could not run — is classified `FAIL` and charged to the product | G-BUILD-04 → G-SCORE-01 | Toml `20260813.195530` | fixed — exit 2 is now ERROR (§29) |
| D-022 | The Toml fixture's `run_conformance.sh` probed the harness with `toml-test -version`, which that harness does not accept; the version guard then refused every run | G-BUILD-04 | Toml `20260813.195530` | fixed — uses the `version` subcommand |
| D-023 | A mismatched closing delimiter is read as a new opening block, not as a malformed close, so the run dies naming a block the model never opened | G-ANA-01 | Toml `20260813.211658` — `=== END COMPASS ===` closing `=== COMPASS.md ===` | fixed — closed by position, §30.2, `299b702` |
| D-024 | The invariant boundary was adopted by the parsers and nine prompts but not by five callers that read delimiters directly; an undamaged response read as wholly unpaired | G-PLAN-02 | Toml `20260813.231738` — `KeyError: 'TOPOLOGY.md'` | fixed — one shared positional pairing, §32, `b7ce19e` |
| D-026 | `plan` and `score release` both enforce "required Sea Trials are covered" and mean different things by it: `plan` accepts an `accepts:` field **or** a `Sea Trials:` proof tag, `score` counts proof tags only. A plan that satisfies G-PLAN-15 in full is refused five times at the release gate | G-PLAN-15 → G-SCORE-09 | ReadingList `20260814.001652` — 7 trials with `accepts:`, 2 with proof tags, 5 blockers | **open** — dissolved by §38 |
| D-027 | An AC block acquires persistent state and never releases it. `database-order` opens `acceptance-order.sqlite3` in the build tree, inserts two rows, asserts on the whole table, and deletes nothing; three executions accumulated six rows and the criterion failed against a product that is correct (`ORDER BY id`). It passes once and fails forever after | G-BUILD-05 | ReadingList `20260814.001652` — `AssertionError` on a two-element comparison against six rows | **open** — closed by §34, detected by §35 |
| D-025 | The two repair prompts are assembled in Python, state no artifact grammar, and wrap their input in XML tags; the model mirrored the tags, and a topology repair it had performed correctly was discarded unread — twice — while Stage 2 spent two batch passes on the declaration already known to be defective | G-PLAN-02 | Toml `20260813.234757` — refused on `DECODER-002`, which the repair had covered | fixed — shared emission contract and a reported discard, §33 |

### D-014 in full, because it is the cleanest example of the whole disease

ReadingList `20260813.160121`, run today with every fix from this week in place:

- 8 of 8 Sea Trials **PASS**, including all 6 required.
- 26 of 26 programmatic assertions **PASS**. `failed: 0, unverified: 0, harness_defects: 0`.
- `score acceptance` exit 0. `score build-report` exit 0.
- `score release` **exit 1**, `INCOMPLETE`, one blocker:
  `BLOCKER: Build directory has uncommitted changes`.

The uncommitted change was `instance/reading_list.sqlite3`, 12 288 bytes, created at 12:20 by
Drydock running the project's own test suite at stage `test`. The generated project has no
`.gitignore`.

**Drydock ran the tests, the tests created a database file, and Drydock then failed the release
because a database file was present.** No model, no acceptance criterion, and no product defect
was involved. A perfect build was rejected by Drydock's own housekeeping.

This is the strongest evidence in the record for the thesis in §1.3: the AC system was not what
was failing this run, and fixing the AC system did not make this run pass.

---

## 5. Use Cases the Gate Model Must Admit

A gate design is only testable against the cases it must **not** reject.

| Id | Use case | Which gate threatens it |
|---|---|---|
| UC-001 | A correct product whose test run leaves a runtime artifact in the tree | G-SCORE-05 (D-014) |
| UC-002 | A story whose only honest oracle is an imported conformance slice — one AC, not two | G-PLAN-12 (D-009) |
| UC-003 | A guardrail that admits no automated proof (`shall never transmit…`) | G-SCORE-12 — already correct |
| UC-004 | A qualitative Sea Trial (`a reader can add a book without instructions`) | G-SCORE-11 |
| UC-005 | A renderer whose output genuinely cannot be derived from its input (`# h` → `<h1>h</h1>`) | G-PLAN-17 — escape hatch |
| UC-006 | A project with no `ACCEPTANCE.json` at all (ReadingList) | G-BUILD-04 — must degrade to model AC |
| UC-007 | One malformed artifact among nineteen good ones | G-PLAN-02 (D-008) |
| UC-008 | A product that is genuinely defective and must be reported as such, loudly | all — the case that must still work |
| UC-009 | A second requirements pass that invalidates a previously verified story | G-REFIT-01 |
| UC-010 | A harness absent from the machine at run time | G-BUILD-04 — must be ERROR, not FAIL |

UC-008 is the one that constrains everything else. A gate model tuned only to stop false
rejections becomes a rubber stamp. ~~Toml's U+3000 defect (D-011) is the case that must keep
failing.~~ **Corrected in §23.1** — that defect does not exist, and the run record contains **no
example of a completed product that is genuinely defective.** UC-008 is currently unevidenced,
which is itself a finding.

---

## 6. Postulated Gate Model

Five principles. Each is a statement about *all 31 gates at once*, which is the property the
current design lacks.

### P-1 — Every gate declares its fault domain

Four domains, and they are not interchangeable:

| Domain | Meaning | Consequence |
|---|---|---|
| **PRODUCT** | The thing Drydock built is wrong | **Blocks.** This is what the gate model is for. |
| **CRITERION** | The test is wrong; the product may be fine | Records `DISPUTED`. Never blocks. Feeds the criterion's score. |
| **KIT** | Harness absent, timeout, signal, permission | `UNVERIFIED`/`ERROR`. Never charged to the build. |
| **DRYDOCK** | Drydock's own bookkeeping is unhappy | **Never blocks a release.** Reported as an operator finding. |

Applying this to §3 reclassifies four score gates immediately: G-SCORE-03, -04, -05 and G-BUILD-07
are DRYDOCK-domain and must not block. D-014 disappears by construction, not by adding a
`.gitignore`.

The rule that makes this enforceable: **a gate may only block on the fault domain it can
distinguish.** G-SCORE-05 cannot distinguish "the build agent left junk" from "the test suite
wrote a database", so it may not block on either.

### P-2 — Authority cannot be inferred from an artifact the model authored

Already implemented, and it is the load-bearing idea. Restated as a precedence order:

```
Commander-supplied argv (ACCEPTANCE.json, staged conformance suite)   → binding
Model AC with an oracle it could not have got wrong (R1 whitelist)    → binding
Model AC that re-types its expected value                             → DISPUTED
Model prose claiming a defect (AC_BROKEN)                             → recorded, terminates nothing
```

**A governed gate outranks a model criterion; a model criterion outranks nothing at all.** The
second clause matters: with no governed contract, model AC must still bind, or ReadingList has no
failure signal whatsoever.

### P-3 — Rejection granularity equals authorship granularity

If a model authors 19 artifacts in one response, a defect in one may cost one, not nineteen
(D-008). If a story fails, it may block its dependents — that is real — but the run must continue
through every independent branch and report the whole picture at the end (D-010, D-015).

The operational form: **no gate may discard work that it did not judge.**

### P-4 — Quantity is never a gate

G-PLAN-12 requires ≥ 2 assertions per story. This is the only gate in the system that is
*upstream-causal to the defect everyone was chasing*: it forces the model to author criteria it
has no oracle for, and every invented criterion is a fresh chance to re-type an expected value
wrongly. The Toml evidence is exact — 15 suite-bound AC, all passing; 10 hand-authored AC,
covering nothing the conformance suite did not already cover, supplying 100% of the failures.

Coverage is measured by the authoritative suite, or it is not measured. Counting assertions
measures nothing and costs a plan.

### P-5 — A stopped run reports the whole state, not the first blocker

Every stage should run to its natural end and emit a verdict per gate. The run's status is a
function over those verdicts, computed once, at the end, by a policy that lives in data. Today the
first fatal wins and everything downstream is unknown — which is why a week of runs produced no
cumulative picture.

### 6.1 The resulting three-layer gate

| Layer | Question | Authority | Blocks? |
|---|---|---|---|
| **Structural** | Can Drydock proceed? | deterministic parse | yes, but only the artifact it judged (P-3) |
| **Acceptance** | Does the product do what was asked? | governed argv, else R1-legal model AC | yes |
| **Hygiene** | Is Drydock's own bookkeeping tidy? | deterministic | **no** — operator finding |

Every one of the 31 gates lands in exactly one layer. The current tree has them interleaved,
which is why G-SCORE-05 (hygiene) and G-SCORE-11 (acceptance) carry the same weight.

### 6.2 Story AC vs Sea Trials, settled

Ed's framing — two separate paths — is correct and the model must keep them separate:

| | Story / block AC | Sea Trials |
|---|---|---|
| Scope | one story | the project |
| Question | did this increment get built | is the project acceptable |
| Authored by | `plan`, per story | Commander (frozen), else `analyze` |
| Consumed by | the build repair loop | `score release` |
| Effect on release | **none, directly** | the only input |
| Effect on build | drives repair | none |

The connection between them is **by construction, not by reference**: a story that does not close
does not build, so a release cannot contain unbuilt work. Story AC does not need to be an input to
the release gate, and making it one (D-004) is what let a wrong criterion fail a perfect project.

### 6.3 Epic / block gates

An epic (a container block) has no AC of its own. Its gate is the conjunction of its children's,
with one addition: **an epic may close `closed/implemented` when its children closed but no
governed gate covered them.** That state is the honest one — the work exists, nothing authoritative
judged it — and it satisfies dependencies so the run continues (P-3).

### 6.4 On D-010, deliberately

A stalled dependent chain is *correct* when the blocking story genuinely fails (Toml's U+3000).
It is a defect only when the stall is caused by a CRITERION- or DRYDOCK-domain fault. Under P-1
those can no longer block, so D-010 resolves without touching the scheduler. It stays open in the
catalog because that reasoning is untested against a real run.

---

## 7. How to Compile Defects and Use Cases in Future

The reason this week cost what it did is that each failure was diagnosed from a fresh reading of
the logs. The runs are all on disk; nothing was harvesting them.

### 7.1 The one-line rule

**Every run that does not pass produces exactly one new row in §4, naming the gate id from §3.**

If the failure cannot be attributed to an existing gate id, that is itself the finding: an
undocumented gate exists, and it gets an id before anything is fixed.

### 7.2 What a `result.json` must carry for this to work

Today `result.json` carries `status`, `error`, `degraded`, `assertions`, and (as of this week)
`execution_status` / `acceptance_status`. It does not carry which gate stopped the run. Adding a
single field would make the whole catalog mechanical:

```json
"gate_verdicts": [
  {"id": "G-SCORE-05", "outcome": "BLOCK", "domain": "DRYDOCK",
   "detail": "instance/reading_list.sqlite3"}
]
```

With that field, §4 is generated, not written, and the pass-rate table in §1.2 is a query.

### 7.3 The regression corpus

`uat/<Fixture>/runs/` is already the corpus — 18 runs, complete with prompts, provider output, and
evidence trees. It should be treated as a fixture library, not an archive:

- Any change to a gate is validated by replaying the recorded runs that gate previously rejected.
- A gate that would now admit Toml `20260813.084830` is wrong (D-011 is a real defect).
- A gate that would now admit ReadingList `20260813.160121` is right (D-014 is not).

That is a decidable acceptance test for the gate model itself, available today, at zero token cost.

### 7.4 Cadence

- **Per run:** one row in §4, one gate id, one sentence.
- **Per change to a gate:** replay §7.3, record which recorded runs flip.
- **Per week:** recompute §1.2. If the pass rate is not moving, the changes are not addressing the
  gates that actually fire.

---

## 8. Acceptance Criteria for the Gate Model

- Every gate that can stop a run has an id in §3, and no gate exists that is not listed there.
- Every gate declares one of the four fault domains (P-1).
- No DRYDOCK-domain gate blocks a release.
- No gate rejects work it did not judge (P-3).
- No gate measures quantity (P-4).
- `result.json` names the gate that stopped the run.
- Replaying the 18 recorded runs reproduces the same verdict for each.
- ReadingList `20260813.160121` passes; Toml `20260813.084830` still fails.

---

## 9. Guardrails

- The 31-gate inventory in §3 is maintained. A new gate without an id is a defect.
- Ids are append-only; a retired gate keeps its id and is marked retired.
- Story AC never becomes an input to the release gate again (D-004).
- No new blocking analyzer that reasons from a criterion's *text* (the `proof_integrity` lesson).
- Sea Trials and story AC stay two paths; the only coupling is by construction (§6.2).

---

## 10. Open Questions

- **Is the hygiene layer allowed to block anything at all?** G-SCORE-07 (staged asset tampered)
  is hygiene by structure but is genuinely about whether the thing scored is the thing built.
  It may be the one hygiene gate that must block.
- **Does `refit` need its own gates,** or is inheriting `G-PLAN-*` and `G-BUILD-*` correct? A
  refit that invalidates an already-verified story (UC-009) has no defined behavior today.
- **What is the right response to a governed gate that stays red past the repair budget?** Stop
  the branch and continue the run (P-3), or stop the run? The record cannot answer this because no
  run has yet reached that state under the new code.
- **D-012:** should the Toml `full` gate carry `st-001`, or should `st-001` carry a `Command:`?
  These give the same verdict and different provenance.

---

## 11. Not in Scope

- Fixing D-011. It is a real product defect and Drydock reporting it is Drydock working.
- Changing `analyze` criterion generation for real Targets.
- Any edit to `docs/Drydock_Specification.md`. The divergence at `:952` (SCORECARD described as
  "seven-dimension quality + drift scores") is recorded as a fact only.

---
---

# PART II — THE PROPOSED MODEL

`2026-08-13` · approved in discussion

## 12. The Two Paths, Stated Once

The whole design follows from separating two things that have been fused since the beginning.

| | **Sea Trials** | **Story / block AC** |
|---|---|---|
| What it is | the user's stated objectives, made as deterministic as possible | test-driven build guidance |
| Question | *is this project acceptable?* | *did this increment get built correctly?* |
| Method | **judged** — an LLM reasons over all available evidence | **executed** — code runs, exits 0 or not |
| Authored by | Commander (frozen), else `analyze` | `plan`, per story |
| Determines the release verdict | **yes — it is the only input** | **no, by any path** |
| Determines block state | no | yes |
| Noise tolerance | none — this is the product's report card | high — some AC will be wrong and that is survivable |

The load-bearing sentence: **a project succeeds if its success criteria are met, regardless of
noise on the acceptance criteria.** Story AC is how Drydock builds the right thing. Sea Trials are
how Drydock reports whether it did.

**Sea Trials are not test-driven.** They are graded. Deterministic evidence feeds the grade; it
does not *constitute* the grade. This is the correction to `score.py:520-535`, where a trial
declaring `Verification: proof` has the grader's verdict discarded and replaced by whether a
model-authored AC happened to tag `Sea Trials: st-NNN` — routing project acceptance through the
test-driven path, which is precisely the fusion this section undoes.

---

## 13. The Verdict Model — `V-*`

### V-1 — Four terminal verdicts, and only four

| Verdict | Meaning | Exit |
|---|---|---|
| **PASSED** | Every project criterion met. | 0 |
| **PENDING MANUAL VERIFICATION** | No criterion demonstrably failed; one or more cannot be settled from available evidence. Each names a next step. | 0 |
| **FAILED** | At least one criterion **demonstrably** failed. | 1 |
| **ERROR** | Drydock could not execute the judgement. Says nothing about the product. | 1 |

`PENDING` is **not a failure**. It is a project with an open question, and it exits 0. This single
change is what makes ReadingList `20260813.160121` report honestly.

### V-2 — The asymmetric evidence rule *(the engineering core)*

> **MET may be reached by inference. NOT MET requires a demonstration.
> Absence of evidence yields PENDING, never NOT MET.**

Deterministic evidence is **monotonic downward only**:

| Transition | Permitted? |
|---|---|
| PENDING → MET, by reasoning over evidence | **yes** — this is what the grader is for |
| PENDING → NOT MET, by reasoning alone | **no** — this is the defect |
| NOT MET → MET, by reasoning | **no** — a red governed gate cannot be argued away |
| MET → NOT MET, by a demonstrated failure | yes |

The grader may only return NOT MET while **citing a specific artifact that exhibits the failure** —
a red conformance case, a failing assertion, a named code path. "I have no proof it holds" is
PENDING. This is the rule that makes the system deterministic in the direction that matters:
**Drydock can only fail a project by exhibiting a failure.**

It also preserves UC-008. Toml's U+3000 defect (D-011) produces 126 red conformance cases, which
pin NOT MET, which the grader cannot reason away. The model gets latitude only in the direction of
absent evidence.

### V-3 — Three per-trial verdicts, one vocabulary

`MET` · `NOT MET` · `PENDING`.

Retires six words covering three states across two subsystems: `PASS`/`FAIL`/`INCONCLUSIVE` in the
grader and `HELD`/`BREACHED`/`UNPROVEN` in the guardrail reporter. One vocabulary, everywhere.

### V-4 — A guardrail is not a special kind of criterion

`Type: guardrail` becomes reporting metadata only. It gets no inference rules of its own, no
separate verdict words, and no absolute-prohibition logic.

The reason it acquired them was that a prohibition seemed unprovable, so the system demanded
positive proof and failed without it. Under V-2 that case is already handled: a prohibition with no
counter-example and supporting evidence grades MET or PENDING, and never FAILED. The special case
was a workaround for the missing asymmetry rule.

Retires `prompts/score_release.md:35-37`, which instructs *"Return `PASS` only when the supplied
evidence positively shows the prohibition held... Never infer that a guardrail held"* — and which
also carries the now-false claim *"which fails the gate exactly as a breach does"* (`score.py:565`
has made it an attestation since this week). The prompt is stale and it is biasing the grader:
st-008's recorded rationale is a verbatim restatement of that instruction.

### V-5 — Deterministic evidence is input, not override

`Verification:` stops selecting a verdict-producing mechanism. Every trial is graded by the same
pass, and every trial's grade sees every piece of evidence. `Verification:` survives only as a
hint about which evidence is most relevant.

Precedence inside the grade:

```
1. A demonstrated failure bound to this criterion    → NOT MET, non-negotiable
2. A governed gate PASS covering this criterion      → MET, non-negotiable
3. Otherwise                                          → the grader reasons: MET or PENDING
```

### V-6 — Hygiene leaves the release path entirely

Under P-1, no DRYDOCK-domain gate blocks. Concretely:

| Gate | Was | Becomes |
|---|---|---|
| G-SCORE-05 build dir dirty | blocker | **removed from the verdict.** Each run is independent evidence; git state is not project acceptance. Kills D-014. |
| G-SCORE-04 no git code identity | blocker | reported provenance field |
| G-SCORE-03 stale applied specs | blocker | operator warning |
| G-SCORE-13 Manifest not closed/verified | warning | unchanged — already correct |
| G-SCORE-07 staged asset modified | blocker | **ERROR**, not FAILED — the thing judged is not the thing built, so no verdict is available |

### V-7 — ERROR is computed first, and separately

Before any grading: can Drydock judge at all? Governed gate could not execute (missing binary,
timeout, signal), staged asset tampered, required artifact missing or unparseable, grader returned
nothing. Any of these → **ERROR**, stop, claim nothing about the product.

This is the fourth fault domain (KIT) surfacing at the top level. Today these are indistinguishable
from FAILED, which is why the run record cannot separate "Drydock broke" from "the product is
wrong" without reading logs.

---

## 14. The AC Tier Model — `T-*`

Story AC never reaches the release verdict (§12). It has one job: drive the build to the right
thing. Four tiers, by how much authority the criterion has earned.

| Tier | Source | Autonomous (`uat`) | Interactive | Rationale |
|---|---|---|---|---|
| **T-1 BLOCKING** | governed argv in `ACCEPTANCE.json`; imported authoritative suite | blocks the block | blocks the block | authority Drydock did not author |
| **T-2 CONSULTATIVE** | model AC with an R1-legal oracle | repairs, then **degrades** the block to `closed/implemented` and continues | raises a **blocking DECISION** and asks | the model could not have got the expected value wrong, but it could still have asked the wrong question |
| **T-3 ADVISORY** | model AC that re-types an expected literal | runs, records `DISPUTED`, never blocks | same | the criterion may be wrong in a way indistinguishable from a product defect |
| **T-4 VOID** | malformed — does not compile, unclosed container | recorded as a DECISION, gates nothing | recorded as a DECISION, gates nothing | it is not a criterion |

**T-2 is the tier that makes UAT finish.** It is the direct answer to *"sometimes in uat it will
fail or retry and sometimes in real life it will stop the build and ask using our existing
DECISIONS process."* Same criterion, same code, different consequence by execution mode — because
in autonomous mode there is nobody to ask, and stopping a run nobody can restart is strictly worse
than continuing with the block honestly marked unverified.

Under T-2, D-010 and D-015 largely dissolve: a chain stalls only on T-1, which is real.

**No tier reaches the release verdict.** A `closed/implemented` block is reported (G-SCORE-13) and
never blocks. The release verdict comes from Sea Trials, which is the whole point of §12.

---

## 15. What `score release` Becomes

```
score release
│
├─ 1. CAN WE JUDGE?                                      → ERROR and stop  (V-7)
│     governed gate executable · staged assets intact · artifacts parse
│
├─ 2. GATHER EVIDENCE   (deterministic, no judgement)
│     governed gate outcomes · AC outcomes by tier · measurements
│     · file facts · test output · dependency manifest · route coverage
│
├─ 3. PIN WHAT IS SETTLED                                (V-5 precedence 1 & 2)
│     demonstrated failure → NOT MET · governed PASS → MET
│
├─ 4. GRADE THE REMAINDER      (one LLM pass, all trials, all evidence)
│     may infer MET · may return PENDING · may return NOT MET only with a citation  (V-2)
│
├─ 5. FOLD                     (policy block in SEA_TRIALS.md, not Python)
│     any NOT MET → FAILED · else any PENDING → PENDING · else PASSED
│
└─ 6. STATE IT
```

### The statement

```
ReadingList: PENDING MANUAL VERIFICATION — st-008

  Automated acceptance passed.  7 of 8 project criteria met.

  st-008  The application shall never transmit a reader's list to a third-party service.
          Evidence:   architecture-local-boundary passed; ui-layout-assets-local passed;
                      no third-party network client in the dependency manifest.
          Next step:  Manually verify that no reader-list data leaves the machine — or
                      rewrite st-008 as an observable criterion and add a deterministic
                      acceptance check.
```

Every PENDING carries a **next step**, and the next step always offers both routes: settle it by
hand, or make it observable. That is the mechanism by which the criteria improve over time.

### Sea Trial wording

Because the grader may now infer, criteria should be authored as **observable positive statements**
rather than unfalsifiable prohibitions. `analyze` and the frozen fixtures adopt this.

| Rather than | Author |
|---|---|
| The application shall never transmit a reader's list to a third-party service. | The application's declared dependencies contain no third-party network client, and no code path issues a request to a non-local host. |

Same intent. The second is checkable, inferable, and its failure is demonstrable — so it can reach
MET or NOT MET instead of parking at PENDING forever.

### `result.json`

```json
"status": "passed | pending | failed | error",
"verdict_line": "ReadingList: PENDING MANUAL VERIFICATION — st-008",
"criteria": [{"id": "st-008", "verdict": "PENDING",
              "rationale": "...", "evidence": [...], "next_step": "..."}],
"gate_verdicts": [{"id": "G-SCORE-05", "outcome": "REPORTED", "domain": "DRYDOCK"}]
```

`build_score.py` and `score.py` converge on one policy engine. Two scorers that can disagree about
the same project is a defect generator; `score release` does not currently read the policy block
that `build_score` honours.

---

## 16. Corrections to Part I

### 16.1 Everything about this process lives in `uat/`

`uat/` is the entire empirical record of Drydock's own acceptance: three fixtures, their frozen
Commander inputs, and every run ever executed —
`uat/<Fixture>/runs/<id>/{result.json,evidence/,workspace/,build/,view/}`, complete with prompts,
provider output, and evidence trees. There is no other source. Any claim about how Drydock behaves
is checkable there and nowhere else.

**Caveat, and it corrects §7.3:** the 18 runs were produced by materially different software. Their
*verdicts* are not comparable across versions, and a recorded run cannot be replayed through the
lifecycle to test a gate change.

What survives version drift is the **evidence**, and the scoring policy is a pure function over it.
So the corpus supports **policy replay, not lifecycle replay**:

- Extract the recorded evidence facts from each run.
- Run the new fold (§15 steps 3–5) over them.
- Assert the verdict each run *should* have produced.

That is a real regression suite, available today, at zero token cost, and it is how the model in
Part II gets tested before a single UAT run is spent. §7.3's claim that gate changes can be
validated by replaying runs is wrong as written; this is the correct form.

### 16.2 Defect status updates

| Id | Under Part II |
|---|---|
| D-008 | still open — P-3, unaddressed by the verdict model |
| D-009 | resolved by P-4 — remove `_MIN_ASSERTIONS_PER_STORY` |
| D-010, D-015 | resolved by T-2 — only T-1 stalls a chain |
| D-011 | still fails, correctly — V-2 pins NOT MET on 126 red cases |
| D-012 | dissolved — `Verification:` no longer selects a mechanism (V-5), so a Sea Trial without a `Command:` is graded like any other |
| D-014 | resolved by V-6 — git state leaves the verdict |
| **D-016** | *new:* `score.py:520-535` overrides the grader's verdict with AC proof-tag binding; `if not referencing: verdict = "INCONCLUSIVE"`. Evidence: ReadingList `20260813.160121`, st-008. Resolved by V-5. |
| **D-017** | *new:* `prompts/score_release.md:35-37` forbids inference for guardrails and asserts INCONCLUSIVE "fails the gate exactly as a breach does", which `score.py:565` has not done since 2026-08-13. Stale instruction, actively biasing the grader. Resolved by V-4. |

---

## 17. Implementation Order

Cheapest and most diagnostic first. (1) and (2) are prompt/policy only and would have changed
today's ReadingList verdict on their own.

| # | Change | Touches |
|---|---|---|
| 1 | V-4 + V-2 — rewrite the grader contract; remove the guardrail inference ban and the stale gate claim | `prompts/score_release.md` |
| 2 | V-6 — hygiene out of the verdict; git state reported, not gating | `score.py`, `build_score.py` |
| 3 | V-1 + V-3 — four terminal verdicts, three trial verdicts, the statement | `score.py`, `uat.py`, `sea_trials.py` |
| 4 | V-5 — `Verification:` becomes a hint; delete the proof-tag override | `score.py:520-535` |
| 5 | V-7 — ERROR computed first and separately | `score.py`, `uat.py` |
| 6 | T-2 — consultative tier, autonomous vs interactive consequence | `build_run.py`, `decisions.py` |
| 7 | P-4 — delete `_MIN_ASSERTIONS_PER_STORY` (D-009) | `planning_session.py:2065` |
| 8 | §16.1 policy-replay harness over the 18 recorded runs | `tests/` |

Item 8 should land alongside item 3, so that everything after it is validated against the corpus
rather than against a fresh UAT run.

---

## 18. Open Questions (Part II)

- **Does `PENDING` exit 0?** Proposed yes — it is not a failure. But UAT's own release-readiness
  question ("can Drydock ship?") probably wants *no run FAILED or ERRORed*, with PENDING counted
  separately. Two different consumers of the same verdict.
- **ERROR and FAILED both exit 1** under the 0/1/2 contract. Distinguished only in `result.json`.
  Acceptable, or does ERROR warrant its own code?
- **Can the grader be trusted with inference at all,** given it is the same class of model that
  authors the criteria? V-2's asymmetry is the answer — it can only be generous, never punitive —
  but that is an argument, not a measurement. §16.1's replay harness can measure it.
- **What settles a PENDING?** A human answer needs somewhere to live. `DECISIONS.json` is the
  existing mechanism and probably the right one.

---
---

# PART III — PROVENANCE, EXIT SEMANTICS, AND THE TDD CONTRACT

`2026-08-13` · approved in discussion

## 19. V-8 — Sea Trial Provenance *(prior to V-2)*

> **Every Sea Trial must trace to user-authored intent. An untraceable criterion is a
> specification defect: it is removed, or presented for user approval. It cannot produce MET,
> PENDING, or NOT MET.**
>
> **Symmetrically, every user-authored intent must be covered by a Sea Trial. An uncovered intent
> is a specification defect of the same kind.**

Provenance is checked **before** grading. V-2 governs how a *valid* criterion is settled;
V-8 governs whether it is a criterion at all. **Inference may settle a criterion. It may not
invent one.**

### 19.1 The ReadingList evidence

`uat/ReadingList/sources/reading-list.md` — the complete user directive — asks for: add a book with
title and author; view in the order added; remove a book; reject empty title or author with a clear
error; automated tests for each behavior; a POSIX `bin/test.sh` exiting zero.
`uat/ReadingList/updates/reading-list.md` adds: mark a book as read, and view read state.

Against the frozen `uat/ReadingList/inputs/SEA_TRIALS.md`:

| Trial | Traces to | Verdict on the criterion |
|---|---|---|
| st-001 … st-006 | the six directives above | valid |
| **st-007** "usable without instructions" | *nothing* | **invented** |
| **st-008** "never transmit to a third-party service" | *nothing* | **invented** |
| *(missing)* mark-as-read | the update directive | **uncovered** |

The exam invented two questions and omitted one that was asked. st-008 was not a criterion that
was hard to prove — **it was never requested.** Every hour spent making the grader reason about
prohibitions was spent on a defect that V-8 removes at the source.

Corrected contract: **seven criteria, including mark-as-read, no privacy guardrail.** Expected
result:

```
ReadingList: PASSED

  Automated acceptance passed.  7 of 7 project criteria met.
```

### 19.2 Where the check lives

Provenance is a property of the criterion, so it is settled at authoring time, not at scoring time:

| Stage | Gate | Consequence |
|---|---|---|
| `analyze` | **G-ANA-04** every emitted trial cites the source span it traces to | untraceable trial is not emitted |
| `analyze` | **G-ANA-05** every directive in the imported sources is covered by a trial | uncovered directive raises a DECISION |
| `refit` | **G-REFIT-02** a source update re-runs both, so a new directive gains a trial | uncovered new directive raises a DECISION |
| `score release` | **G-SCORE-14** a trial with no provenance is reported and **excluded from the fold** | never produces a verdict |

G-SCORE-14 is the backstop for frozen Commander files authored before the rule existed — exactly
the state the three fixtures are in today.

The citation is the mechanism. A trial carries `Source: reading-list.md:5-6`, and a trial that
cannot name one does not exist. This is the same shape as P-2 — **authority cannot be inferred
from an artifact the model authored** — applied one layer up. Sea Trials had no provenance rule
because they *were* the authority; V-8 says the user is.

### 19.3 Consequences

- The guardrail problem largely evaporates. Most unfalsifiable prohibitions in the record are
  model-invented safety boilerplate. A user-authored prohibition is rarer, and when it exists the
  user can be asked what would satisfy them.
- `analyze`'s job narrows from *"author project acceptance criteria"* to *"transcribe the user's
  directives into typed, observable criteria, and state what you could not transcribe."* That is a
  far more constrained task and a far more checkable one.
- D-006 is only half-fixed. Freezing `SEA_TRIALS.md` stopped the exam changing every run; it did
  not stop the exam being wrong. **A frozen wrong exam is a stable wrong exam.**

### 19.4 New defects

| Id | Defect | Gate | Evidence |
|---|---|---|---|
| **D-018** | `analyze` emits Sea Trials with no basis in the user sources | G-ANA-04 | ReadingList st-007, st-008 |
| **D-019** | A user directive present in the sources has no Sea Trial | G-ANA-05 | ReadingList mark-as-read, `updates/reading-list.md` |
| **D-020** | The three frozen fixture `SEA_TRIALS.md` files were authored before V-8 and carry both defects | G-SCORE-14 | all three fixtures |

---

## 20. Exit Semantics — `X-*`

The exit code has been carrying a verdict, and it cannot. `score release` exiting 1 has meant both
*"the project is not acceptable"* and *"I could not tell"*, and `uat` exiting non-zero has meant
both *"the fixture project failed"* and *"Drydock is broken"* — the distinction the whole run
record needs and does not have.

### X-1 — The exit code answers *"did this command do its job?"*, never *"is the project good?"*

| Code | Meaning |
|---|---|
| `0` | The command ran and produced its output. **A verdict exists.** |
| `1` | The command could not do its job. No verdict is available. |
| `2` | Usage error. |

This is already the `AGENTS.md` contract; it has simply not been applied honestly. **A project
failing is not an operational failure of the scoring command** — the command worked perfectly and
reported a failure. That is success for `score release`.

### X-2 — `score release`

| Verdict | Exit | Because |
|---|---|---|
| PASSED | 0 | judged |
| PENDING MANUAL VERIFICATION | 0 | judged |
| FAILED | 0 | **judged** |
| ERROR | 1 | not judged |

The verdict is **data** — `status` and `verdict_line` in `result.json`, the statement in
`SCORECARD.md`. For scripted gating, `--require PASSED` (or `--require PASSED,PENDING`) exits 1
when the verdict is outside the named set. Explicit, opt-in, and the default stays informational.

### X-3 — `build`

Already effectively advisory: UAT polls `status --ready` (`uat.py:880`) and records build's exit as
degraded rather than fatal. Formalize it. Exit 0 = a build pass executed. **Whether blocks closed
is `build status`, not an exit code.** Block state is `closed/verified` · `closed/failed` ·
`closed/implemented`, which is three values and does not fit in a boolean.

### X-4 — `uat` asks a different question entirely, and this is the important one

UAT's question is **not** "did the fixture project pass." It is **"did Drydock reach the correct
conclusion?"**

So **a fixture declares its expected verdict**, in `uat.json`:

```json
"expect": {"verdict": "PASSED"}
```

`uat` exits 0 when the observed verdict equals the expected one and no stage ERRORed.

This reframes Toml completely. Toml has a genuine product defect — D-011, U+3000 accepted as
whitespace via `strings.TrimSpace`, 126 red valid-cases. If Drydock reports `FAILED: st-00N` and
names that defect, **Drydock worked correctly** and the UAT run is a pass. Today the same event
reads as Drydock failing, which is why eight Toml runs produced no usable signal about Drydock at
all.

It also answers "what does exit 0 mean": from `uat`, it means **Drydock reached the right
conclusion about the fixture** — which is the only thing a self-test can honestly assert.

| Fixture | Expected | Rationale |
|---|---|---|
| ReadingList | `PASSED` | 7 traceable criteria, all satisfiable, product builds |
| CommonMark | `PASSED` | authoritative suite, achievable |
| Toml | `FAILED` **or** `PASSED` | open — see §22 |

---

## 21. The TDD Contract, Re-examined

`prompts/BLUEPRINTS_CONTRACT.md:240-288` carries ten authoring patterns. Reviewed against the tier
model, three findings.

### 21.1 What is cleanly solved

The two things that started this — **malformed containers and mangled encodings** — are solved
structurally, not by guidance:

- **Containers.** `=== AC <id> === … === END AC <id> ===` with the id in both markers. The id is
  never inferred from position, and an unclosed container is detectable rather than silently
  absorbing the next criterion. This is the XML-delimiter lesson applied.
- **Encodings.** The R1 rule — *never type an expected value twice; bind it to a name and use the
  name on both sides* — makes escaping disagreement **impossible by construction** rather than
  policed after the fact. `raw = "C:\\Users\\nodejs"`; `source = f"raw = '{raw}'\n"`;
  `assert decoded["raw"]["value"] == raw`. There is no second literal to get wrong.

Neither depends on the model being careful. That is the property that was missing.

### 21.2 Gap — the patterns do not name the tier they produce

An author following pattern 2 with an R1-legal oracle writes a **T-2 CONSULTATIVE** criterion. The
same author re-typing an expected literal writes **T-3 ADVISORY**, which gates nothing. The
contract never says so, so the author cannot aim.

The contract should state the consequence directly: *this is how you write a criterion that
counts; this is what happens to one that does not.* A model that knows a re-typed literal
demotes its criterion to advisory has a reason to bind the name instead. Today it has a rule with
no stated consequence, which is the weakest form of instruction.

### 21.3 Gap — patterns 2 and 5 fight P-4

Pattern 2 ("exercise every callable workflow… coverage is enumerated from the interface, not
sampled") and pattern 5 ("boundaries: empty, one, many, absent optionals, declared maxima") are
**coverage-maximizing**. They push toward more criteria, and every additional model-authored
criterion is a fresh opportunity to be wrong about an expected value.

This is the same defect as G-PLAN-12 (`_MIN_ASSERTIONS_PER_STORY`) wearing prose instead of a
gate — and it is the mechanism behind the Toml numbers: 15 suite-bound criteria all passed, and 10
hand-authored ones covering nothing the conformance suite did not already cover supplied 100% of
the failures.

Both patterns need the same condition attached: **where an authoritative suite covers this surface,
it is the coverage; do not restate its cases.** Coverage is measured by the authoritative suite or
it is not measured.

### 21.4 Gap — pattern 6 is unobserved

"RED before GREEN — the assertion must fail against the pre-implementation tree and pass after."
Authored at plan time before code exists, every criterion is red by construction, and nobody ever
observes it. `analyze_proof` (vacuity) is the only surviving check and it asks a weaker question:
does the assertion have an effective failure path at all.

The honest options are to observe it — run the criterion once against the tree before the block's
first implementation pass, which is cheap and turns pattern 6 into evidence — or to stop claiming
it. Running it also yields something valuable free: **a criterion that passes before the code is
written is a defect regardless of the tier it claims.**

### 21.5 Aside — pattern 7 caused D-014

"Fresh store per test, or explicit teardown." The ReadingList suite left
`instance/reading_list.sqlite3` behind, which dirtied the tree, which failed the release. The
pattern existed and was not followed and no gate checked it. Under V-6 it stops mattering for the
verdict — recorded here because the pattern is worth keeping for its own sake, not as a gate.

---

## 22. Revised Open Questions

- **What is Toml's expected verdict?** If `FAILED` (D-011 is real and Drydock should say so), Toml
  becomes a passing UAT fixture immediately and stops blocking release. If `PASSED`, the U+3000
  defect must be fixed first and Toml stays red until it is. These are different projects: one
  tests Drydock, the other tests the Toml build. **Recommendation: `FAILED`, with a second fixture
  or a follow-up run tracking the product fix separately.**
- **Do the three frozen `SEA_TRIALS.md` files get rewritten under V-8?** They are the exams, they
  are demonstrably wrong (D-020), and every run is graded against them. Rewriting them is a
  fixture change, not a code change, and it is the single cheapest correction available.
- **Who resolves an uncovered directive (G-ANA-05)?** A DECISION is the mechanism, but in
  autonomous UAT there is nobody to answer. Same shape as T-2, and probably the same answer:
  record it, proceed, report it.
- **Does provenance citation survive `refit`?** A trial cites `reading-list.md:5-6`; the update
  rewrites the file. Line spans are fragile. Cite the directive text rather than the span.

---
---

# PART IV — CORRECTIONS AND THE TWO-DESTINATION TEST MODEL

`2026-08-13` · approved in discussion

## 23. Corrections to Parts I–III

### 23.1 D-011 is retracted

**Claimed:** the Toml parser accepts U+3000 as whitespace via Go's `strings.TrimSpace`, which
accepts Unicode whitespace where TOML permits only ASCII space and tab — a genuine product defect
producing 126 valid-case failures.

**Actual,** from `uat/Toml/runs/20260813.084830`:

```
toml-test v2.2.0
  valid tests:   79 passed, 126 failed
invalid tests:  471 passed,   3 failed

FAIL valid/array/bool
     input:  a = [true, false]
     stderr: line 1: unsupported or invalid scalar
```

Every `valid/array/*` case fails, and the manifest says why:

| Block | Story | State |
|---|---|---|
| 1–2 | architecture, parser-lexical-scalars | `closed/verified` |
| **3** | **parser-strings** | **`closed/failed`** |
| 4–8 | parser-keys, parser-arrays-inline, parser-datetimes, parser-tables, decoder-interface | **`pending`** |

**Six stories never built.** Arrays, datetimes, and tables are absent from the parser, not
mis-implemented. The 126 failures are unbuilt work.

Consequences, and they matter:

1. **D-011 is not an independent defect.** It is D-010 — the dependency stall — with a large
   number attached. `parser-keys` depends on `parser-strings`, and everything follows from there.
2. **The Toml product was never demonstrated defective.** It was never finished. No claim about
   its correctness is supported by the record.
3. **§22's recommendation is reversed.** Toml's expected verdict (X-4) is **`PASSED`**, not
   `FAILED`. The block-3 failure was `strings-escape-boundaries`, the re-typed-literal criterion —
   **T-3 ADVISORY** under §14, which cannot block. Under the tier model blocks 4–8 build.
4. **UC-008 is unevidenced.** Across 18 runs there is *no* example of a completed product that is
   genuinely defective. Every failure was a stall, a gate, a criterion, or Drydock itself. The gate
   model's most important case has never been observed, so nothing in the record constrains the
   model against becoming a rubber stamp. **This is the strongest argument for §16.1's policy-replay
   harness**, which can construct the case synthetically.

Method note: the claim came from over-generalizing one observed case in an earlier session and was
then restated twice as established. It survived because nothing required a citation. The §7.1 rule
— *one row, one gate id, one sentence, per non-passing run* — exists to stop exactly this.

### 23.2 D-018/D-019/D-020 close

All three fixture `SEA_TRIALS.md` files are V-8 clean as of `185b55a`:

| Fixture | Trials | Provenance |
|---|---|---|
| ReadingList | 7 | all seven trace to `sources/reading-list.md` + `updates/reading-list.md`; mark-as-read now covered as st-007; st-006 enumerates the required tests; the invented privacy guardrail is gone |
| Toml | 1 | `sh sources/full_test.sh` exits zero — the source's stated definition of success, verbatim |
| CommonMark | 1 | `sh full_test.sh` exits zero — likewise |

**D-012 dissolves with them.** A Sea Trial with no `Command:` was only a problem because
`Verification: proof` routed it through AC proof-tag binding; under V-5 that override is gone and
the governed `full` gate in `ACCEPTANCE.json` carries the verdict.

Toml and CommonMark reducing to a single criterion is the model working as intended: the user
stated one definition of success, so there is one Sea Trial, and its oracle is a supplied command.

---

## 24. The Two-Destination Test Model — `TD-*`

### TD-1 — Best practice is not reduced; it is addressed to the right artifact

§21.3's claim that TDD patterns 2 and 5 "fight P-4" is **wrong as phrased**. It reads as *write
fewer tests*, which is not the finding and would be a defect.

The correct statement: **the ten patterns are addressed to the wrong artifact.**
`BLUEPRINTS_CONTRACT.md` applies all ten to `=== AC ===` blocks, which is the only test destination
the contract knows about. There should be two, and exhaustive coverage belongs to the second.

| | **Story AC** — `=== AC <id> ===` | **Native test suite** — `go test ./...`, `bin/test.sh` |
|---|---|---|
| Job | **gate the block** | **know the code works** |
| Count | few | unbounded |
| Authored | by `plan`, before code exists | by the build agent, alongside the code |
| Oracle discipline | R1-legal only; no re-typed literal; must survive as a gate | full latitude — the code exists, so expectations are observed, not predicted |
| Patterns | 1, 4, 6, 9, 10 | **all ten**, especially 2 (every route × verb), 5 (boundaries), 3 (idempotence), 7 (isolation), 8 (naming) |
| Effect | binding — T-1 / T-2 | **diagnostic** — repair guidance, never blocks |
| Runs | at its block | after every block, cumulatively |
| Graded by | nothing — it is a gate, not a criterion | **Sea Trials**, via the project's test criterion |

This is *more* TDD, not less. The native suite has no ceiling; an AC block is permanently
constrained by having to survive as a gate. And it matches how the work is actually done: the suite
is exhaustive, the CI gate is one command.

### TD-2 — Why the split is not arbitrary

An AC block is authored **before the code exists**, so every expected value in it is a
*prediction*. That is the entire root cause from §1. A native test is authored **alongside the
code**, so its expected values are *observed*. The same assertion is safe in one destination and
hazardous in the other, and the destination — not the assertion — is what determines which.

This also explains why the R1 whitelist feels restrictive: it is the correct discipline for a
predictive artifact and the wrong discipline for an observational one. Applying it to the native
suite would be a mistake.

### TD-3 — Coverage is graded, not gated

P-4 ("quantity is never a gate") and exhaustive TDD are fully compatible once the destinations are
separate:

- **Exhaustive coverage** lives in the native suite and is **graded at the Sea Trials level**.
  ReadingList st-006 does this already — *"shall carry automated tests for adding, listing,
  removing, rejecting, marking read, and displaying read state"* — a user directive, enumerated,
  observable, and enforced by st-001 (`bin/test.sh` exits zero). One command, one oracle, nothing
  re-typed.
- **Gates** live in AC blocks and are few and bulletproof.

`_MIN_ASSERTIONS_PER_STORY` (G-PLAN-12, D-009) is still deleted: it counted the wrong artifact.
Coverage is measured by the suite the user asked for, or by an imported authoritative suite, and
never by counting AC blocks.

### TD-4 — Where an authoritative suite exists, it is the coverage

Unchanged and load-bearing. Toml's 15 suite-bound criteria all passed; its 10 hand-authored ones
restated cases `toml-test` already covers and supplied every failure. Do not restate an
authoritative suite's cases in either destination.

### TD-5 — Changes implied

| # | Change | Touches |
|---|---|---|
| a | Split the ten patterns by destination; state which apply where and why (TD-2) | `prompts/BLUEPRINTS_CONTRACT.md:240-288` |
| b | Give the build agent an explicit contract to grow the native suite as it writes code | `prompts/build.md` |
| c | State each AC tier's consequence in the authoring contract, so the author can aim (§21.2) | `prompts/BLUEPRINTS_CONTRACT.md` |
| d | Resolve the native suite command per Target and run it after every block, diagnostic only | `build_run.py` |
| e | Observe pattern 6: run each criterion once against the pre-implementation tree (§21.4) | `build_run.py` |

Items (a)–(c) are prompt-only. Item (d) is the regression-suite work from the original plan that
was never built.

---

## 25. Revised Open Questions

- **UC-008 has no evidence.** No completed-but-defective product exists in 18 runs. Construct one
  synthetically in the policy-replay harness (§16.1) before trusting any gate model, including this
  one.
- **Toml's expected verdict is `PASSED`** (§23.1). Confirm by running it under the tier model: if
  blocks 4–8 build and `full_test.sh` still fails, *then* there is a product defect worth naming —
  and UC-008 finally has an example.
- **Does the native suite need its own quarantine?** Red generated tests accumulate across blocks
  by design. Without a visible running count a build ends quietly with fifty unresolved
  regressions.
- **What settles a PENDING?** Unchanged from §18. `DECISIONS.json` is the likely home.

---
---

# PART V — HANDOFF

`2026-08-13` · approved in discussion

## 26. Consolidated Implementation Order

§17 covered Part II only. This supersedes it and carries every change implied by Parts II–IV.
Ordered so that each phase is validated by the one before it.

### Phase 0 — Foundation *(no LLM, no UAT run, testable today)*

| # | Change | Touches | Why first |
|---|---|---|---|
| 0.1 | Policy-replay harness: extract evidence facts from the 18 recorded runs, run the fold over them, assert the verdict each should produce (§16.1) | `tests/` | Everything after is corpus-validated instead of run-validated |
| 0.2 | Synthesize the missing UC-008 case — a completed-but-defective product — and assert it reports FAILED (§23.1) | `tests/` | The gate model's most important case has never been observed; without it the model is unconstrained against becoming a rubber stamp |

### Phase 1 — Prompt only *(each would have changed today's ReadingList verdict alone)*

| # | Change | Touches |
|---|---|---|
| 1.1 | V-4 — delete the guardrail inference ban and the stale "fails the gate exactly as a breach does" claim (D-017) | `prompts/score_release.md:35-37` |
| 1.2 | TD-5a — split the ten TDD patterns by destination; state which apply to AC and which to the native suite, and why (TD-2) | `prompts/BLUEPRINTS_CONTRACT.md:240-288` |
| 1.3 | TD-5c — state each AC tier's consequence, so the author can aim (§21.2) | `prompts/BLUEPRINTS_CONTRACT.md` |
| 1.4 | TD-5b — build agent's contract to grow the native suite alongside the code | `prompts/build.md` |

### Phase 2 — The verdict model

| # | Change | Touches | Closes |
|---|---|---|---|
| 2.1 | V-6 — hygiene leaves the verdict; git state reported, not gating | `score.py:362-366`, `build_score.py:433-440` | **D-014** |
| 2.2 | V-1 + V-3 — four terminal verdicts, three trial verdicts, the statement | `score.py`, `sea_trials.py` | |
| 2.3 | V-5 — `Verification:` becomes a hint; delete the proof-tag override | `score.py:520-535` | **D-016** |
| 2.4 | V-7 — ERROR computed first and separately | `score.py`, `uat.py` | **partly done — see §29** |
| 2.5 | Converge `score.py` and `build_score.py` on one policy engine | both | |

### Phase 3 — The tier model

| # | Change | Touches | Closes |
|---|---|---|---|
| 3.1 | T-2 — consultative tier; autonomous degrades, interactive asks | `build_run.py`, `decisions.py` | **D-010, D-015** |
| 3.2 | P-4 — delete `_MIN_ASSERTIONS_PER_STORY` | `planning_session.py:2065` | **D-009** |
| 3.3 | TD-5d — resolve the native suite per Target; run after every block, diagnostic only | `build_run.py` | |
| 3.4 | TD-5e — observe pattern 6: run each criterion once against the pre-implementation tree | `build_run.py` | |

### Phase 4 — Provenance

| # | Change | Touches | Closes |
|---|---|---|---|
| 4.1 | G-ANA-04 — every emitted trial cites the directive it transcribes | `prompts/analyze.md`, `sea_trials.py` | **D-018** |
| 4.2 | G-ANA-05 — every source directive is covered by a trial; uncovered raises a DECISION | `analyze` | **D-019** |
| 4.3 | G-SCORE-14 — a trial with no provenance is reported and excluded from the fold | `score.py` | backstop |
| 4.4 | G-REFIT-02 — a source update re-runs both checks | `refit` | |

*Fixtures are already V-8 clean as of `185b55a` (§23.2); Phase 4 is for real Targets.*

### Phase 5 — Harness semantics

| # | Change | Touches |
|---|---|---|
| 5.1 | X-1/X-2/X-3 — exit code reports whether the command did its job, never the verdict; `--require` for scripted gating | `cli.py`, `score.py` |
| 5.2 | X-4 — per-fixture expected verdict in `uat.json`; `uat` exits 0 when observed matches expected | `uat.py`, `uat/*/uat.json` |
| 5.3 | `gate_verdicts` in `result.json`, so §4 is generated rather than written (§7.2) | `uat.py` |

### Not scheduled

| Defect | Why |
|---|---|
| ~~**D-008** — one malformed artifact discards a batch of 19~~ | **Scheduled and done.** §30.1 demonstrated it at `analyze` as well as `plan` and made it the most frequent cause of a dead run in the record; §30.3 is the fix, `299b702` |

---

## 27. Open Questions — Reconciled

Supersedes §10, §18, §22, and §25, which accumulated across four passes and are partly stale.

### 27.1 Resolved during the session

| Question | Resolution |
|---|---|
| May the hygiene layer block anything? (§10) | No. G-SCORE-07 becomes **ERROR** — the thing judged is not the thing built, so no verdict exists (V-6) |
| Does `PENDING` exit 0? (§18) | Yes — and so does FAILED. The exit code reports whether the command judged, not what it judged (X-1) |
| ERROR and FAILED both exit 1? (§18) | No. ERROR = 1, FAILED = 0 (X-2) |
| Can the grader be trusted to infer? (§18) | Only generously. V-2's asymmetry means inference can raise PENDING→MET but never reach NOT MET. Measured by 0.1/0.2 |
| D-012 — `st-001` carries no `Command:` (§22) | Dissolved. `Verification:` no longer selects a mechanism (V-5) |
| Toml's expected verdict (§22) | **`PASSED`** — the U+3000 defect does not exist (§23.1) |
| Rewrite the frozen `SEA_TRIALS.md`? (§22) | Done by the author, `185b55a`. All three fixtures V-8 clean |
| Does a red native suite reach the verdict? (§25) | Yes, and legitimately — through Sea Trials. A red suite fails `bin/test.sh`, which fails ReadingList st-001. It never reaches the verdict as *story AC*, which is the separation §12 requires |

### 27.2 Decided by recommendation, reversible

| Question | Call |
|---|---|
| What settles a PENDING? | `DECISIONS.json`. It is the existing mechanism for "a human owes an answer" and needs no new artifact |
| Provenance citation across `refit` | Cite the **directive text**, not a line span. Spans break when the source is rewritten |
| Uncovered directive in autonomous mode | Same shape as T-2: record the DECISION, proceed, report it. There is nobody to ask |

### 27.3 Settled by the author, 2026-08-13

**Q1 — A T-1 governed gate still red after the repair budget: stop the branch, finish the run.**
`spec:approved` · `impl:unimplemented`

The block closes `closed/failed`, its dependents are marked **blocked** and are not built, and
every independent branch continues. The run completes and reports every gate verdict.

This is P-3 and P-5 in operational form, and it becomes **P-3a**:

> A failing block stops what depends on it. It does not stop what does not.

Applied to Toml `20260813.084830`, which is the case that motivated it:

```
block 3  parser-strings      closed/failed   ← gate red
block 4  parser-keys         blocked (depends on 3)
block 5  parser-arrays       BUILT  ✓
block 6  parser-datetimes    BUILT  ✓
block 7  parser-tables       blocked (depends on 4)
```

One run yields every independent defect instead of the first one. Eight Toml runs each reported a
single block-3 failure and nothing about blocks 4–8; under P-3a one run would have reported the
state of all eight. Dependents are skipped rather than built, so no block is ever judged against a
known-broken foundation — the objection this could have raised does not arise.

Implementation: `build_run.py:3561`, `if status == "failed" or step_id is not None or story_id is
not None: break` becomes a per-branch skip driven by the dependency graph. Scheduled as **3.1a**,
alongside T-2.

**Q2 — Implementation starts at Phase 0 + Phase 1.** Phases 2–5 wait for the measurement Phase 0
produces.

---

## 28. Divergence from the Specification

Stated as fact, per standing instruction. No edit is proposed.

Implementing Parts II–V would diverge from `docs/Drydock_Specification.md` in three places:

1. **`:952`** — `SCORECARD.md` described as "seven-dimension quality + drift scores". Already false
   as of 2026-08-13; the rubric was deleted this week.
2. **`score release` verdicts** — the specification documents a pass/fail release gate. V-1
   introduces four terminal verdicts, of which `PENDING MANUAL VERIFICATION` has no counterpart.
3. **Exit codes** — X-1 makes `score release` exit 0 on FAILED. Any documented statement that a
   failing release gate exits non-zero becomes false.

The specification is the author's. These are surfaced so the divergence is a decision rather than
an accident.

---

## 29. Exit 2 as the Gate's "Could Not Run" — Adopted, With a Caveat

`2026-08-13` · settled by the author · `spec:na` · `impl:implemented`

**A governed acceptance command exiting 2 means it could not run.** `run_gate` classifies it
`OUTCOME_ERROR` alongside an absent executable, a timeout, and a signal: it does not block, it is
never charged to the build, and `score release` reports *could not run* rather than *failed*.
This is the narrow half of 2.4 — the fault domain is now right at the point of execution. The
verdict-level half (V-7: ERROR computed first, before grading, as a terminal verdict) is still
unimplemented.

The convention is `diff`'s and `grep`'s: **1 is a legitimate negative answer, 2 is trouble.** It is
already Drydock's stated contract in `AGENTS.md`, so this applies to a gate script the same rule
Drydock's own commands follow.

**The caveat, recorded deliberately.** The evidence for this convention inside Drydock is one
location: the three shipped Toml gate scripts, which the author wrote. No Commander-supplied
command has ever been observed using exit 2, and nothing enforces the meaning — a third-party
suite is free to exit 2 for "tests failed". Adopting a project-wide rule on a single instance is
thin, and it is adopted anyway because the failure is asymmetric: reading a real product failure
as a kit fault yields PENDING and a visible unverified block, while reading a kit fault as a
product failure yields a false FAILED, which is the defect this whole file exists to remove. A
misread in the safe direction is loud and recoverable; a misread in the other direction is what
produced eighteen runs of no signal.

Left as is. If a real Target ever ships a gate that means "failed" by exit 2, the fix is a
per-gate declaration in `ACCEPTANCE.json`, not a change to the default.

D-021 and D-022 in §4 are the run that produced this.

---
---

# PART VI — REFIT, 2026-08-13

Written for `/apply-refit uat-gates` after a `/clear`. Every item below carries a flag line; the
skill surfaces `impl:unimplemented` as code items. Sections marked `impl:implemented` are the
record of work already done, kept so the next session does not redo them.

Evidence for all of it: Toml `20260813.195530` and Toml `20260813.211658`, the first two runs of
the day carrying the Phase 1 work.

## 30. Run 20260813.211658 — analyze discarded four good artifacts

### 30.1 What happened

`2026-08-13` · `spec:na` · `impl:na`

The run died at `analyze`, 76 seconds and one LLM call in, at commit `f2e63da` — so it carries
both of the day's fixes and reached a *new* failure, earlier in the lifecycle than any Toml run
before it.

```
Error: Analyze failed: LLM output contained an unexpected artifact block: END COMPASS
  No generated artifacts were written.
```

The model emitted five artifacts. Four are well-formed and every one of them is an allowed name:

| Block | Open | Close | State |
|---|---|---|---|
| `ANALYSIS.md` | `=== ANALYSIS.md ===` | `=== END ANALYSIS.md ===` | well-formed |
| `SEA_TRIALS.md` | `=== SEA_TRIALS.md ===` | `=== END SEA_TRIALS.md ===` | well-formed |
| `TECHNOLOGY_STACK.md` | `=== TECHNOLOGY_STACK.md ===` | `=== END TECHNOLOGY_STACK.md ===` | well-formed |
| **`COMPASS.md`** | `=== COMPASS.md ===` | **`=== END COMPASS ===`** | **dropped the `.md`** |
| `discovery-identity.json` | `=== discovery-identity.json ===` | `=== END discovery-identity.json ===` | well-formed |

One artifact's closing marker lost four characters. Nothing was written. The frozen
`SEA_TRIALS.md` — the exam, already correct on disk — was not even reached.

**This is D-008 at a new stage.** It was catalogued at `plan` (one malformed artifact discards a
batch of 19) and left *Not scheduled* in §26 on the grounds that it is a transport problem
independent of the verdict model. Four of the twenty recorded runs have now died this way, it is
the single most frequent cause in the record, and it is now demonstrated at `analyze` as well as
`plan`. **The recommendation is to schedule it.**

Two independent defects compound here, and they want separate fixes.

### 30.2 A mismatched close is read as an open (D-023)

`2026-08-13` · `spec:na` · `impl:implemented`

`_parse_delimited_blocks` in `artifact_blocks.py` has no concept of *a close that does not match
its open*. Seeing `=== END COMPASS ===` while inside `COMPASS.md`, it does not recognise a
malformed close — it recognises a **new block named `END COMPASS`**, which then fails the
allow-list at `artifact_blocks.py:100-105` and raises.

The diagnostic is therefore actively misleading. It names a block the model never opened, and
says nothing about the one that is actually wrong. Anyone reading that error looks for `COMPASS`
in the prompt contract and finds nothing.

The fix: when a line matches the close form and the run is inside an open block, treat it as that
block's close. Report a mismatch as a mismatch, naming both markers, rather than inventing a
block. §21.1 credits the `=== AC <id> === … === END AC <id> ===` containers with making an
unclosed container *detectable rather than silently absorbing the next criterion* — that lesson
was applied to AC containers and never to the artifact parser the whole lifecycle runs through.

**Do not fix this by making the close fuzzy-match the open.** The close's name is a checksum on
the open; matching them loosely throws away the property that makes the container detectable at
all. Recognise the close by position, and report the name disagreement.

### 30.3 A parse defect discards artifacts it did not judge (D-008)

`2026-08-13` · `spec:approved` · `impl:implemented`

Even with 30.2 fixed, the surviving behaviour is wrong: one bad block aborts every block.
`artifact_blocks.py:100-105` loops over the parsed names and raises on the first that is not
allowed, before a single artifact is written.

This is P-3 verbatim — **no gate may discard work that it did not judge.** The parser judged
`COMPASS.md`. It did not judge `ANALYSIS.md`, and it destroyed it anyway.

The shape of the fix, per P-3 and P-1:

- Parse every block independently. A block that opens, closes, and carries an allowed name is
  accepted.
- A malformed or disallowed block is **rejected individually**, with its name and reason.
- The command proceeds on the accepted set and reports the rejected ones.
- Whether a missing artifact is fatal is then a question about *that artifact*, decided by the
  caller. `analyze` needs `ANALYSIS.md` and `SEA_TRIALS.md`; a missing `COMPASS.md` is a
  reportable gap, not a dead run.

That last point is the one that makes this safe: rejecting individually is not the same as
tolerating loss. The caller states which artifacts it requires, and a required artifact that did
not survive is still fatal — but it fails naming the artifact, which is a fault the operator can
act on.

Applies identically at `plan` (`planning_session.py:3421-3436`), which is the original D-008 and
the more expensive one: there the discarded batch cost 19 blueprints and eight LLM calls.

### 30.4 Guarantee the block end: make the close invariant

`2026-08-13` · `spec:approved` · `impl:implemented`

**Why it truncated.** Not a random slip. The evidence:

| Artifact | Its own first heading | Closed |
|---|---|---|
| `ANALYSIS.md` | `# Blueprint Analysis: TOML 1.0.0 Parser` | correctly |
| `SEA_TRIALS.md` | `# Sea Trials: TOML 1.0.0 Parser` | correctly |
| `TECHNOLOGY_STACK.md` | `# Technology Stack` | correctly |
| **`COMPASS.md`** | **`# COMPASS: TOML 1.0.0 Parser`**, then `## Compass` | **`=== END COMPASS ===`** |

The only artifact that closed wrongly is the only one whose content restates its own filename stem
verbatim, in the same casing. Twenty-five lines separated the open from the close. At the close,
the salient token in context was `COMPASS` — just used twice as a heading — and it beat the
`COMPASS.md` typed twenty-five lines earlier. **The model echoed the name of the thing, not the
name of the file.**

This predicts recurrence: any artifact whose content restates its filename stem is exposed. It has
not bitten before because the older artifacts' headings do not collide with their filenames.

**There is no way to guarantee what a model types.** What is achievable is to leave nothing that
*can* be got wrong. The close delimiter currently carries a variable that must be reproduced from
memory, across arbitrary content, while the content actively competes for it.

**The fix — the close carries no variable part:**

```
=== BEGIN ARTIFACT COMPASS.md ===
# COMPASS: TOML 1.0.0 Parser
...
=== END ARTIFACT ===
```

The name appears exactly once, at the open, where it is being typed deliberately. The close is a
constant token with nothing to recall and nothing to collide with. This is MIME multipart
discipline: one invariant boundary, and the part's name is data *inside* the part rather than
syntax in its terminator.

**Three independent layers, and they should all land:**

| Layer | Change | Effect |
|---|---|---|
| **Prevent** | invariant close token (this section) | the class stops existing |
| **Recover** | close by position; a name disagreement is reported, not fatal (§30.2) | a residual slip is survivable, including a wholly wrong name |
| **Contain** | per-artifact rejection (§30.3) | an unrecoverable block costs one artifact, not the run |

Prevention alone is not enough — it constrains only artifacts Drydock's own prompts define, and
the parser still has to survive whatever arrives. Recovery alone leaves the diagnostic misleading.
Containment alone leaves every run one formatting slip away from losing an artifact it did not
need to lose.

**Migration.** The parser accepts both forms; the named close stays valid and stays checked, so
nothing recorded stops parsing. Prompts move to the invariant form. Touches
`artifact_blocks.py`, `prompts/analyze.md`, `prompts/plan_create.md`, and any prompt emitting
`=== <name> ===` containers. **The `=== AC <id> === … === END AC <id> ===` containers are
deliberately excluded** — there the id in both markers is a real checksum binding a criterion to
its identity (§21.1), the content is code rather than prose about itself, and the collision that
caused this cannot arise.

### 30.5 Re-running may simply work, and that is the problem

`2026-08-13` · `spec:na` · `impl:na`

The failure is a model formatting slip, so the next run has good odds of not hitting it. That
makes it tempting to re-run and move on, and it is exactly why this has survived four runs
without a fix: each individual occurrence looks like bad luck. It is not bad luck at a 20% rate.
It costs a whole run, it is independent of everything else being worked on, and the run it costs
is 28 minutes and 4M tokens.

## 31. Work completed 2026-08-13, recorded

### 31.1 The Toml conformance harness version probe (D-022)

`2026-08-13` · `spec:na` · `impl:implemented`

`uat/Toml/sources/run_conformance.sh` probed the suite with `toml-test -version`, which that
harness does not accept as a flag: it printed general help, exited 0, and the version guard
compared the help text against the expected `v2.2.0` and refused to run. Every governed gate in
the fixture routes through that script, so no conformance case executed in run
`20260813.195530` — surfacing as three failed layout criteria, `test` exiting 2, and a release
blocked on `full: FAIL (exit 2)`, none of which concerned the decoder. Now uses the `version`
subcommand, as `setup_harness.sh` always did. The guard is otherwise unchanged. Commit `78b161c`.

### 31.2 Exit 2 is a kit fault (D-021)

`2026-08-13` · `spec:na` · `impl:implemented`

See §29 for the decision and its recorded caveat. `run_gate` classifies exit 2 as `OUTCOME_ERROR`;
it does not block and is never charged to the build. Narrow half of §26 item 2.4. Commit `f2e63da`.

### 31.3 The replay corpus carries the run

`2026-08-13` · `spec:na` · `impl:implemented`

`20260813.195530` is in `tests/fixtures/uat_corpus.json` scored **ERROR** — the verdict it should
have produced, against the FAILED it did produce. 19 runs, 11 scored.
`test_exactly_one_recorded_run_was_unjudgeable` names it, so the corpus asserts the gap between
what Drydock concluded and what it should have concluded, in a test, until 2.4's verdict half
lands.

`20260813.211658` is **not** in the corpus and should not be: it never reached the gate, so it
offers no facts. It joins the eight unscored runs. Regenerate with `python tests/uat_corpus.py`
and the freeze-integrity test will require the count updates in
`tests/test_gate_policy_replay.py`.

### 31.4 Order for the next session — closed

`2026-08-13` · `spec:na` · `impl:implemented`

Items 1–3 (§30.2 recovery, §30.3 containment, §30.4 prevention) landed in commit `299b702`.
Item 4, the re-run, produced §32 and its regression. All three layers are now in the tree and
tested, and §32's fix is what makes them true of the whole lifecycle rather than of the parsers
alone.

§26 item 3.1a (P-3a, the per-branch stall) remains the highest-value item after those, and is
unchanged by any of this.

---

## 32. Run 20260813.231738 — the invariant boundary was adopted by half the codebase (D-024)

### 32.1 What happened

`2026-08-13` · `spec:na` · `impl:implemented`

The re-run called for by §31.4 item 4 died 90 seconds and three LLM calls in, at commit `f2e63da`
plus `299b702`:

```
error: KeyError: 'TOPOLOGY.md'
A MAJOR ERROR HAS OCCURRED — drydock plan toml --override has stopped.
```

The model's Stage 1 output was flawless — `TOPOLOGY.md` and `DECISIONS.json`, both in the new
invariant form, both well-formed. Replaying the recorded output through the tree as it stood:

```
blocks parsed:  ['TOPOLOGY.md', 'DECISIONS.json']     ← the parser: correct
unpaired:       {'TOPOLOGY.md', 'DECISIONS.json'}     ← the check: everything damaged
plan_shape:     unclosed BEGIN ARTIFACT TOPOLOGY.md, orphan-end ARTIFACT
```

`_continue_short_plan` drops the damaged set from its accumulator and then indexes
`accumulated[TOPOLOGY_BLOCK]`. Nothing survived, so the loop indexed a topology it had itself
discarded one line earlier.

### 32.2 Why — the shape of the defect, which is the part worth keeping

§30.4 changed the *grammar*. Commit `299b702` taught the two artifact **parsers** the new
boundary and migrated nine prompts to emit it. It did not touch five other callers, because
those callers do not parse. They ask a **structural question of the raw response** — *did
everything that opened also close?* — by counting named `=== END <name> ===` lines.

**The invariant close carries no name to count.** That is its entire purpose (§30.4), and it is
exactly what makes a name-counting check blind to it. Every artifact of an undamaged response
read as unclosed, and every close read as an orphan.

| Site | Symptom |
|---|---|
| `planning_session._unpaired_artifact_names` | the crash — accumulator emptied |
| `planning_session._artifact_delimiter_defects` | fatal *"damaged artifact delimiters"* on clean output |
| `planning_session._artifact_delimiters_are_complete` | outside-text waiver path permanently dead |
| `plan_shape.check_delimiters` | every artifact unclosed, plus an orphan `ARTIFACT` |
| `planning_session._extract_conformed_spec` | `plan conform` silently finds no spec — a backreference cannot pair a nameless close |

The generalisation, and it outranks the specific bug: **a grammar with two readers has one of
them wrong.** Five checks answered a question about delimiters by re-deriving the delimiter rules
locally. Each was correct when written. None could be correct after the grammar moved, and
nothing in the design made that failure visible — the parser and the checks disagreed silently,
and the first symptom was a `KeyError` four functions away from the cause.

This is the same structural failure as §1.3, one layer down: **thirty-one gates authored against
no shared model of what a gate is** becomes **six readers authored against no shared model of
what a delimiter is.** The fix has the same shape too — one authority, shared, rather than a
sixth correct copy.

### 32.3 The fix

`artifact_blocks.pair_artifact_delimiters` computes pairing **once**, positionally, and every
caller shares it. It mirrors the parser's own recovery rules rather than re-deriving them: an
open with a block already open leaves that block unclosed; a close terminates the open block
whether or not it names it (§30.2); a name-mismatched close followed by real content is a
transposed boundary and opens what it names.

The property that matters is not that the walk handles both grammars — it is that **a structural
check can no longer disagree with what the parser extracted.** A future grammar change has one
place to land.

`plan_shape`'s duplicate delimiter regexes are deleted rather than extended; `_extract_conformed_spec`
goes through the shared parser and still degrades to *spec left unchanged* on an unusable
response. Genuine damage still reports in the invariant form: unclosed artifact, duplicate open,
orphan close, and a body that absorbed a restarted artifact. Commit `b7ce19e`, 18 tests.

**One test was itself an instance of the defect.** `tests/test_plan_shape.py` fed the checker a
hand-rolled block extractor — a sixth reader of the grammar — so the shape tests passed green
against blocks the real parser never produced. Replaced with the real parser. A test double that
re-implements the contract under test cannot witness the contract changing.

### 32.4 What this says about §30.5

§30.5 argued that a 20%-rate formatting slip is not bad luck and must be fixed rather than
re-run. That was right, and this run adds the other half: **the fix for a transport defect is
itself transport, and it is the same class of change that caused the defect.** Three consecutive
runs — `211658`, `195530`, `231738` — died in the delimiter layer, one of them on the fix for the
previous one. The three layers of §30.4 (prevent, recover, contain) all landed; what was missing
was that nothing verified the *whole lifecycle* spoke the grammar, only that the parsers did.

Cost of the lesson: three runs, roughly 40 minutes and 6M tokens, none of which observed anything
about the Toml product.

### 32.5 Defect record

| Id | Defect | Gate | Evidence | Status |
|---|---|---|---|---|
| **D-024** | The invariant boundary (§30.4) was adopted by the parsers and by nine prompts, and not by five callers that read delimiters directly; an undamaged Stage 1 response read as wholly unpaired and `plan` died indexing the topology it had discarded | G-PLAN-02 | Toml `20260813.231738` — `KeyError: 'TOPOLOGY.md'` | fixed — one shared positional pairing, `b7ce19e` |

The run is in `tests/fixtures/uat_corpus.json` as **unscored**: it never reached a gate, so it
offers no facts. 21 runs, 11 scored. `test_a_run_that_never_reached_the_gate_offers_no_facts`
now names ten.

### 32.6 Order for the next session

`2026-08-13` · `spec:na` · `impl:na`

1. **Re-run Toml.** Three consecutive runs have been lost to the delimiter layer and none of them
   observed the product. Prevention, recovery, and containment are all in the tree, and the
   lifecycle now shares one reading of the grammar.
2. **§26 item 3.1a — P-3a, the per-branch stall** (§27.3 Q1). Unchanged, still the highest-value
   remaining item, and still the only `impl:unimplemented` flag in this file.

Phase 2 onward still waits on the measurement Phase 0 produces, per §27.3 Q2.

---

## 33. Run 20260813.234757 — the repair prompt taught the model the wrong grammar (D-025)

### 33.1 What happened

`2026-08-13` · `spec:na` · `impl:implemented`

The re-run called for by §32.6 item 1 cleared the delimiter layer, ran the whole plan stage, and
died at final validation:

```
Plan integrity check failed:
  analyzed stories are not delivered by any Manifest story: DECODER-002
```

Five LLM calls, and the defect was real in only the first one:

| # | Output | Envelope | `covers:` on `decoder-interface` |
|---|---|---|---|
| 1 | `234919` | `=== BEGIN ARTIFACT TOPOLOGY.md ===` | `DECODER-001` — the genuine defect |
| 2 | `235011` | **`<TOPOLOGY.md>`** | `DECODER-001, DECODER-002` — **corrected** |
| 3 | `235050` | invariant | Stage 2 batch 1 |
| 4 | `235213` | invariant | Stage 2 batch 2 |
| 5 | `235315` | **`<TOPOLOGY.md>`** | `DECODER-001, DECODER-002` — **corrected again** |

`_repair_declaration_coverage` fired correctly and the model answered correctly. Both times the
answer arrived in an XML envelope, `_parse_strict_blocks` raised `OutsideArtifactTextError`, the
`_parse_repair_artifact_envelopes` fallback matched only `<artifact name="…">` and returned `{}`,
and the loop fell through `set(repair_blocks) != {TOPOLOGY_BLOCK}` to `return declaration` — the
uncorrected one, with no message. Stage 2 then spent two full batch passes authoring ten
Blueprints against a topology already known to be defective.

Topology parsing, `covers` splitting, `render_story_block`, the Manifest round-trip and
`analyzed_story_ids` were each replayed against the recorded run and are all correct. The entire
loss is in the repair transport.

### 33.2 Why — a prompt that demonstrates a grammar it does not want back

`_topology_repair_assembly` and `_artifact_repair_assembly` are built in Python, not in
`prompts/`. Both said *"emit exactly one fully paired block"* without ever stating what a paired
block looks like, and then supplied the original body inside `<original-topology>` /
`<original-artifact name="…">`. The only delimiter syntax anywhere in that prompt was XML, so the
model used XML. The fallback parser's existence is the tell: someone had already observed models
copying the input tags and guessed at `<artifact name="…">` rather than removing the thing being
copied.

**This is D-024 a third time.** §30.4's invariant boundary reached the parsers, then reached the
five structural checks (§32), and never reached the two prompts assembled in Python — because
`grep` over `prompts/` does not find them. The generalisation from §32.2 holds and needs widening:
**a grammar with two readers has one of them wrong** — and a prompt is a reader. Nine files under
`prompts/` were migrated; the two prompts that live in `.py` files were invisible to that
migration.

The new rule, which is the part worth keeping:

> A prompt must never demonstrate a boundary syntax it does not want back, and must never
> hand-type the syntax it does.

### 33.3 The fix

`artifact_blocks` gains `artifact_open`, `wrap_artifact`, and `emission_contract_lines` — the
grammar rendered from `ARTIFACT_OPEN_TEMPLATE` and `ARTIFACT_CLOSE_TOKEN`, never retyped. Both
repair assemblies state the contract through it and supply the original body via `wrap_artifact`,
so the form the prompt shows and the form the parser reads are one object. The XML envelopes are
gone from both prompts.

`_read_repair_blocks` is the single reader for both repair loops, which previously parsed the
reply independently — the same duplication §32.3 removed one layer down. The envelope fallback
survives as recovery for replies already in flight and now also accepts `<NAME>…</NAME>` where the
name looks like a filename; a reply mixing the two forms is refused, because an envelope is a
concession to observed behaviour and not a third supported grammar.

**A discarded repair is now reported.** Proceeding on the uncorrected declaration stays correct —
final validation owns the refusal — but four separate paths returned it silently, so the operator
saw a refusal naming a defect the model had in fact corrected, three minutes and two batch passes
earlier. Every discard names its reason.

Verified against the recorded run: `_read_repair_blocks` recovers `TOPOLOGY.md` from
`20260813.235011` with `covers: DECODER-001, DECODER-002` intact. Tests in
`tests/test_planning_session.py` and `tests/test_artifact_blocks.py`; full suite green.

### 33.4 Corpus

`20260813.234757` is in `tests/fixtures/uat_corpus.json` as **unscored** — it never reached a
gate, so it offers no facts. 22 runs, 11 scored.
`test_a_run_that_never_reached_the_gate_offers_no_facts` now names eleven.

### 33.5 Order for the next session

`2026-08-13` · `spec:na` · `impl:na`

1. **Re-run Toml.** Four consecutive runs have now been lost in the transport layer, each one
   further down it than the last: parser (`211658`), structural checks (`231738`), repair prompt
   (`234757`). The layer is out of untouched surfaces.
2. **§26 item 3.1a — P-3a, the per-branch stall** (§27.3 Q1). Unchanged, still the highest-value
   remaining item, and still the only `impl:unimplemented` flag in this file.

§32.4's lesson compounds: the fix for a transport defect is itself transport. Cost across the four
runs is roughly 45 minutes and 7M tokens, none of it spent observing the Toml product.

**Superseded by Part VII.** Item 1 was executed against ReadingList rather than Toml
(`20260814.001652`): the transport layer held, the product built correctly, and the run was
refused at the release gate for reasons in Drydock's bookkeeping. §40 carries the current order.
This section's claim that 3.1a is the only `impl:unimplemented` item no longer holds.

---
---

# PART VII — THE COLLAPSED VERDICT MODEL

`2026-08-13` · approved in discussion

Evidence: ReadingList `20260814.001652`, the first run in the record to reach `score release`
with a complete and correct product. It reported `INCOMPLETE` with five blockers, and the same
file records the grader stating, in its own rationales, that all five criteria are met.

Part VII supersedes V-1, V-2, V-3, V-5, and the `Verification:`-driven machinery in Part II. It
does not disturb P-1 … P-5, P-3a, V-4, V-6, V-7, V-8, the tier model (§14), the two-destination
test model (§24), or the exit semantics (§20).

## 34. An acceptance criterion acquires and releases its own state

`2026-08-13` · `spec:approved` · `impl:unimplemented`

**The defect.** `database-order` (D-027) inserted two rows into `acceptance-order.sqlite3`,
asserted that `list_books()` returned exactly those two, and removed nothing. The store lives in
the build tree and survives every execution, so run two saw four rows and run three saw six. The
product is correct — `app/database.py:68` is `SELECT … ORDER BY id`. The criterion failed itself.

Three of the six rows were left by executions in which the assertion *failed*, which is the
mechanism that makes this compound: a red criterion poisons its own next execution.

**Rejected: sandboxing.** Running each criterion in a disposable copy of the tree makes the
criterion idempotent by making its environment disposable. It hides the class rather than removing
it, and it costs the property that makes an acceptance criterion worth running — that it ran where
the product runs.

**Rejected: delete the store first.** "Fresh store" is add/destroy. It tests against a schema the
criterion just created rather than the schema the product ships, so uniqueness constraints,
referential integrity, and every defect that only appears against existing rows become
unobservable. It would also have hidden the ordering defect it was meant to catch, had one existed:
`ORDER BY id`, `ORDER BY rowid`, and an accidental `ORDER BY title` all agree on an empty table.

**Adopted: add/delete, against the real store.** A criterion arrives at whatever state exists,
acquires what it needs, asserts, and releases exactly what it acquired. Three properties follow,
and none of them hold today:

| Property | Why it matters |
|---|---|
| Idempotent | the criterion's verdict does not depend on how many times it has run |
| Order-independent | no criterion's result depends on another criterion having run first |
| Schema-real | RI, uniqueness, and populated-table defects are reachable |

It also changes what the assertion may claim. `assert [b["title"] for b in books] == [first,
second]` is a statement about the whole table, derived from a local action — true only of an empty
store. The correct assertion is about the rows the criterion owns: they are present, in that
relative order, positioned after whatever was already there. That holds on the first execution and
the thousandth, and it is a *stronger* order test, because it runs against a populated table where
the candidate orderings no longer coincide.

### 34.1 Teardown is a declared part; the control flow is composed

The teardown must run when the assertion fails, or the failing path — the one that will recur —
leaves the wreckage. A criterion that inserts, asserts, then deletes performs no cleanup on red.

The model is a reliable author of *what to acquire and what to release*, and an unreliable author
of *the construct that guarantees release runs*: it is boilerplate with no local motivation, and it
is omitted precisely when the body looks like it cannot fail. So the criterion declares the parts
and Drydock composes the control flow:

```
=== AC <id> ===
Intent: …
Requires: executable=python3; scope=test

Setup:      <acquire>
            <assert>
Teardown:   <release>
=== END AC <id> ===
```

`try`/`finally` in Python, `trap` in shell, `defer` in Go — rendered by Drydock from one place,
never typed by the model. This is §33.3's rule one layer down: the form the prompt shows and the
form the executor runs are one object.

Four consequences, all load-bearing:

1. **`Teardown:` is optional and absent from most criteria.** `assert 1 + 1 == 2` acquires nothing.
   A required field that most criteria fill with a placeholder stops carrying information.
2. **Acquisition is inside the guarded region.** Partial setup — first insert lands, second raises
   — still tears down what it got. This is why `Setup:` is a declared part rather than a preamble.
3. **Teardown failure is never product failure.** An exception in teardown is reported *alongside*
   the assertion's result, never in place of it, and never converts a pass into a fail. Its fault
   domain is CRITERION or KIT (P-1). A composed `finally` that swallowed the assertion error would
   be the worst available outcome, and it is the mistake a hand-typed one makes.
4. **Structure becomes machine-checkable.** With named parts, "does this criterion release what it
   acquires" is answerable by reading the block, not by running it three times.

### 34.2 Applies to both persistent destinations

The same discipline governs the native test suite (§24). D-014 was this defect in the suite —
`instance/reading_list.sqlite3` left behind — and D-027 is the same defect in an AC block. TDD
pattern 7 already states it and nothing enforced it in either destination.

## 35. Residue is observed, not declared

`2026-08-13` · `spec:approved` · `impl:unimplemented`

With `Teardown:` optional, its absence cannot be a syntax defect — so parsing cannot answer "did
the author forget it". And forgetting is the expected failure: the criterion that most needs a
teardown is the one whose author was thinking about the assertion.

The answer is V-2's asymmetry applied to housekeeping: **do not demand a declaration of tidiness;
observe the residue.** After a criterion executes, compare the build tree against what was there
before. A criterion that leaves a file behind is reported by name, with the residue named.

| Property | Value |
|---|---|
| Scope | the build tree only — files appearing or changing |
| Depth | file level. Score does not open a store to diff its contents |
| Fault domain | CRITERION |
| Effect | reported. Never blocks, never reaches the verdict |

**Why file-level is sufficient.** A criterion that leaks into a store leaks *the store itself* on
its first execution, because the file did not exist yet. `acceptance-order.sqlite3` appearing in
the build tree is exactly the observation that was available and unmade. The "same size, different
content" case only arises on the second and later executions of a criterion the first execution
already reported. Catching it once, early, is the whole value.

It needs no declaration from the model, and it does not care whether the cause was a missing
`Teardown:`, a teardown that removed half of what it acquired, or a teardown that never ran because
the assertion failed.

**This is D-014 recast honestly.** The same observation that once failed a perfect release becomes
a finding attributed to the criterion that produced it, at the moment it produced it, instead of a
blocker discovered four stages later with no path back to the cause.

**Out of scope: external surfaces.** An S3 object, a queue, a remote table carry the same teardown
obligation and are not observable this way. Left out deliberately. The reason to revisit is not the
teardown rule but a containment rule — an AC that reaches outside the build tree is a larger
problem than one that fails to tidy up inside it.

## 36. Score observes; it does not read reports

`2026-08-13` · `spec:approved` · `impl:implemented`

**The rule.** `score release` grades the finished tree by observing it at grading time. Anything it
cannot observe for itself is not available to pin a verdict.

A verdict about a finished project cannot be assembled from observations of intermediate states. An
AC that passed at block 3 is a statement about the tree as it stood at block 3, and block 7 can
have broken it. Every recorded outcome from `build` — AC results, block states, gate outcomes, the
Manifest — is **history, not evidence**. It stays in the run record as operator context and repair
signal, and it never reaches the release verdict.

| Trial names | Score does |
|---|---|
| a command (`bin/test.sh` exits zero) | runs it, now, against the final tree |
| a file or structural fact | looks |
| a behavior with no command | writes an ephemeral probe and runs it (§36.1) |
| nothing observable | MANUAL (§37) |

**The governed gate is executed, not inherited.** `ACCEPTANCE.json`'s `full` gate is a command, so
score runs it. V-5's precedence rule survives in wording and changes entirely in meaning: *a
governed gate PASS* is one score just watched happen.

**The build layer may run the same command.** It should — that is repair signal and it is what an
AC is for. The forbidden thing is the release verdict inheriting that run's outcome. Same script,
two consumers, no shared state, neither one's result the other's evidence.

**Score does not read the Manifest.** It is a mid-run report like any other. "Nothing is built yet"
does not need a block state to express it; it reads as criteria that are NOT MET, each naming what
is missing.

Two consequences:

- Score becomes a pure function of the finished tree plus the trials, which is what makes it
  independently re-runnable — the property the policy-replay corpus (§16.1) quietly depends on.
- It costs an execution: the suite runs again, at the end, having already run during build. That is
  the price of a verdict about the artifact that actually shipped, and it is cheap against what a
  stale-evidence verdict costs.

Score is itself an executor, so §35's residue rule applies to it: a suite that leaves rows behind
dirties the tree during grading.

### 36.1 The ephemeral probe — the third test destination

`2026-08-13` · `spec:approved` · `impl:implemented`

A trial that names no command — *"a reader can add a book and see it listed"* — is settled by the
grader writing the exercise and running it: `add_book()`, `list_books()`, `remove_book()`, under
§34's add/delete discipline.

**This is the safe place for a model to author a test, and it is the only one.** An AC block is
authored before the code exists, so every expected value in it is a *prediction* — the root cause
in §1 and the entire reason R1 exists. A probe is authored against code that exists and can be
read, so its expectations are *observed*. The grader calls the real function and sees what returns.
There is nothing to get wrong about a signature that is on screen.

| | Story AC | Native suite | **Ephemeral probe** |
|---|---|---|---|
| Authored | before the code | alongside the code | **after the code, at grading** |
| Expectations | predicted | observed | **observed** |
| Persists | yes | yes | **no — discarded after one verdict** |
| Oracle discipline | R1-legal only | full latitude | full latitude |
| Effect | gates the block | diagnostic | **produces the trial verdict** |

Because it is ephemeral it cannot rot, cannot be re-run against a tree it was not written for, and
never becomes a gate anyone maintains.

**Grounding rule.** A probe must be grounded in source the grader actually read. An import error
against a symbol the source does not contain is the *absence of the capability* and grades NOT MET
(§37). An import error because the grader guessed a module name without reading is grader
incompetence, not a product verdict.

**No repair budget.** Score observes; it has nothing to fix. The grader may author a different
probe before reporting — that is doing its job, not a budget — but there is no retry loop and no
repair pass at the score stage.

**This supplies UC-008.** A completed-but-defective product becomes observable by a probe that
executes cleanly and gets the wrong answer — the case 22 runs have never produced.

## 37. The verdict vocabulary collapses; PENDING is retired

`2026-08-13` · `spec:approved` · `impl:implemented`

`PENDING MANUAL VERIFICATION` (V-1) was doing two unrelated jobs:

1. **A property of the criterion.** *"The product looks pretty"* cannot be settled by any machine,
   ever, however finished the product is. More evidence does not help. That is a terminal answer,
   not a waiting state.
2. **A property of the project.** Score run at the start finds nothing built. Genuinely "not yet",
   and transient.

One word for both made the second look like the first, which is how a finished, correct project
gets reported as though it had open questions.

**Resolution: grade it.** The user asked for a grade, so an unbuilt criterion gets an F. Three
trial states and three run states, and no fourth:

| Trial | Meaning |
|---|---|
| **MET** | observed to work |
| **NOT MET** | observed to be absent or wrong, **with a citation** |
| **MANUAL** | no machine can settle it; a named human check |

| Run | Meaning | Exit (X-2 unchanged) |
|---|---|---|
| **PASSED** | every trial MET; MANUAL attested | 0 |
| **FAILED** | at least one NOT MET | 0 |
| **ERROR** | Drydock could not grade | 1 |

### 37.1 V-2 restated, because "absence of evidence" was ambiguous

V-2 said *absence of evidence yields PENDING, never NOT MET*. Two different absences hid in that
sentence:

- **The capability is absent.** The grader looked, read the source, ran a probe, and there is no
  page, no route, no green. **That is a demonstration.** NOT MET, citing what it saw.
- **The grader's ability to observe is absent.** Harness missing, tree unreadable, probe could not
  execute for reasons about Drydock. Not a grade. ERROR, or MANUAL where the criterion is the
  reason.

V-2 exists to kill the second dressed as the first — *"I could not prove it works, therefore it
fails"* — which is the disease this whole file removes. It was never meant to shield an unbuilt
feature from an F.

> **NOT MET requires the grader to have looked and to cite what it saw, including seeing nothing
> where something was required. It may not conclude NOT MET from not having looked.**

The generous direction is preserved: inference may raise a criterion to MET; it may never reach
NOT MET without a citation.

### 37.2 MANUAL is legitimate, rare, and a criticism of the criteria

At the end of a finished project every criterion is MET, NOT MET, or MANUAL. **A large MANUAL set
is a defect in the criteria, not in the product** — a trial nobody made observable. This is V-8
arriving from the other direction, and the correction is §15's "next step": rewrite the trial as
something checkable. MANUAL attests; it never blocks.

### 37.3 The statement

Score lists every criterion and what it observed. That is the whole answer, and it makes
`score release` useful mid-build rather than only at the end.

```
ReadingList: FAILED — 2 of 3

  st-001  MET         Flask is the declared and imported framework (app/main.py:3).
  st-002  MET         Bootstrap 5.3 is served locally (static/bootstrap.min.css).
  st-003  NOT MET     No template renders the list page; app/templates/ is empty.
                      Probe: GET / → 404.
```

"Nothing is built yet" needs no state of its own: it reads as criteria that are NOT MET, each
naming what is missing. Same shape whether the project is empty, half-built, or finished and
broken.

## 38. Sea Trials are referenced by nothing

`2026-08-13` · `spec:approved` · `impl:implemented`

**Where `proof` came from: distrust of the grader.** The release verdict was meant to be
deterministic, so rather than let a model judge a criterion, the verdict became a *lookup* — bind
each trial to a test that already ran and report that test's exit status. A lookup needs a key, so
`Sea Trials: st-NNN` was added to AC blocks as a backward pointer, and `Verification: proof` became
the switch selecting the lookup over the judgement.

It did not remove the model from the verdict. It moved it — to a tag typed hours earlier, in a
different artifact, with no evidence attached and nothing to check it against. A missing tag became
indistinguishable from a missing capability, which is precisely what `20260814.001652` reported
five times, each alongside a grader rationale asserting the criterion was met.

**The direction rule.** Sea Trials flow *into* `plan` as context for authoring AC. Nothing points
back. Once `plan` has decided an AC is valid, that AC's relationship to the Sea Trial is over.

Retired by that rule:

| Retired | Was | Because |
|---|---|---|
| `Sea Trials:` proof tags | bound a trial to an AC | nothing reads them |
| `Verification:` as mechanism selector | chose proof / measurement / evidence | every trial is graded the same way (§36) |
| `score.py:520-535` proof-tag override | discarded the grader's verdict | **D-016** |
| G-PLAN-13 | `accepts:` names a known trial | validates a reference that no longer exists |
| G-PLAN-14 | proof tag names a known trial | same |
| G-PLAN-15 | required trials have coverage | `plan` certifying at plan time something observable only at score time |
| `accepts:` on a Manifest block | block-to-trial trace | it is a reference back (**see §41**) |

**Losing G-PLAN-15 is not losing a safety net.** It checks that a *reference exists*, not that a
capability was built. The plan in `20260814.001652` satisfied it completely, and would have
satisfied it with every trial referenced by a block that then failed to build. Whether the project
meets its criteria is settled at score, against what exists — the only place the question is
answerable.

## 39. What run 20260814.001652 actually was

`2026-08-13` · `spec:na` · `impl:na`

The first run in the record to build a complete, correct product and reach the release gate.

```
Release gate: ReadingList  INCOMPLETE
  BLOCKER: Required Sea Trial st-001 is INCONCLUSIVE
  BLOCKER: Required Sea Trial st-002 is INCONCLUSIVE
  BLOCKER: Required Sea Trial st-003 is INCONCLUSIVE
  BLOCKER: Required Sea Trial st-005 is INCONCLUSIVE
  BLOCKER: Required Sea Trial st-006 is INCONCLUSIVE
```

`evidence/score-release.json` records the contradiction in one file: every blocked criterion
carries a grader rationale asserting it is met — *"the complete automated suite exits zero with 28
tests passed"*, *"submitted title and author are accepted, persisted, and shown in the public
list"* — and an evidence array reading `no code-bound proof references this criterion`.

**Cause (D-026).** The Manifest carries `accepts:` for all seven trials; `plan` emitted proof tags
for two (`st-004`, `st-007`). G-PLAN-15 accepts either and passed. `score` counts proof tags only
and blocked the other five. Nothing was malformed and nothing was missing: the plan satisfied the
contract as written and the release gate read a different contract.

**This is §32.2 one layer up.** *A grammar with two readers has one of them wrong.* There it was
the parser and five structural checks; here it is plan integrity and the release gate. Same
signature — silent disagreement, first symptom far from the cause.

**The one product-shaped failure was a criterion defect (D-027).** `database-order` failed with an
`AssertionError`; the product is correct. §34 is the fix, §35 the detection.

**The honest verdict for this run is `PASSED: 7 of 7`** — the §33/§32/§30 transport work held, the
build is correct, and every refusal came from Drydock's bookkeeping.

## 40. Implementation order for Part VII

`2026-08-13` · `spec:na` · `impl:na`

| # | Change | Touches | Closes |
|---|---|---|---|
| 7.1 | Delete the proof-tag override; `Verification:` becomes a hint | `score.py:520-535` | **D-016** |
| 7.2 | Retire proof tags, G-PLAN-13/14/15 | `planning_session.py:2134-2163`, `prompts/` | **D-026** |
| 7.3 | MET / NOT MET / MANUAL; PASSED / FAILED / ERROR; the listing statement | `score.py`, `sea_trials.py`, `prompts/score_release.md` | V-1, V-3 |
| 7.4 | V-2 restated as §37.1 in the grader contract | `prompts/score_release.md` | |
| 7.5 | Score observes at grading time; no mid-run report is evidence; governed gate executed | `score.py` | |
| 7.6 | Ephemeral probe: the grader authors and runs a grounded exercise | `prompts/score_release.md`, `score.py` | **UC-008** |
| 7.7 | `Setup:` / `Teardown:` parts; composed control flow | `prompts/BLUEPRINTS_CONTRACT.md`, the AC executor | **D-027** |
| 7.8 | Residue observation at the build tree, CRITERION-attributed, non-blocking | the AC executor, `score.py` | **D-014** class |

7.1 and 7.2 alone would have made `20260814.001652` report `PASSED: 7 of 7`. They are the cheapest
items in this file and they unblock the only run that has ever reached the gate cleanly.

§26 item 3.1a (P-3a, the per-branch stall) remains scheduled and is unaffected.

## 41. Open questions (Part VII)

`2026-08-13` · `spec:na` · `impl:na`

- **Does `accepts:` retire with the proof tags?** The direction rule (§38) says a reference from
  the build layer back to a Sea Trial should not exist, which retires it. Against that, `accepts:`
  is the only human-readable record of which trial motivated a block, and it gates nothing.
  Recorded as *retire*, flagged because it was not settled explicitly.
- **Where do the composed `Setup:` / `Teardown:` renderings live** — one per `Requires: executable`
  value, in the AC executor, or declared in stack guidance under `Rigging/`?
- **Does the ephemeral probe get recorded as evidence?** It must be, to serve as a NOT MET
  citation. Open: whether it is stored per-run under `evidence/` or inlined in the verdict.
- **How does §35 observe the tree cheaply** for a large build — a manifest of paths and mtimes
  before and after each criterion, or a git status against the build directory's own index?

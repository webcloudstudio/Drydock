# NOTES: UAT Gate Model — Acceptance, Epics, and Release

| Field | Value |
|-------|-------|
| Version | 2026-08-13 V2 |
| Route | uat |
| Status | Working notes — not canonical specification |
| Description | Theoretical pass over the whole UAT lifecycle: every gate that can stop a run, given a stable reference id, evidenced against all 18 recorded runs; then the proposed verdict model that replaces them. |
| Pending spec | 6 approved items |
| Pending impl | 6 unimplemented sections |

**§1–§11 are analysis. §12–§17 are the proposed model**, approved in discussion 2026-08-13.
Nothing here authorizes an edit to `docs/Drydock_Specification.md`.

Companion file: `notes/notes_uat.md` holds the 2026-08-10 diagnosis and the Sea Trials redesign.
This file supersedes its gate inventory (§"Gate inventory after simplification"), which listed four
gates. The real count is **31**.

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
| D-008 | One malformed artifact discards a batch of 19 blueprints | G-PLAN-02 | CommonMark `20260811.184523`, `.215210` | **open** |
| D-009 | Assertion-count minimum forces the model to author AC it has no oracle for | G-PLAN-12 | CommonMark `20260811.215210` — killed 8 LLM calls in | **open** |
| D-010 | A story that will not close stalls every dependent block | G-BUILD-08 | Toml, all 8 runs | **open by design — see §6.4** |
| D-011 | Toml parser accepts U+3000 as whitespace (`strings.TrimSpace`) | G-BUILD-04 | Toml `20260813.084830`, 126 valid-case failures | **open — genuine product defect** |
| D-012 | Sea Trial `st-001` carries no `Command:`; release resolves through model proof tags | G-SCORE-09 | Toml fixture | **open** |
| D-013 | `ACCEPTANCE.json` stage keys are model-chosen slugs; a rename silently unbinds the gate | G-BUILD-04 | not yet observed | **open — latent** |
| D-014 | **`test` creates `instance/reading_list.sqlite3`; `score release` then blocks the build as dirty** | G-TEST-01 → G-SCORE-05 | ReadingList `20260813.160121` | **open — see below** |
| D-015 | Build does not converge inside the pass budget; recorded as `degraded` with no attribution | G-BUILD-08 | 6 runs | **open** |

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
rejections becomes a rubber stamp, and Toml's U+3000 defect (D-011) is the case that must keep
failing.

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

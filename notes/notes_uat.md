# NOTES: UAT, Sea Trials, and Story Acceptance

| Field | Value |
|-------|-------|
| Version | 2026-08-10 V1 |
| Route | uat |
| Status | Working notes — not canonical specification |
| Description | Diagnosis of the four-day UAT failure loop and the redesign of story acceptance and Sea Trials into two typed, separately gated definitions of done. |
| Pending spec | 10 approved items |
| Pending impl | 13 unimplemented sections |

## Goal

Build UAT the correct way, and iterate that: a UAT run must distinguish a defect in the product
Drydock built from a defect in Drydock's own checkers, and neither definition of done — story or
project — may harden into a gate that no correct build can pass.

## Decisions

### Diagnosis: why the loop did not converge
`2026-08-10` · `spec:na` · `impl:na`

Root cause: **the UAT fixture is not fixed.** Every run executes `init → import → analyze → plan →
build → score` from scratch, and `analyze` asks an LLM to author `SEA_TRIALS.md` fresh each time.
Those generated criteria then become the binding contract `build` must satisfy and `score` grades.
Each run is therefore a new random draw of acceptance criteria, and every fix was fitted to a
sample of size one. This is why CommonMark and ReadingList stopped passing without changing.

Three consequences, each visible in the commit log:

1. **Unsatisfiable criteria are born at `analyze` and only detected at `score`.** Nothing checks at
   authoring time that a criterion is achievable. `4c638ff`, `facd000`, `0267a71` are all the same
   defect: the criterion was wrong, the application was fine, discovered ~250k tokens downstream
   with an error message pointing at the build.
2. **The repair layer is an unbounded blacklist.** `proof_integrity.py` carries seven independent
   analyzers, each added in response to one observed failure. The space of bad assertions is not
   enumerable, and each analyzer has its own false-positive rate against legitimate snippets — two
   have already been retracted (`ef53688`, `d91d66b`). The accumulated surface area is the
   mechanism by which the simple fixtures started failing.
3. **Consequence was not a property of the criterion.** Anything written into `SEA_TRIALS.md`
   entered the scorer as an absolute, and the only place to soften it was the scorer itself.

The harness also could not tell the two failure modes apart: `result.json` reports
`status: failed`, `error: "ReadingList: plan exited 1"` for both "Drydock produced a bad artifact"
and "Drydock's checker rejected a good artifact". Those need opposite fixes.

### Two definitions of done, two gating mechanisms
`2026-08-10` · `spec:approved` · `impl:unimplemented`

Story acceptance and Sea Trials are genuinely two layers, distinguished by mechanism:

| | Story acceptance | Sea Trials |
|---|---|---|
| Scope | one story | the project |
| Gate | **mechanical** — 4 retries, no build-complete without closure | **judgemental** — evaluated once at release |
| Authored by | `plan`, into blueprints | `analyze`, or the Commander override |
| Read by | build agent, acceptance runner, retry loop, scorer | the scorer |
| Failure mode | contract that cannot self-heal in four retries | a wrong judgement |

Stories gate the release *by construction*: if it does not build, it does not build. Sea Trials are
project acceptance criteria and **may legitimately duplicate a story's AC** — the CommonMark case,
where a story is "run the tests" and the Sea Trial is "the tests pass". Duplication across the two
layers is by design, not redundancy to eliminate.

### Story acceptance results are reported, not consumed by the release gate
`2026-08-10` · `spec:approved` · `impl:unimplemented`

"27 of 27 passed" is the build process self-testing, and the count climbing across the retry loop
is the methodology demonstrating itself. It belongs in the record and in the trend. It is **not** an
input to the release decision — the release gate has exactly one input, Sea Trials.

Action: keep story acceptance counts in evidence, `result.json`, and the report; remove
story-level acceptance coverage from the release rubric in `score.py` / `build_score.py`.

### Gate inventory after simplification
`2026-08-10` · `spec:approved` · `impl:unimplemented`

Acceptance criteria are gated three times today, and only the last is about whether the criterion
passed:

| # | Phase | Gate | Fate |
|---|---|---|---|
| 1 | `plan` | Shape & topology (`plan_shape`, `plan_topology`) | **Kept**, load-bearing |
| 2 | `plan` | Tooling authorization (`validate_declared_external_usage`) | **Retired** — see below |
| 3 | `build` | Execution, 4 retries, `question_gates`, `dependency_gate` | **Kept** |
| 4 | `score` | Sea Trials | **Kept**, redesigned |

Final state: two structural gates (plan shape/topology, build execution) and one definition-of-done
gate at each level.

Note: today's ReadingList failures are frequently **gate 1**, not acceptance —
`BOOK-CATALOG-004 not delivered by any Manifest story`, five LLM calls in, never reaching a single
acceptance criterion. Some of the "acceptance false positives" of the last four days are plan-shape
failures wearing an acceptance-shaped error message.

### Sea Trials as a typed table
`2026-08-10` · `spec:approved` · `impl:unimplemented`

Sea Trials becomes a table whose rows carry properties as columns, plus one policy block.

- **Rows declare what each criterion *is*** — its properties.
- **The policy block declares what those properties *mean*** — how columns combine into a gate
  verdict, written once at the top of the file.

This is a separation, not a default-with-override: the row is data, the policy is the scoring
function over that data. There is no duplication.

| Column | Values | Notes |
|---|---|---|
| ID | `st-NNN` | binding target for `Sea Trials:` references |
| Criterion | the statement | |
| Category | technical · behavioral · qualitative · outcome · guardrail | `TRIAL_TYPES` already carries these |
| Testability | deterministic · judgeable · neither | "renders in my branding" · "reads professionally" · "I want to become a billionaire" |
| Consequence | blocks · scores · attests | currently entangled with `Verification:` |

**Testability and consequence stay separate columns.** Collapsing them is the exact defect behind
the guardrail-hardening loop; `78f9233` and `c1f8589` were both walking that back by hand.

**Not a column: settlement.** Whether a criterion is proved by its own code block, by a bound story
assertion, or by neither is *observable* from the row — code present, `Sea Trials:` reference
present, or absent. Declaring it invites a row claiming deterministic proof it does not carry.

**Precedence rule:** where the policy block disagrees with the rubric compiled into
`build_score.py`, the file wins. Otherwise changing a gate means editing Python, which is the loop
being left behind.

### Commander Sea Trials override, exclusive authorship
`2026-08-10` · `spec:approved` · `impl:unimplemented`

`SEA_TRIALS.md` becomes overridable by the Commander, sitting beside `TECHNOLOGY_STACK.md`.

- Commander file present → the model **never** writes it.
- Absent → `analyze` authors it as today.

Exclusive per run, **not merged**. If `analyze` still emits criteria and the override layers on
top, there are two writers, a merge, and per-criterion precedence questions — and nothing is
gained. `TECHNOLOGY_STACK.md` works precisely because it is pure Commander input.

Normal Targets will use the generated path; the override is expected mainly in UAT mode.

This also removes the structural defect that the model writes the exam it will be graded on,
without freezing any artifact.

Caveat to resolve at implementation: `authorization_for()` reads `TECHNOLOGY_STACK.md` by raw
lowercase substring match (`_technology_stack_contains`). A scoring policy resolved by substring
match is a defect generator — `SEA_TRIALS.md` needs a deliberate parse contract, not `in`.

### Executable deterministic Sea Trials blocks
`2026-08-10` · `spec:approved` · `impl:unimplemented`

A Sea Trial settles one of three ways:

1. **Own check** — carries its own Programmatic Acceptance, self-contained, run against the
   finished build.
2. **Bound** — a `Sea Trials: st-NNN` reference reaches a story assertion (the CommonMark case).
3. **Judged or attested** — not deterministically verifiable, by declaration.

Only (3) needs the attestation machinery. (1) removes the binding as a *requirement*: the criterion
that failed a clean 27-of-27 ReadingList run (`78f9233`) had no way to be proved except by a story
declaring `Sea Trials: st-003`.

Own checks obey both cross-cutting rules below: state as oracle, and three-valued outcome.

### Three-valued assertion outcome
`2026-08-10` · `spec:approved` · `impl:unimplemented`

An assertion that fails because it could not read a file never reached the code under test. It is
not a failure, it is a non-result:

| Outcome | Meaning |
|---|---|
| **PASS** | exercised the code, oracle satisfied |
| **FAIL** | exercised the code, oracle violated |
| **UNVERIFIED** | never got there — permissions, missing path, import error, harness fault |

Only FAIL is evidence about the product. UNVERIFIED is evidence about the kit: counted separately,
reported loudly, never charged against the build. A Rigging-declared tool missing at run time is
UNVERIFIED.

`proof_integrity.analyze_structure` already reasons about exactly this class — "defects that make a
proof fail before it can exercise the code under test" — but only *statically*, at authoring time.
There is no runtime counterpart, which is why these land as product failures today. Likely a large
share of the false positives discarded by hand over the last four days.

Action: add the runtime classification, surface it per assertion, and aggregate it into
`result.json` as a harness-defect vs product-defect distinction for the run.

### TDD patterns for story unit tests
`2026-08-10` · `spec:approved` · `impl:unimplemented`

The story-acceptance prompt was never reviewed, so the model invents assertion style per run. Every
story-level failure observed in four days has one shape: **the oracle was a string in captured
output.** Seven analyzers in `proof_integrity.py` police that one bad habit.

The kit is sandboxed and the commands are real, so the contract can be stated directly.

#### The core rule

> **Act on the system. Read the state back. Compare to expected.**

Arrange–Act–Assert, where the assertion reads *state*, never text a process printed.

| Oracle | Verdict |
|---|---|
| Return value, parsed JSON, status code, DB row, file contents read back, exit status | **Correct** |
| Substring of captured stdout/stderr, test-runner tally text, log lines | **Forbidden** |

Rationale: a state oracle cannot pass against a stub and cannot fail because a runner printed the
word "warning". `4c638ff`, `7bea12a`, `d91d66b`, `ef53688`, `0267a71` all vanish under this rule.

#### Pattern 1 — Round trip (the default form)

For anything that stores, mutates, or removes state:

```
create  → read back → assert present, with expected field values
update  → read back → assert changed, and only the intended fields changed
delete  → read back → assert absent
```

The read-back is a *separate call through the public interface*, not an inspection of the object
returned by the write. A write that returns a plausible object while persisting nothing must fail.

#### Pattern 2 — Exercise every callable workflow

One test per public entry point, per verb. Coverage is enumerated from the interface, not sampled:

- **HTTP API** — every route × every method it declares, including the declared error paths.
- **CLI** — every subcommand, and every flag that changes behavior.
- **Library** — every exported function.

For a reading-list web app, that reads concretely as: GET the page and assert 200 plus a specific
element present; POST a book and assert the declared status, then GET the list and assert the title
appears in the *parsed* body; DELETE it and assert absent on re-read; GET a nonexistent id and
assert 404; POST a duplicate and assert the declared behavior.

#### Pattern 3 — Idempotence

Where a verb claims idempotence (PUT, DELETE), apply it twice and assert the second is a no-op:
same resulting state, and the declared status for a repeat. Where a verb is *not* idempotent
(POST), apply twice and assert the declared behavior — two resources, or the declared conflict.
Preference for idempotent verbs where the semantics allow, since the assertion is stronger.

#### Pattern 4 — Negative paths assert the contract, not the message

Invalid input asserts the declared failure signal — status code, exception type, exit status —
never the wording of an error message. Message text is prose and belongs to no contract.

#### Pattern 5 — Boundaries

Empty collection, exactly one, many. Absent optional fields. Declared maxima. These are where a
plausible-looking implementation actually breaks.

#### Pattern 6 — RED before GREEN

The assertion must be shown to fail against the pre-implementation tree and pass after. A check
that passes against a stub is not a check. This is `proof_integrity.analyze_proof`'s "vacuous
proof" test, moved from post-hoc detection to the authoring contract.

#### Pattern 7 — Isolation and determinism

- Each test arranges its own data and does not depend on another test's residue or on ordering.
- No wall-clock dependence, no third-party network, no unseeded randomness, no sleep-based timing.
- Fresh store per test, or explicit teardown.

#### Pattern 8 — One behavior per test, named for the behavior

The test name states the behavior asserted. A failure should be diagnosable from the name alone.

#### Pattern 9 — Subprocess discipline

Where a check must shell out, **exit status is the verdict**. A substring check beside an exit
status assertion is redundant at best and a false-positive generator at worst (`0267a71`). Never
assert that a literal is absent from captured output.

#### Pattern 10 — In-language tooling

See the tooling section below. The check is written in the project's language and uses that
language's libraries. An in-language HTTP client yields a status code and a parsed body — state.
`curl` yields stdout — text to scrape. The tooling rule and the oracle rule are the same rule seen
twice.

Action: write these into the story-acceptance authoring prompt (`prompts/plan_create.md`,
`prompts/BLUEPRINTS_CONTRACT.md`, `prompts/build.md` as applicable). Models are well trained on
TDD; the contract's job is to fix the *oracle*, not to teach testing.

### Acceptance tooling gate retired; in-language libraries rule
`2026-08-10` · `spec:approved` · `impl:unimplemented`

`validate_declared_external_usage` parses a check's code, finds e.g.
`subprocess.run(["curl", ...])`, looks for a matching `Requirements:` line written by the model
inside that same check, and raises when absent — **without ever asking whether curl is installed.**
A check that works perfectly on a machine where curl has been present for a decade fails planning
because the model forgot a declaration line. That is why `sh`, `bash`, `python3` needed the
hard-coded `_BASELINE_EXECUTABLES` exemption in `fe712f6`.

The gate conflated two questions. Only the second has a cost:

| Situation | Consequence |
|---|---|
| Declared in Rigging / stack, present | Use it. Silent. |
| Present but not declared | Use it. **Recommend** adding it to Rigging. Never blocks. |
| Absent, would need installing | The only thing that could gate — and it is designed out below. |

**Authoring rule that dissolves the gate:** an acceptance check is written in the project's own
language and uses that language's libraries — Python check, Python libraries; Go check, Go
libraries. Reaching for an external executable is the exception and requires a Rigging entry.
`curl` is a stretch, will not work in all environments, and belongs in Rigging if genuinely needed.

Installation is not the builder's purview. "Needs installation" stops being a case the system
reasons about because it stops being a case the system produces — it *should not happen*.

Consequences:
- Declaration moves from the check to the environment. Rigging / `TECHNOLOGY_STACK.md` is declared
  once by the Commander and true for every check in the project. The per-check `Requirements:` line
  survives as a **report**, not a gate.
- `_BASELINE_EXECUTABLES` retires. "Standard build system" is a stated baseline in the declaration,
  not a frozenset someone must edit and re-release.
- A Rigging-declared tool missing at run time is **UNVERIFIED**, not FAIL.

### proof_integrity analyzers demoted to authoring-time
`2026-08-10` · `spec:approved` · `impl:unimplemented`

The seven analyzers (`analyze_proof`, `analyze_literals`, `analyze_structure`, `analyze_invocation`,
`analyze_shell_escapes`, `analyze_swallowed_output`, tally-vocabulary) are the real prize of the
last four days: each is a documented, tested description of a way an LLM writes a broken assertion.

As **gates** they fight the model after the fact and accumulate false positives.
As **prompt content and authoring-time warnings** they are exactly the corpus that teaches the model
not to write those assertions. Keep the knowledge, drop the enforcement.

Action: convert each analyzer from a blocking defect into (a) prompt guidance in the acceptance
authoring contract, and (b) a warning that may cost marks, never a hard gate.

### UAT fixtures carry a frozen SEA_TRIALS.md
`2026-08-10` · `spec:approved` · `impl:unimplemented`

With the Commander override in place, a `SEA_TRIALS.md` checked into each UAT fixture beside
`TECHNOLOGY_STACK.md` means every run is graded against the **same exam**. The release gate stops
being a fresh random draw, which is the single change that makes a regression detectable — while
`analyze` keeps generating criteria for real Targets, where generation is the product.

`uat --stage` (`1c8530b`) is the replay mechanism this needs.

### What the four days bought
`2026-08-10` · `spec:na` · `impl:na`

Nothing is discarded; most of it becomes the new model.

| Learning | Fate |
|---|---|
| `78f9233` UNPROVEN is an attestation, not a breach | Becomes the `attests` value in the consequence column |
| `c1f8589` the author declares testability | Becomes the testability column |
| `1d80e45`, `b6a05f6` topology coverage repair | Gate 1, unchanged, still load-bearing |
| `1c8530b` `uat --stage` | Replay mechanism for a frozen fixture `SEA_TRIALS.md` |
| `5d83511` cached/uncached token reporting, evidence trees | Unchanged |
| `4c638ff`, `7bea12a`, `d91d66b`, `ef53688`, `0267a71` | Subsumed by the state-oracle rule; survive as authoring-time warnings |
| `fe712f6` baseline executable exemption | Retired — the in-language rule removes the case |
| `facd000`, `594bd6f` Toml self-fail loop patches | Re-evaluate against the new model; likely subsumed |

### Implementation order
`2026-08-10` · `spec:na` · `impl:unimplemented`

Three separable changes. (1) and (3) are independently useful and neither depends on the other.
(2) is the main event and cannot be exercised end to end until (1) lands.

1. **Make a run reach the gate.** Plan topology stable (`b6a05f6` may already have done this —
   confirm with a rerun), plus the PASS/FAIL/UNVERIFIED classification and the harness-defect vs
   product-defect field in `result.json`. Small, and it ends the blind debugging immediately.
2. **The Sea Trials table.** Columns, policy block, precedence rule, Commander override, executable
   deterministic blocks, frozen fixture `SEA_TRIALS.md`. Testable the moment (1) lands.
3. **Demote the acceptance gates.** Tooling authorization retired, `proof_integrity` analyzers moved
   to authoring-time, the TDD patterns written into the prompts.

## Acceptance Criteria

- A ReadingList UAT run reaches `score` and produces a gate verdict.
- `result.json` distinguishes a harness defect from a product defect without reading logs.
- An assertion that cannot read a file reports UNVERIFIED and does not fail the build.
- A Sea Trial whose consequence column says `attests` never blocks a release.
- A Commander `SEA_TRIALS.md` in a fixture is used verbatim; `analyze` does not overwrite it.
- Changing a gate's severity requires editing `SEA_TRIALS.md`, not `build_score.py`.
- No acceptance check fails planning for undeclared tooling that is present on the machine.
- Two consecutive UAT runs of the same fixture reach the same gate verdict.

## Guardrails

- The scoring rubric may not be re-hardcoded into `build_score.py` once the policy block exists.
- No new static analyzer may be added to `proof_integrity.py` as a *blocking* gate.
- Testability and consequence remain separate columns; they may not be recollapsed.
- Sea Trials authorship is exclusive per run — Commander file or model, never merged.
- Story acceptance counts are reported, never consumed by the release gate.

## Open Questions

- Parse contract for `SEA_TRIALS.md`: how is the table read, and how is the policy block expressed
  so it is machine-evaluable rather than substring-matched?
- Does the rerun after the base-artifact reformat clear the `plan` topology failure, or is more
  work needed in step (1)?
- Do `facd000` / `594bd6f` (Toml self-fail loop) survive the new model, or are they subsumed?

## Not in scope yet

- Freezing the whole UAT pipeline (`analyze`/`plan` outputs). The frozen `SEA_TRIALS.md` achieves
  the regression property for the release gate without it.
- Changes to `analyze` criterion generation quality for real Targets.
- Rigging content beyond declaring externally provided executables.

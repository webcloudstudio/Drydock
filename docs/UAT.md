# Drydock UAT

UAT generates **evidence of a build**. A UAT run rebuilds a known open-source project from its own
published specification, grades the result against that project's own conformance suite, and seals
every input, prompt, transcript, command, and artifact into a hash-verified proof kit. The evidence
is the deliverable: it is what a user reads to confirm that a pipelined build was performed
correctly.

The ordinary way to drive Drydock is interactively, through the web console. UAT is the other mode.
Once a project has been built once, its changes — refits — and its backtests are pipelined, run
unattended, and judged by a governed gate rather than by a human reading output. UAT is how that
pipeline is exercised and how its results are published.

This document has two parts. **Part I** is reference: what `uat/` holds, how to run it, and how to
read what comes out. **Part II** is a procedure for an LLM to follow when building a new kit from an
upstream repository.

---

# Part I — Using UAT

## 1. What `uat/` contains

`drydock uat <kits>` runs encapsulated. It does not write to the ordinary output directory or logs;
every artifact lands under `uat/<Kit>/`.

```text
uat/
  README.md              pointer to this file
  <Kit>/                 one kit, publishable as its own repository
    README.md            what the kit builds and how to run it
    uat.json             source bundle, updates, and the governed scoring entry point
    index.html           project page: documents, input bundles, and every run
    view/                generated viewer per linked artifact; mirrors the kit's paths
    assets/kit.css       generated stylesheet shared by every viewer
    inputs/              optional lifecycle decisions seeded before analysis
    sources/             Blueprint inputs and supplied build assets
      full_test.sh       required scoring entry point; supplied, never authored
    updates/             replacement sources that drive incremental rebuilds
    runs/<run-id>/       one complete unattended run
```

`uat/` is gitignored in the Drydock repository. Each kit is its own repository, or untracked — which
is why this file, not a file under `uat/`, is the tracked home for how kits are defined, authored,
run, and read.

## 2. Running a kit

```bash
drydock uat                      # every kit under uat/
drydock uat Toml                 # one kit
```

| Flag | Effect |
|---|---|
| `--uat-root <path>` | Directory holding the kits (default `<workspace>/uat`) |
| `--max-build-passes <n>` | Repair passes allowed per build before the kit fails |
| `--llm-provider`, `--model`, `--effort` | Provider and model selection for the whole run |

A run is long and consumes subscription quota. The `Toml` kit takes roughly thirty minutes and
eighteen LLM calls.

## 3. Reviewing the report — `index.html`

Each kit has an `index.html` project page for navigation. It carries the latest verdict, one row per
recorded run linking that run's own `index.html`, the governed documents at the kit root, and the
`inputs/`, `sources/`, and `updates/` bundles the runs were built from. It is written at the end of
every run.

Every linked text artifact — Markdown, logs, transcripts, delivered source — is reached through a
generated viewer under `view/`, which carries the report's own styling: Markdown is rendered, and
anything else is shown as source. Each viewer links the raw file, and `SHA256SUMS` covers the raw
files, never the viewers. `view/` and `assets/` are generated output, rewritten on every rebuild.

## 4. Rebuilding reports — `--report`

```bash
drydock uat --report             # rebuild proof kits from every completed run
drydock uat --report Toml        # rebuild one kit's proof kits
```

`--report` regenerates `index.html`, `view/`, and `assets/` in full from the runs already recorded
under `runs/`. It executes no build and makes no LLM call. Use it after changing report styling or
layout, or to restore a report from runs that are still on disk.

## 5. Reading a run

```text
runs/<run-id>/
  README.md             run verdict, elapsed time, token and cost accounting
  index.html            linked proof kit
  result.json           every child command, argv, exit code, elapsed time
  SHA256SUMS            integrity manifest
  inputs/               exact declared lifecycle inputs for this run
  sources/              the exact bundle imported for this run
  workspace/            the isolated Drydock workspace, including targets/<target>/
  build/<target>/       the delivered application
  evidence/
    commands/           stdout and stderr of every child command
    prompts/            the assembled prompt for every LLM call
    prompt_outputs/     the parsed model output
    provider_raw/       the unmodified provider transcript
    llm.jsonl           one record per call: tokens, elapsed time, execution id
    manifest.json       evidence index
```

When a build fails, the authoritative diagnosis is
`workspace/targets/<target>/evidence/<block-id>.md`: the pre-build acceptance observation, the
stacked context, the build-directory changes, and the post-build result for every criterion.

Verify a kit with:

```bash
cd runs/<run-id> && sha256sum -c SHA256SUMS
```

Absolute paths are rewritten to run-relative paths when the kit is sealed, so a run stays readable
on any machine.

---

# Part II — LLM Instructions: Building a Kit from a Repository

How to build a Drydock UAT kit from an upstream repository, without reading `src/drydock/`.

Everything an author needs to know about Drydock's plumbing is stated here as a rule. Follow the
rules; do not re-derive them from the source. If a rule turns out to be wrong, fix this file — do not
go back to reading the package.

**Typical instruction to an assistant:** "Follow Part II of `docs/UAT.md`. Build a kit for
`<owner>/<repo>` at tag `<tag>`. The specification is `<path>`, the conformance suite is `<path>`,
the implementation language is `<lang>`."

## 6. What a kit is

A kit is one known open-source project that Drydock rebuilds from its own published specification,
graded against that project's own conformance suite. The kit supplies the specification, the suite,
an external scoring instrument, and the lifecycle decisions. Drydock supplies the implementation. The
score is the fraction of the suite that passes.

A kit lives at `uat/<Kit>/` and is discovered by the presence of `uat.json`.

A kit is an exam. The build agent sits the exam; it must not also write it, mark it, or decide when
it is over. Every rule below keeps those roles apart.

## 7. The rules you must not re-derive

These are the non-obvious facts about how Drydock treats a kit. Every one of them has changed a
kit's design at least once.

### R1 — Sources are flattened by basename

Declared sources are copied into the run's `sources/` **flattened**: `sources/a/b/x.txt` arrives as
`sources/x.txt`. Nested directory structure cannot be carried. Duplicate basenames are a hard
discovery error.

*Consequence:* any suite case that needs a directory tree of fixture files (module search paths,
include paths, multi-file inputs) cannot run. Exclude it explicitly — see §12.

### R2 — Build prompts receive no imported source content

The full source bundle reaches `analyze` and `plan` and stops there. A build story's prompt gets
**none** of it as text. Markdown sources are not promoted into the Blueprint, and staged non-Markdown
assets appear to the builder only as *file names* on disk.

*Consequence:* **the normative specification must not ship as `.md`.** Ship it as `.txt`. A `.txt`
source is injected as prose at `analyze`/`plan` *and* staged onto disk where a build story can open
it. A `.md` specification survives into the build only as whatever `analyze` paraphrased.

Rename or render upstream Markdown to `.txt`. Keep `INSTRUCTIONS.md` as `.md` — it is author intent,
meant for the analysis, not for re-reading during the build.

### R3 — Staging is opt-in and LLM-authored

Whether a source is written to disk in the build directory is decided by a `## Source Roles` table
that the **model** writes during `analyze`. An unsteered `analyze` stages nothing.

*Consequence:* `INSTRUCTIONS.md` must contain an explicit Source Roles table telling `analyze` what
to record, with `stage` as the build disposition for every file the builder must read or run. This is
load-bearing. Omit it and the builder has a specification it cannot open.

### R4 — Exit code 2 is a kit fault

An acceptance gate that exits `2` is treated as a fault in the kit, not a failure of the build, and
is never charged against the score. Reserve `2` in your scoring instrument for its own errors: a
missing corpus, an unset environment variable, a stale exclusion. Gates time out at 1800 seconds.

### R5 — Scoring assets are hash-verified

Files staged into the build directory are recorded by SHA-256 at import and restored before grading.
A model that edits the scoring script is reported as tampering rather than obeyed. Say so in
`INSTRUCTIONS.md`; it saves a wasted repair pass.

### R6 — There is no per-story source selection

A build story's `context:` resolves against the Blueprint, never against `sources/`. You cannot give
story 4 chapter 4 of the manual. The specification ships whole or not at all. Budget for it: the
whole bundle is re-injected at `analyze` and at each `plan` batch.

### R7 — Prose is chunked, never dropped

A prose source over 48,000 characters is split into 12,000-character chunks and all chunks are
injected. Nothing is silently truncated. Large is expensive, not lossy.

### R8 — Seeded lifecycle files are never overwritten

`analyze` will not overwrite an existing `TECHNOLOGY_STACK.md` or `SEA_TRIALS.md`. Seeding them
before `analyze` makes the kit's decisions the decisions of record. `ACCEPTANCE.json` is not a
Blueprint artifact at all — no LLM command can write it, which is what makes it the exam.

### R9 — `updates` must match an imported basename

Every entry in `uat.json`'s `updates` list must share a basename with a declared source; it replaces
that file mid-run to exercise `refit`. An update naming a file that was never imported is a discovery
error.

## 8. Kit directory layout

```text
uat/<Kit>/
  uat.json               kit definition; its presence is what makes this a kit
  README.md              what it builds, why this target, how to run and score it
  NEXT_STEPS.md          design decisions and open items (authoring notes)
  PROVENANCE.md          upstream tag and a SHA-256 per verbatim file
  LICENSE                upstream licence plus an attribution note
  USER_NOTES.md          host prerequisites, if any
  .gitignore             runs/ archive/ __pycache__/ *.pyc
  inputs/                lifecycle decisions, seeded before analyze
    SEA_TRIALS.md
    TECHNOLOGY_STACK.md
  sources/               everything declared in uat.json — flat, unique basenames
    INSTRUCTIONS.md      the build brief
    <spec>.txt           the normative specification — .txt, never .md  (R2)
    <suite>              the conformance corpus, verbatim
    exclusions.txt       cases this kit cannot run, with reasons
    run_conformance.*    the scoring instrument
    full_test.sh         the scoring entry point
  tools/                 authoring tools; NOT declared in uat.json, never imported
    fetch_upstream.sh
    render_*.py
  runs/<run-id>/         generated
```

Anything not listed in `uat.json` is invisible to Drydock. `tools/` is deliberately outside the
bundle: it runs on your machine, not in the build.

## 9. `uat.json`

```json
{
  "target": "jq",
  "expect": { "verdict": "PASSED" },
  "sources": [
    "sources/INSTRUCTIONS.md",
    "sources/jq-manual.txt",
    "sources/jq.test",
    "sources/exclusions.txt",
    "sources/run_conformance.py",
    "sources/full_test.sh"
  ],
  "updates": [],
  "sea_trials": "inputs/SEA_TRIALS.md",
  "technology_stack": "inputs/TECHNOLOGY_STACK.md",
  "test_command": ["sh", "sources/full_test.sh"],
  "acceptance": { "full": ["sh", "sources/full_test.sh"] }
}
```

| Field | Required | Meaning |
|---|---|---|
| `target` | no | Target name created by `init`; defaults to the directory name |
| `expect.verdict` | no | Expected outcome, e.g. `PASSED` |
| `sources` | **yes** | Non-empty list of kit-relative file paths. Must exist, must be inside the kit, basenames must be unique after flattening (R1) |
| `updates` | no | Files applied mid-run to drive `import --update` → `refit --sources` → incremental build, once each, in order; each basename must match a source (R9) |
| `sea_trials` | no | Kit-local Sea Trials, seeded after `init` and before `analyze` (R8) |
| `technology_stack` | no | Kit-local technology stack, seeded at the same point (R8) |
| `test_command` | **yes** | Non-empty argv, run from the completed application root after the build. Defaults to `acceptance.full`; state it only when the two must differ. A nonzero exit fails the kit |
| `acceptance.full` | no | The governed full gate, always `["sh", "sources/full_test.sh"]`. Valid on its own — `stages` is not required |
| `acceptance.stages` | no | Per-story gates, keyed by story id. Only declare these if the suite has a partition worth using |

Paths are relative to the kit directory. All fields are validated at discovery, so a bad kit fails in
a second rather than in an hour.

Both lifecycle inputs are explicit. Root-level magic filenames are ignored. When either key is
omitted, `analyze` creates that artifact inside the run Target.

Every non-Markdown source is an artifact for the build to use — a test harness, a fixture corpus, a
tool — and is staged verbatim into the build directory's `sources/`. Markdown is specification prose
and becomes Blueprint input instead.

## 10. Upstream acquisition — `tools/fetch_upstream.sh`

Pin a **release tag**, never a branch. Fetch from
`https://raw.githubusercontent.com/<owner>/<repo>/<tag>/<path>`.

The script must:

1. Declare `TAG=` at the top as the single point of change.
2. Fetch each file to its destination, failing hard on a non-200.
3. Write `PROVENANCE.md` with the tag, the upstream path, the destination, and a SHA-256 per file.
4. Support `--verify`, which re-hashes what is on disk against `PROVENANCE.md` and fetches nothing.

Corpus files are **never** hand-edited. Drift is expressed only through `exclusions.txt`.

If the specification is not already plain prose — a YAML manual, reStructuredText, a docs tree —
write a deterministic renderer in `tools/` that produces the `.txt`, and give it a `--check` mode that
fails when the output is stale. Drop pure CLI-surface sections (invocation flags, colour options,
packaging) — the kit's interface contract is fixed by `INSTRUCTIONS.md`, not by upstream's option
surface.

## 11. The scoring instrument

Two files: `sources/run_conformance.*` does the work, `sources/full_test.sh` is the entry point.

**Never let the implementation grade itself.** Many projects ship a self-test mode. Using it means
the model can pass by satisfying its own harness. Re-implement the corpus protocol externally and
drive the candidate as a subprocess.

The instrument must be **language-neutral**: it takes the candidate command from an environment
variable, and knows nothing about how the candidate is implemented.

### 11.1 Every kit stages `sources/full_test.sh`

One file, one name, in every kit. It is the single scoring entry point, and it is *supplied, not
authored*: it ships in the kit, is declared in `sources`, is staged verbatim into the build directory,
and is hash-verified and restored before grading — so a build that edits it is reported as tampering
rather than obeyed.

Declare it, and nothing else:

```json
"acceptance": { "full": ["sh", "sources/full_test.sh"] }
```

**Why this is mandatory.** Without a governed gate, `score release` has no oracle and falls back to
the grader's judgement. A criterion the grader cannot settle is `MANUAL`, and `MANUAL` never blocks —
so a project that built a quarter of its stories grades `PASSED`. That is not hypothetical: it is
what the CommonMark kit did before it had one.

The rule holds even when the *product* owns its tests. ReadingList's source prose makes "the
application provides a POSIX-compatible `bin/test.sh`" a requirement, so its harness is a three-line
dispatcher — but it is still Commander-owned, so an undelivered suite is a reported failure instead
of a missing gate.

The template:

```sh
#!/bin/sh
# full_test.sh — scoring entry point. Do not filter, skip, or reinterpret.
set -eu
if [ ! -x ./<binary> ]; then
    echo "error: no executable ./<binary> at the application root." >&2
    exit 1
fi
CANDIDATE="$PWD/<binary>" exec python3 sources/run_conformance.py
```

### 11.2 The harness exit-status standard

The harness's exit status is the verdict. Drydock reads it through
`acceptance_contract.run_gate`, which sorts it into three fault domains. A harness that does not
follow this table hands the wrong domain to the release gate.

| Status | Verdict | Meaning | Charged against |
|---|---|---|---|
| `0` | `PASS` | The product met the criterion. | — |
| `2` | `ERROR` | The harness could not run: a missing tool, an unset variable, a version mismatch. | The kit, never the build |
| any other nonzero | `FAIL` | The harness ran and the product failed. | The build |

Beyond the status itself, Drydock also classifies as `ERROR`: an executable that is not found, a
timeout at `GATE_TIMEOUT_SECONDS` (1800s), a signal, and a permission refusal. Unbounded output is
`FAIL`, not `ERROR` — a product that will not stop talking has failed, and calling that a kit fault
would excuse it.

Three consequences to write into every harness:

**Reserve `2` for the harness's own preconditions.** A missing conformance binary, an unset
`DECODER`, an installed suite of the wrong version — these say nothing about the product, so they
must not be charged to it. Do not use `127`: the shell's own "command not found" status reads as
`FAIL` and blames the build for a tool the kit failed to install.

**A missing deliverable is `1`, not `2`.** If the entry point the harness invokes is the thing the
build was asked to produce, its absence is a product failure. `./commonmark` and `bin/test.sh` are
deliverables; `toml-test` is not.

**Never `exec` a runner that exits with a failure count.** POSIX exit statuses are eight bits, so the
OS reports `n & 0xFF`:

```
exit(654) -> 142    nonzero, fine
exit(256) -> 0      "pass"
```

A runner ending in `exit(failed + errored)` — which is exactly what CommonMark's `spec_tests.py`
does — therefore reports success on exactly 256 or 512 failures. Both are reachable in a 655-example
suite: a parser failing 256 examples would have scored a clean pass. Capture the runner instead, and
require the status and the reported tally to agree:

```sh
set +e
output=$(python3 sources/spec_tests.py --program "$PWD/commonmark" --spec sources/spec.txt 2>&1)
status=$?
set -e
printf '%s\n' "$output"
[ "$status" -ne 0 ] && exit 1
printf '%s\n' "$output" | grep -q '0 failed, 0 errored, 0 skipped' || exit 1
```

The harness parsing its own instrument is fine — it *is* the instrument. The acceptance check above
it still asserts nothing but `full_test.sh`'s exit code.

A runner that already returns a boolean needs no guard. jq's `run_conformance.py` ends with
`return 0 if tally[FAIL] == 0 and tally[ERROR] == 0 else 1`, and Toml execs `toml-test`, which exits
`1` rather than a count.

### 11.3 Separate "could not run" from "ran and failed"

Check the deliverable's entry point before invoking the suite, and fail with a diagnostic naming what
was expected:

```sh
if [ ! -x ./commonmark ]; then
    echo "error: no executable ./commonmark at the application root." >&2
    echo "The deliverable is an executable named commonmark that reads UTF-8 Markdown on stdin" >&2
    echo "and writes HTML to stdout." >&2
    exit 1
fi
```

Two failures that look alike in a tally are different verdicts in the record. The interface
precondition is a distinct step from the conformance run on purpose: a missing deliverable and a
genuine conformance failure must be distinguishable in the evidence.

### 11.4 Run the suite unfiltered

No `--pattern`, no `--number`, no selector, no skip list. A tally reading `10 passed, 1 failed, 644
skipped` measures almost nothing, which is why `0 skipped` is worth asserting alongside `0 failed`.
Scoped per-story checks belong in `acceptance.stages`, never in `full_test.sh`.

### 11.5 `run_conformance.*` contract

| Aspect | Requirement |
|---|---|
| Candidate | From `$CANDIDATE`/`$JQ`/equivalent or `--<flag>`; unset is exit 2 |
| Comparison | **Structural, not textual.** Parse both sides and compare values, so formatting is not under test |
| Timeout | Per case, default 10 s; a timeout is `errored`, not `failed` |
| Verdict | Exit 0 iff `failed == 0 and errored == 0` |
| Kit faults | Exit 2 — missing corpus, unset candidate, stale exclusion (R4) |
| Summary | One last line: `<name>: NNN passed, N failed, N errored, N skipped (corpus <file> @ <tag>)` |
| Flags | `--json`, `-v`, `--list`, `--select REGEX`, `--timeout` |

`--select` is a development convenience and must never be wired to an acceptance gate.

**Adopt the upstream project's exit-code semantics** if it has any, and state them in
`INSTRUCTIONS.md` as the interface contract. Distinguishing "did not compile" from "compiled then
raised" is usually necessary to grade a suite correctly.

**Do not use language-provided line splitting on corpus text.** Python's `str.splitlines()` is
Unicode-aware and breaks on U+000B, U+000C, U+0085, U+2028, and U+2029 — characters that appear
inside string literals in real conformance suites, where they shred one expected value into several
and fail a correct implementation. Split on `\n` only.

## 12. `sources/exclusions.txt`

Cases the kit physically cannot run. Format: a `#` reason line per group, then the verbatim key lines
that identify the cases.

Rules:

- The corpus is never edited. Exclusion is the only mechanism.
- Every exclusion carries a written reason.
- **An exclusion matching zero cases is exit 2.** This is the drift alarm; without it, a corpus bump
  silently shrinks the exam.
- Exclude the narrowest thing that works. If loader cases need a directory tree (R1) but *grammar*
  cases for the same feature are pure parse errors, exclude the loader cases and keep the grammar
  cases in the scored set.
- Do not exclude anything merely because it looks hard. Difficulty is the point.

## 13. `sources/INSTRUCTIONS.md`

The build brief. The build agent reads this prose and will otherwise write its own scorer. Required
sections, in order:

1. **Objective** — what to build, from which file, measured by which corpus. State that the suite's
   size is a property of the pinned corpus and that no case count may ever be asserted.
2. **Run Harness** — `full_test.sh` reproduced verbatim, plus: run `ls sources/` and correct the
   paths against what is actually on disk; correcting a path is the *only* permitted edit; no added
   flags, filters, skips, or exit-code redirection.
3. **Read-only scoring assets** — name them and state the hash-verification rule (R5): that
   `sources/full_test.sh` is supplied, read-only, hash-verified, and that changing it is not a
   repair.
4. **Interface contract** — the deliverable's name and location by exact path (`an executable named
   commonmark at the application root`), how it is invoked, stdin/stdout shape, and an exit-code
   table.
5. **Test / verification process** — the exact commands, and what the summary line looks like. State
   that exactly one terminal story runs `sh sources/full_test.sh`, asserts only
   `result.returncode == 0`, prints stdout and stderr for diagnosis, and carries the Sea Trial; that
   no other check may invoke it; and that file-presence checks are not acceptance.
6. **The corpus format** — how cases are delimited and what comparison is applied.
7. **Declared exclusions** — which cases are skipped and why; and explicitly which adjacent-looking
   cases are **not** excluded and must pass.
8. **Source Roles** — the table `analyze` must record (R3):

   | Source | Role | Plan disposition | Build disposition |
   |---|---|---|---|
   | `<spec>.txt` | normative specification | context | stage |
   | `<suite>` | conformance test suite | context | stage |
   | `run_conformance.py` | conformance harness | context | stage |
   | `INSTRUCTIONS.md` | author intent | context | prompt-only |

9. **Suggested implementation order** — where the difficulty actually is. Name the architectural
   decision that must be made before any feature work, because a wrong one stalls the build
   permanently.
10. **Definition of Done** — the gate exits zero; **assert `returncode == 0` and nothing about the
    printed tally**, because a check that reads the runner's output measures the runner; no
    acceptance check that merely asserts a staged file exists; **every third-party implementation or
    binding of the target is forbidden by name**, as is shelling out to a system copy of it; the
    dependency policy; no network at test time; deliver a project `README.md`.

Item 10's forbidden-implementations clause is not optional. A wrapper around the real thing scores
perfectly and makes the exercise meaningless.

## 14. `inputs/TECHNOLOGY_STACK.md`

```markdown
# Technology Stack

**Approved:** <date>

| Technology | Rigging | Notes |
|---|---|---|
| Python | python.md | Python 3.11 or newer. Standard library only. |
| Shell | common.md | POSIX sh for the supplied scoring entry point. |
```

The Rigging column must name a real file in `Rigging/stack/`, or be `—`. Discovery validates this.
Run `ls Rigging/stack/` to see the catalogue.

## 15. `inputs/SEA_TRIALS.md`

The `## Policy` table must list all three consequences — `blocks`, `scores`, `attests` — even when
only one is used. Keep `st-001` naming the same command as `acceptance.full`, character for
character.

```markdown
# Sea Trials: <Kit>

## Policy

| Consequence | On FAIL | On INCONCLUSIVE |
|---|---|---|
| blocks  | fail   | attest |
| scores  | score  | score  |
| attests | report | report |

## st-001: The supplied scoring script passes
Type: technical
Required: yes
Criterion: The completed implementation shall make sh sources/full_test.sh exit zero; that script's exit status is the sole acceptance verdict.
Testability: deterministic
Consequence: blocks
Verification: proof
Pattern: ubiquitous
```

Field vocabularies: `Type` ∈ technical | behavioral | qualitative | outcome | guardrail;
`Verification` ∈ proof | measurement | evidence | llm; `Consequence` ∈ blocks | scores | attests.

One trial is usually right for a conformance kit. The gate is the exam; extra trials add LLM-judged
noise on top of a deterministic measurement.

## 16. Should the kit have stage gates?

Only if the corpus has a partition worth using. **Measure before deciding** — count cases per section
and look at the distribution. If two sections own half the suite, there is no partition and inventing
one removes the property the kit exists to measure. Declare `acceptance.full` alone and say in the
README that the absence of stages is deliberate.

## 17. Calibration — the step that makes the kit real

**Do not ship a kit until the scoring instrument scores the real implementation perfectly.**
Everything else is authoring; this is the part that can be wrong.

1. **Positive.** Obtain the pinned upstream release — prefer an official static binary, so no
   toolchain is needed — and run the instrument against it.
   **Required result: `0 failed, 0 errored`, exit 0.** Any failure is a defect in your instrument or
   a missing exclusion. Never in upstream.
2. **Negative.** Run an *older* release of the same project. It must score visibly worse and exit
   non-zero. This proves the instrument produces a gradient rather than a binary, and that the suite
   actually discriminates.
3. **Drift alarm.** Add a bogus line to `exclusions.txt`; confirm exit 2 with a "matched no case"
   message; revert.
4. **Fault handling.** Unset the candidate variable; confirm exit 2, not a false pass.
5. **End to end.** In a scratch directory, copy the sources **flattened by basename** (R1), drop in
   the real implementation as the expected deliverable name, and run `sh sources/full_test.sh`.
   Confirm exit 0. Remove the deliverable; confirm the interface error and exit 1.

Expect calibration to find real defects in your instrument. That is what it is for. Record the
results in `README.md` and `NEXT_STEPS.md` so a later reader can reproduce them.

## 18. Verification

```bash
python -m pytest tests/test_uat.py::test_shipped_kits_declare_every_asset_their_score_command_runs -p no:randomly
python -c "from pathlib import Path; from drydock.uat import discover_fixtures; print(discover_fixtures(Path('uat'), '<Kit>'))"
ruff check uat/<Kit>/
```

Always pass `-p no:randomly` to pytest in this repository; without it the suite takes twenty minutes
instead of fifteen seconds.

The `discover_fixtures` call is the cheap authoring check — it exercises source existence and
containment, basename collision, the Sea Trials parse, and the Rigging-name validation in one shot.

## 19. The interactive authoring run

For a new kit, run it by hand first — you want to inspect the Blueprint after `analyze`, read the
QuarterDeck, and choose the stack yourself. Use `helpers/<kit>.sh`, a copy of `helpers/template.sh`
with a `read` between every stage, plus `helpers/Import_<Kit>.sh` for the imports. See
`helpers/jq.sh` and `helpers/Import_jq.sh` for a worked example.

The interactive path does **not** seed the lifecycle inputs for you. `drydock uat` does that; you must
do it yourself after `drydock init`:

```bash
cp uat/<Kit>/inputs/TECHNOLOGY_STACK.md targets/<Kit>/
cp uat/<Kit>/inputs/SEA_TRIALS.md        targets/<Kit>/
# ACCEPTANCE.json is written from uat.json's acceptance block — no LLM can author it (R8)
```

Both land at `targets/<Kit>/`, not in `blueprint/`.

Import the bundle as a **directory**, exactly as `drydock uat` does — one call, one analysis pass:

```bash
drydock import <Kit> uat/<Kit>/sources --format markdown $OPTS
```

Per-file imports also work and let you stage the bundle in phases, at the cost of one LLM call each.

## 20. Authoring checklist

- [ ] Upstream pinned to a release tag; `PROVENANCE.md` written; `--verify` passes
- [ ] Specification ships as `.txt`, not `.md` (R2)
- [ ] All `sources/` basenames unique (R1)
- [ ] `INSTRUCTIONS.md` contains the Source Roles table with `stage` on every readable asset (R3)
- [ ] `INSTRUCTIONS.md` forbids third-party implementations **by name**
- [ ] `INSTRUCTIONS.md` marks the harness supplied and read-only (R5)
- [ ] `sources/full_test.sh` exists and is listed in `sources`
- [ ] `acceptance.full` is `["sh", "sources/full_test.sh"]`
- [ ] Exactly one story runs the full suite, asserting only the exit code, never the tally
- [ ] Entry-point check is a distinct step before the suite runs
- [ ] Exit `2` for harness preconditions, `1` for a missing deliverable, never `127` (R4)
- [ ] Harness cannot return `0` on a truncated failure count
- [ ] Suite runs with no selector and reports `0 skipped`
- [ ] Scoring instrument is external to the implementation and language-neutral
- [ ] Line splitting is `\n`-only
- [ ] Exclusions carry reasons; a stale exclusion is exit 2
- [ ] Stage gates declared only if the corpus was measured and has a real partition
- [ ] Positive calibration: 0 failed, 0 errored, exit 0
- [ ] Negative calibration: an older release scores worse and exits non-zero
- [ ] `sh -n sources/full_test.sh` parses — enforced by `tests/test_uat.py`
- [ ] `discover_fixtures` clean; `test_shipped_kits_declare_every_asset_their_score_command_runs`
      passes; `ruff check uat/<Kit>/` clean
- [ ] `README.md` records the calibration table and the reproduction command
- [ ] `helpers/<kit>.sh` and `helpers/Import_<Kit>.sh` written for the interactive path

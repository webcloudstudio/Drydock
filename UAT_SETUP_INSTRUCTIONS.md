# UAT Kit Setup Instructions

How to build a Drydock UAT kit from an upstream repository, without reading `src/drydock/`.

Everything an author needs to know about Drydock's plumbing is stated here as a rule. Follow the
rules; do not re-derive them from the source. If a rule turns out to be wrong, fix this file — do
not go back to reading the package.

**Typical instruction to an assistant:** "Follow `UAT_SETUP_INSTRUCTIONS.md`. Build a kit for
`<owner>/<repo>` at tag `<tag>`. The specification is `<path>`, the conformance suite is `<path>`,
the implementation language is `<lang>`."

---

## 1. What a kit is

A kit is one known open-source project that Drydock rebuilds from its own published specification,
graded against that project's own conformance suite. The kit supplies the specification, the
suite, an external scoring instrument, and the lifecycle decisions. Drydock supplies the
implementation. The score is the fraction of the suite that passes.

A kit lives at `uat/<Kit>/` and is discovered by the presence of `uat.json`. `uat/` is gitignored
in the Drydock repository — each kit is its own repository, or untracked.

---

## 2. The rules you must not re-derive

These are the non-obvious facts about how Drydock treats a kit. Every one of them has changed a
kit's design at least once.

### R1 — Sources are flattened by basename

Declared sources are copied into the run's `sources/` **flattened**: `sources/a/b/x.txt` arrives as
`sources/x.txt`. Nested directory structure cannot be carried. Duplicate basenames are a hard
discovery error.

*Consequence:* any suite case that needs a directory tree of fixture files (module search paths,
include paths, multi-file inputs) cannot run. Exclude it explicitly — see §7.

### R2 — Build prompts receive no imported source content

The full source bundle reaches `analyze` and `plan` and stops there. A build story's prompt gets
**none** of it as text. Markdown sources are not promoted into the Blueprint, and staged
non-Markdown assets appear to the builder only as *file names* on disk.

*Consequence:* **the normative specification must not ship as `.md`.** Ship it as `.txt`. A `.txt`
source is injected as prose at `analyze`/`plan` *and* staged onto disk where a build story can open
it. A `.md` specification survives into the build only as whatever `analyze` paraphrased.

Rename or render upstream Markdown to `.txt`. Keep `INSTRUCTIONS.md` as `.md` — it is author
intent, meant for the analysis, not for re-reading during the build.

### R3 — Staging is opt-in and LLM-authored

Whether a source is written to disk in the build directory is decided by a `## Source Roles` table
that the **model** writes during `analyze`. An unsteered `analyze` stages nothing.

*Consequence:* `INSTRUCTIONS.md` must contain an explicit Source Roles table telling `analyze` what
to record, with `stage` as the build disposition for every file the builder must read or run. This
is load-bearing. Omit it and the builder has a specification it cannot open.

### R4 — Exit code 2 is a kit fault

An acceptance gate that exits `2` is treated as a fault in the kit, not a failure of the build, and
is never charged against the score. Reserve `2` in your scoring instrument for its own errors: a
missing corpus, an unset environment variable, a stale exclusion. Gates time out at 1800 seconds.

### R5 — Scoring assets are hash-verified

Files staged into the build directory are recorded by SHA-256 at import and restored before
grading. A model that edits the scoring script is reported as tampering rather than obeyed. Say so
in `INSTRUCTIONS.md`; it saves a wasted repair pass.

### R6 — There is no per-story source selection

A build story's `context:` resolves against the Blueprint, never against `sources/`. You cannot
give story 4 chapter 4 of the manual. The specification ships whole or not at all. Budget for it:
the whole bundle is re-injected at `analyze` and at each `plan` batch.

### R7 — Prose is chunked, never dropped

A prose source over 48,000 characters is split into 12,000-character chunks and all chunks are
injected. Nothing is silently truncated. Large is expensive, not lossy.

### R8 — Seeded lifecycle files are never overwritten

`analyze` will not overwrite an existing `TECHNOLOGY_STACK.md` or `SEA_TRIALS.md`. Seeding them
before `analyze` makes the kit's decisions the decisions of record. `ACCEPTANCE.json` is not a
Blueprint artifact at all — no LLM command can write it, which is what makes it the exam.

### R9 — `updates` must match an imported basename

Every entry in `uat.json`'s `updates` list must share a basename with a declared source; it
replaces that file mid-run to exercise `refit`. An update naming a file that was never imported is
a discovery error.

---

## 3. Directory layout

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

---

## 4. `uat.json`

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
| `target` | no | Target name; defaults to the directory name |
| `expect.verdict` | no | Expected outcome, e.g. `PASSED` |
| `sources` | **yes** | Non-empty list of kit-relative file paths. Must exist, must be inside the kit, basenames must be unique after flattening (R1) |
| `updates` | no | Files applied mid-run to exercise `refit`; each basename must match a source (R9) |
| `sea_trials` | no | Seeded before `analyze` (R8) |
| `technology_stack` | no | Seeded before `analyze` (R8) |
| `test_command` | **yes** | Non-empty argv, run from the application root |
| `acceptance.full` | no | The governed full gate. Valid on its own — `stages` is not required |
| `acceptance.stages` | no | Per-stage gates. Only declare these if the suite has a partition worth using |

Paths are relative to the kit directory. All fields are validated at discovery, so a bad kit fails
in a second rather than in an hour.

---

## 5. Upstream acquisition — `tools/fetch_upstream.sh`

Pin a **release tag**, never a branch. Fetch from
`https://raw.githubusercontent.com/<owner>/<repo>/<tag>/<path>`.

The script must:

1. Declare `TAG=` at the top as the single point of change.
2. Fetch each file to its destination, failing hard on a non-200.
3. Write `PROVENANCE.md` with the tag, the upstream path, the destination, and a SHA-256 per file.
4. Support `--verify`, which re-hashes what is on disk against `PROVENANCE.md` and fetches nothing.

Corpus files are **never** hand-edited. Drift is expressed only through `exclusions.txt`.

If the specification is not already plain prose — a YAML manual, reStructuredText, a docs tree —
write a deterministic renderer in `tools/` that produces the `.txt`, and give it a `--check` mode
that fails when the output is stale. Drop pure CLI-surface sections (invocation flags, colour
options, packaging) — the kit's interface contract is fixed by `INSTRUCTIONS.md`, not by upstream's
option surface.

---

## 6. The scoring instrument

Two files: `sources/run_conformance.*` does the work, `sources/full_test.sh` is the entry point.

**Never let the implementation grade itself.** Many projects ship a self-test mode. Using it means
the model can pass by satisfying its own harness. Re-implement the corpus protocol externally and
drive the candidate as a subprocess.

The instrument must be **language-neutral**: it takes the candidate command from an environment
variable, and knows nothing about how the candidate is implemented.

### `full_test.sh`

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

The interface precondition is separate from the conformance run on purpose: a missing deliverable
and a genuine conformance failure must be distinguishable in the evidence.

### `run_conformance.*` contract

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
inside string literals in real conformance suites, where they shred one expected value into
several and fail a correct implementation. Split on `\n` only.

---

## 7. `sources/exclusions.txt`

Cases the kit physically cannot run. Format: a `#` reason line per group, then the verbatim key
lines that identify the cases.

Rules:

- The corpus is never edited. Exclusion is the only mechanism.
- Every exclusion carries a written reason.
- **An exclusion matching zero cases is exit 2.** This is the drift alarm; without it, a corpus
  bump silently shrinks the exam.
- Exclude the narrowest thing that works. If loader cases need a directory tree (R1) but *grammar*
  cases for the same feature are pure parse errors, exclude the loader cases and keep the grammar
  cases in the scored set.
- Do not exclude anything merely because it looks hard. Difficulty is the point.

---

## 8. `sources/INSTRUCTIONS.md`

The build brief. Required sections, in order:

1. **Objective** — what to build, from which file, measured by which corpus. State that the
   suite's size is a property of the pinned corpus and that no case count may ever be asserted.
2. **Run Harness** — `full_test.sh` reproduced verbatim, plus: run `ls sources/` and correct the
   paths against what is actually on disk; correcting a path is the *only* permitted edit; no
   added flags, filters, skips, or exit-code redirection.
3. **Read-only scoring assets** — name them and state the hash-verification rule (R5).
4. **Interface contract** — the deliverable's name and location, how it is invoked, stdin/stdout
   shape, and an exit-code table.
5. **Test / verification process** — the exact commands, and what the summary line looks like.
6. **The corpus format** — how cases are delimited and what comparison is applied.
7. **Declared exclusions** — which cases are skipped and why; and explicitly which
   adjacent-looking cases are **not** excluded and must pass.
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
    acceptance check that merely asserts a staged file exists; **every third-party implementation
    or binding of the target is forbidden by name**, as is shelling out to a system copy of it; the
    dependency policy; no network at test time; deliver a project `README.md`.

Item 10's forbidden-implementations clause is not optional. A wrapper around the real thing scores
perfectly and makes the exercise meaningless.

---

## 9. `inputs/TECHNOLOGY_STACK.md`

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

## 10. `inputs/SEA_TRIALS.md`

The `## Policy` table must list all three consequences — `blocks`, `scores`, `attests` — even when
only one is used.

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

One trial is usually right for a conformance kit. The gate is the exam; extra trials add
LLM-judged noise on top of a deterministic measurement.

---

## 11. Should the kit have stage gates?

Only if the corpus has a partition worth using. **Measure before deciding** — count cases per
section and look at the distribution. If two sections own half the suite, there is no partition and
inventing one removes the property the kit exists to measure. Declare `acceptance.full` alone and
say in the README that the absence of stages is deliberate.

---

## 12. Calibration — the step that makes the kit real

**Do not ship a kit until the scoring instrument scores the real implementation perfectly.**
Everything else is authoring; this is the part that can be wrong.

1. **Positive.** Obtain the pinned upstream release — prefer an official static binary, so no
   toolchain is needed — and run the instrument against it.
   **Required result: `0 failed, 0 errored`, exit 0.** Any failure is a defect in your instrument
   or a missing exclusion. Never in upstream.
2. **Negative.** Run an *older* release of the same project. It must score visibly worse and exit
   non-zero. This proves the instrument produces a gradient rather than a binary, and that the
   suite actually discriminates.
3. **Drift alarm.** Add a bogus line to `exclusions.txt`; confirm exit 2 with a "matched no case"
   message; revert.
4. **Fault handling.** Unset the candidate variable; confirm exit 2, not a false pass.
5. **End to end.** In a scratch directory, copy the sources **flattened by basename** (R1), drop in
   the real implementation as the expected deliverable name, and run `sh sources/full_test.sh`.
   Confirm exit 0. Remove the deliverable; confirm the interface error and exit 1.

Expect calibration to find real defects in your instrument. That is what it is for. Record the
results in `README.md` and `NEXT_STEPS.md` so a later reader can reproduce them.

---

## 13. Verification

```bash
python -m pytest tests/test_uat.py::test_shipped_kits_declare_every_asset_their_score_command_runs -p no:randomly
python -c "from pathlib import Path; from drydock.uat import discover_fixtures; print(discover_fixtures(Path('uat'), '<Kit>'))"
ruff check uat/<Kit>/
```

Always pass `-p no:randomly` to pytest in this repository; without it the suite takes twenty
minutes instead of fifteen seconds.

The `discover_fixtures` call is the cheap authoring check — it exercises source existence and
containment, basename collision, the Sea Trials parse, and the Rigging-name validation in one shot.

---

## 14. Running the kit

### Unattended

```bash
drydock uat <Kit>                  # one kit
drydock uat                        # every kit under uat/
drydock uat --report <Kit>         # rebuild proof kits from completed runs
```

Flags: `--uat-root <path>`, `--max-build-passes <n>`, `--llm-provider`, `--model`, `--effort`.

### Interactive, one stage at a time

For a new kit, run it by hand first — you want to inspect the Blueprint after `analyze`, read the
QuarterDeck, and choose the stack yourself. Use `helpers/<kit>.sh`, a copy of
`helpers/template.sh` with a `read` between every stage, plus `helpers/Import_<Kit>.sh` for the
imports. See `helpers/jq.sh` and `helpers/Import_jq.sh` for a worked example.

The interactive path does **not** seed the lifecycle inputs for you. `drydock uat` does that; you
must do it yourself after `drydock init`:

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

Per-file imports also work and let you stage the bundle in phases, at the cost of one LLM call
each.

---

## 15. Authoring checklist

- [ ] Upstream pinned to a release tag; `PROVENANCE.md` written; `--verify` passes
- [ ] Specification ships as `.txt`, not `.md` (R2)
- [ ] All `sources/` basenames unique (R1)
- [ ] `INSTRUCTIONS.md` contains the Source Roles table with `stage` on every readable asset (R3)
- [ ] `INSTRUCTIONS.md` forbids third-party implementations **by name**
- [ ] Definition of Done asserts the exit code only, never the tally
- [ ] Scoring instrument is external to the implementation and language-neutral
- [ ] Instrument reserves exit 2 for its own faults (R4)
- [ ] Line splitting is `\n`-only
- [ ] Exclusions carry reasons; a stale exclusion is exit 2
- [ ] Stage gates declared only if the corpus was measured and has a real partition
- [ ] Positive calibration: 0 failed, 0 errored, exit 0
- [ ] Negative calibration: an older release scores worse and exits non-zero
- [ ] `discover_fixtures` clean; `test_shipped_kits_declare_every_asset_their_score_command_runs`
      passes; `ruff check uat/<Kit>/` clean
- [ ] `README.md` records the calibration table and the reproduction command
- [ ] `helpers/<kit>.sh` and `helpers/Import_<Kit>.sh` written for the interactive path

# UAT Kits

`drydock uat <kits>` runs encapsulated. It does not write to the ordinary output directory or
logs; every artifact lands under `uat/<Kit>/`. Because `uat/` is ignored by the Drydock
repository and each kit is published as its own repository, this file is the tracked home for
how kits are defined, authored, run, and read.

## Layout

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

Each kit has an `index.html` project page for navigation. It carries the latest verdict, one row
per recorded run linking that run's own `index.html`, the governed documents at the kit root, and
the `inputs/`, `sources/`, and `updates/` bundles the runs were built from. It is written at the
end of every run and rebuilt in full by `drydock uat --report`.

Every linked text artifact — Markdown, logs, transcripts, delivered source — is reached through a
generated viewer under `view/`, which carries the report's own styling: Markdown is rendered, and
anything else is shown as source. Each viewer links the raw file, and `SHA256SUMS` covers the raw
files, never the viewers. `view/` and `assets/` are generated output, rewritten on every rebuild.

## Running

```bash
drydock uat                      # every kit under uat/
drydock uat Toml                 # one kit
drydock uat --report             # rebuild proof kits from completed runs
drydock uat --report Toml        # rebuild one kit's proof kits
```

| Flag | Effect |
|---|---|
| `--uat-root <path>` | Directory holding the kits (default `<workspace>/uat`) |
| `--max-build-passes <n>` | Repair passes allowed per build before the kit fails |
| `--llm-provider`, `--model`, `--effort` | Provider and model selection for the whole run |

A run is long and consumes subscription quota. The `Toml` kit takes roughly thirty minutes and
eighteen LLM calls.

## Kit definition

`uat.json` declares:

- `target` — the Target name created by `init`.
- `sources` — kit-local files imported before the initial lifecycle. Required and nonempty. Paths
  are relative to the kit root; the bundle is flattened to `sources/<basename>` in the build, so
  basenames must be unique.
- `updates` — files that replace an imported basename to drive
  `import --update` → `refit --sources` → incremental build, once each, in order.
- `sea_trials` — optional kit-local Sea Trials path, seeded after `init` and before `analyze`.
- `technology_stack` — optional kit-local technology-stack path, seeded at the same point. Named
  Rigging files are validated against the catalog during discovery.
- `acceptance.full` — **required.** The governed scoring entry point, always
  `["sh", "sources/full_test.sh"]`. Discovery rejects a kit without it.
- `acceptance.stages` — optional per-story gates, keyed by story id.
- `test_command` — argv run from the completed application root after the build. Defaults to
  `acceptance.full`; state it only when the two must differ. A nonzero exit fails the kit.

Both lifecycle inputs are explicit. Root-level magic filenames are ignored. When either key is
omitted, `analyze` creates that artifact inside the run Target.

Every non-Markdown source is an artifact for the build to use — a test harness, a fixture corpus,
a tool — and is staged verbatim into the build directory's `sources/`. Markdown is specification
prose and becomes Blueprint input instead.

## Building a new kit

A kit is an exam. The build agent sits the exam; it must not also write it, mark it, or decide
when it is over. Every rule below keeps those roles apart.

### 1. Every kit stages `sources/full_test.sh`

One file, one name, in every kit. It is the single scoring entry point, and it is *supplied, not
authored*: it ships in the kit, is declared in `sources`, is staged verbatim into the build
directory, and is hash-verified and restored before grading — so a build that edits it is
reported as tampering rather than obeyed.

Declare it, and nothing else:

```json
"acceptance": { "full": ["sh", "sources/full_test.sh"] }
```

**Why this is mandatory.** Without a governed gate, `score release` has no oracle and falls back
to the grader's judgement. A criterion the grader cannot settle is `MANUAL`, and `MANUAL` never
blocks — so a project that built a quarter of its stories grades `PASSED`. That is not
hypothetical: it is what the CommonMark kit did before it had one.

The rule holds even when the *product* owns its tests. ReadingList's source prose makes "the
application provides a POSIX-compatible `bin/test.sh`" a requirement, so its harness is a
three-line dispatcher — but it is still Commander-owned, so an undelivered suite is a reported
failure instead of a missing gate.

### 2. The harness exit-status standard

The harness's exit status is the verdict. Drydock reads it through
`acceptance_contract.run_gate`, which sorts it into three fault domains. A harness that does not
follow this table hands the wrong domain to the release gate.

| Status | Verdict | Meaning | Charged against |
|---|---|---|---|
| `0` | `PASS` | The product met the criterion. | — |
| `2` | `ERROR` | The harness could not run: a missing tool, an unset variable, a version mismatch. | The kit, never the build |
| any other nonzero | `FAIL` | The harness ran and the product failed. | The build |

Beyond the status itself, Drydock also classifies as `ERROR`: an executable that is not found, a
timeout at `GATE_TIMEOUT_SECONDS` (1800s), a signal, and a permission refusal. Unbounded output
is `FAIL`, not `ERROR` — a product that will not stop talking has failed, and calling that a kit
fault would excuse it.

Three consequences to write into every harness:

**Reserve `2` for the harness's own preconditions.** A missing conformance binary, an unset
`DECODER`, an installed suite of the wrong version — these say nothing about the product, so they
must not be charged to it. Do not use `127`: the shell's own "command not found" status reads as
`FAIL` and blames the build for a tool the kit failed to install.

**A missing deliverable is `1`, not `2`.** If the entry point the harness invokes is the thing
the build was asked to produce, its absence is a product failure. `./commonmark` and `bin/test.sh`
are deliverables; `toml-test` is not.

**Never `exec` a runner that exits with a failure count.** POSIX exit statuses are eight bits, so
the OS reports `n & 0xFF`:

```
exit(654) -> 142    nonzero, fine
exit(256) -> 0      "pass"
```

A runner ending in `exit(failed + errored)` — which is exactly what CommonMark's `spec_tests.py`
does — therefore reports success on exactly 256 or 512 failures. Both are reachable in a
655-example suite: a parser failing 256 examples would have scored a clean pass. Capture the
runner instead, and require the status and the reported tally to agree:

```sh
set +e
output=$(python3 sources/spec_tests.py --program "$PWD/commonmark" --spec sources/spec.txt 2>&1)
status=$?
set -e
printf '%s\n' "$output"
[ "$status" -ne 0 ] && exit 1
printf '%s\n' "$output" | grep -q '0 failed, 0 errored, 0 skipped' || exit 1
```

The harness parsing its own instrument is fine — it *is* the instrument. The acceptance check
above it still asserts nothing but `full_test.sh`'s exit code.

A runner that already returns a boolean needs no guard. jq's `run_conformance.py` ends with
`return 0 if tally[FAIL] == 0 and tally[ERROR] == 0 else 1`, and Toml execs `toml-test`, which
exits `1` rather than a count.

### 3. Separate "could not run" from "ran and failed"

Check the deliverable's entry point before invoking the suite, and fail with a diagnostic naming
what was expected:

```sh
if [ ! -x ./commonmark ]; then
    echo "error: no executable ./commonmark at the application root." >&2
    echo "The deliverable is an executable named commonmark that reads UTF-8 Markdown on stdin" >&2
    echo "and writes HTML to stdout." >&2
    exit 1
fi
```

Two failures that look alike in a tally are different verdicts in the record. The check has to be
a distinct step for the evidence to distinguish them.

### 4. Run the suite unfiltered

No `--pattern`, no `--number`, no selector, no skip list. A tally reading `10 passed, 1 failed,
644 skipped` measures almost nothing, which is why `0 skipped` is worth asserting alongside
`0 failed`. Scoped per-story checks belong in `acceptance.stages`, never in `full_test.sh`.

### 5. State the harness contract in `INSTRUCTIONS.md`

The build agent reads this prose and will otherwise write its own scorer. Say plainly:

- what the deliverable is, by exact name and path (`an executable named commonmark at the
  application root`);
- that `sources/full_test.sh` is supplied, read-only, hash-verified, and that changing it is not
  a repair;
- that exactly one terminal story runs `sh sources/full_test.sh`, asserts only
  `result.returncode == 0`, prints stdout and stderr for diagnosis, and carries the Sea Trial;
- that no other check may invoke it, and that file-presence checks are not acceptance.

Keep `st-001` in `inputs/SEA_TRIALS.md` naming the same command, character for character.

### Checklist

| | |
|---|---|
| `sources/full_test.sh` exists and is listed in `sources` | required |
| `acceptance.full` is `["sh", "sources/full_test.sh"]` | required |
| Exit `2` for harness preconditions, `1` for a missing deliverable, never `127` | required |
| Harness cannot return `0` on a truncated failure count | required |
| Entry-point check is a distinct step before the suite runs | required |
| Suite runs with no selector and reports `0 skipped` | required |
| `INSTRUCTIONS.md` marks the harness supplied and read-only | required |
| Exactly one story runs the full suite, asserting only the exit code | required |
| `sh -n sources/full_test.sh` parses | enforced by `tests/test_uat.py` |

## Reading a run

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

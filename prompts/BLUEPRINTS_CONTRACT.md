---
name: Blueprints Contract
description: Contract governing the layout, file types, header format, and dependency conventions for Drydock Blueprint files.
version: 20260816 V15
---

## Overview

A **Blueprint** is the complete Typed Specification for one project. It lives at
`$DRYDOCK_WORKSPACE/targets/<Target>/blueprint/` and contains all human-authored and
process-created specification files. The Blueprint is the single source of truth for what the
project is, what it must do, and how it is built.

---

## Specification File Types

| File | Purpose | Required |
|------|---------|----------|
| `METADATA.md` | Project identity: name, display_name, short_description, status, stack, code_root | Yes |
| `COMPASS.md` | Project guidance: intent, constraints, and guardrails | Yes |
| `ARCHITECTURE.md` | Modules, routes, boundaries, interfaces, technical decisions | Yes |
| `README.md` | One-line description and `## Intent` section | Yes |
| `DATABASE.md` | Persistence contract: access patterns, typed interfaces, all stores, schemas, migrations | If has persistent state |
| `UI-GENERAL.md` | Shared UI patterns across screens | If has UI |
| `SCREEN-{Name}.md` | Per-screen: route, layout, interactions, programmatic and user acceptance | If has UI |
| `FEATURE-{Name}.md` | Per-feature: purpose, status, trigger, sequence, routes, reads, writes, acceptance, guardrails | As needed |
| `ARCHITECTURE_compact.md` | Compact architecture derivative for downstream build-step injection | Optional |
| `DATABASE_compact.md` | Compact persistence derivative for downstream build-step injection | Optional |
| `HOMEPAGE.md` | Portfolio homepage: branding, contact, bio | If publishes a portfolio |
| `HOMEPAGE-PUBLISHER.md` | Template-based homepage publishing configuration | If publishes a portfolio |
| `IDEAS.md` | Feature ideas and backlog — no typed header required | No |
| `*-AC.md` / `AC-*.md` / `*-AC-*.md` | Acceptance criteria — any file where `AC` is a whole word in the filename | As needed |
| `changes/TICKET-NNN-{Name}.md` | Post-baseline change, defect, or spike request | As needed |

Every authored Specification file ends with `## Programmatic Acceptance`, `## User Acceptance`,
and `## Guardrails`. Use `- None.` when no entries apply. Planning disclosures and Commander
responses are records in the target's `DECISIONS.json`.

`ARCHITECTURE_compact.md` is a compact derivative of `ARCHITECTURE.md` produced by
`drydock rigging compact`. Drydock uses filename-selected compaction algorithms rather than
phase-aware compact variants.

`DATABASE_compact.md` is a compact derivative of `DATABASE.md` produced by `drydock rigging compact`.

---

## Specification File Header Format

Every authored Specification file except `METADATA.md` and `README.md` must begin with a typed
header. Operational and generated files (`IDEAS.md`, build plans, analysis outputs, and AC files)
are not authored Specification files.

```markdown
# {FileType}: {ObjectName}

| Field       | Value |
|-------------|-------|
| Version     | YYYYMMDD V1 |
| Description | One sentence summary. |
| Depends On  | FEATURE-SERVICE-CATALOG.md, UI-GENERAL.md |
| Provides    | GET /welcome, GET /welcome/summary |
| Phase       | 2 |
```

**FileType values:** `COMPASS`, `SCREEN`, `FEATURE`, `DATABASE`, `UI-GENERAL`, `ARCHITECTURE`,
`HOMEPAGE`, `CHANGE`

**ObjectName:** Human-readable name matching the file subject (e.g., `Welcome Summary`,
`Service Catalog`).

**Fields:**

| Field | Set By | Required | Description |
|-------|--------|----------|-------------|
| `Version` | Author | Yes | Date + increment: `YYYYMMDD V1`. Every agent write must set this to the current date with the next increment. If the existing version is already today's date, increment the number. Never carry forward a stale date. |
| `Description` | Author | Yes | One sentence |
| `Depends On` | `drydock plan create` | No | Filenames this file requires to exist before build |
| `Provides` | `drydock plan create` | No | HTTP routes or interfaces this file exposes |
| `Phase` | `drydock plan create` | No | Build phase hint (integer); tooling may override |

**Additional optional fields for SCREEN files:**

| Field | Required | Description |
|-------|----------|-------------|
| `Route` | No | The URL this screen is served at |
| `Parent` | No | Parent menu item or `—` |
| `Main Menu` | No | Menu label and position |
| `Sub Menu` | No | Submenu label and position |
| `Tab Order` | No | Tab index within parent, or `—` |

`Depends On` and `Provides` are written by `drydock plan create` — do not edit manually.
`Phase` is written by `drydock plan create` — do not edit manually unless overriding.

**Additional required fields for CHANGE files (`changes/TICKET-NNN-{Name}.md`):**

| Field | Set By | Required | Description |
|-------|--------|----------|-------------|
| `Amends` | Author / `drydock refit` | Yes | The parent Blueprint spec this ticket modifies (e.g. `FEATURE-Copy.md`). `drydock refit` reads this field to resolve dependency inheritance and inject parent context. |
| `Depends On` | `drydock refit` | Yes | Copied from the parent spec's `Depends On` set plus the parent spec filename itself. Do not edit manually. |
| `Scope` | Author / `drydock refit --sources` | Yes | `additive` or `amending`. Governs what the ticket supersedes. |
| `Created` | `drydock refit` | Yes | ISO date the ticket was authored. |
| `Origin` | `drydock refit --sources` | No | The source version this ticket came from, as `<source>@<commit>`. Absent on hand-authored tickets. |
| `Stories` | `drydock refit --sources` | No | The Manifest story ids this ticket owns. When present, `drydock refit` emits exactly these ids and never invents new ones. |

**Scope semantics.** A ticket declares its authority over its parent in one sentence directly
below the header table.

- `additive` — the ticket adds behavior. It supersedes nothing, and every assertion in the parent
  Blueprint remains in force. Sentence: *"This ticket is additive. It supersedes nothing; every
  assertion in `<parent>` remains in force."*
- `amending` — the ticket alters behavior already specified. It supersedes only the sections
  listed under `## Amended Sections`, each of which must exist as a heading in the parent.
  Sentence: *"This ticket amends `<parent>`. It supersedes only the sections named under
  `## Amended Sections`; every other assertion in `<parent>` remains in force."*

An additive ticket must never claim authority over its whole parent: a single added requirement
would otherwise supersede assertions it does not mention and that have already been proven.

---

## Common Authored Specification Sections

Plan and Build disclosures use the existing `DECISIONS.json` schema. `severity: blocking` is the
only decision gate and blocks only the attached story while its Commander response is absent.
Analyze questionnaire answers are converted to `origin: analyze-questionnaire` records. Commander
responses remain in the same records across replans.

Every authored Specification file ends with these sections, using `- None.` when no entries apply:

```markdown
## Programmatic Acceptance

- None.

## User Acceptance

- None.

## Guardrails

- None.

```

`Programmatic Acceptance` contains executable Python assertion snippets. Each check is one
explicitly delimited block that can run from the build directory after the story implementing the
file completes:

```
=== AC {check-id} ===
Intent: One sentence stating what the check proves.
Suite: scoped
Requires: executable=python3; scope=test

<Python source, verbatim, to the end marker>
=== END AC {check-id} ===
```

The delimiters are the whole format. The id lives in the opening marker, so it is never inferred
from a nearby heading. Declarations are the `Key: value` lines at the top of the block, ending at
the first blank line; `Intent:` is required and the rest are optional. Everything after that blank
line is the proof body, taken character for character to the matching end marker.

Nothing inside the body can move a boundary. A Markdown fence, a `##` line, a `###` line, or a
`Requires:` line inside a string is ordinary content — which matters, because a target that
processes markup will legitimately embed all of them in its proof. Write the body as plain Python;
do not wrap it in a fence.

Write `=== END AC {check-id} ===` for every `=== AC {check-id} ===` you open, with the same id.
The end marker is not optional and the next opening marker does not stand in for it. Where the
boundary is decidable Drydock inserts the missing marker and reports having done so; where it is
not, planning stops.

An end marker naming a different id, a stray end marker, and a duplicate id are hard errors that
stop planning. None of them degrade into a criterion that silently stops gating.

A backslash in the proof body belongs in a raw string or is doubled. Write `r"\d+"`, `"\\("`, or
`r"\("` — never a bare `"\("`. A bare backslash before a character Python does not recognize as
an escape is not the escape you wrote: it survives today only by a rule scheduled to become a
hard error, and it costs the criterion its binding status. This applies to every proof that
embeds a regular expression, a Windows path, or a target language's own escape syntax.

### The oracle rule

> **Act on the system. Read the state back. Compare to expected.**

Arrange–Act–Assert, where the assertion reads *state*, never text a process printed.

| Oracle | Verdict |
|---|---|
| Return value, parsed JSON, status code, DB row, file contents read back, exit status | **Correct** |
| Substring of captured stdout/stderr, test-runner tally text, log lines | **Forbidden** |

A state oracle cannot pass against a stub and cannot fail because a runner printed the word
"warning". Almost every acceptance defect observed in practice has the same shape: the oracle was
a string in captured output.

### The expected value must be one you could not get wrong

Reading state back is half the rule. The other half is what you compare it *to*.

> **Never type an expected value twice. Bind it to a name and use the name on both sides.**

You are authoring this criterion before the code exists, so a hand-typed expectation is a
prediction about bytes you have not seen. When the prediction is wrong the criterion fails against
a correct implementation, and nothing downstream can tell that from a real defect. This is the
single largest source of wasted build budget on record.

| Expected value | Verdict |
|---|---|
| A name bound to the value the criterion supplied as input | **Correct** |
| A status code, exit status, or count | **Correct** |
| A contract token read off a declared interface — `"integer"`, `"application/json"`, `"POST"` | **Correct** |
| A staged suite's exit status | **Correct** |
| A string literal you typed out as the expected result | **Forbidden** |

The forbidden row is judged mechanically: a string expectation carrying anything escapable —
whitespace, a backslash, a quote, a newline, a non-ASCII character — that the criterion did not
also supply as input. A criterion that breaks the rule still runs and is still reported, but it
settles `DISPUTED` and gates nothing, so it buys the story no coverage at all.

The case this comes from. Wrong:

```
source = 'basic = "line\\nvalue"\nraw = \'C:\\\\Users\\\\nodejs\'\n'
result = subprocess.run(["./toml-decoder"], input=source, capture_output=True, text=True)
decoded = json.loads(result.stdout)
assert decoded["raw"]["value"] == r"C:\Users\nodejs"     # re-typed, and wrong
```

A TOML literal string preserves its backslashes verbatim, so the decoder returned the doubled
form and the expectation was wrong. Right:

```
raw = "C:\\Users\\nodejs"
source = f"raw = '{raw}'\n"
result = subprocess.run(["./toml-decoder"], input=source, capture_output=True, text=True)
decoded = json.loads(result.stdout)
assert decoded["raw"]["value"] == raw                    # one spelling, cannot disagree
```

When a transform's output genuinely cannot be derived from its input — a renderer turning `# h`
into `<h1>h</h1>` — do not hand-write the expectation at all. Bind the criterion to the
authoritative suite that defines correctness for that transform. Where no such suite exists, put
the case in the project's own test suite, where the implementer writes it against real output,
rather than predicting it here.

### Two test destinations

A project carries tests in two places, and they are not the same artifact with different names.

| | **Story AC** — `=== AC <id> ===` | **The project's own test suite** |
|---|---|---|
| Job | gate the block | know the code works |
| Count | few | unbounded |
| Authored | here, by planning, **before the code exists** | by the build agent, **alongside the code** |
| Oracle discipline | the rules above, without exception | full latitude — expectations are observed, not predicted |
| Effect | binding: it decides whether the block closes | diagnostic: it guides repair, and its command is what a project criterion runs |
| Runs | at its block | continuously, cumulatively |

The split is not a matter of taste. Every expected value written here is a *prediction* about
bytes that do not exist yet, and a wrong prediction fails a correct implementation — which is why
the oracle rule and the no-re-typed-literal rule are absolute in this file. A test written beside
the finished code compares against output its author has actually seen, so the same assertion that
is hazardous here is safe there.

So this is *more* testing, not less. Exhaustive coverage belongs to the project's suite, which has
no ceiling. An AC block is permanently constrained by having to survive as a gate, so author few
and author them bulletproof. Coverage is never demonstrated by the number of AC blocks a story
carries; it is demonstrated by the suite, and it is graded at the project level through the Sea
Trial that runs that suite.

**Where an authoritative suite exists, it is the coverage.** A conformance corpus staged into
`sources/` defines correctness for the surface it covers. Bind one criterion to it and do not
restate its cases in either destination — a restated case adds no coverage and adds one more
expectation that can be wrong.

**The terminal story is the last story in the build order** — the one on which every other story
is a transitive dependency and after which no further story runs. It is decided by position in the
graph, never by name, type, or kind. A story is not terminal because it is called "verify", because
its `kind` is a test harness, or because it stages the test assets: staging the corpus is
foundational work that runs first, and running the corpus is terminal work that runs last. When a
plan contains several verification stories, exactly one of them is terminal and it is the one every
other story precedes. Identify it by resolving `depends` before writing any suite criterion.

**Only the terminal story runs the whole suite.** No intermediate story's acceptance invokes the
runner unscoped. A partial capability fails most of an authoritative corpus by construction, so an
unscoped mid-build run reports the schedule rather than a defect — and it is slow in exact
proportion to how incomplete the code is, because unimplemented cases exhaust the runner's per-case
timeout instead of returning. It costs most at the point in the build where it teaches least, and a
build agent that starts one mid-story typically abandons it and reports the suite as hung.

**An intermediate story runs its own slice, and the slice executes.** Scoped to the cases that
story implements, the run is neither slow nor red by construction: those are exactly the cases its
code is supposed to pass, so the result is a verdict about the story rather than a report on the
schedule. This is what makes build progress visible — the corpus goes green in the order the plan
builds it, and a regression in an earlier story is caught by the later story that re-runs it.

Executing is the whole point, so:

- The slice **runs cases**. A criterion that invokes the runner's list or dry-run mode executes
  nothing, passes before the story's code exists, and proves only that the runner starts. Such a
  criterion is a defect: it is green from the first build call to the last and steers no repair.
- The slice is **selected by the story's capability**, using the runner's own scoping flag — not by
  case count, not at random, and never by a selector that silently pulls in cases belonging to
  unbuilt stories. Size and inspect each selector with the runner's list mode **while planning**;
  that is where list mode belongs, not in a criterion.
- Every slice invocation supplies each environment variable the runner declares required.

**Together the slices cover the corpus.** Every case an authoritative suite contains belongs to
some story's slice. A case no intermediate slice reaches is first executed by the terminal gate,
where a failure arrives with the whole build already spent and no story to attribute it to.
Overlap between slices is expected and costs nothing — a case exercised by two capabilities
legitimately belongs to both — but a gap is a story whose work no one checked.

**A story that only stages the suite asserts staging.** Where a story's obligation is that the
corpus parses, the exclusion list applies, and the runner starts — and it implements none of the
behavior under test — its criterion invokes the runner's list or dry-run mode and asserts the
runner exits `0` and reports the expected count. This is the one criterion for which executing
nothing is correct, because there is nothing of the product to execute yet. Leaving such a story
with no criterion at all is a defect: it produces a story that cannot be verified and a build block
that closes advisory.

If an imported instruction states where the suite may run, that statement governs.

### What a criterion is worth

Every criterion you write lands in one of four tiers. The tier is decided by how the criterion is
written, not by how it is labelled, and it decides what the criterion can do:

| Tier | What it is | What it does |
|---|---|---|
| **BLOCKING** | a Commander-governed gate, or a criterion bound to a staged authoritative suite | fails the block |
| **CONSULTATIVE** | a criterion whose expected value could not have been invented — a status code, an exit status, a value the criterion itself supplied as input | drives repair; unattended, it marks the block implemented-but-unverified rather than stalling the run |
| **ADVISORY** | a criterion that re-types an expected literal | runs, is reported `DISPUTED`, **gates nothing** |
| **VOID** | malformed: does not compile, or an unclosed container | not a criterion; recorded as a decision and gates nothing |

Aim deliberately. A hand-typed expectation does not merely risk being wrong — it demotes the
criterion to ADVISORY, so the story it was written to protect ends up with no gate at all. Binding
the value to a name is what buys the criterion its authority back.

None of these tiers reaches the release verdict. Story AC decides whether an increment was built;
project acceptance is decided by Sea Trials alone.

### Authoring patterns

Patterns **1, 4, 6, 9, and 10** are the discipline of a gate and govern what you write here.
Patterns **2, 3, 5, 7, and 8** are the discipline of a test suite: state them as expectations on
the project's own suite, which the build agent grows beside the code, rather than enumerating them
into AC blocks.

**1 — Round trip (the default form).** For anything that stores, mutates, or removes state:

```
create  → read back → assert present, with expected field values
update  → read back → assert changed, and only the intended fields changed
delete  → read back → assert absent
```

The read-back is a *separate call through the public interface*, not an inspection of the object
returned by the write. A write that returns a plausible object while persisting nothing must fail.

**2 — Exercise every callable workflow.** *Suite pattern.* One test per public entry point, per
verb. Coverage is enumerated from the interface, not sampled: every HTTP route × every method it
declares including declared error paths; every CLI subcommand and every flag that changes
behavior; every exported library function. This belongs to the project's suite. Here, name the
routes a SCREEN provides — that gate is real — and leave the enumeration to the suite. Where a
staged authoritative suite already covers the surface, it is the coverage.

**3 — Idempotence.** *Suite pattern.* Where a verb claims idempotence (PUT, DELETE), apply it twice and assert the
second is a no-op — same resulting state, and the declared status for a repeat. Where a verb is not
idempotent (POST), apply twice and assert the declared behavior: two resources, or the declared
conflict. Prefer idempotent verbs where the semantics allow; the assertion is stronger.

**4 — Negative paths assert the contract, not the message.** Invalid input asserts the declared
failure signal — status code, exception type, exit status — never the wording of an error message.
Message text is prose and belongs to no contract.

**5 — Boundaries.** *Suite pattern.* Empty collection, exactly one, many. Absent optional fields.
Declared maxima. This is where a plausible-looking implementation actually breaks — and where a
predicted expectation is most likely to be wrong, which is why the cases belong beside the code
rather than here. Where a staged authoritative suite covers the surface, it is the coverage.

**6 — RED before GREEN.** The assertion must fail against the pre-implementation tree and pass
after. A check that passes against a stub is not a check.

**7 — Isolation and determinism.** *Suite pattern, and it applies here too.* Each test arranges its own data and does not depend on another
test's residue or on ordering. No wall-clock dependence, no third-party network, no unseeded
randomness, no sleep-based timing. Fresh store per test, or explicit teardown.

**8 — One behavior per test, named for the behavior.** *Suite pattern.* A failure should be
diagnosable from the test's name alone.

**9 — Subprocess discipline.** Where a check must shell out, **exit status is the verdict**. A
substring check beside an exit-status assertion is redundant at best and a false-positive generator
at worst. Never assert that a literal is absent from captured output.

**10 — In-language tooling.** A check is written in the project's own language and uses that
language's libraries — Python check, Python libraries; Go check, Go libraries. An in-language HTTP
client yields a status code and a parsed body, which is state. `curl` yields stdout, which is text
to scrape. Pattern 10 and the oracle rule are the same rule seen twice.

### Declaring external tooling

Reaching for an external executable is the exception, not the norm, and `curl` in particular will
not work in every environment. When a check genuinely needs one, the tool belongs in the project's
Rigging or `TECHNOLOGY_STACK.md`, declared once by the Commander and true for every check in the
project. A per-check declaration is also accepted and is recorded as a report:

```markdown
Requires: python-package=httpx; scope=test
Requires: executable=node; scope=test
```

Kinds are `python-package` and `executable`; scopes are `runtime` and `test`. Framework test
clients include their transport dependencies. `Requires:` metadata is not acceptance intent, and
a missing declaration never fails planning — a tool that is present and undeclared works fine.
A declared tool that is *absent* when the check runs reports UNVERIFIED, not FAIL: the check never
reached the code under test, so it says nothing about the build.

### Satisfiability

Every assertion must be satisfiable by a correct implementation. An expectation no implementation
can meet is a defect, not a red baseline. Escaping is the usual source of one: inside a raw
literal, `\n` and `\r` are a backslash followed by a letter, not a control character, so
`r"text\n"` asserts against six characters ending in a literal backslash. Binding the value to a
name and using it on both sides removes the question entirely, which is why that is the rule.

### Runnability

**Subprocess mode.** Match the mode to `input=`. Text input declares `text=True` or `encoding=...`;
binary input uses a bytes-like value and does not declare `text`, `encoding`, `errors`, or
`universal_newlines`. A mismatch raises `TypeError` before the program under test starts, which
reports UNVERIFIED — the criterion buys the story nothing. Write:

```
payload = "one line\n"
result = subprocess.run(["./program"], input=payload, capture_output=True, text=True)
assert result.returncode == 0
```

For a binary or invalid-encoding criterion, write:

```
result = subprocess.run(["./program"], input=b"\xff", capture_output=True)
assert result.returncode != 0
```

**ASCII test data.** Acceptance data is ASCII. Do not invent an encoding requirement: characters
outside ASCII test a property the specification never stated, and a criterion that fails on them
fails the build for something nobody asked the product to do. When the imported specification does
state an encoding requirement, the criterion says so and may then use that encoding:

```
=== AC runtime-utf8 ===
Intent: The executable round-trips UTF-8 source, per INSTRUCTIONS.md.
Encoding: utf-8

source = "café\n"
result = subprocess.run(
    ["./program"], input=source, capture_output=True, text=True, encoding="utf-8"
)
assert result.returncode == 0
assert source.strip() in result.stdout
=== END AC runtime-utf8 ===
```

`Encoding:` is a declaration of deliberate intent, reviewable as such. Absent it, ASCII.

**Stated behavior only.** A criterion asserts behavior the source states, not behavior its phrasing
implies. "Takes no arguments", "has no configuration", and "has no side effects" describe the
surface a program offers; they are not requirements that it detect and reject an argument, a
configuration file, or a write. Where the source supplies a reference implementation, that
implementation bounds what the criteria may demand: a criterion the reference shape would fail is a
criterion the source did not ask for.

**Every check is standalone.** Drydock writes each fenced block to its own script and runs it in
its own process from the build directory. Checks in the same file share no imports, no variables,
and no execution order. A snippet that reads a name another snippet bound raises `NameError` on
every run — it reports UNVERIFIED rather than failing the build, which means it verifies nothing
and buys nothing. Each snippet imports what it uses and binds every name it reads.

**A check that shells out prints what it captured before it asserts.** `capture_output=True`
routes the runner's tally and its failing cases into a variable; asserting on the exit code alone
then discards them, and the failure reports the assertion with no evidence of what went wrong.
Print the captured `stdout` and `stderr` first, so the console, the evidence file, and the repair
pass all carry the runner's own account of the failure. Printing is for diagnosis; it is never the
oracle.

**A check that drives a suite prints its tally.** A criterion answers one yes-or-no question, so a
run that fixes a hundred cases and a run that fixes none report the same failure, and the build
reads that as a stalled repair and stops paying for calls that were working. The count is what
separates them. Where the runner reports a machine-readable summary, parse it and print the
counts on one line before asserting:

```
report = json.loads(result.stdout)
summary = report["summary"]
print(f"{summary['pass']} passed, {summary['fail']} failed, {summary['error']} errored")
assert summary["fail"] == 0 and summary["error"] == 0
```

Print the counts even when the criterion asserts on the parsed object rather than on the text.
Requesting `--json` and asserting straight off the parsed report leaves nothing on either stream,
and a suite of hundreds of cases then reports its progress as a single bit.

```markdown
## Programmatic Acceptance

=== AC health-check ===
Intent: The health endpoint returns an OK response.

from app import create_app

client = create_app().test_client()
response = client.get("/health")
assert response.status_code == 200
assert response.get_json()["status"] == "ok"
=== END AC health-check ===

=== AC suite-conformance ===
Intent: The implementation passes the conformance sections this story owns.
Suite: scoped

import os
import subprocess
import sys

# tests/run_suite.py documents RUNNER as required: it is the runner's only knowledge of the
# implementation. Read the asset and supply every variable it declares required.
result = subprocess.run(
    [sys.executable, "tests/run_suite.py", "--sections", "headings,lists"],
    capture_output=True, text=True,
    env={**os.environ, "RUNNER": f"{os.getcwd()}/program"},
)
print(result.stdout)
print(result.stderr, file=sys.stderr)
assert result.returncode == 0
=== END AC suite-conformance ===
```

`User Acceptance` contains only Commander-observed checks that cannot be honestly automated,
such as look-and-feel or subjective workflow acceptance. Do not place deterministic behavior in
`User Acceptance`.

Do not tag an assertion with a project-acceptance ID. Sea Trials flow into planning as context for
authoring acceptance; nothing points back at them. Project acceptance is settled at `score release`
by observing the finished tree, never by looking up which assertion claimed which criterion.

**Programmatic acceptance is the story's definition of done, and a deterministic definition of
done is never sampled.** Drydock builds each block in a single pass with no iterate loop, so the
acceptance you author *is* the objective handed to the builder: sample the checks and the builder
builds to the sample. When an authoritative, externally-authored test suite already defines
"correct" for what a story builds — an imported conformance suite and its runner (for example a
specification's example suite plus a `*_tests.py` runner) — the acceptance runs that suite and
requires a full pass over the story's scope, never a hand-picked subset. A feature story binds to
the sections it owns and declares `Suite: scoped`; a terminal verification story gates on the whole
suite and declares `Suite: full`. The marker is one of the block's declaration lines and tells the
runner the check gates on the whole test suite rather than a story-scoped sample.

**A scoped selector must select something.** A check that runs a suite with a section filter
matching no cases exits zero and reports a pass while proving nothing. Select on a heading that
actually owns cases, never on a chapter title that merely contains such headings. Drydock fails a
criterion that is already green before the story's code exists.
**The runner's exit status is the verdict, and it is the whole verdict.** A conformance runner
already decides pass or fail and reports it the one way a caller can rely on. Asserting on its
printed summary as well adds no information and adds a failure mode: the case count belongs to the
installed suite rather than to the specification, and runners column-align their summaries
(`valid tests: 205 passed,  0 failed` carries two spaces), so a literal such as
`assert "valid tests: 210 passed, 0 failed" in result.stdout` is false on correct code and no
implementation can move it. The same holds for tallies of errors, skips, and warnings: a runner
with none of them commonly prints no such line at all, so requiring one is false on a clean run.

Print the captured output for diagnosis, assert `result.returncode == 0`, and stop there. This
holds for both `Suite: scoped` and `Suite: full`.

Place a whole-project deterministic suite on the story that **completes the runnable capability**
— never on a foundation step that cannot yet run it, where it would fail vacuously. Naming the suite file or asserting it is staged (`Path(...).is_file()`)
is staging, not testing: a stubbed or absent definition of done for an available suite is a defect,
not an acceptable check.

An assertion that invokes a staged asset obeys that asset's own documented interface. Read the
asset before writing the call. Every environment variable it declares required is supplied, and it
is supplied by extending the inherited environment — `env={**os.environ, "NAME": value}`. Never
write `env={"NAME": value}`: that replaces the environment, leaving the child with no `PATH`, so
nothing it invokes resolves and the assertion fails at every level of implementation quality. Never
repair a staged asset's interface by editing the asset; it is restored before grading, so the edit
is reported as tampering rather than honored.

An assertion that feeds input to a program passes it through `subprocess` `input=` rather than a
shell. When a shell is unavoidable, `printf '%s'` copies its argument verbatim: `\n` reaches the
program as a backslash and a letter, not a newline, so the program is graded on input the author
never wrote. Use `printf '%b'` or a real line break.

`COMPASS.md` uses `## Compass`, `## Constraints`, and `## Guardrails` as its body sections.
Success criteria belong in `SEA_TRIALS.md`; open questions in spike questionnaires. Do not add
those sections to `COMPASS.md`.

---

---

## Acceptance Criteria Files

**Naming rule:** any file where `AC` is a whole word in the filename is an acceptance criteria
file. `AC` must be delimited by `-`, `_`, or file boundaries — not embedded in another word.
Examples: `AC-001-login.md`, `FEATURE-LOGIN-AC.md`, `AC-NAVIGATION.md`.
`ACCEPTANCE_CRITERIA.md` does NOT follow this standard (AC is not a standalone word).

AC files enable test-driven design and a way to enforce specific behaviors without polluting the
parent specification.

**Two types of AC statements:**

| Type | Example | Rule |
|------|---------|------|
| Positive assertion | "The status badge color is red" | Reconcile into parent spec, then archive this entry |
| Negative/guardrail | "Field X must not appear on this screen" | Keep permanently in AC — these guard against model hallucination, not spec omission |

**Reconciliation:** When a positive AC fact has been implemented and verified, move it to the
parent spec body and delete the AC entry. Negative guardrails are permanent — never move them to
the spec.

**AC file format:**

```markdown
# AC: {ObjectName}

| Field       | Value |
|-------------|-------|
| Version     | YYYYMMDD V1 |
| Description | Acceptance criteria for {ObjectName}. |
| Parent      | FEATURE-{Name}.md |

## Guardrails

- Field X must not appear on this screen.
- The delete button must not be shown to read-only users.

## Assertions

- The status badge is rendered in red when severity is HIGH.
```

**Standard AC filename forms:**
- `AC-NNN-{Name}.md` — numbered sequential acceptance-criteria ticket (authored)
- `{Parent}-AC.md` — paired directly with a spec file (e.g. `FEATURE-LOGIN-AC.md`)
- `AC-{Topic}.md` — topic-scoped AC file (e.g. `AC-NAVIGATION.md`)

**All fix and change tickets use AC naming** — `AC` as a whole word in the filename. A targeted
bug fix is expressed as a testable acceptance criterion.

---

## Dependency Declarations

`drydock plan create` scans spec file headers to populate `Depends On` and `Provides`. The
following conventions apply automatically without explicit header declaration:

| Convention | Rule |
|------------|------|
| `SCREEN-*.md` → `UI-GENERAL.md` | All screens depend on shared UI patterns |
| `DATABASE.md` → Phase 1 | Always first phase; always base context |
| `ARCHITECTURE.md` → base context | Included in every phase prompt |
| `FEATURE-*.md` providing routes → listed in `Provides` | Extracted from route tables in file |
| `SCREEN-*.md` using a route → depends on providing `FEATURE` | Matched from route references in body |

The `Depends On` and `Provides` fields form a simple directed dependency graph. `drydock plan
create` traverses this graph to assign phases, assign build order, and compute context sizes.
A file can only be built in a phase after all its `Depends On` files are built.

---

## Persistence Encapsulation (DATABASE.md scope)

`DATABASE.md` is the project's persistence contract — not SQL schema alone. It documents every
persistent store and the typed class that encapsulates it:

- **Relational tables** — schema plus the row dataclass / CRUD class / composing `Database` class.
- **Config / `.env`** — required keys and the typed `Config` class.
- **File stores** — directories and the `FileStore` class.
- **External services** — the service contract and its wrapper.

Application code reaches each store only through its class. A storage change that leaves the
interface unchanged does not invalidate downstream features.

Every `DATABASE.md` includes `## Access Patterns` and `## Persistence Interfaces` before schema
details. Access patterns name the caller, operation, store, and interface method. Persistence
interfaces name the store, public interface, module location, allowed callers, and notes.

`ARCHITECTURE.md` includes a module ownership table for persistence, configuration, file-store, and
external-service boundaries. It states which module owns each boundary and which low-level APIs that
module may access.

Any Manifest story that implements `DATABASE.md` includes `persistence.md` in `stack:` plus the
selected backend stack file such as `sqlite.md`, `postgres.md`, or `aws-dynamodb.md`.

---

## METADATA.md — Service Identity Fields

In addition to standard project fields, service repositories should declare:

```
service_name:      Platform        # top-level service grouping (e.g. Platform, Analytics, Tools)
service_component: GAME            # component name within the service (matches directory name)
```

These fields are used by build-time service registration artifacts and by GAME's service registry
scanner to group related repositories under a named service.

---

## Authoring Conventions

**Authoring phase:** all unresolved product decisions go in `DECISIONS.json`. Do not create
`MANIFEST.md` or numbered ticket files while authoring.

**Build phase:** run `drydock plan create` once the specification is ready. Use `drydock status`
to check for spec errors and staleness before building. After a build, fold changes back by editing
the specification and re-applying with `drydock refit`.

**Spikes:** a spike is a runnable investigation. Results feed future iterations. When run, the
finding is written into the named file, resolving the matching `## Open Question` in place.

**Feature specifications:** all feature purpose, status, triggers, sequences, routes, reads,
writes, acceptance criteria, and guardrails belong in individual `FEATURE-*.md` files. README,
METADATA, and generated files do not contain feature specifications.

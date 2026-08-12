---
name: Blueprints Contract
description: Contract governing the layout, file types, header format, and dependency conventions for Drydock Blueprint files.
version: 20260731 V11
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
Sea Trials: st-001

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

An unterminated block, an end marker naming a different id, a stray end marker, and a duplicate id
are all hard errors that stop planning. None of them degrade into a criterion that silently stops
gating.

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

### Authoring patterns

**1 — Round trip (the default form).** For anything that stores, mutates, or removes state:

```
create  → read back → assert present, with expected field values
update  → read back → assert changed, and only the intended fields changed
delete  → read back → assert absent
```

The read-back is a *separate call through the public interface*, not an inspection of the object
returned by the write. A write that returns a plausible object while persisting nothing must fail.

**2 — Exercise every callable workflow.** One test per public entry point, per verb. Coverage is
enumerated from the interface, not sampled: every HTTP route × every method it declares including
declared error paths; every CLI subcommand and every flag that changes behavior; every exported
library function.

**3 — Idempotence.** Where a verb claims idempotence (PUT, DELETE), apply it twice and assert the
second is a no-op — same resulting state, and the declared status for a repeat. Where a verb is not
idempotent (POST), apply twice and assert the declared behavior: two resources, or the declared
conflict. Prefer idempotent verbs where the semantics allow; the assertion is stronger.

**4 — Negative paths assert the contract, not the message.** Invalid input asserts the declared
failure signal — status code, exception type, exit status — never the wording of an error message.
Message text is prose and belongs to no contract.

**5 — Boundaries.** Empty collection, exactly one, many. Absent optional fields. Declared maxima.
This is where a plausible-looking implementation actually breaks.

**6 — RED before GREEN.** The assertion must fail against the pre-implementation tree and pass
after. A check that passes against a stub is not a check.

**7 — Isolation and determinism.** Each test arranges its own data and does not depend on another
test's residue or on ordering. No wall-clock dependence, no third-party network, no unseeded
randomness, no sleep-based timing. Fresh store per test, or explicit teardown.

**8 — One behavior per test, named for the behavior.** A failure should be diagnosable from the
test's name alone.

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
can meet is a defect, not a red baseline. String literals are the usual source of one: inside a raw
literal, `\n` and `\r` are a backslash followed by a letter, not a control character, so
`r"text\n"` asserts against six characters ending in a literal backslash. Write control characters
in a normal string (`"text\n"`), concatenate (`r"\*text\*" + "\n"`), or write `"\\n"` when a
literal backslash is genuinely intended. Drydock warns about this at `drydock validate` and at plan
time; the warning does not remove the criterion or stop the build, so the authoring is yours to get
right.

### Runnability

Two authoring rules are enforced at plan time. A criterion that breaks either is rejected before
any build spends a call on it, because no implementation can turn it green.

**Text mode.** Every `subprocess` call declares `text=True`. A criterion drives a program that
reads and writes text; left in binary mode the call takes `bytes`, and passing it a `str` raises
`TypeError` before the program under test starts. Write:

```
result = subprocess.run(["./program"], input="one line\n", capture_output=True, text=True)
assert result.returncode == 0
assert result.stdout == "<p>one line</p>\n"
```

**ASCII test data.** Acceptance data is ASCII. Do not invent an encoding requirement: characters
outside ASCII test a property the specification never stated, and a criterion that fails on them
fails the build for something nobody asked the product to do. When the imported specification does
state an encoding requirement, the criterion says so and may then use that encoding:

```
=== AC runtime-utf8 ===
Intent: The executable round-trips UTF-8 source, per INSTRUCTIONS.md.
Encoding: utf-8

result = subprocess.run(
    ["./program"], input="café\n", capture_output=True, text=True, encoding="utf-8"
)
assert result.stdout == "<p>café</p>\n"
=== END AC runtime-utf8 ===
```

`Encoding:` is a declaration of deliberate intent, reviewable as such. Absent it, ASCII.

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

```markdown
## Programmatic Acceptance

=== AC health-check ===
Intent: The health endpoint returns an OK response.
Sea Trials: st-001

from app import create_app

client = create_app().test_client()
response = client.get("/health")
assert response.status_code == 200
assert response.get_json()["status"] == "ok"
=== END AC health-check ===

=== AC suite-conformance ===
Intent: The implementation passes the conformance sections this story owns.
Suite: scoped

import subprocess
import sys

result = subprocess.run(
    [sys.executable, "tests/run_suite.py", "--sections", "headings,lists"],
    capture_output=True, text=True,
)
print(result.stdout)
print(result.stderr, file=sys.stderr)
assert result.returncode == 0
=== END AC suite-conformance ===
```

`User Acceptance` contains only Commander-observed checks that cannot be honestly automated,
such as look-and-feel or subjective workflow acceptance. Do not place deterministic behavior in
`User Acceptance`.

`Sea Trials:` optionally lists the stable project-acceptance IDs proved by an assertion. It is one
of the block's declaration lines. Every listed ID exists in `SEA_TRIALS.md`.

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
— never on a foundation step that cannot yet run it, where it would fail vacuously — and mirror it
into `SEA_TRIALS.md` with `Sea Trials:` so it is both the completing block's acceptance and a
project-acceptance criterion. Naming the suite file or asserting it is staged (`Path(...).is_file()`)
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

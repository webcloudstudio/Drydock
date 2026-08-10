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

`Programmatic Acceptance` contains executable Python assertion snippets. Each check uses a stable
`### {check-id}` heading, a short intent sentence, and one fenced `python` block that can run from
the build directory after the story implementing the file completes.

Every external tool used directly or indirectly by a check is declared immediately after its
heading with one or more machine-readable lines:

```markdown
Requires: python-package=httpx; scope=test
Requires: executable=node; scope=test
```

V1 kinds are `python-package` and `executable`; scopes are `runtime` and `test`. Framework test
clients include their transport dependencies. `Requires:` metadata is not acceptance intent.

Every assertion must be satisfiable by a correct implementation. An expectation no implementation
can meet is a defect, not a red baseline. String literals are the usual source of one: inside a raw
literal, `\n` and `\r` are a backslash followed by a letter, not a control character, so
`r"text\n"` asserts against six characters ending in a literal backslash. Write control characters
in a normal string (`"text\n"`), concatenate (`r"\*text\*" + "\n"`), or write `"\\n"` when a literal
backslash is genuinely intended. Drydock rejects this defect at `drydock validate` and blocks the
build before the step runs.

**Every check is standalone.** Drydock writes each fenced block to its own script and runs it in
its own process from the build directory. Checks in the same file share no imports, no variables,
and no execution order. A snippet that reads a name another snippet bound raises `NameError` on
every run and can never pass. Each snippet imports what it uses and binds every name it reads.
Drydock rejects an unparseable snippet, and a snippet reading an unbound name, at
`drydock validate` and blocks the build before the step runs.

**A check that shells out prints what it captured before it asserts.** `capture_output=True`
routes the runner's tally and its failing cases into a variable; asserting on the exit code alone
then discards them, and the failure reports the assertion with no evidence of what went wrong.
Print the captured `stdout` and `stderr` first, so the console, the evidence file, and the repair
pass all carry the runner's own account of the failure. A count in that output that exceeds the
expected total — `365` cases run where the specification defines `362` — is itself a defect a
reader can only catch when the output is visible.

````markdown
## Programmatic Acceptance

### health-check
The health endpoint returns an OK response.

Sea Trials: st-001

```python
from app import create_app

client = create_app().test_client()
response = client.get("/health")
assert response.status_code == 200
assert response.get_json()["status"] == "ok"
```

### suite-conformance
The implementation passes the conformance sections this story owns.

Suite: scoped

```python
import re
import subprocess
import sys

result = subprocess.run(
    [sys.executable, "tests/run_suite.py", "--sections", "headings,lists"],
    capture_output=True, text=True,
)
print(result.stdout)
print(result.stderr, file=sys.stderr)
assert result.returncode == 0
assert re.search(r"\b0\s+failed\b", result.stdout)
```
````

`User Acceptance` contains only Commander-observed checks that cannot be honestly automated,
such as look-and-feel or subjective workflow acceptance. Do not place deterministic behavior in
`User Acceptance`.

`Sea Trials:` optionally lists the stable project-acceptance IDs proved by an assertion. It
appears between the intent sentence and Python fence. Every listed ID exists in
`SEA_TRIALS.md`.

**Programmatic acceptance is the story's definition of done, and a deterministic definition of
done is never sampled.** Drydock builds each block in a single pass with no iterate loop, so the
acceptance you author *is* the objective handed to the builder: sample the checks and the builder
builds to the sample. When an authoritative, externally-authored test suite already defines
"correct" for what a story builds — an imported conformance suite and its runner (for example a
specification's example suite plus a `*_tests.py` runner) — the acceptance runs that suite and
requires a full pass over the story's scope, never a hand-picked subset. A feature story binds to
the sections it owns and declares `Suite: scoped`; a terminal verification story gates on the whole
suite and declares `Suite: full`. The marker sits on its own line in the check's heading block and
tells the runner the check gates on the whole test suite rather than a story-scoped sample.
The assertion requires runner success. It may additionally verify the failure count, matched with
a whitespace-tolerant regular expression (`re.search(r"\b0\s+failed\b", result.stdout)`). Never
assert a runner's tally as a literal substring of its output: the case count belongs to the
installed suite, not to the specification, and runners column-align their summaries
(`valid tests: 205 passed,  0 failed` carries two spaces), so a literal such as
`assert "valid tests: 210 passed, 0 failed" in result.stdout` is false on correct code and no
implementation can move it. Drydock removes such a criterion from the specification at plan time.
The failure count is the only tally an assertion may require. Never require a count of errors,
skips or warnings in captured output: only passes and failures are reliably tallied, and a runner
with none of the others commonly prints no such line at all, so `re.search(r"\b0\s+errors?\b",
result.stdout)` is false on a clean run and no implementation can move it. This holds for both
`Suite: scoped` and `Suite: full` — a scoped run additionally expects tests outside its slice to
be skipped. Drydock removes such a criterion from the specification at plan time.

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

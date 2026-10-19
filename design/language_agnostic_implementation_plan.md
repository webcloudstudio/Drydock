# Language-Agnostic Target Generation and Library Encapsulation

| Field | Value |
|---|---|
| Date | 2026-10-19 |
| Status | Proposed implementation plan; revised after review |
| Branch | `main` only |
| Initial Target languages | Python and Go |
| Initial databases | SQLite and PostgreSQL |

## Objective and boundaries

Drydock remains a Python application. It generates Target application code in the selected
language. Every planning, build and repair step uses the same persisted selection.

Drydock ships tested library code with the product, per language, under
`Rigging/languages/<language>/`. Build agents write application code that calls these libraries;
they do not write replacement libraries. The work adds minimal layers to existing mechanisms and
does not rewrite the shipped, tested Python database library.

Excluded: Refit methodology, database versioning and change sets, impact analysis,
per-criterion coverage and tracing, and any check that fails a build because of pre-existing
Target code.

## Settled decisions

- `TECHNOLOGY_STACK.md` in the Target directory is the only selection record.
- Every Rigging file declares `**Type:**`. One configuration table states how many files of each
  type a Target selects. Adding a type is one table row; no code change.
- `language` is exactly one. `database` is zero or one. Other types follow the table.
- `Type` governs selection counts only. Existing `Foundation`, `Tier` and `Category` fields keep
  driving build order and the QuarterDeck grouping unchanged.
- A language is selectable only when `Rigging/languages/<language>/` ships its bundle: the
  language file, its compact and its libraries. Python and Go ship initially.
- Drydock resolves and injects required prompt content. Correctness does not depend on an LLM
  opening files.
- Existing Python fallbacks stay. Required language selection makes them unreachable.

## Ordered implementation

### 1. Type-based selection rules

Add `Rigging/rigging_types.json`:

```json
{
  "language":   {"min": 1, "max": 1},
  "database":   {"min": 0, "max": 1},
  "web-server": {"min": 0, "max": 1},
  "cli":        {"min": 0, "max": 1}
}
```

A type absent from the table has no limit. Add `**Type:**` to every selectable Rigging file;
rename `persistence-engine` to `database`. One validation function in `technology_stack.py`
reads the table and returns every defect. QuarterDeck save, stack approval, planning and build
preflight call that function; none carries its own rule.

`declared_language` reads only the selected language file. A free-text row naming a language
does not establish or override the selection.

Existing `Prerequisite:` lines are the dependency source. Refuse a selection whose
prerequisites name a different language (Go plus FastAPI). Audit prerequisite lines that name
`python.md` without requiring Python (`terraform.md`, `aws-*.md`, `github-actions.md`) so they
do not reject Go stacks.

Acceptance:

- Zero or two languages are refused. Two databases are refused. No database is accepted.
- Go plus FastAPI is refused, naming the conflicting prerequisite.
- A new type added to the table is enforced without code changes.

### 2. QuarterDeck selection and approval process

Current behavior (`QuarterDeck/app.py`, `technology_stack.py`):

| Gap | Today |
|---|---|
| Language choices | Radios list every `Foundation: language` file, including `typescript.md`, which ships no bundle |
| Second language | A table row may select `go.md` while the radio holds `python.md`; `split_foundations` hides the second row, which the next autosave silently drops |
| Database | Checkboxes; several may be selected |
| Save | `api_set_technology_stack` writes any rows without validation |
| Change after approval | Autosave carries the approval marker forward; a valid language switch stays approved |

Required process:

1. **Select.** Each `max: 1` type renders as one radio group, with a None choice only when
   `min` is `0`. The language group lists shipped bundles only and has no None choice. The
   free-text table's Rigging dropdown excludes files whose type has a radio group, so a second
   language or database cannot be entered there.
2. **Save.** Autosave writes the draft and returns the validation defects. QuarterDeck shows
   them inline beside the offending group. A draft may be invalid; it cannot be approved.
3. **Approve.** Approval runs the shared validation and refuses with every defect listed.
4. **Change.** Changing the language or database of an approved stack removes the approval
   marker. QuarterDeck states that the plan and compacts must be regenerated. Editing other rows
   keeps approval.
5. **Consume.** Planning and build preflight refuse an unapproved or invalid stack before any
   LLM call.

Acceptance:

- The language group offers Python and Go only; exactly one is always selected.
- The table cannot add a second language or database.
- Saving two languages through the API returns the defect; approving it fails.
- Switching an approved stack from Python to Go unapproves it.
- Plan and build refuse an unapproved stack without invoking an LLM.

### 3. Language context in build prompts

Builders of a Rigging file receive the full file; consumers receive its compact (existing rule).
Inject the selected language's `<language>_compact.md` into every build and repair prompt
whether or not the block's `stack:` names it. The language foundation block receives the full
file. Shared inclusions appear once; prompt sizing counts the injected compact.

Acceptance:

- A Go block whose `stack:` omits `go.md` receives `go_compact.md`.
- A Python block receives `python_compact.md` the same way.

### 4. Compaction by language

Compaction is language-blind today: `rigging_compact.resolve_role` selects the architecture,
database or contracts role by filename, and the three role prompts carry no language.

- Pass the Target's selected language into the compaction job block for every role, so
  `DATABASE_compact.md`, `ARCHITECTURE_compact.md` and contract compacts present interfaces and
  call signatures in that language.
- Record the language in each compact's provenance line. A compact whose recorded language
  differs from the Target's selection is stale and is regenerated by the existing freshness
  gate.
- Rigging scope compaction is unchanged; language bundles keep their own compacts.

Acceptance:

- A Go Target's `DATABASE_compact.md` shows Go call signatures.
- Switching the Target language marks Target compacts stale.
- A fake runner verifies the language appears in each role's assembled prompt.

### 5. Native application foundations

`go.md` states the Go toolchain, tools and utilities, the standard-library CLI layout and the
`net/http` server layout, with native test fixtures. `cli.md`, FastAPI, Flask and Django remain
Python files through their prerequisites. The language foundation builds before persistence
generation; the root `go.mod` exists before the Go persistence module is linked. Reconcile
`go.md` with the nested persistence module.

Acceptance:

- Python and Go fixtures each demonstrate a CLI application and an HTTP application.
- Persistence generation never precedes language initialization.

### 6. Library CRUD guards

Add standard guards to the shipped libraries in both languages:

| Verb | Guard |
|---|---|
| `get`, `update`, `delete` | Key input required; refused before any SQL runs |
| `create` | Required (NOT NULL, no default) columns supplied |
| `list` | Declared filter inputs only |
| All | Undeclared operation or input refused |

Correct calls behave exactly as today. `delete` without its key raises and removes no rows
(today it issues `DELETE FROM <table>`). Each guard has a Python and a Go unit test.

### 7. Native acceptance outcomes

Preserve native results through the outer executor: pass, failure, skipped/not-run,
unavailable tool, compilation error and timeout stay distinct. A skipped Go test reported as
`status: skip` must not become an ordinary failure. Timeouts terminate child processes.

### 8. Verification and delivery

One tested slice per local commit on `main`; no push. Update README, changelog and affected
design `## Behavior` (`foundations.md`, `run.md`, `plan.md`, `rigging.md`). Fake LLM runners
only. Verify installed-wheel resource resolution. Run lint and the regression suite. Report
missing integration prerequisites (Go toolchain, PostgreSQL DSN) rather than treating skips as
passes.

## Completion criteria

- QuarterDeck permits exactly one language and at most one database, from shipped bundles only.
- One shared validation governs save, approval, planning and build.
- Changing the language or database unapproves the stack.
- Every build prompt carries the selected language's compact.
- Target compacts are generated for, and keyed to, the selected language.
- Python and Go libraries guard CRUD calls identically.
- Native acceptance outcomes stay accurate.
- Existing Python database behavior is unchanged for correct calls.

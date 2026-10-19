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

Excluded: Refit methodology, ticket wiring, impact analysis, per-criterion coverage and tracing,
and any check that fails a build because of pre-existing Target code.

## Settled decisions

- `TECHNOLOGY_STACK.md` in the Target directory is the only selection record.
- Every Rigging file declares `**Type:**`. One configuration table states how many files of each
  type a Target selects. Adding a type is one table row; no code change.
- `language` is exactly one. `database` is zero or one. Other types follow the table.
- `Type` governs selection counts only. Existing `Foundation`, `Tier` and `Category` fields keep
  driving build order and the QuarterDeck grouping unchanged.
- Python and Go ship initially. A language is supported only when its bundle ships libraries
  and a compact.
- Drydock resolves and injects required prompt content. Correctness does not depend on an LLM
  opening files.
- Existing Python fallbacks stay. Required language selection makes them unreachable.

## Ordered implementation

### 1. Type-based selection

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
rename `persistence-engine` to `database`. `technology_stack.py` validates counts from the table
at stack approval, planning and build preflight. QuarterDeck renders a `max: 1` type as a radio
group, with a None choice when `min` is `0`.

Existing `Prerequisite:` lines are the dependency source. Resolve them transitively and refuse
a selection whose prerequisites name a different language (Go plus FastAPI). Audit prerequisite
lines that name `python.md` without requiring Python (`terraform.md`, `aws-*.md`,
`github-actions.md`) so they do not reject Go stacks.

Acceptance:

- Zero or two languages are refused. Two databases are refused. No database is accepted.
- Go plus FastAPI is refused, naming the conflicting prerequisite.
- A new type added to the table is enforced without code changes.

### 2. Language context and compaction by language

Builders of a Rigging file receive the full file; consumers receive its compact (existing
rule). Inject the selected language's `<language>_compact.md` into every build and repair
prompt whether or not the block's `stack:` names it. The language foundation block receives
the full file.

Compaction is language-blind today: `rigging_compact.resolve_role` selects the role by filename
and the role prompts carry no language. Pass the Target's language into the compaction job block
so `DATABASE_compact.md` and contract compacts present call signatures in that language. A
language change marks existing compacts stale.

Remove obsolete SQLAlchemy/Alembic assumptions from prompts that contradict the shipped
libraries.

Acceptance:

- A Go block whose `stack:` omits `go.md` receives `go_compact.md`.
- A Go Target's `DATABASE_compact.md` shows Go call signatures.
- Shared inclusions appear once; prompt sizing counts the injected compact.

### 3. Native application foundations

`go.md` states the Go toolchain, tools and utilities, the standard-library CLI layout and the
`net/http` server layout, with native test fixtures. `cli.md`, FastAPI, Flask and Django remain
Python files through their prerequisites. The language foundation builds before persistence
generation; the root `go.mod` exists before the Go persistence module is linked. Reconcile
`go.md` with the nested persistence module.

Acceptance:

- Python and Go fixtures each demonstrate a CLI application and an HTTP application.
- Persistence generation never precedes language initialization.

### 4. Library CRUD guards

Add standard guards to the shipped libraries in both languages:

| Verb | Guard |
|---|---|
| `get`, `update`, `delete` | Key input required; refused before any SQL runs |
| `create` | Required (NOT NULL, no default) columns supplied |
| `list` | Declared filter inputs only |
| All | Undeclared operation or input refused |

Correct calls behave exactly as today. Shared behavior for nulls, text keys, binary values,
returned keys, errors and transactions is defined once and tested in both languages.

Acceptance:

- `delete` without its key raises and removes no rows (today it issues `DELETE FROM <table>`).
- Each guard has a Python and a Go unit test.

### 5. Database versioning by change set

Neither library applies versions today; `create_ticket_migration_records` writes Alembic
comment skeletons only. Ship one change-set runner per language library, Liquibase-style:

- Change sets are ordered SQL files, `NNNN_<name>.sql`, for the Target's database.
- `0001` is the initial schema, so fresh and incremental builds use the same path.
- A `drydock_schema_version` table records version, name, checksum and time applied.
- `apply(up_to=N)` applies each pending change set once, in order, each in a transaction.
- A changed checksum on an applied change set is refused.
- Python and Go implement identical semantics with no new dependency.

Ticket-to-change-set wiring belongs to Refit.

Acceptance:

- Fresh database reaches version N. Re-running is a no-op. `up_to` stops at the given version.
- A failing change set rolls back and leaves the version unchanged.
- An edited applied change set is refused.

### 6. Native acceptance outcomes

Preserve native results through the outer executor: pass, failure, skipped/not-run,
unavailable tool, compilation error and timeout stay distinct. A skipped Go test reported as
`status: skip` must not become an ordinary failure. Timeouts terminate child processes.

### 7. Verification and delivery

One tested slice per local commit on `main`; no push. Update README, changelog and affected
design `## Behavior`. Fake LLM runners only. Verify installed-wheel resource resolution. Run
lint and the regression suite. Report missing integration prerequisites (Go toolchain,
PostgreSQL DSN) rather than treating skips as passes.

## Completion criteria

- One persisted language selection controls every step.
- Selection counts come from `Rigging/rigging_types.json`.
- Every build prompt carries the selected language's compact; compacts use the Target language.
- Python and Go libraries guard CRUD calls and apply versioned change sets identically.
- Native acceptance outcomes stay accurate.
- Existing Python database behavior is unchanged for correct calls.

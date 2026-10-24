# PostgreSQL

**Type:** database
**Version:** 20261023 V3
**Tier:** platform
**Category:** Persistence
**Foundation:** database
**Description:** PostgreSQL as a Drydock store: what it enforces, how it differs from SQLite, and how a Target reaches it.

Technology reference. This file does not change between projects.

Prerequisite: `stack/persistence.md`

---

## Foundation Contract

The published Python binding follows. Go callers use the language-native API in
`languages/go/go.md`; Go tests run through the existing Blueprint AC container.
Carried verbatim into `postgres_compact.md`.

- package: persistence
- entry: open_database(dsn) -> Database
- fixture: db_session
- fixture_source: persistence/testing.py

### How is this engine configured and initialized?

Provide a running PostgreSQL server and a `postgresql://` DSN through `DATABASE_URL`; keep
credentials out of source control. The shipped Python binding uses `psycopg` or `psycopg2`;
declare `psycopg[binary]` in project dependencies. Drydock applies generated `schema.sql` at the
DATABASE step and before acceptance runs, creating referenced tables first. Declare schema
changes in `DATABASE.md`; idempotent creation does not migrate existing tables. Provision schema
migrations separately when existing data must be retained.

### How does this engine implement the shared persistence contract?

The shipped Python binding is `Rigging/languages/python/persistence/postgres.py`, used through `persistence.db` and
`open_database(dsn)`. Call declared table operations; configure DATABASE_URL with the PostgreSQL DSN before provisioning and use `db_session()`
against that store. SQLite does not verify PostgreSQL. The
engine binds parameters and returns generated IDs with `RETURNING`. PostgreSQL enforces declared
lengths and types. Shipped-library tests include driver doubles; actual PostgreSQL behavior
requires an integration run against a server. The Go binding is `languages/go/persistence/postgres.go`, verified against this engine.
Use `OpenDatabase(ctx, dsn)` and generated typed methods; `OpenSession(ctx, dsn)` supplies
a test store. The Go library is linked as `drydock.local/persistence`.

**How the Python binding is built.** Drydock builds this foundation deterministically. No build agent writes,
edits, or replaces any file listed below.

1. Plan declares the store in `DATABASE.md`: every table, every column, and each access pattern's
   `Repository operation` as `<table>.<verb>`.
2. Plan emits the story that implements `DATABASE.md`, with `persistence.md` and `postgres.md` in
   `stack:`. That story is the DATABASE step. Its builder writes no persistence code.
3. Before that story's step runs, Drydock writes the package into the build root, so a story in
   the same step can import it:

| Layer | File | Origin |
|---|---|---|
| Library | `persistence/db.py` | shipped `Rigging/languages/python/persistence/db.py`, copied unchanged: `Database`, statement construction, parameter binding, engine selection |
| Engines | `persistence/sqlite.py`, `persistence/postgres.py` | shipped, copied unchanged; the DSN selects one at runtime |
| Declaration | `persistence/schema.py` | generated from `DATABASE.md`: `SCHEMA` (tables, operations, row dataclasses) and `open_database(dsn)`; contains no SQL |
| Interface | `persistence/__init__.py` | generated; exports `Database`, `PersistenceError`, `UnknownOperation`, `SCHEMA`, `open_database` |
| Verification | `schema-verification.json` | generated runtime catalog and count probes |
| Fixture | `persistence/testing.py` | generated; `db_session()` |
| DDL | `schema.sql` | generated from `DATABASE.md`; `CREATE ... IF NOT EXISTS` throughout |

4. Drydock applies `schema.sql` through `open_database` to the configured store — `DATABASE_URL`,
   else `DATABASE_PATH`, else `data/app.db` — at the DATABASE step and again before every
   acceptance run, so a criterion that drives the application through its own client finds the
   declared tables.

Every later story writes callers only: `route → service → db.<table>.<name>(...)`. The package
exposes one attribute per declared table and one method per declared operation. Changing the
store means changing `DATABASE.md` and rebuilding.

Each Kind returns one fixed shape, so a pattern's Output declares the row, never a wrapper
around it:

| Kind | Returns |
|---|---|
| `get` | the Output row, or `None` (Go `nil`) when nothing matches |
| `list` | a list of Output rows, one per record; the Output names the row's columns |
| `create` | the Output row, read back by key; the key when no Output is declared |
| `update` | the Output row, read back by its Match, or `None` when nothing matched; the count when it reaches many rows or no Output is declared |
| `upsert` | the Output row inserted or replaced, read back by its Match |
| `delete` | the Output built from its Match, or `None` when nothing matched; the count when it reaches many rows or no Output is declared |

```python
# persistence/testing.py — generated by Drydock
@contextmanager
def db_session() -> Iterator[Database]: ...
def committed_session() -> Iterator[Database]: ...

# application code
from persistence import open_database

db = open_database(config.database_path)

# a criterion
from persistence.testing import db_session

with db_session() as db:
    row = db.<table>.create(...)  # the declared Output row

# conftest.py
import pytest
from persistence import testing

@pytest.fixture
def db_session():
    with testing.db_session() as db:
        yield db
```

`db_session()` opens the configured application store (DATABASE_URL, else DATABASE_PATH,
else data/app.db) and starts a rollback transaction. Schema is provisioned only at the DATABASE
step. Pass the yielded database into the feature; setup, action, and assertions share that
connection. The fixture always rolls back, including on assertion failure; rollback errors fail
the criterion. It never creates a temporary database or applies schema. Default application
operations remain autocommitted. `committed_session()` (Go: `OpenCommittedSession(ctx, "")`)
opens that same store with autocommit and closes the connection; the criterion owns business
cleanup. HTTP, subprocess, multi-connection, and durability checks use
committed operations with criterion-owned identifiers and idempotent recovery/cleanup through
supported interfaces; never reset the database or delete unrelated records.

---

## You do not write the access layer

Drydock generates the persistence package from `DATABASE.md` and copies the PostgreSQL engine in
unchanged. Connection handling, parameter binding, `RETURNING`, and row mapping all live there. A
hand-written cursor, connection pool, or SQL string is a review failure.

**By language**

| Language | Adapter | What the build writes |
|---|---|---|
| Python | `Rigging/languages/python/persistence/postgres.py`, shipped | callers only — `db.<table>.<verb>(...)` |
| Go | `Rigging/languages/go/persistence/postgres.go`, shipped | typed callers; declarations and fixtures are generated |
| other languages | none yet | a Target declaring `DATABASE.md` fails before planning |

The Python engine imports its DB-API driver lazily and accepts `psycopg` or `psycopg2`. Add
`psycopg[binary]` to the project's dependencies when the production DSN is PostgreSQL.

## Role

PostgreSQL is the production engine. It is selected at runtime from a `postgresql://` DSN; the
same build runs SQLite in development and test.

## What it enforces that SQLite does not

- **Column length.** `VARCHAR(n)` is real. A value longer than `n` is rejected.
- **Types.** A column accepts only its declared type.
- **Creation order.** A referenced table must exist before the table citing it. Drydock emits
  `CREATE TABLE` in dependency order for this reason, and refuses a foreign-key cycle.

Because of the first two, a green SQLite test is not evidence about lengths or types. Treat
PostgreSQL as the authority on both.

## Schema changes

Within a release the schema is built once, at the DATABASE build step, and never migrated.
Across releases PostgreSQL does support the changes that matter: `ALTER TABLE … ALTER COLUMN …
TYPE varchar(n)` widens without a table rewrite, and `DROP NOT NULL` is instant while
`SET NOT NULL` scans the table.

## Guardrails

- Never import `psycopg` or `psycopg2` outside the generated `persistence/` package.
- Never build SQL by formatting values into a string; the engine binds parameters.
- Never create or alter schema at application startup.
- Never store credentials in the repository; the DSN comes from the environment through the typed
  `Config` class.

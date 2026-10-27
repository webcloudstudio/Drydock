<!-- Compacted from Rigging/stack/sqlite.md sha256=29724e729a440b297d34d0c623e656b802beb57bb9feb1ba25518aa47a1eb860 on 2026-10-24 by drydock rigging compact — regenerate with: drydock rigging compact --include-file {rel_source} -->

## Database process — Python

**Where is the schema?**
Drydock generates `<application root>/schema.sql` from `DATABASE.md` and the `persistence/` package.
Do not write or replace either artifact.

**How do I initialize a selected store?**
Call `persistence.initialize_database(dsn)` and close the returned database.
This creates missing tables and indexes, preserves rows, and does not migrate existing tables.

**How do I open a store?**
Call `persistence.open_database(dsn)` and close the returned database. Opening does not initialize it.
Use the application configuration: `DATABASE_URL`, then `DATABASE_PATH`, then `data/app.db`.

**How do I run tests?**
Use the inherited `DATABASE_URL` and `DATABASE_PATH`; Drydock supplies a disposable SQLite store
for the build agent and a separate store per pytest test. Use `persistence.testing.db_session()`
for ordinary persistence tests. Do not hardcode or directly inspect `data/app.db`.

**How do I test initialization of a fresh store?**
Use `from drydock_acceptance import database_environment` and
`with database_environment(url="init.db") as root:`. Call the product's init command inside the
context; the helper supplies a temporary directory and DSN but does not create the schema.
Drydock supplies this helper to acceptance criteria and build agents. The normal acceptance
runner remains responsible for the authoritative criterion result.

**How do I inspect data?**
Use generated repository operations on the configured test store. Do not import SQLite drivers
or author SQL in application code. Never remove or replace a managed application store.


## Foundation Contract

The published Python binding follows. Go callers use the language-native API in
`languages/go/go.md`; Go tests run through the existing Blueprint AC container.
Carried verbatim into `sqlite_compact.md`.

- package: persistence
- entry: open_database(dsn) -> Database
- fixture: db_session
- fixture_source: persistence/testing.py

### How is this engine configured and initialized?

For the shipped Python binding, use the standard-library `sqlite3` driver and a file path or
`sqlite://` DSN. Configuration resolves `DATABASE_URL`, then `DATABASE_PATH`, then `data/app.db`.
Drydock provisions the build store at the DATABASE step; later acceptance verifies it without
reprovisioning. Explicit Python init uses `persistence.initialize_database(dsn)` to apply generated
`schema.sql` to a newly selected store, creating missing tables/indexes and preserving data. Declare
schema changes in `DATABASE.md`; rebuilding applies idempotent creation statements, not a
migration of existing tables. The engine owns connections and enables foreign keys.

### How does this engine implement the shared persistence contract?

The shipped Python binding is `Rigging/languages/python/persistence/sqlite.py`, used through `persistence.db` and
`open_database(dsn)`. Call declared table operations and use `db_session()` for criteria; do not
import the driver in application code. SQLite does not prove PostgreSQL length/type enforcement.
Library verification is in `tests/test_shipped_database.py`; verify Target-specific operations
separately. The Go binding is `languages/go/persistence/sqlite.go`, verified against this engine.
Use `OpenDatabase(ctx, dsn)` and generated typed methods; `OpenSession(ctx, dsn)` supplies
a test store. The Go library is linked as `drydock.local/persistence`. The detailed Python interface follows.

**How the Python binding is built.** Drydock builds this foundation deterministically. No build agent writes,
edits, or replaces any file listed below.

1. Plan declares the store in `DATABASE.md`: every table, every column, and each access pattern's
   `Repository operation` as `<table>.<verb>`.
2. Plan emits the story that implements `DATABASE.md`, with `persistence.md` and `sqlite.md` in
   `stack:`. That story is the DATABASE step. Its builder writes no persistence code.
3. Before that story's step runs, Drydock writes the package into the build root, so a story in
   the same step can import it:

| Layer | File | Origin |
|---|---|---|
| Library | `persistence/db.py` | shipped `Rigging/languages/python/persistence/db.py`, copied unchanged: `Database`, statement construction, parameter binding, engine selection |
| Engines | `persistence/sqlite.py`, `persistence/postgres.py` | shipped, copied unchanged; the DSN selects one at runtime |
| Declaration | `persistence/schema.py` | generated from `DATABASE.md`: `SCHEMA` (tables, operations, row dataclasses) and `open_database(dsn)`; contains no SQL |
| Interface | `persistence/__init__.py` | generated; exports `Database`, `PersistenceError`, `UnknownOperation`, `SCHEMA`, `open_database`, `initialize_database` |
| Verification | `schema-verification.json` | generated runtime catalog and count probes |
| Fixture | `persistence/testing.py` | generated; `db_session()` |
| DDL | `schema.sql` | generated from `DATABASE.md`; `CREATE ... IF NOT EXISTS` throughout |

4. Drydock applies `schema.sql` through `open_database` to the configured store — `DATABASE_URL`,
   else `DATABASE_PATH`, else `data/app.db` — at the DATABASE step. Later acceptance verifies
   without provisioning. Explicit Python init can initialize another selected store through
   `initialize_database(dsn)`; the application never authors SQL or replaces generated schema.

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
else data/app.db). Schema is provisioned only at the DATABASE step. Pass the yielded database into
the feature. Under the acceptance harness, every database the criterion's process opens, including
this fixture, the application behind `web_client()`, and commands run through `cli_runner()`, joins
one transaction that the harness rolls back when the criterion ends, pass or fail. Leaving the
`with` block rolls nothing back, so a later request still sees the setup. Outside the harness (the
project's pytest suite) the fixture starts its own transaction and rolls it back on exit. It never
creates a temporary database or applies schema. `committed_session()` opens the same store with
autocommit for project tests that need committed state, and joins the harness transaction under
acceptance. A process the criterion launches cannot see that transaction and must not depend on
its rows. Never reset the database or delete unrelated records.

---

# SQLite — Contract Surface

## Connection

### config_key: SQLite DSN
SQLite accepts a plain filesystem path or a `sqlite://` DSN for runtime database selection.

Constraints: The same build must support SQLite for development and testing and PostgreSQL for production through the configured DSN.

## Schema Rules

### Rule: enforced-constraints
SQLite enforces `PRIMARY KEY`, `NOT NULL`, `UNIQUE`, `DEFAULT`, and `REFERENCES` when foreign keys are enabled.

### Rule: production-length-validation
SQLite accepts values exceeding declared column lengths; production PostgreSQL may reject them.

Constraints: Declare production column lengths and do not rely on SQLite to validate them.

### Rule: type-validation
SQLite permits values of any type in any column.

Constraints: SQLite tests do not prove production column-type validity.

### Rule: schema-migrations
SQLite supports only `ADD COLUMN` and `RENAME` for `ALTER TABLE`; it does not support type changes or `ADD CONSTRAINT`.

Constraints: Build the schema once from `schema.sql` during the DATABASE build step.

## Access

### Rule: generated-access-layer
Consumers access persistence through the generated persistence package.

Constraints: Do not import `sqlite3`, create handwritten connection helpers, cursors, or SQL strings outside the generated `persistence/` package; do not retain database connections on application objects; do not create or alter schema at application startup.

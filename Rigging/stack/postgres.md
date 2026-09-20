# PostgreSQL

**Version:** 20260919 V3
**Category:** Persistence
**Foundation:** database
**Description:** PostgreSQL as a Drydock store: what it enforces, how it differs from SQLite, and how a Target reaches it.

Technology reference. This file does not change between projects.

Prerequisite: `stack/persistence.md`

---

## Foundation Contract

The published shape of this foundation. Drydock synthesizes the story that builds it and every
acceptance criterion writes against these names. Carried verbatim into `postgres_compact.md`.

- package: persistence
- entry: open_session() -> Session
- fixture: db_session
- fixture_source: conftest.py

```python
# conftest.py
import pytest
from persistence import open_session

@pytest.fixture
def db_session():
    with open_session() as session:
        yield session
```

A criterion calls `db_session`; it never opens a connection itself.

---

## You do not write the access layer

Drydock generates the persistence package from `DATABASE.md` and copies the PostgreSQL engine in
unchanged. Connection handling, parameter binding, `RETURNING`, and row mapping all live there. A
hand-written cursor, connection pool, or SQL string is a review failure.

**By language**

| Language | Adapter | What the build writes |
|---|---|---|
| Python | `Rigging/database/postgres.py`, shipped | callers only — `db.<table>.<verb>(...)` |
| anything else | none yet | nothing; a Target declaring a `DATABASE.md` in another language fails before planning |

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

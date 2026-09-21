<!-- Compacted from Rigging/stack/postgres.md sha256=444759d5eb24ba719a30ee6854624c14af7b33d788963eceb6dcfc44884b5aa6 on 2026-09-20 by drydock rigging compact — regenerate with: drydock rigging compact --include-file {rel_source} -->

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

# PostgreSQL — Contract Surface

### db.<table>.<verb>

Call the generated Python persistence package through table-scoped verbs.

Constraints: Do not write a hand-coded access layer, cursor, connection pool, or SQL string.

### DATABASE.md

Declare the database schema in `DATABASE.md`.

Constraints: PostgreSQL tables are emitted in dependency order; foreign-key cycles are refused.

### postgresql://

Select PostgreSQL at runtime with a `postgresql://` DSN.

Constraints: Provide the DSN through the typed `Config` class from the environment; never store credentials in the repository.

### Python adapter

Use `Rigging/database/postgres.py` as the shipped PostgreSQL adapter.

Constraints: Add `psycopg[binary]` to project dependencies when the production DSN is PostgreSQL. Import `psycopg` or `psycopg2` only inside the generated `persistence/` package.

### Rule: PostgreSQL type enforcement

PostgreSQL rejects values exceeding `VARCHAR(n)` limits and values incompatible with declared column types.

Constraints: SQLite test success does not establish PostgreSQL length or type compatibility.

### Rule: schema lifecycle

Build the schema once at the DATABASE build step.

Constraints: Do not create or alter schema at application startup; schema changes are not migrated within a release.

<!-- Compacted from Rigging/stack/postgres.md sha256=ad71aaa597c50f7d153c7aeb345d69973898dcbdad61fa42600772664b44ec50 on 2026-09-20 by drydock rigging compact — regenerate with: drydock rigging compact --include-file {rel_source} -->

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

## Persistence

### config_key `postgresql://` DSN
Selects PostgreSQL as the production database engine at runtime.

Constraints: The DSN is supplied through the environment via the typed `Config` class; credentials must not be stored in the repository.

### `db.<table>.<verb>(...)`
Provides the generated persistence API for callers to access database tables.

Constraints: Callers must not write hand-crafted cursors, connection pools, SQL strings, parameter binding, row mapping, or `RETURNING` handling.

### Rule: postgres-dependencies
A Python project using a production PostgreSQL DSN must declare `psycopg[binary]` as a dependency; the engine accepts `psycopg` or `psycopg2`.

### Rule: supported-language
Only Python Targets may declare `DATABASE.md`; a Target using another language fails before planning.

### Rule: schema-order
Referenced tables must be created before tables that cite them, and foreign-key cycles are rejected.

### Rule: schema-lifecycle
The schema is created once during the DATABASE build step; applications must not create or alter schema at startup.

### Rule: type-enforcement
PostgreSQL enforces declared column types and `VARCHAR(n)` lengths; values exceeding a declared length are rejected.

### Rule: access-boundary
`psycopg` and `psycopg2` may be imported only within the generated `persistence/` package.

### Rule: parameter-binding
SQL values must be passed as bound parameters and never formatted directly into SQL strings.

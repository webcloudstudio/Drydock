<!-- Compacted from Rigging/stack/sqlite.md sha256=174baecf981b6326cb08968b69481ded0b4f5fe8163f02a1e22f6bc2d7481d3e on 2026-09-20 by drydock rigging compact — regenerate with: drydock rigging compact --include-file {rel_source} -->

## Foundation Contract

The published shape of this foundation. Drydock synthesizes the story that builds it and every
acceptance criterion writes against these names. Carried verbatim into `sqlite_compact.md`.

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

A criterion calls `db_session`; it never opens a connection itself and never imports `sqlite3`.

---

# SQLite — Contract Surface

### config_key

Configure the database using a plain SQLite path or a `sqlite://` DSN.

Constraints: Runtime selection also supports PostgreSQL through the DSN; non-Python Targets declaring `DATABASE.md` fail before planning.

### Rule: access-layer-boundary

Call persistence through `db.<table>.<verb>(...)`; do not write hand-coded connection helpers, cursors, or SQL strings.

Constraints: Only the generated `persistence/` package may import `sqlite3`.

### Rule: schema-enforcement

SQLite enforces `PRIMARY KEY`, `NOT NULL`, `UNIQUE`, `DEFAULT`, and `REFERENCES` with foreign keys enabled.

Constraints: The schema is built once from `schema.sql`; application startup must not create or alter schema.

### Rule: production-validation

Declare column lengths and types for the production engine because SQLite does not enforce length or strict types.

Constraints: A passing SQLite test does not prove production column lengths or types.

### Rule: migration-support

SQLite schema changes support only `ADD COLUMN` and `RENAME`.

Constraints: Do not rely on `DROP COLUMN`, type changes, or `ADD CONSTRAINT`.

<!-- Compacted from Rigging/stack/sqlite.md sha256=99cf06148c6e5e7fee5ebe5f5531b1fc0a708fddc58dc294783820ba2d288ef4 on 2026-09-20 by drydock rigging compact — regenerate with: drydock rigging compact --include-file {rel_source} -->

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

### config_key: DATABASE.md language

Declaring `DATABASE.md` for a non-Python language fails before planning.

Constraints: Python is the supported language; other languages have no adapter.

### config_key: SQLite DSN

SQLite accepts a plain filesystem path or a `sqlite://` DSN.

### Rule: enforced-constraints

SQLite enforces `PRIMARY KEY`, `NOT NULL`, `UNIQUE`, `DEFAULT`, and `REFERENCES`.

Constraints: Foreign-key enforcement is enabled.

### Rule: unsupported-validation

SQLite does not enforce column lengths or strict column types.

Constraints: Do not rely on SQLite tests to validate production column lengths or types.

### Rule: schema-migrations

SQLite supports only `ADD COLUMN` and `RENAME` among the documented schema alterations.

Constraints: Schema is built once from `schema.sql`; `DROP COLUMN` before SQLite 3.35, type changes, and `ADD CONSTRAINT` are unsupported.

### Rule: persistence-access

Application callers use the generated persistence package through `db.<table>.<verb>(...)`.

Constraints: Do not import `sqlite3` outside `persistence/`; do not retain a `sqlite3.Connection` on application objects; do not create or alter schema at application startup.

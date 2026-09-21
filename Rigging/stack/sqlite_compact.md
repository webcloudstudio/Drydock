<!-- Compacted from Rigging/stack/sqlite.md sha256=ba89984c1d3686e1167765f77153509d066f6a94b2a9950b66a64441e60c961d on 2026-09-20 by drydock rigging compact — regenerate with: drydock rigging compact --include-file {rel_source} -->

## Foundation Contract

The published shape of this foundation. Drydock synthesizes the story that builds it and every
acceptance criterion writes against these names. Carried verbatim into `sqlite_compact.md`.

- package: persistence
- entry: open_session() -> Session
- fixture: db_session
- fixture_source: persistence/testing.py

```python
# persistence/testing.py
from contextlib import contextmanager
from persistence import open_session

@contextmanager
def db_session():
    with open_session() as session:
        yield session

# conftest.py
import pytest
from persistence import testing

@pytest.fixture
def db_session():
    with testing.db_session() as session:
        yield session
```

A criterion imports `db_session` from `persistence.testing` and uses it as a context manager —
`with db_session() as session:` — against the built database layer, without pytest. The pytest
suite receives the same session through the `conftest.py` fixture. Neither opens a connection
of its own, and a criterion never imports `sqlite3`.

---

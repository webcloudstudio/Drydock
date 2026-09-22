<!-- Compacted from Rigging/stack/postgres.md sha256=9864f69f53347f61b0a5caf1d7eac7266327ce840e8f45a5e79bbe74a44b89bc on 2026-09-20 by drydock rigging compact — regenerate with: drydock rigging compact --include-file {rel_source} -->

## Foundation Contract

The published shape of this foundation. Drydock synthesizes the story that builds it and every
acceptance criterion writes against these names. Carried verbatim into `postgres_compact.md`.

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
of its own.

---

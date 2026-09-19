"""PostgreSQL engine for ``db.py``.

Shipped by Drydock and copied into the build unchanged. Do not edit it here.

PostgreSQL is the production engine: it enforces ``VARCHAR(n)`` length, requires a referenced
table to exist before the table citing it, and returns a generated key through ``RETURNING``
rather than through a cursor attribute.
"""

from __future__ import annotations

import threading
from typing import Any

try:
    from .db import Driver, PersistenceError
except ImportError:  # flat layout
    from db import Driver, PersistenceError

__all__ = ["PostgresDriver"]


class PostgresDriver(Driver):
    """One connection per thread, opened on first use, matching the SQLite caller contract."""

    paramstyle = "format"
    returning = True

    def __init__(self, dsn: str) -> None:
        self._dsn = dsn
        self._local = threading.local()

    def connect(self) -> Any:
        connection = getattr(self._local, "connection", None)
        if connection is None:
            connection = _driver_module().connect(self._dsn)
            self._local.connection = connection
        return connection

    def close(self) -> None:
        connection = getattr(self._local, "connection", None)
        if connection is not None:
            connection.close()
            self._local.connection = None

    def inserted_key(self, cursor: Any) -> Any:
        row = cursor.fetchone()
        return row[0] if row else None


def _driver_module() -> Any:
    """Import the DB-API driver lazily, so this file imports without PostgreSQL installed."""
    try:
        import psycopg  # type: ignore[import-not-found]
    except ImportError:
        try:
            import psycopg2 as psycopg  # type: ignore[import-not-found,no-redef]
        except ImportError as exc:
            raise PersistenceError(
                "PostgreSQL was selected by the DSN but no driver is installed. "
                "Add `psycopg[binary]` to the project's dependencies."
            ) from exc
    return psycopg

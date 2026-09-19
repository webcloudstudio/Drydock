"""SQLite engine for ``db.py``.

Shipped by Drydock and copied into the build unchanged. Do not edit it here.

SQLite is the development and test engine. It parses the same declaration PostgreSQL does and
ignores what it does not enforce — ``VARCHAR(n)`` length in particular — so one rendered schema
serves both engines and nothing is stripped for one of them.
"""

from __future__ import annotations

import sqlite3
import threading
from pathlib import Path
from typing import Any

try:
    from .db import Driver
except ImportError:  # flat layout
    from db import Driver

__all__ = ["SqliteDriver"]


class SqliteDriver(Driver):
    """One connection per thread, opened on first use in that thread.

    A ``sqlite3.Connection`` belongs to the thread that created it and raises ``ProgrammingError``
    when used from another, so a single connection opened during construction is valid in no web
    request at all. This is not concurrency: queries stay sequential within a workflow, and the
    rule only stops one connection being shared across unrelated ones.
    """

    paramstyle = "qmark"
    returning = False

    def __init__(self, dsn: str) -> None:
        self._path = _path_from(dsn)
        self._local = threading.local()

    def connect(self) -> sqlite3.Connection:
        connection = getattr(self._local, "connection", None)
        if connection is None:
            if self._path != ":memory:":
                Path(self._path).parent.mkdir(parents=True, exist_ok=True)
            connection = sqlite3.connect(self._path)
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("PRAGMA foreign_keys=ON")
            self._local.connection = connection
        return connection

    def close(self) -> None:
        connection = getattr(self._local, "connection", None)
        if connection is not None:
            connection.close()
            self._local.connection = None

    def inserted_key(self, cursor: Any) -> Any:
        return cursor.lastrowid


def _path_from(dsn: str) -> str:
    """Read a filesystem path out of a DSN, accepting a bare path as well as a URL."""
    if "://" not in dsn:
        return dsn or ":memory:"
    _, _, remainder = dsn.partition("://")
    return remainder or ":memory:"

# Database Adapters

**Version:** 20260919 V1
**Category:** Persistence
**Description:** Shipped persistence source copied into a build unchanged, one file per engine.

This directory is not guidance. Every other Rigging file is Markdown a build agent reads; these
are Python files Drydock copies into the Target. They are hardened and tested once, in Drydock's
own suite (`tests/test_shipped_database.py`), so every Target inherits a persistence layer that
has already passed rather than one re-derived from prose on each build.

| File | Responsibility |
|---|---|
| `db.py` | Public `Database`, the declared-table surface, statement construction, driver selection |
| `sqlite.py` | SQLite engine: thread-local connection, PRAGMAs, `?` parameters, `lastrowid` |
| `postgres.py` | PostgreSQL engine: `%s` parameters, `RETURNING`, lazy driver import |

`schema.py` sits beside them in the build and is **generated** from `DATABASE.md`. It carries the
tables, the operations, and the row dataclasses, and contains no SQL. Statements are constructed
by the driver for the engine in use, so a parameter placeholder never appears in generated code
or in a caller.

Both engines are copied into every build and selected at runtime from the DSN, because the same
build runs SQLite in test and PostgreSQL in production. `VARCHAR(n)` is emitted to both: Postgres
enforces the length, SQLite parses the same declaration and ignores it, and nothing is stripped
for either.

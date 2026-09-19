# SQLite

**Version:** 20260919 V3
**Category:** Persistence
**Description:** SQLite as a Drydock store: what it enforces, what it ignores, and how a Target reaches it.

Technology reference. This file does not change between projects.

Prerequisite: `stack/persistence.md`

---

## You do not write the access layer

Drydock generates the persistence package from `DATABASE.md` and copies the SQLite engine in
unchanged. Connection handling, thread discipline, PRAGMAs, parameter binding, and row mapping all
live there. A hand-written connection helper, cursor, or SQL string is a review failure.

**By language**

| Language | Adapter | What the build writes |
|---|---|---|
| Python | `Rigging/database/sqlite.py`, shipped | callers only — `db.<table>.<verb>(...)` |
| anything else | none yet | nothing; a Target declaring a `DATABASE.md` in another language fails before planning |

## Role

SQLite is the development and test engine. It is a file, it needs no server, and it opens from a
plain path or a `sqlite://` DSN. Production relational storage is PostgreSQL; see
`stack/postgres.md`.

Both engines are copied into every build and selected at runtime from the DSN, so the same build
runs SQLite in test and PostgreSQL in production without rebuilding.

## What it enforces

`PRIMARY KEY`, `NOT NULL`, `UNIQUE`, `DEFAULT`, and — with `PRAGMA foreign_keys=ON`, which the
shipped engine sets — `REFERENCES`.

## What it ignores

**Column length.** SQLite has type affinity, not length. `VARCHAR(50)` parses and is stored as
`TEXT`, and a 500-character value is accepted. The same declaration is emitted to PostgreSQL,
which does enforce it, so **a length violation passes in test and fails in production.** Declare
lengths for the production engine and do not rely on SQLite to catch them.

**Type strictness.** Any value may be stored in any column. A test that passes on SQLite has not
proven the column types.

**`ALTER TABLE`.** Only `ADD COLUMN` and `RENAME` are supported; there is no `DROP COLUMN` before
3.35, no type change, and no `ADD CONSTRAINT`. Within a release this never arises — the schema is
built once, at the DATABASE build step, from `schema.sql`.

## Guardrails

- Never import `sqlite3` outside the generated `persistence/` package.
- Never hold a `sqlite3.Connection` on an application object; the engine owns connection lifetime.
- Never create or alter schema at application startup.
- Never treat a green SQLite test as proof that column lengths or types hold in production.

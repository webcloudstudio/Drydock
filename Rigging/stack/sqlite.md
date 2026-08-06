# SQLite Best Practices

**Version:** 20260603 V1  
**Category:** Persistence
**Description:** SQLite database patterns: schema, queries, migrations, and connection management

Technology reference for SQLite in Python applications. This file does not change between projects.

Prerequisites: `stack/python.md`, `stack/persistence.md`

**Encapsulation**: the connection, helpers, and migrations below are the *internals* of the
`Database`/table classes defined in `stack/persistence.md`. Application code calls
`db.<table>.method()` — it never calls `get_db()`, `query()`, or `execute()` directly.

---

## Connection Setup

**Rule**: Always enable WAL mode, foreign keys, and use Row factory.

`get_db()` is the *configuration* helper. It opens and configures one connection; it does not
decide who holds it. `Database.connect()` in `stack/persistence.md` §1 calls it once per thread.

```python
import sqlite3
import os

def get_db(db_path):
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA journal_mode=WAL')
    conn.execute('PRAGMA foreign_keys=ON')
    return conn
```

### PRAGMAs

| PRAGMA | Value | Why |
|--------|-------|-----|
| `journal_mode=WAL` | Write-Ahead Logging | Allows concurrent reads during writes |
| `foreign_keys=ON` | Enforce FK constraints | SQLite disables FK enforcement by default |

### Threads

**Rule**: The result of `get_db()` belongs to the calling thread. Never cache it on an object
that other threads reach.

This rule is not about writing concurrent code. Application code stays sequential. A web server
hands each request to a worker thread on its own, so an application acquires threads whether or
not it ever uses them, and the only requirement is that each one gets its own connection.

A `sqlite3.Connection` is bound to its creating thread. Using it elsewhere raises:

```
sqlite3.ProgrammingError: SQLite objects created in a thread can only be used in that same thread.
```

This is the default failure mode for any threaded server. The application is constructed on the
main thread; each request is handled on a worker thread. A connection opened during construction
and cached on a module-level or instance attribute works in every single-threaded unit test and
fails on the first HTTP request. Hold one connection per thread — see `stack/persistence.md` §1.

WAL is what makes per-thread connections worth having: each thread's connection reads
concurrently while another writes.

`check_same_thread=False` is **not** the fix. It disables the safety check without making the
connection safe, leaving cursor and transaction state shared across threads. If a single shared
connection is genuinely required, it needs an explicit lock around every statement — which
serializes reads and discards the benefit of WAL.

Startup work — `initialize()`, `_run_migrations()`, seeding — runs on whichever thread starts the
application, against that thread's own connection. That is correct and needs no special handling;
it is simply not the connection request handlers use.

Long-lived worker pools accumulate one connection per thread. That is acceptable at the
single-server scale SQLite is recommended for below.

---

## Schema Design

**Rule**: Use `TEXT` for dates (ISO 8601), `INTEGER` for booleans, and a JSON `TEXT` column for extensible fields.

```sql
CREATE TABLE IF NOT EXISTS items (
    id          INTEGER PRIMARY KEY,
    name        TEXT UNIQUE NOT NULL,
    status      TEXT DEFAULT 'active',
    extra       TEXT DEFAULT '{}',        -- JSON for extensible fields
    created_at  TEXT DEFAULT (datetime('now')),
    updated_at  TEXT DEFAULT (datetime('now'))
);
```

### JSON Column Pattern

```python
import json

def get_extra(row):
    return json.loads(row['extra'] or '{}')

def set_extra(db, item_id, key, value):
    row = db.execute('SELECT extra FROM items WHERE id = ?', (item_id,)).fetchone()
    extra = json.loads(row['extra'] or '{}')
    extra[key] = value
    db.execute('UPDATE items SET extra = ? WHERE id = ?', (json.dumps(extra), item_id))
    db.commit()
```

**Why**: JSON columns let you add fields without migrations.

---

## Queries

**Rule**: Always use parameterized queries. Never interpolate user input into SQL.

```python
# CORRECT — parameterized
db.execute('SELECT * FROM items WHERE id = ?', (item_id,))
db.execute('INSERT INTO items (name, status) VALUES (?, ?)', (name, status))

# NEVER — string interpolation
db.execute(f"SELECT * FROM items WHERE id = {item_id}")  # SQL INJECTION
```

### Helper Patterns

```python
def row_to_dict(row):
    """Convert sqlite3.Row to dict, parsing JSON columns."""
    if row is None:
        return None
    d = dict(row)
    if 'extra' in d:
        d['extra'] = json.loads(d['extra'] or '{}')
    return d

def query(db, sql, params=(), one=False):
    rows = db.execute(sql, params).fetchall()
    if one:
        return row_to_dict(rows[0]) if rows else None
    return [row_to_dict(r) for r in rows]

def execute(db, sql, params=()):
    cursor = db.execute(sql, params)
    db.commit()
    return cursor.lastrowid
```

---

## Migrations

**Rule**: Run migrations at startup using `PRAGMA table_info()` to detect missing columns.

```python
def _run_migrations(db):
    """Add columns that don't exist yet. Runs on every startup."""
    columns = {r['name'] for r in db.execute('PRAGMA table_info(items)').fetchall()}

    migrations = [
        ('new_field', 'ALTER TABLE items ADD COLUMN new_field TEXT DEFAULT ""'),
        ('priority',  'ALTER TABLE items ADD COLUMN priority INTEGER DEFAULT 0'),
    ]

    for col_name, sql in migrations:
        if col_name not in columns:
            db.execute(sql)

    db.commit()
```

### New Table Detection

```python
def _table_exists(db, table_name):
    row = db.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
        (table_name,)
    ).fetchone()
    return row is not None
```

**Why**: Startup migrations avoid manual schema management. `PRAGMA table_info` is idempotent.

---

## Limitations

| Scenario | SQLite OK? | Alternative |
|----------|-----------|-------------|
| Single-server web app | Yes | — |
| Local tool / CLI | Yes | — |
| Multiple concurrent writers | No | PostgreSQL |
| Multi-server deployment | No | PostgreSQL |
| Dataset > 1GB | Maybe | PostgreSQL |
| Full-text search (heavy) | Maybe | PostgreSQL + pg_trgm |

---

## Backup

**Rule**: Use file copy with WAL checkpoint first.

```python
import shutil

def backup_database(db_path, backup_dir='data/backups'):
    os.makedirs(backup_dir, exist_ok=True)
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    backup_path = os.path.join(backup_dir, f'backup_{timestamp}.db')

    conn = sqlite3.connect(db_path)
    conn.execute('PRAGMA wal_checkpoint(TRUNCATE)')
    conn.close()

    shutil.copy2(db_path, backup_path)
    return backup_path
```

**Why**: WAL checkpoint flushes pending writes before copying.

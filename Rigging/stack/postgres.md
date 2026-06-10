# PostgreSQL Best Practices

**Version:** 20260320 V1  
**Description:** PostgreSQL database patterns: schema, queries, and connection management

Technology reference for PostgreSQL in Python applications. This file does not change between projects.

Prerequisites: `stack/python.md`

---

## Connection Setup

**Rule**: Use `psycopg2` with connection pooling. Store connection string in environment variable.

```python
import os
import psycopg2
from psycopg2.extras import RealDictCursor
from psycopg2.pool import SimpleConnectionPool

DATABASE_URL = os.environ['DATABASE_URL']

pool = SimpleConnectionPool(minconn=1, maxconn=10, dsn=DATABASE_URL)

def get_db():
    conn = pool.getconn()
    conn.autocommit = False
    return conn

def release_db(conn):
    pool.putconn(conn)
```

### With Context Manager

```python
from contextlib import contextmanager

@contextmanager
def db_connection():
    conn = pool.getconn()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        pool.putconn(conn)
```

**Why**: Connection pooling avoids overhead. Context manager ensures proper commit/rollback.

---

## Schema Design

**Rule**: Use native types (TIMESTAMP, BOOLEAN, JSONB). Use JSONB for extensible fields.

```sql
CREATE TABLE IF NOT EXISTS items (
    id          SERIAL PRIMARY KEY,
    name        TEXT UNIQUE NOT NULL,
    status      TEXT DEFAULT 'active',
    extra       JSONB DEFAULT '{}',
    created_at  TIMESTAMP DEFAULT NOW(),
    updated_at  TIMESTAMP DEFAULT NOW()
);

CREATE OR REPLACE FUNCTION update_timestamp()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER items_updated
    BEFORE UPDATE ON items
    FOR EACH ROW
    EXECUTE FUNCTION update_timestamp();
```

### JSONB Queries

```sql
SELECT * FROM items WHERE extra->>'tech_stack' = 'flask';
UPDATE items SET extra = jsonb_set(extra, '{port}', '8080') WHERE id = 1;
SELECT * FROM items WHERE extra ? 'workflow';
```

**Why**: JSONB is indexable and queryable unlike plain TEXT JSON.

---

## Queries

**Rule**: Always use parameterized queries with `%s` placeholders. Never interpolate.

```python
# CORRECT
cursor = db.execute('SELECT * FROM items WHERE id = %s', (item_id,))

# NEVER
db.execute(f"SELECT * FROM items WHERE id = {item_id}")
```

### Helper Patterns

```python
def query(sql, params=(), one=False):
    with db_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(sql, params)
            if one:
                return cur.fetchone()
            return cur.fetchall()

def execute(sql, params=()):
    with db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            if cur.description:
                return cur.fetchone()
            return cur.rowcount
```

---

## Migrations

**Rule**: Use numbered migration files. Track applied migrations in a table.

```
migrations/
├── 001_initial_schema.sql
├── 002_add_priority_column.sql
└── 003_create_audit_table.sql
```

```python
def run_migrations(db):
    db.execute('''
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version INTEGER PRIMARY KEY,
            applied_at TIMESTAMP DEFAULT NOW()
        )
    ''')
    db.commit()

    applied = {r[0] for r in db.execute('SELECT version FROM schema_migrations').fetchall()}

    migration_files = sorted(glob.glob('migrations/*.sql'))
    for f in migration_files:
        version = int(os.path.basename(f).split('_')[0])
        if version not in applied:
            with open(f) as sql_file:
                db.execute(sql_file.read())
            db.execute('INSERT INTO schema_migrations (version) VALUES (%s)', (version,))
            db.commit()
            logger.info('Applied migration %s', f)
```

**Why**: Numbered files are auditable, version-controlled, reproducible.

---

## Indexing

**Rule**: Index columns in WHERE, JOIN, ORDER BY. Use partial indexes for filtered queries.

```sql
CREATE INDEX idx_items_status ON items(status);
CREATE INDEX idx_items_active ON items(status) WHERE status = 'active';
CREATE INDEX idx_items_tech ON items USING GIN (extra);
```

---

## Backup

**Rule**: Use `pg_dump` for logical backups. Schedule via bin/ scripts.

```bash
#!/bin/bash
# CommandCenter Operation
# Name: Database Backup
# Type: batch

set -euo pipefail
TIMESTAMP=$(date '+%Y%m%d_%H%M%S')
BACKUP_DIR="data/backups"
mkdir -p "$BACKUP_DIR"

pg_dump "$DATABASE_URL" > "$BACKUP_DIR/backup_${TIMESTAMP}.sql" 2>&1

# Keep last 7 backups
ls -t "$BACKUP_DIR"/backup_*.sql | tail -n +8 | xargs -r rm
```

---

## When to Use PostgreSQL Over SQLite

| Need | Use PostgreSQL |
|------|---------------|
| Multiple concurrent writers | Yes |
| Multi-server deployment | Yes |
| Full-text search | Yes |
| JSONB with indexing | Yes |
| Dataset > 1GB | Yes |
| Complex queries (CTEs, window functions) | Yes |

For single-server tools, prefer SQLite (see `stack/sqlite.md`).

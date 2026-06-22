<!-- Compacted from postgres.md on 2026-06-22 by drydock rigging compact — regenerate with: drydock rigging compact --include-file {rel_source} -->

# PostgreSQL Best Practices — Usage Surface

## Configuration

### DATABASE_URL

Environment variable holding the PostgreSQL connection string used to initialize the connection pool.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| DATABASE_URL | str (env var) | yes | PostgreSQL DSN, e.g. `postgresql://user:pass@host/db` |

Returns: N/A — read at module load time

---

## Connection

### get_db

Returns a connection from the pool with `autocommit=False`.

Returns: `psycopg2.connection` — pooled connection; caller must commit/rollback and call `release_db`

### release_db

Returns a connection to the pool.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| conn | psycopg2.connection | yes | Connection previously obtained from `get_db` |

Returns: `None`

### db_connection

Context manager that yields a connection, commits on success, and rolls back on exception.

Returns: `psycopg2.connection` — yielded inside `with` block; commit/rollback handled automatically

---

## Queries

### query

Executes a parameterized SELECT and returns one or all rows as dicts.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| sql | str | yes | SQL string with `%s` placeholders |
| params | tuple | no | Positional parameters for placeholders (default `()`) |
| one | bool | no | If `True`, returns a single row; otherwise returns all rows (default `False`) |

Returns: `dict \| list[dict] \| None` — single row dict when `one=True`, list of dicts otherwise

### execute

Executes a parameterized INSERT/UPDATE/DELETE (or any non-SELECT).

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| sql | str | yes | SQL string with `%s` placeholders |
| params | tuple | no | Positional parameters for placeholders (default `()`) |

Returns: `dict \| int` — first row as dict if the statement returns rows; otherwise row count

---

## Migrations

### run_migrations

Applies all unapplied numbered `.sql` files from the `migrations/` directory.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| db | psycopg2.connection | yes | Active database connection |

Returns: `None` — creates `schema_migrations` table if absent; logs each applied file

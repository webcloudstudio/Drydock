<!-- Compacted from Rigging/stack/sqlite.md sha256=cadcfa52c5fa9cbf8a0a92b6a8d230d4888e584b888aaf933c24579f32f651ce on 2026-08-06 by drydock rigging compact — regenerate with: drydock rigging compact --include-file {rel_source} -->

# SQLite Best Practices — Contract Surface

## Connection

### get_db
Opens and configures a SQLite connection for the supplied database path.

| Input | Type | Required |
|---|---|---|
| `db_path` | path | Yes |

Returns a configured `sqlite3.Connection`.

Constraints: Enable WAL mode, foreign-key enforcement, and `sqlite3.Row` row factory. Use one connection per thread; do not share connections across threads or use `check_same_thread=False` as a substitute.

## Schema

### Rule: schema-types
Defines dates as ISO 8601 `TEXT`, booleans as `INTEGER`, and extensible fields as JSON stored in `TEXT` columns.

### items
The `items` table contains the following fields:

| Field | Type | Constraints / Default |
|---|---|---|
| `id` | `INTEGER` | Primary key |
| `name` | `TEXT` | Unique, not null |
| `status` | `TEXT` | Default `'active'` |
| `extra` | `TEXT` | JSON, default `'{}'` |
| `created_at` | `TEXT` | Default current datetime |
| `updated_at` | `TEXT` | Default current datetime |

### get_extra
Parses an item's `extra` field as JSON.

| Input | Type | Required |
|---|---|---|
| `row` | SQLite row containing `extra` | Yes |

Returns a JSON object, defaulting to `{}` when the field is empty.

### set_extra
Updates one key in an item's JSON `extra` field and commits the change.

| Input | Type | Required |
|---|---|---|
| `db` | database connection | Yes |
| `item_id` | item identifier | Yes |
| `key` | JSON object key | Yes |
| `value` | JSON-compatible value | Yes |

## Queries

### row_to_dict
Converts a SQLite row to a dictionary and parses the `extra` JSON field when present.

| Input | Type | Required |
|---|---|---|
| `row` | SQLite row or `None` | Yes |

Returns a dictionary or `None`.

### query
Executes a parameterized SQL query and returns converted rows.

| Input | Type | Default |
|---|---|---|
| `db` | database connection | Required |
| `sql` | SQL string | Required |
| `params` | query parameters | `()` |
| `one` | boolean | `False` |

Returns one dictionary or `None` when `one=True`; otherwise returns a list of dictionaries.

### execute
Executes a parameterized SQL statement and commits it.

| Input | Type | Default |
|---|---|---|
| `db` | database connection | Required |
| `sql` | SQL string | Required |
| `params` | query parameters | `()` |

Returns the statement's `lastrowid`.

### Rule: parameterized-queries
All SQL queries must use parameters; user input must never be interpolated into SQL.

## Migrations

### _run_migrations
Adds missing columns to the `items` table and commits the migration transaction.

Constraints: Run at startup and detect existing columns with `PRAGMA table_info()`; migrations must be idempotent.

### _table_exists
Checks whether a named SQLite table exists.

| Input | Type | Required |
|---|---|---|
| `db` | database connection | Yes |
| `table_name` | table name | Yes |

Returns a boolean.

## Backup

### backup_database
Checkpoints the database WAL and copies the database file into a timestamped backup.

| Input | Type | Default |
|---|---|---|
| `db_path` | database path | Required |
| `backup_dir` | backup directory | `'data/backups'` |

Returns the backup file path.

Constraints: Checkpoint the WAL before copying; create the backup directory when absent.

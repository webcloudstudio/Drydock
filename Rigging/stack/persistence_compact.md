<!-- Compacted from Rigging/stack/persistence.md sha256=0e39be9fcbe467abf4112391c0ab77d95713ee3ae2bca3600c435e40ed9417c7 on 2026-10-23 by drydock rigging compact — regenerate with: drydock rigging compact --include-file {rel_source} -->

# Persistence & Service Encapsulation — Contract Surface

## Relational Persistence

### `db.<table>.<name>`
Executes a declared persistence operation using keyword arguments matching its declared Input fields.

| Input | Type |
|---|---|
| Declared Input fields | `str`, `int`, `float`, `bool`, or `bytes`; optional fields are marked `?` |

Returns the declared Output shape: row, nullable row, list of rows, or changed-row count.

Constraints: Only declared table operations are callable. Unknown operations raise `UnknownOperation`. No raw SQL, joins, OR operators, or alternate store-access paths are permitted outside `persistence/`.

### `db.<table>.get`
Retrieves at most one row by a unique Match key; returns the row or `None`.

### `db.<table>.list`
Retrieves zero or more rows using optional equality filters for supplied Input fields; returns a list of rows.

### `db.<table>.create`
Creates one row using every Input field; returns the created row.

### `db.<table>.update`
Updates supplied non-Match Input fields for rows selected by Match, defaulting to the primary key; returns the row or `None` for a unique match, or a changed-row count for a non-unique match.

### `db.<table>.upsert`
Inserts or replaces a row selected by exactly one unique Match key; returns the resulting row.

### `db.<table>.delete`
Deletes rows selected by Match; returns the Output built from the Match or `None` for a unique match, or a changed-row count for a non-unique match.

### Rule: operation-surface
Build callers from the generated `DATABASE_compact.md` Operation Surface. The operation name, Kind, Match, rows, return shape, Input fields, Output fields, caller types, SQL, and fingerprint are authoritative.

### Rule: database-runtime
The generated package exposes one attribute per declared table and one method per declared operation. Callers use one shared `Database` instance synchronously; returned rows are frozen dataclasses without connection state.

### Rule: engine-selection
SQLite and PostgreSQL engines are available at runtime and selected from the DSN.

### Rule: schema-lifecycle
The generated `schema.sql` is applied once during the DATABASE step. Application startup does not create or alter schema.

### Rule: persistence-guardrails
Do not hand-write repositories, DAOs, ORM models, session factories, migrations, raw SQL, or database-driver imports outside `persistence/`. Do not edit generated `persistence/` files; change `DATABASE.md` and rebuild.

## Configuration

### `Config.load`
Loads and validates environment-backed configuration once at startup.

| Field | Source | Type | Required |
|---|---|---:|---:|
| `secret_key` | `SECRET_KEY` | `str` | yes |
| `database_path` | `DATABASE_PATH` | `str` | no; default `data/app.db` |
| `port` | `APP_PORT` | `int` | no; default `5001` |
| `debug` | `APP_DEBUG` | `bool` | no; `true` only when value is `"1"` |

Returns a frozen typed `Config`. Missing required variables raise `RuntimeError`; malformed typed values fail during startup.

Constraints: Only `Config` reads `os.environ`. Configuration is environment-driven; no Dev, Prod, or Test subclasses exist.

## File Storage

### `FileStore.__init__(root: str)`
Creates a file store rooted at the supplied directory.

### `FileStore.read(name: str)`
Reads and returns the named application file as UTF-8 text.

Returns `str`.

### `FileStore.write(name: str, data: str)`
Writes UTF-8 text to the named application file, creating parent directories as needed.

### `FileStore.list(pattern: str = "*")`
Lists names of files in the root matching the supplied glob pattern.

Returns `list[str]`.

Constraints: Callers do not build application paths or call `open()` or `shutil`; path-traversal validation and atomic writes belong to `FileStore`.

## External Services

### `ServiceClient.__init__(backend, name: str | None = None)`
Initializes a service wrapper with a backend handle and named logger.

### `ServiceClient._guard(op, *args, **kwargs)`
Executes a backend operation, logs failures, and re-raises exceptions.

### `MessageBus.publish(topic: str, payload: dict)`
Publishes a payload to a topic through the wrapped backend.

Returns `str`.

### `MessageBus.subscribe(topic: str, handler)`
Registers a handler for messages from a topic.

Returns `None`.

Constraints: Every external-service wrapper extends `ServiceClient`, exposes typed methods, and does not leak its SDK client. Cloud SDK imports remain inside service wrappers.

## Acceptance Transactions

### Rule: database-acceptance-session
Database criteria use the configured store with `with db_session() as db:`. Setup, behavior, and assertions execute in one transaction, and the fixture rolls it back.

Constraints: Do not replace the configured database, create temporary databases, apply DDL, commit, close the owned connection, or open another connection inside the rollback scope.

### Rule: committed-acceptance-session
HTTP, CLI, subprocess, background-work, and commit/restart criteria use `persistence.testing.committed_session()` for setup, readback, and cleanup on the configured store.

Constraints: Each criterion owns a stable identifier, reconciles only its own residue, verifies setup, checks only owned records, cleans up through supported interfaces in `try/finally`, and treats cleanup failure as criterion failure.

### Rule: durability-coverage
Acceptance evidence includes independent commit/reconnect durability coverage and uses runtime catalog and row-count evidence to verify database provisioning.

### Rule: immutable-history
Immutable ledger records are never deleted or history-reset; identify them or use supported reversal entries.

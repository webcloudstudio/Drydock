<!-- Compacted from Rigging/stack/persistence.md sha256=68dbc5deb5795e32a81a79d845f944f32579f655d19b279592a706857d16dd99 on 2026-10-23 by drydock rigging compact — regenerate with: drydock rigging compact --include-file {rel_source} -->

# Persistence & Service Encapsulation — Contract Surface

## Relational Persistence

### Rule: typed-persistence-boundary

All persistence and external-service access occurs through typed encapsulation classes.

Constraints: Application code must not execute raw SQL, read `os.environ`, open application files, or import cloud SDKs directly.

### Rule: generated-database-package

The persistence package is generated from `DATABASE.md`; callers use only its declared table attributes and repository verbs.

Constraints: Do not hand-write repositories, DAOs, ORM models, connection helpers, session factories, migrations, or files under `persistence/`.

### `open_database`

Opens a configured database and returns a synchronous `Database` with one attribute per declared table.

| Input | Type |
|---|---|
| `dsn` | `str` |

Constraints: Engine selection is determined at runtime from the DSN. Callers share one instance synchronously and do not manage connections, locking, or threads. Returned rows are frozen dataclasses without connection state.

### `Database.<table>.get`

Retrieves at most one row by a declared unique-key match.

| Input | Type |
|---|---|
| Declared Match fields | Keyword arguments |

Returns the row or `None`.

### `Database.<table>.list`

Lists rows matching supplied input-field equality filters joined with AND.

| Input | Type |
|---|---|
| Declared Input fields | Optional keyword arguments |

Returns a list of rows.

### `Database.<table>.create`

Creates one row using every declared input field.

| Input | Type |
|---|---|
| Declared Input fields | Keyword arguments |

Returns the created row.

### `Database.<table>.update`

Updates rows selected by Match fields, defaulting to the primary key.

| Input | Type |
|---|---|
| Match fields | Keyword arguments |
| Other Input fields | Keyword arguments |

Returns the updated row or `None` for a unique match; returns the affected count for a non-unique match.

### `Database.<table>.upsert`

Inserts or replaces a row selected by exactly one declared unique key.

| Input | Type |
|---|---|
| Declared Input fields | Keyword arguments |

Returns the inserted or replaced row.

### `Database.<table>.delete`

Deletes rows selected by every declared Match field.

| Input | Type |
|---|---|
| Match fields | Keyword arguments |

Returns the output built from the Match or `None` for a unique match; returns the affected count for a non-unique match.

Constraints: Unknown verbs raise `UnknownOperation`. No OR clauses, joins, SQL, or undeclared operations exist. Each write is one package-managed statement.

### Rule: schema-lifecycle

The generated `schema.sql` is applied once during the DATABASE step.

Constraints: Application startup must not create or alter schema.

## Configuration

### `Config.load`

Loads and validates one environment-derived immutable configuration.

| Field | Type | Source |
|---|---|---|
| `secret_key` | `str` | Required `SECRET_KEY` |
| `database_path` | `str` | `DATABASE_PATH`, default `data/app.db` |
| `port` | `int` | `APP_PORT`, default `5001` |
| `debug` | `bool` | `APP_DEBUG == "1"` |

Returns a frozen `Config`.

Constraints: Environment is loaded once. Missing required variables or malformed typed values raise at startup. No `Dev`, `Prod`, or `Test` subclasses exist. Only `Config` reads `os.environ`.

## File Storage

### `FileStore.__init__`

Creates a file store rooted at a directory.

| Input | Type |
|---|---|
| `root` | `str` |

### `FileStore.read`

Reads a UTF-8 application file by name.

| Input | Type |
|---|---|
| `name` | `str` |

Returns `str`.

### `FileStore.write`

Writes UTF-8 data to an application file, creating parent directories as needed.

| Input | Type |
|---|---|
| `name` | `str` |
| `data` | `str` |

Returns `None`.

### `FileStore.list`

Lists root-relative file names matching a glob pattern.

| Input | Type | Default |
|---|---|---|
| `pattern` | `str` | `"*"` |

Returns `list[str]`.

### Rule: file-access-boundary

`FileStore` is the only application code that opens files or uses `shutil`.

Constraints: Callers must not build application paths or call `open()` or `shutil` directly. Path-traversal validation and atomic writes are enforced by `FileStore`.

## External Services

### `ServiceClient.__init__`

Initializes a service wrapper with a backend handle and named logger.

| Input | Type |
|---|---|
| `backend` | Backend object |
| `name` | `str \| None` |

### `ServiceClient._guard`

Executes a backend operation, logs failures, and re-raises exceptions.

| Input | Type |
|---|---|
| `op` | Callable |
| `*args` | Positional arguments |
| `**kwargs` | Keyword arguments |

Returns the operation result.

### `MessageBus.publish`

Publishes a payload to a topic through the wrapped backend.

| Input | Type |
|---|---|
| `topic` | `str` |
| `payload` | `dict` |

Returns `str`.

### `MessageBus.subscribe`

Registers a handler for a topic through the wrapped backend.

| Input | Type |
|---|---|
| `topic` | `str` |
| `handler` | Callable |

Returns `None`.

### Rule: service-wrapper-boundary

Every external-service wrapper extends `ServiceClient`, exposes typed methods, and does not expose the SDK client.

Constraints: Cloud SDK imports occur only inside service wrappers. AWS integrations use the project-owned cloud client library.

## Acceptance Transactions

### Rule: database-acceptance-session

Database criteria use a rollback-scoped session on the configured store.

Constraints: Use `with db_session() as db:`; Go uses `OpenSession(ctx, "")` with checked deferred cleanup. Setup, operation, and assertions use the same database and transaction. Do not replace configured database settings, create temporary databases, apply DDL, commit, close the owned connection, or open another connection. The shipped fixture rolls back.

### Rule: committed-acceptance-session

HTTP, CLI, background-work, commit/restart, and durability criteria use committed sessions.

Constraints: Use `persistence.testing.committed_session()`; Go uses `OpenCommittedSession(ctx, "")`. Use criterion-specific stable identifiers, reconcile only owned residue, assert setup success, verify only owned records, and clean up through supported interfaces in `try/finally` or checked `defer`. Cleanup failure fails the criterion; retries must remain safe. Immutable ledger history is never deleted or reset.

### Rule: database-evidence

Database acceptance proves provisioning through runtime catalog and row-count evidence; feature criteria prove behavior.

Constraints: Database acceptance must not be replaced by a project test count. Include independent commit/reconnect durability coverage.

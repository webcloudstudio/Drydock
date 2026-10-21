<!-- Compacted from Rigging/stack/persistence.md sha256=faaae951cc9641b1a3799eb0a46030514bc49afa4ba8f9ca71949fa3861addbd on 2026-10-20 by drydock rigging compact — regenerate with: drydock rigging compact --include-file {rel_source} -->

# Persistence & Service Encapsulation — Contract Surface

## Persistence

### Rule: typed-persistence-boundary

All persistence and external-service access goes through typed encapsulation classes.

Constraints: Route, feature, and business-logic code must not execute raw SQL, read `os.environ`, open application files, or import cloud SDKs.

### function_name

`open_database(dsn)` opens the generated database abstraction selected by the DSN.

| Input | Type |
|---|---|
| `dsn` | `str` |

Returns a `Database` with one attribute per declared table.

Constraints: The generated persistence package is derived from `DATABASE.md`; callers must not create repositories, DAOs, ORM models, session factories, migrations, or alternate storage paths.

### Database.table.get

Retrieves one row by identifier.

| Input | Type |
|---|---|
| `id` | declared identifier type |

Returns a frozen dataclass or `None`.

### Database.table.list

Lists rows matching declared access-pattern fields.

Returns a list of frozen row dataclasses.

### Database.table.create

Creates a row using exactly the declared operation input fields.

Returns the new record identifier.

### Database.table.update

Updates a row using exactly the declared operation input fields.

Returns no specified value.

### Database.table.delete

Deletes a row by the declared operation input fields.

Returns no specified value.

### Rule: declared-operation-surface

Each declared table exposes only the methods specified by its `DATABASE.md` access patterns. Unsupported verbs raise `UnknownOperation` naming the granted operations.

### Rule: database-lifecycle

Callers construct one `Database`, share it, and call methods synchronously. Returned rows contain no connection state.

Constraints: `schema.sql` is applied once during the DATABASE build step. Application startup must not create or alter schema.

### Rule: generated-engine-access

Both SQLite and PostgreSQL engines are available at runtime and selected from the DSN.

Constraints: Code outside `persistence/` must not import `sqlite3` or `psycopg`, and nothing under `persistence/` is edited by hand.

## Configuration

### Config.load

Loads and validates environment configuration once at startup.

Returns a frozen `Config`.

| Field | Type | Source | Default |
|---|---|---|---|
| `secret_key` | `str` | `SECRET_KEY` | required |
| `database_path` | `str` | `DATABASE_PATH` | `data/app.db` |
| `port` | `int` | `APP_PORT` | `5001` |
| `debug` | `bool` | `APP_DEBUG == "1"` | `False` |

Constraints: Missing required environment variables raise `RuntimeError`. Malformed typed values fail during startup. No code other than `Config` reads `os.environ`; no Dev/Prod/Test subclasses are permitted.

## File Storage

### FileStore.__init__

Creates a file store rooted at the supplied directory.

| Input | Type |
|---|---|
| `root` | `str` |

### FileStore.read

Reads a UTF-8 application file by name.

| Input | Type |
|---|---|
| `name` | `str` |

Returns `str`.

### FileStore.write

Writes UTF-8 application data by name.

| Input | Type |
|---|---|
| `name` | `str` |
| `data` | `str` |

Returns `None`.

### FileStore.list

Lists application files matching a glob pattern.

| Input | Type | Default |
|---|---|---|
| `pattern` | `str` | `"*"` |

Returns `list[str]`.

### Rule: file-access-boundary

Only `FileStore` opens application files or uses file utilities.

Constraints: Callers must not construct application paths or call `open()` or `shutil` directly. Path-traversal validation and atomic writes are required in `FileStore`.

## External Services

### ServiceClient.__init__

Initializes a service wrapper with a backend handle and optional logger name.

| Input | Type |
|---|---|
| `backend` | backend object |
| `name` | `str \| None` |

### ServiceClient._guard

Executes a backend operation, logs failures, and re-raises exceptions.

| Input | Type |
|---|---|
| `op` | callable |
| `*args` | operation arguments |
| `**kwargs` | operation keyword arguments |

Returns the operation result.

### MessageBus.publish

Publishes a payload to a topic through the wrapped backend.

| Input | Type |
|---|---|
| `topic` | `str` |
| `payload` | `dict` |

Returns `str`.

### MessageBus.subscribe

Registers a handler for a topic through the wrapped backend.

| Input | Type |
|---|---|
| `topic` | `str` |
| `handler` | callable |

Returns `None`.

### Rule: service-wrapper-boundary

Every external-service wrapper extends `ServiceClient`, exposes typed methods, and does not expose the SDK client.

Constraints: Cloud SDK imports must remain inside their service wrappers.

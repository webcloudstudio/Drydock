<!-- Compacted from Rigging/stack/persistence.md sha256=e8b2ce6c978be9e777153690fbcdb9fb3cb59e2d63f6e442b5220a17480dfbe5 on 2026-09-20 by drydock rigging compact — regenerate with: drydock rigging compact --include-file {rel_source} -->

# Persistence & Service Encapsulation — Contract Surface

## Relational stores

### function open_database
Opens a database selected at runtime from the configured DSN.

| Input | Type | Required |
|---|---|---|
| `dsn` | string | yes |

Returns a `Database` instance with one attribute per declared table.

Constraints: Callers use synchronous methods and share one instance. Returned rows are frozen dataclasses or `None`; list operations return lists of rows. Schema is applied once during the DATABASE build step and never at application startup.

### Database.<table>.<verb>
Executes a declared repository operation for a table.

| Input | Type | Required |
|---|---|---|
| Declared operation keyword arguments | Per `DATABASE.md` `Input:` fields | Per declaration |

Returns the operation’s declared result.

Constraints: Only verbs declared in `DATABASE.md` are available. Undeclared verbs raise `UnknownOperation` naming the granted operations. No other arguments or access paths are accepted.

## Configuration

### Config
Provides typed application configuration loaded from the environment.

| Field | Type | Required |
|---|---|---|
| `secret_key` | string | yes |
| `database_path` | string | no; defaults to `data/app.db` |
| `port` | integer | no; defaults to `5001` |
| `debug` | boolean | no; true only when `APP_DEBUG` equals `"1"` |

### Config.load
Reads and validates configuration once at startup.

Returns a frozen `Config`.

Constraints: `SECRET_KEY` is required. Malformed typed values fail at startup. Missing required environment variables raise `RuntimeError`. No other code reads `os.environ`. No environment-specific subclasses exist.

## Files

### FileStore.__init__
Creates a file store rooted at a directory.

| Input | Type | Required |
|---|---|---|
| `root` | string | yes |

### FileStore.read
Reads an application file by name.

| Input | Type | Required |
|---|---|---|
| `name` | string | yes |

Returns the file contents as a string.

### FileStore.write
Writes string data to an application file by name.

| Input | Type | Required |
|---|---|---|
| `name` | string | yes |
| `data` | string | yes |

Returns `None`.

### FileStore.list
Lists files matching a pattern.

| Input | Type | Required |
|---|---|---|
| `pattern` | string | no; defaults to `"*"` |

Returns a list of file-name strings.

Constraints: Callers do not construct paths or call `open()` or `shutil` directly. Path-traversal validation and atomic writes are enforced by `FileStore`.

## External services

### ServiceClient.__init__
Creates a service wrapper base with a backend handle and named logger.

| Input | Type | Required |
|---|---|---|
| `backend` | backend handle | yes |
| `name` | string or `None` | no; defaults to the subclass name |

### ServiceClient._guard
Executes a backend operation with uniform exception logging.

| Input | Type | Required |
|---|---|---|
| `op` | callable | yes |
| `*args` | any | no |
| `**kwargs` | any | no |

Returns the callable’s result. Logs the service name and re-raises any exception.

### MessageBus.publish
Publishes a payload to a topic through the wrapped backend.

| Input | Type | Required |
|---|---|---|
| `topic` | string | yes |
| `payload` | dictionary | yes |

Returns a string message identifier.

### MessageBus.subscribe
Registers a handler for a topic.

| Input | Type | Required |
|---|---|---|
| `topic` | string | yes |
| `handler` | callable | yes |

Returns `None`.

Constraints: External-service wrappers extend `ServiceClient`, expose typed methods, and never expose the SDK client. Cloud SDK imports remain inside their wrappers.

## Access rules

### Rule: typed-persistence-boundary
All persistence and external-service access goes through typed encapsulation classes.

Constraints: Route, feature, and business-logic code must not execute raw SQL, read `os.environ`, open application files, or import cloud SDKs.

### Rule: generated-relational-package
The relational persistence package is generated from `DATABASE.md`.

Constraints: Do not hand-write repositories, DAOs, ORM models, connection helpers, session factories, or migrations. Do not edit `persistence/`; change `DATABASE.md` and rebuild.

### Rule: database-engine-selection
SQLite and PostgreSQL engines are available in every build and selected at runtime from the DSN.

### Rule: startup-schema
Application startup must not create or alter the database schema.

### Rule: wrapper-inheritance
Every external-service wrapper extends `ServiceClient`.

### Rule: declared-operation-surface
Downstream code depends only on operations declared in `DATABASE.md`, not on the underlying schema.

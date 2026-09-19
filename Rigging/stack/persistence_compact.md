<!-- Compacted from Rigging/stack/persistence.md sha256=e8b2ce6c978be9e777153690fbcdb9fb3cb59e2d63f6e442b5220a17480dfbe5 on 2026-09-19 by drydock rigging compact — regenerate with: drydock rigging compact --include-file {rel_source} -->

# Persistence & Service Encapsulation — Contract Surface

## Relational Persistence

### function open_database
Opens the generated database package using a runtime DSN.

| Input | Type | Required |
|---|---|---|
| `database_url` | DSN string | Yes |

Returns a `Database` instance.

Constraints: Runtime engine selection is based on the DSN; callers use synchronous, single-threaded semantics and do not manage connections, locking, or schema creation.

### Database.table.operation
Executes a declared repository operation for a generated table.

| Input | Type | Required |
|---|---|---|
| Declared operation keyword arguments | Operation-specific | As declared in `DATABASE.md` |

Returns the operation-specific result. Table attributes and verbs exist only when declared in `DATABASE.md`; undeclared verbs raise `UnknownOperation` naming the granted operations.

### Rule: generated-persistence
The `persistence/` package and `schema.sql` are generated from `DATABASE.md`; callers must not add repositories, DAOs, ORM models, connection/session factories, migrations, raw SQL, or direct database-driver imports.

Constraints: `schema.sql` is applied once during the DATABASE build step; application startup must not create or alter schema.

## Configuration

### Config.load
Loads and validates environment configuration once at startup.

Returns a frozen `Config` with:

| Field | Type | Source | Default |
|---|---|---|---|
| `secret_key` | `str` | `SECRET_KEY` | Required |
| `database_path` | `str` | `DATABASE_PATH` | `data/app.db` |
| `port` | `int` | `APP_PORT` | `5001` |
| `debug` | `bool` | `APP_DEBUG == "1"` | `False` |

Constraints: Missing required variables raise `RuntimeError`; malformed typed values fail at startup. No other code reads `os.environ`, and no environment-specific subclasses are used.

## File Storage

### FileStore.__init__
Creates a file store rooted at a directory.

| Input | Type | Required |
|---|---|---|
| `root` | `str` | Yes |

### FileStore.read
Reads an application file as UTF-8 text.

| Input | Type | Required |
|---|---|---|
| `name` | `str` | Yes |

Returns the file contents as `str`.

### FileStore.write
Writes UTF-8 text to an application file.

| Input | Type | Required |
|---|---|---|
| `name` | `str` | Yes |
| `data` | `str` | Yes |

Returns `None`.

### FileStore.list
Lists matching file names in the store root.

| Input | Type | Required |
|---|---|---|
| `pattern` | `str` | No; defaults to `"*"` |

Returns `list[str]`.

Constraints: Path-traversal validation and atomic writes are enforced by `FileStore`; callers must not build application paths or call `open()` or `shutil` directly.

## External Services

### ServiceClient.__init__
Initializes a service wrapper with a backend handle and named logger.

| Input | Type | Required |
|---|---|---|
| `backend` | Backend handle | Yes |
| `name` | `str \| None` | No |

### ServiceClient._guard
Executes a backend operation, logs failures, and re-raises exceptions.

| Input | Type | Required |
|---|---|---|
| `op` | Callable | Yes |
| `*args`, `**kwargs` | Operation arguments | As required by `op` |

Returns the operation result.

### MessageBus.publish
Publishes a payload to a topic through the wrapped transport.

| Input | Type | Required |
|---|---|---|
| `topic` | `str` | Yes |
| `payload` | `dict` | Yes |

Returns a `str` message identifier.

### MessageBus.subscribe
Registers a handler for a topic.

| Input | Type | Required |
|---|---|---|
| `topic` | `str` | Yes |
| `handler` | Callable | Yes |

Returns `None`.

### Rule: service-encapsulation
Every external-service wrapper extends `ServiceClient`, exposes typed methods, and never exposes its SDK client.

Constraints: Application code must not import cloud SDKs or access external services outside their typed wrappers.

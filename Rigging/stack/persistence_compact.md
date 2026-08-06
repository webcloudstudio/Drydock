<!-- Compacted from Rigging/stack/persistence.md sha256=419a6a4324409bc5ad773f8714c74f6a5e97ec482b14beea654e1e1847c5d2d2 on 2026-08-06 by drydock rigging compact — regenerate with: drydock rigging compact --include-file {rel_source} -->

# Persistence & Service Encapsulation — Contract Surface

## Database

### ItemTable.create

Creates an item.

| Input | Type | Required |
|---|---|---|
| `name` | `str` | Yes |
| `status` | `str` | No; defaults to `"active"` |

Returns: `int` item ID.

### ItemTable.get

Retrieves an item by ID.

| Input | Type | Required |
|---|---|---|
| `item_id` | `int` | Yes |

Returns: `Item | None`.

### ItemTable.list

Lists all items.

Returns: `list[Item]`.

### ItemTable.update

Updates fields for an item.

| Input | Type | Required |
|---|---|---|
| `item_id` | `int` | Yes |
| `**fields` | field values | Yes |

Returns: `None`.

### ItemTable.delete

Deletes an item.

| Input | Type | Required |
|---|---|---|
| `item_id` | `int` | Yes |

Returns: `None`.

### Database.__init__

Creates a database facade for the specified path.

| Input | Type | Required |
|---|---|---|
| `path` | `str` | Yes |

Constraints: Exposes one table attribute per table, such as `items`; callers use table methods and never execute raw SQL.

### Database.connect

Returns the calling workflow’s configured database connection.

Returns: `sqlite3.Connection`.

Constraints: One connection is maintained per workflow; callers use synchronous database methods and do not manage connections, threads, or locking.

### Item

Represents a database row.

| Field | Type | Default |
|---|---|---|
| `id` | `int | None` | Required |
| `name` | `str` | Required |
| `status` | `str` | `"active"` |
| `created_at` | `str | None` | `None` |

## Configuration

### Config.load

Loads and validates environment-backed application configuration.

Returns: `Config`.

| Field | Source | Type | Required |
|---|---|---|---|
| `secret_key` | `SECRET_KEY` | `str` | Yes |
| `database_path` | `DATABASE_PATH` | `str` | No; defaults to `"data/app.db"` |
| `port` | `APP_PORT` | `int` | No; defaults to `5001` |
| `debug` | `APP_DEBUG` | `bool` | No; `True` only when value is `"1"` |

Constraints: Missing required variables or malformed typed values fail during startup. Only `Config` reads environment variables.

## File Storage

### FileStore.__init__

Creates a file store rooted at the specified directory.

| Input | Type | Required |
|---|---|---|
| `root` | `str` | Yes |

### FileStore.read

Reads a UTF-8 application file by name.

| Input | Type | Required |
|---|---|---|
| `name` | `str` | Yes |

Returns: `str`.

### FileStore.write

Writes UTF-8 data to an application file, creating parent directories as needed.

| Input | Type | Required |
|---|---|---|
| `name` | `str` | Yes |
| `data` | `str` | Yes |

Returns: `None`.

### FileStore.list

Lists files matching a pattern.

| Input | Type | Default |
|---|---|---|
| `pattern` | `str` | `"*"` |

Returns: `list[str]`.

Constraints: Path-traversal validation and atomic writes are enforced by `FileStore`; callers do not construct paths or call file APIs directly.

## External Services

### ServiceClient.__init__

Creates a service wrapper around a backend handle.

| Input | Type | Required |
|---|---|---|
| `backend` | backend handle | Yes |
| `name` | `str | None` | No |

### ServiceClient._guard

Executes a backend operation with uniform exception logging and re-raises failures.

| Input | Type | Required |
|---|---|---|
| `op` | callable | Yes |
| `*args` | operation arguments | No |
| `**kwargs` | operation keyword arguments | No |

Returns: The operation result.

### MessageBus.publish

Publishes a payload to a topic.

| Input | Type | Required |
|---|---|---|
| `topic` | `str` | Yes |
| `payload` | `dict` | Yes |

Returns: `str` message identifier.

### MessageBus.subscribe

Registers a handler for a topic.

| Input | Type | Required |
|---|---|---|
| `topic` | `str` | Yes |
| `handler` | callable | Yes |

Returns: `None`.

### Rule: encapsulated-persistence

All persistence and external-service access uses typed encapsulation classes.

Constraints: Application code must not execute raw SQL, read `os.environ`, open or manipulate application files directly, or import cloud SDKs outside their wrapper classes.

### Rule: typed-service-boundary

Service wrappers extend `ServiceClient` and expose typed methods without leaking SDK clients.

### Rule: interface-dependency

Downstream code depends on class interfaces rather than underlying schemas or service implementations.

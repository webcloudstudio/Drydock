<!-- Compacted from Rigging/stack/persistence.md sha256=419a6a4324409bc5ad773f8714c74f6a5e97ec482b14beea654e1e1847c5d2d2 on 2026-08-06 by drydock rigging compact — regenerate with: drydock rigging compact --include-file {rel_source} -->

# Persistence & Service Encapsulation — Contract Surface

## Relational persistence

### Item

Represents a persisted item row.

| Field | Type | Default |
|---|---|---|
| `id` | `int \| None` | required |
| `name` | `str` | required |
| `status` | `str` | `"active"` |
| `created_at` | `str \| None` | `None` |

### ItemTable.__init__

Constructs typed item-table access from a connection provider.

| Input | Type |
|---|---|
| `connect` | callable returning `sqlite3.Connection` |

### ItemTable.create

Creates an item and returns its generated identifier.

| Input | Type | Default |
|---|---|---|
| `name` | `str` | required |
| `status` | `str` | `"active"` |

Returns: `int`.

### ItemTable.get

Retrieves an item by identifier.

| Input | Type |
|---|---|
| `item_id` | `int` |

Returns: `Item \| None`.

### ItemTable.list

Lists all items.

Returns: `list[Item]`.

### ItemTable.update

Updates fields for an item.

| Input | Type |
|---|---|
| `item_id` | `int` |
| `**fields` | item fields |

Returns: `None`.

### ItemTable.delete

Deletes an item.

| Input | Type |
|---|---|
| `item_id` | `int` |

Returns: `None`.

### Database.__init__

Constructs database access and exposes one typed table attribute per relational table, such as `db.items`.

| Input | Type |
|---|---|
| `path` | `str` |

### Database.connect

Returns the calling workflow’s database connection, opening and configuring it on first use.

Returns: `sqlite3.Connection`.

Constraints: The database provides one connection per workflow, instance methods are safe to call concurrently, returned rows are plain dataclasses without connection state, and table classes receive a connect provider rather than a connection.

## Configuration

### Config

Provides immutable, typed application configuration loaded from environment variables.

| Field | Type | Source | Default |
|---|---|---|---|
| `secret_key` | `str` | `SECRET_KEY` | required |
| `database_path` | `str` | `DATABASE_PATH` | `"data/app.db"` |
| `port` | `int` | `APP_PORT` | `5001` |
| `debug` | `bool` | `APP_DEBUG == "1"` | `False` |

### Config.load

Loads and validates configuration at startup.

Returns: `Config`.

Constraints: Missing required variables or malformed typed values raise a startup error, and no code outside `Config` reads `os.environ`.

## File storage

### FileStore.__init__

Constructs file storage rooted at the supplied directory.

| Input | Type |
|---|---|
| `root` | `str` |

### FileStore.read

Reads an application file relative to the store root.

| Input | Type |
|---|---|
| `name` | `str` |

Returns: `str`.

### FileStore.write

Writes string data to an application file relative to the store root.

| Input | Type |
|---|---|
| `name` | `str` |
| `data` | `str` |

Returns: `None`.

### FileStore.list

Lists file names matching a pattern relative to the store root.

| Input | Type | Default |
|---|---|---|
| `pattern` | `str` | `"*"` |

Returns: `list[str]`.

Constraints: Path-traversal validation and atomic writes are enforced by `FileStore`; callers do not build paths or open or manipulate application files directly.

## External services

### ServiceClient.__init__

Constructs a service wrapper with a backend handle and named logger.

| Input | Type | Default |
|---|---|---|
| `backend` | any | required |
| `name` | `str \| None` | subclass name |

### ServiceClient._guard

Executes a backend operation, logs failures, and re-raises exceptions.

| Input | Type |
|---|---|
| `op` | callable |
| `*args` | operation arguments |
| `**kwargs` | operation keyword arguments |

Returns: The backend operation result.

### MessageBus.publish

Publishes a payload to a topic through the service wrapper.

| Input | Type |
|---|---|
| `topic` | `str` |
| `payload` | `dict` |

Returns: `str`.

### MessageBus.subscribe

Registers a handler for a topic.

| Input | Type |
|---|---|
| `topic` | `str` |
| `handler` | callable |

Returns: `None`.

### Rule: encapsulated-access

All persistence and external-service access goes through typed encapsulation classes.

Constraints: Application code does not execute raw SQL, read `os.environ`, open application files directly, or import cloud SDKs. Service wrappers extend `ServiceClient` and do not expose SDK clients. ORM model classes may serve as table encapsulation without a second hand-written layer.

### Rule: database-composition

Each relational table provides a row dataclass and CRUD class composed by one `Database` class.

Constraints: Schema creation, migrations, PRAGMAs, JSON-column handling, and connection management remain inside `Database` or table classes; downstream code depends on class interfaces rather than underlying schemas.

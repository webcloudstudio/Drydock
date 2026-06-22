<!-- Compacted from persistence.md on 2026-06-22 by drydock rigging compact — regenerate with: drydock rigging compact --include-file {rel_source} -->

# Persistence & Service Encapsulation — Usage Surface

## Database

### Database.__init__
Constructs the database connection and exposes one attribute per table (e.g. `db.items`).

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| path | str | yes | Filesystem path to the SQLite database file |

Returns: `Database` — instance with table accessors as attributes (e.g. `db.items`)

### ItemTable.create
Inserts a new item row and returns its generated ID.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| name | str | yes | Item name |
| status | str | no | Item status; defaults to `"active"` |

Returns: `int` — the new row's primary key

### ItemTable.get
Fetches a single item by primary key.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| item_id | int | yes | Primary key of the item to retrieve |

Returns: `Item | None` — the matching row dataclass, or `None` if not found

### ItemTable.list
Returns all item rows.

Returns: `list[Item]` — every row as an `Item` dataclass

### ItemTable.update
Updates one or more fields on an existing item.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| item_id | int | yes | Primary key of the item to update |
| **fields | any | yes | Keyword arguments matching column names to update |

Returns: `None`

### ItemTable.delete
Deletes an item by primary key.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| item_id | int | yes | Primary key of the item to delete |

Returns: `None`

## Config

### config_key: SECRET_KEY
Required. Application secret key.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| SECRET_KEY | str (env) | yes | Application secret key |

### config_key: DATABASE_PATH
Path to the SQLite database file.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| DATABASE_PATH | str (env) | no | Defaults to `"data/app.db"` |

### config_key: APP_PORT
Port the application listens on.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| APP_PORT | int (env) | no | Defaults to `5001` |

### config_key: APP_DEBUG
Enables debug mode when set to `"1"`.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| APP_DEBUG | str (env) | no | Set to `"1"` to enable; defaults to `False` |

### Config.load
Reads and validates all environment variables at startup; raises `RuntimeError` on missing required vars.

Returns: `Config` — frozen dataclass with fields `secret_key`, `database_path`, `port`, `debug`

## FileStore

### FileStore.__init__
Creates a file store rooted at the given directory.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| root | str | yes | Root directory for all managed files |

Returns: `FileStore`

### FileStore.read
Reads a file by name relative to the store root.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| name | str | yes | Filename relative to root |

Returns: `str` — file contents as UTF-8 text

### FileStore.write
Writes text to a file relative to the store root, creating intermediate directories as needed.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| name | str | yes | Filename relative to root |
| data | str | yes | UTF-8 text to write |

Returns: `None`

### FileStore.list
Globs files in the store root matching a pattern.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| pattern | str | no | Glob pattern; defaults to `"*"` |

Returns: `list[str]` — matching filenames (not full paths)

## Service Clients

### ServiceClient.__init__
Base constructor shared by all external-service wrappers; wires the backend handle and logger.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| backend | any | yes | SDK or transport client instance |
| name | str \| None | no | Logger name; defaults to the subclass name |

Returns: `ServiceClient`

### MessageBus.publish
Sends a payload to a named topic and returns a delivery receipt identifier.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| topic | str | yes | Destination topic name |
| payload | dict | yes | Message body |

Returns: `str` — delivery receipt / message ID

### MessageBus.subscribe
Registers a handler to receive messages from a named topic.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| topic | str | yes | Topic to subscribe to |
| handler | callable | yes | Callback invoked with each received message |

Returns: `None`

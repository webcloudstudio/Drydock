<!-- Compacted from Rigging/stack/persistence.md sha256=8e3449043cb4d896787c713ac683d7ec025a13222e0d6d5c67ee6c6e3c07e351 on 2026-10-24 by drydock rigging compact — regenerate with: drydock rigging compact --include-file {rel_source} -->
<!-- Manually aligned with the source initialization contract on 2026-10-27. -->

# Persistence & Service Encapsulation — Contract Surface

## Relational Persistence

### Rule: persistence-boundary

All persistence and external-service access goes through typed encapsulation classes.

Constraints: Route, feature, and business-logic code must not execute raw SQL, read `os.environ`, open application files, import `sqlite3`/`psycopg`, or import cloud SDKs outside their encapsulation classes.

### function_open_database

Opens the generated persistence package using a database DSN.

| Parameter | Type |
|---|---|
| `dsn` | `str` |

Returns a `Database` instance with one attribute per declared table.

Constraints: Callers use the generated package and must not write repositories, DAOs, ORM models, connection helpers, session factories, or migrations.

### Database.<table>.<operation>

Executes a declared database operation using keyword arguments matching its `Input` fields.

| Input | Type |
|---|---|
| Declared operation fields | `str`, `int`, `float`, `bool`, or `bytes` |

Returns the declared operation `Output`: a row, `None`, a list of rows, or an integer row count.

Constraints: Unknown operations raise `UnknownOperation`. No other arguments, operators, OR conditions, joins, or SQL access paths are accepted. Calls are synchronous, and returned rows are frozen dataclasses without connection state.

### Rule: operation-kinds

Declared operations use one of six kinds: `get`, `list`, `create`, `update`, `upsert`, or `delete`.

Constraints: Operation names are the caller contract. Match fields select rows using AND semantics; bare fields use equality, and comparison terms may use `=`, `<`, `<=`, `>`, or `>=`. `list` filters are optional. `Order` controls list ordering. Every write executes as one package-level statement.

| Kind | Selection | Return |
|---|---|---|
| `get` | Unique-key match | Row or `None` |
| `list` | Optional input-field match | Ordered list of rows |
| `create` | None | Created row |
| `update` | Match, defaulting to primary key | Row/`None`, or count for many rows |
| `upsert` | Exactly one unique-key match | Inserted or replaced row |
| `delete` | Input-field match | Matched output/`None`, or count for many rows |

### Rule: operation-surface

Each operation exposes a generated contract containing its call path, kind, rows, match terms, sets, input schema, output schema, SQL, and 12-character SHA-256 contract fingerprint.

Constraints: Callers build against `DATABASE_compact.md`’s generated `Operation Surface`. Contract fingerprints change only when the operation name, kind, match, order, row behavior, return shape, or input/output field names and types change.

### Rule: database-runtime

The generated package supports SQLite and PostgreSQL selected from the runtime DSN.

Constraints: Both engines are present in every build. DATABASE generates idempotent schema.sql and provisions the build store. Ordinary startup does not apply DDL. Explicit source-required Python init uses initialize_database(dsn).

### function_initialize_database

Signature: `persistence.initialize_database(dsn: str) -> Database`

Creates missing tables/indexes using generated schema.sql, resolved independently of cwd. Returns an open store; caller closes it. Repeated calls preserve existing records and table definitions. No reset or migration. Works inside acceptance rollback; ordinary raw DDL remains forbidden there. Missing scripts and execution failures propagate.

## Configuration

### Config.load

Loads and validates environment configuration once at startup.

| Field | Source | Type | Required/default |
|---|---|---|---|
| `secret_key` | `SECRET_KEY` | `str` | Required |
| `database_path` | `DATABASE_PATH` | `str` | `"data/app.db"` |
| `port` | `APP_PORT` | `int` | `5001` |
| `debug` | `APP_DEBUG` | `bool` | `True` only when value is `"1"` |

Returns a frozen `Config` instance.

Constraints: Missing required variables or malformed typed values raise a startup error. No code outside `Config` reads `os.environ`. There are no environment-specific subclasses.

## File Storage

### FileStore.__init__

Creates a typed file store rooted at a directory.

| Parameter | Type |
|---|---|
| `root` | `str` |

### FileStore.read

Reads an application file by name.

| Parameter | Type |
|---|---|
| `name` | `str` |

Returns the file contents as `str`.

### FileStore.write

Writes string data to an application file, creating parent directories as needed.

| Parameter | Type |
|---|---|
| `name` | `str` |
| `data` | `str` |

Returns `None`.

### FileStore.list

Lists file names matching a pattern.

| Parameter | Type | Default |
|---|---|---|
| `pattern` | `str` | `"*"` |

Returns `list[str]`.

Constraints: Callers must not construct application paths or call `open()`/`shutil` directly. Path-traversal validation and atomic-write behavior belong to `FileStore`.

## External Services

### ServiceClient.__init__

Initializes a service wrapper with a backend handle and named logger.

| Parameter | Type | Required/default |
|---|---|---|
| `backend` | backend handle | Required |
| `name` | `str \| None` | Wrapper class name |

### ServiceClient._guard

Executes a backend operation and logs failures before re-raising them.

| Parameter | Type |
|---|---|
| `op` | callable |
| `*args` | operation arguments |
| `**kwargs` | operation keyword arguments |

Returns the operation result or re-raises its exception.

### MessageBus.publish

Publishes a typed payload through the wrapped service backend.

| Parameter | Type |
|---|---|
| `topic` | `str` |
| `payload` | `dict` |

Returns `str`.

### MessageBus.subscribe

Registers a handler for a topic.

| Parameter | Type |
|---|---|
| `topic` | `str` |
| `handler` | callable |

Returns `None`.

Constraints: Every external-service wrapper extends `ServiceClient`, exposes typed methods, and never exposes the SDK client. Cloud SDK imports remain inside service wrappers.

## Acceptance Transactions

### Rule: acceptance-store

Ordinary persistence acceptance uses the configured database provisioned by the DATABASE step.

Constraints: Ordinary persistence criteria must not replace database configuration, create temporary databases, apply DDL, assume an empty store, commit, or clean up records. Assertions use records created by the criterion or relative counts.

### database_environment

Harness-owned Python acceptance fixture: `from drydock_acceptance import database_environment`.

`with database_environment(url=None, path=None) as root:` yields a temporary `Path` and sets
cwd there. None unsets a variable, empty string sets it empty, and relative file names become
absolute scratch paths. Only `url` accepts `sqlite://`. Restores cwd and both variables on exit,
including failures. Creates no schema or parent directories; `url="missing/app.db"` tests open
failure. Test configuration priority, prefix, fallback and default through the product interface.

Constraints: Configuration/open-failure acceptance only; no populated-store CRUD, external
paths, other engines, direct DSN mutation or caller-authored schema setup. Source-required init
acceptance calls the product initializer inside this scratch context, then verifies creation,
repeatability and data preservation. The fixture itself still creates no schema.

### Rule: python-criterion-transaction

The acceptance harness starts one transaction before each Python criterion and rolls it back afterward.

Constraints: `db_session()`, `web_client()`, and `cli_runner()` participate in that transaction. Seed through `with db_session() as db:` and pass that database into feature operations. Exiting the context does not roll back the transaction.

### Rule: process-criterion

Criteria that launch subprocesses, servers, or shell scripts cannot access the criterion transaction.

Constraints: Such criteria must not depend on rows written in the transaction and must exercise stored behavior in-process.

### Rule: go-criterion-transaction

Go criteria use transaction helpers appropriate to their execution mode.

Constraints: In-process Go criteria use `OpenSession(ctx, "")` with checked deferred cleanup. Go HTTP, CLI, and restart criteria use `OpenCommittedSession(ctx, "")` with a criterion-owned identifier and checked deferred cleanup through supported product interfaces.

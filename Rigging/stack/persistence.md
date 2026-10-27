# Persistence & Service Encapsulation

**Type:** guidance
**Version:** 20261026 V6
**Category:** Persistence
**Description:** The single boundary rule for all persistent stores and external services — typed access classes, no raw access in application code

Technology reference. Framework-agnostic. This file does not change between projects.

Prerequisite: `stack/common.md`

---

## The Invariant

**Rule**: All persistence and external-service access goes through a typed encapsulation
class. Route, feature, and business-logic code never executes raw SQL, reads `os.environ`,
opens application files directly, or imports a cloud SDK (`boto3`). The typed class interface
— not the underlying schema or service — is the dependency boundary.

**Why**: A storage or service change is absorbed at the class. Downstream code depends on the
interface, so a schema change that does not change the interface changes nothing else. This is
the same swap-layer discipline a cloud client library enforces for AWS (`import boto3`
outside the wrapper fails review), generalized to every store.

A code review that finds raw SQL, `os.environ`, `open()` on application data, or a cloud SDK
import outside its encapsulation class fails.

**Relational rule**: the relational layer is generated, not written. Drydock emits it from
`DATABASE.md` and copies the engines in unchanged; the build writes callers. See section 1.

---

## 1. Relational stores → the generated persistence package

**You do not write this layer.** Drydock generates it from `DATABASE.md` at the DATABASE build
step and copies the engines in unchanged. Writing a repository, a connection helper, a session
factory, or a migration by hand is a review failure: the generated package already implements the
declaration, and a hand-written second path is storage access no Blueprint cites.

The build writes **callers**.

```text
route → service → db.<table>.<name>(...) → generated package → database
```

Language bindings are shipped in `languages/<language>/persistence/`; generation templates live
beside them in `templates/`. Python and Go implement the same declared operations. The language
instructions own native names, dependencies and fixtures. Go uses `OpenDatabase(ctx, dsn)` and
generated typed repository methods; the Python examples below use `open_database(dsn)`.

The Python package lands at `persistence/` in the build:

| File | Origin |
|---|---|
| `db.py`, `sqlite.py`, `postgres.py` | shipped by Drydock, copied unchanged |
| `schema.py` | generated from `DATABASE.md` — tables, operations, row dataclasses |
| `schema.sql` (beside the package) | generated DDL, applied once at the DATABASE step |

### Calling it

```python
from persistence import open_database

db = open_database(config.database_url)

ticket = db.tickets.get(id=ticket_id)                 # a frozen dataclass, or None
open_tickets = db.tickets.list(status="open")         # a list of them
history = db.rates.history(currency="USD", start_date=start)  # range list; end_date omitted
ticket = db.tickets.create(status="open", title=title)  # the declared Output row
db.tickets.update(id=ticket_id, status="closed")      # the row, or None
rate = db.rates.replace_rate(date=day, currency="USD", rate="1.0393")  # upsert: the row
changed = db.rates.reprice_currency(currency="USD", rate="1.0400")     # many-row update: a count
db.tickets.delete(id=ticket_id)                       # the Output built from the Match, or None
```

One attribute per declared table, one method per declared operation. The method name is the
`<name>` of the pattern's `Repository operation` cell, `<table>.<name>`, and its keyword arguments
are that pattern's `Input:` fields — nothing else is accepted. An operation the table does not
declare raises `UnknownOperation` naming what it does grant.

### Operations: a name and a Kind

An operation's **name** is the contract callers depend on. Its **Kind** is how the package runs
it, one of six: `get`, `list`, `create`, `update`, `upsert`, `delete`.

- **Simple:** the name is the Kind. `rates.get`, `rates.update` — no Kind row is written.
- **Named:** any other name declares its Kind: `rates.reprice_currency` with `| Kind | update |`.
  A table may hold several operations of one Kind, each under its own name. Two names with the
  same Kind, Match, Sets, and Output are synonyms, and the plan refuses the second.

**Which rows an operation reaches is declared, never inferred.** A pattern's `| Match |` row names
the Input fields that select rows, joined with AND, every field required except on a `list`. A
bare field is compared by equality with the column of its name; a term `<column> <op> <field>`
(`=`, `<`, `<=`, `>`, `>=`) compares an argument with a column, as `date >= start_date`. A Match
whose equality fields cover the table's `PK` or a declared `UNIQUE` reaches at most one row; any
other Match reaches many. A `list` with `| Order | `date` asc |` returns its rows in that order,
and in no stated order otherwise; do not re-sort or filter what an operation already returns. Every write is one statement inside the package, so a caller never composes a
read-then-write.

| Kind | Selects rows by | Writes | Rows | Returns |
|---|---|---|---|---|
| `get` | Match: a unique key | — | 0..1 | the row, or `None` |
| `list` | each supplied Input field, compared as its Match term states (optional filters) | — | 0..n | a list of rows, in its Order |
| `create` | — | every Input field | 1 | the row |
| `update` | Match (default: the `PK`); comparison terms allowed | the other Input fields supplied | 0..1 on a unique key, else 0..n | the row or `None`; the count when it reaches many |
| `upsert` | Match: exactly one unique key | inserts the row, or replaces its other Input fields | 1 | the row |
| `delete` | Match: every Input field; comparison terms allowed | — | 0..1 on a unique key, else 0..n | the Output built from the Match or `None`; the count when it reaches many |

No other operator, no OR, no join, and no SQL exists outside the package.

### The operation contract

`DATABASE_compact.md` ends with a generated `## Operation Surface`: per table, one block per
operation, rendered from the declaration by Drydock, never by a model. Build against it.

````markdown
#### `db.rates.replace_rate` — FEATURE-RATE-004

| Kind | Rows | Match | Sets | Contract |
|---|---|---|---|---|
| upsert | 1 | `date`, `currency` | `rate` | `3f9a1c04be72` |

- Input: `{"date": "str", "currency": "str", "rate": "str"}`
- Output: `{"id": "int", "date": "str", "currency": "str", "rate": "str"}`

```sql
INSERT INTO "rates" ("date", "currency", "rate") VALUES (?, ?, ?) ON CONFLICT ("date", "currency") DO UPDATE SET "rate" = excluded."rate";
SELECT "id", "date", "currency", "rate" FROM "rates" WHERE "date" = ? AND "currency" = ?;
```
````

- **Call:** `db.<table>.<name>(...)`; Go `db.<Table>.<Name>(ctx, <Table><Name>Input{...})`.
- **Input / Output:** JSON field names with caller types `str`, `int`, `float`, `bool`, `bytes`.
  `?` marks a field the caller may omit: a `list` filter or bound, or a column an `update` sets
  only when supplied. A `- Order:` line states a `list`'s sort keys. Output is `{...}`, `{...} | null`, `[{...}]`, or `"int" (rows changed)`.
- **SQL:** the statements the runtime executes, in SQLite placeholder form; PostgreSQL binds the
  same positions. A test holds it byte-identical to the shipped driver.
- **Contract:** the operation's fingerprint, the first 12 hex digits of a SHA-256.

### What forces a rebuild

Only a contract change. The fingerprint hashes the name, Kind, Match terms, Order, rows, return shape, and each
Input and Output field's name and caller type. It excludes everything a caller cannot see: column
length (`VARCHAR(12)` and `VARCHAR(40)` are both `str`), nullability, `Required`, `DEFAULT`,
indexes, and the SQL. Refit rebuilds the callers of an operation only when its fingerprint moves;
any other `DATABASE.md` edit rebuilds the generated package alone.

**The declaration fixes the surface.** `DATABASE.md` names every operation in the
`Repository operation` cell of each access pattern, as `<table>.<name>`. That is the persistence
surface, not a suggestion for one. To reach the store differently, change the declaration and
rebuild; there is no second door.

**Why**: the declaration is the only description of the store the rest of the plan is allowed to
depend on. Generating from it means the operations a Blueprint cites and the operations that exist
cannot drift — they are the same list. Plan already refuses to write a plan whose tables,
operations, and citations disagree; generating the layer keeps the built code in that agreement
rather than trusting each build to re-derive it from prose.

**Caller contract**: `Database` presents single-threaded semantics. Callers construct one instance,
share it freely, call methods synchronously, and never reason about threads, connections, or
locking. Connection lifetime is internal to the package and may change without affecting any
caller. Returned rows are frozen dataclasses and carry no connection state.

**Engine selection is runtime, not build time.** Both engines are copied into every build and
chosen from the DSN, because the same build runs SQLite in development and test and PostgreSQL in
production. `VARCHAR(n)` is declared once and emitted to both: PostgreSQL enforces the length,
SQLite parses the same declaration and ignores it.

**Schema is built once.** `schema.sql` is applied at the DATABASE build step and never again
within a release. Application startup does not create or alter schema.

**Guardrails**

- Do not write a repository, DAO, ORM model, or session factory.
- Do not import `sqlite3`, `psycopg`, or a SQL string anywhere outside `persistence/`.
- Do not edit anything under `persistence/` — edit `DATABASE.md` and rebuild.
- Do not create or alter schema at application startup.

### Acceptance transactions

**Acceptance store lifecycle.** The DATABASE step provisions and verifies the configured store
once. Ordinary persistence criteria never replace DATABASE_URL/DATABASE_PATH, create a temporary
database, apply DDL, or assume an empty store. Configuration tests use the harness-owned fixture
below. The store may hold data before any criterion runs: assert on records the
criterion created, or on a count read before setup (`after == before + 5`), never on an absolute
table count.

For SQLite configuration and source-required open-failure acceptance, import
`database_environment` from `drydock_acceptance`. The harness supplies this module only inside
Python acceptance. `with database_environment(url="sqlite://primary.db", path="fallback.db") as root:`
sets both variables to absolute scratch paths and changes cwd to the yielded `Path`. None
unsets a variable; empty string sets it empty; other arguments must be relative file names.
Only `url` accepts `sqlite://`. Both variables and cwd are restored on exit, even on failure.
The fixture creates no schema or parent directory; `url="missing/app.db"` tests open failure.
Use separate contexts to test URL priority, prefix stripping, fallback and the default
`data/app.db`. Assert behavior through the declared product interface, never ordinary CRUD
against these unprovisioned paths. Direct DSN replacement remains forbidden.

The acceptance harness owns isolation. It begins one transaction before each Python criterion and
rolls it back when the criterion ends, pass or fail. Every database the criterion's process opens
joins it: `db_session()`, the application behind `web_client()`, and commands run through
`cli_runner()`. Setup, behavior and readback therefore see one another's writes, and none persists;
leaving a `with db_session() as db:` block rolls nothing back. Seed with `with db_session() as db:`
and pass that database into feature operations. Never commit, clean up, or open a transaction.

A criterion that launches a process (`subprocess`, a server on a port, a shell script) cannot see
that transaction. It does not open the store and does not depend on rows it wrote; exercise stored
behavior in-process instead. Go criteria use `OpenSession(ctx, "")` with checked deferred cleanup,
which rolls back its own transaction. Go HTTP, CLI and restart criteria use
`OpenCommittedSession(ctx, "")` with a criterion-owned identifier and checked `defer` cleanup
through supported product interfaces. Database acceptance must not be replaced by a project test
count: runtime catalog and row-count evidence proves provisioning, feature criteria prove behavior.

## 2. Config / `.env` → one typed Config class

One typed `Config` reads the environment once and validates at startup. Nothing else reads
`os.environ`. There are no `Dev`/`Prod`/`Test` subclasses — every field is inherited from the
environment, so the environment (`.env`) selects the configuration, not a Python subclass.

```python
# config.py
import os
from dataclasses import dataclass
from dotenv import load_dotenv
load_dotenv()

@dataclass(frozen=True)
class Config:
    secret_key: str
    database_path: str
    port: int
    debug: bool = False

    @classmethod
    def load(cls) -> "Config":
        try:
            return cls(
                secret_key=os.environ["SECRET_KEY"],
                database_path=os.environ.get("DATABASE_PATH", "data/app.db"),
                port=int(os.environ.get("APP_PORT", "5001")),
                debug=os.environ.get("APP_DEBUG") == "1",
            )
        except KeyError as e:
            raise RuntimeError(f"Missing required env var: {e}") from e
```

Typed fields mean a missing or malformed variable crashes at startup, not at first use.

---

## 3. Files → typed FileStore class

A `FileStore` owns a root directory and is the only code that opens application files. Callers
never build paths or call `open()`/`shutil` directly.

```python
# filestore.py
from pathlib import Path

class FileStore:
    def __init__(self, root: str): self._root = Path(root)
    def read(self, name: str) -> str:
        return (self._root / name).read_text(encoding="utf-8")
    def write(self, name: str, data: str) -> None:
        p = self._root / name; p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(data, encoding="utf-8")
    def list(self, pattern: str = "*") -> list[str]:
        return [p.name for p in self._root.glob(pattern)]
```

Path-traversal validation and atomic writes live here, once.

---

## 4. External services → wrapper modules over a shared base class

Every external-service wrapper extends one `ServiceClient` base class. The base owns the
backend handle, a named logger, and a uniform call guard; subclasses expose typed methods and
never leak the SDK client.

```python
# service.py — base class for all external-service wrappers
import logging

class ServiceClient:
    """Base for service wrappers. Owns the backend handle, logger, and a uniform
    call guard. Subclasses expose typed methods; they never expose the SDK client."""
    def __init__(self, backend, name: str | None = None):
        self._backend = backend
        self.log = logging.getLogger(name or type(self).__name__)

    def _guard(self, op, *args, **kwargs):
        try:
            return op(*args, **kwargs)
        except Exception:
            self.log.exception("%s call failed", type(self).__name__)
            raise
```

Wrappers subclass it. AWS commonly uses a project-owned cloud client library
(`client.queue`, `client.share`, `client.catalog`); any new service follows the same shape — e.g.
a `MessageBus` over SQS, even when it maps 1:1:

```python
# messagebus.py — the wrapper hides the transport
class MessageBus(ServiceClient):
    def publish(self, topic: str, payload: dict) -> str:
        return self._guard(self._backend.send, topic, payload)
    def subscribe(self, topic: str, handler) -> None: ...
```

**Why**: the base class makes logging and error handling uniform across services; the wrapper
is the seam. Swapping the transport, or stubbing it in tests, changes one class. See
`stack/cloud-client-library.md`, `stack/aws-sqs.md`, `stack/aws-s3.md`, `stack/aws-dynamodb.md`.

---

## Summary Checklist

- [ ] No hand-written repository, DAO, ORM model, session factory, or migration
- [ ] No raw SQL, `sqlite3`, or `psycopg` import outside the generated `persistence/` package
- [ ] Nothing under `persistence/` edited by hand
- [ ] No schema created or altered at application startup
- [ ] No `os.environ` reads outside the Config class
- [ ] No `open()`/`shutil` on application data outside FileStore
- [ ] No cloud SDK import outside its service wrapper
- [ ] One typed `Config`, ENV-driven, no Dev/Prod/Test subclasses
- [ ] Service wrappers extend the `ServiceClient` base class
- [ ] Downstream specs depend on the declared operations, not the schema
- [ ] Callers built against the Operation Surface contract: name, Input/Output JSON, rows

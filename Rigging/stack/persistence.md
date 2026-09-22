# Persistence & Service Encapsulation

**Version:** 20260919 V3
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
route → service → db.<table>.<verb>(...) → generated package → database
```

The package lands at `persistence/` in the build:

| File | Origin |
|---|---|
| `db.py`, `sqlite.py`, `postgres.py` | shipped by Drydock, copied unchanged |
| `schema.py` | generated from `DATABASE.md` — tables, operations, row dataclasses |
| `schema.sql` (beside the package) | generated DDL, applied once at the DATABASE step |

### Calling it

```python
from persistence import open_database

db = open_database(config.database_url)

ticket = db.tickets.get(id=ticket_id)          # returns a frozen dataclass, or None
open_tickets = db.tickets.list(status="open")  # returns a list of them
new_id = db.tickets.create(status="open", title=title)
db.tickets.update(id=ticket_id, status="closed")
db.tickets.delete(id=ticket_id)
```

One attribute per declared table, one method per declared access pattern. The method name is the
verb of that pattern's `Repository operation` cell, and its keyword arguments are that pattern's
`Input:` fields — nothing else is accepted. A verb the table does not declare raises
`UnknownOperation` naming what it does grant.

**The declaration fixes the surface.** `DATABASE.md` names every operation in the
`Repository operation` cell of each access pattern, as `<table>.<verb>`. That is the persistence
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

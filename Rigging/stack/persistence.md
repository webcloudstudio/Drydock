# Persistence & Service Encapsulation

**Version:** 20260603 V1
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

**ORM exception**: where an ORM is used (Django, SQLAlchemy), the ORM model class *is* the
table encapsulation and satisfies §1 — do not add a second hand-written layer.

---

## 1. Relational tables → typed Database class

Each table gets a row dataclass and a CRUD class. One `Database` class composes them and owns
the connection. Application code calls `db.<table>.method()` — never raw SQL.

```python
# db.py
import sqlite3
from dataclasses import dataclass

@dataclass
class Item:
    id: int | None
    name: str
    status: str = "active"
    created_at: str | None = None

class ItemTable:
    def __init__(self, conn): self._c = conn
    def create(self, name: str, status: str = "active") -> int:
        cur = self._c.execute(
            "INSERT INTO items (name, status) VALUES (?, ?)", (name, status))
        self._c.commit(); return cur.lastrowid
    def get(self, item_id: int) -> Item | None:
        r = self._c.execute("SELECT * FROM items WHERE id = ?", (item_id,)).fetchone()
        return Item(**r) if r else None
    def list(self) -> list[Item]:
        return [Item(**r) for r in self._c.execute("SELECT * FROM items").fetchall()]
    def update(self, item_id: int, **fields) -> None: ...
    def delete(self, item_id: int) -> None: ...

class Database:
    def __init__(self, path: str):
        self._conn = sqlite3.connect(path)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self.items = ItemTable(self._conn)   # one attribute per table
```

PRAGMAs, JSON-column handling, and migrations (see `stack/sqlite.md`) live inside
`Database`/the table classes, never in callers.

---

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

- [ ] No raw SQL outside table/Database classes
- [ ] No `os.environ` reads outside the Config class
- [ ] No `open()`/`shutil` on application data outside FileStore
- [ ] No cloud SDK import outside its service wrapper
- [ ] Each table: row dataclass + CRUD class, composed in one Database class
- [ ] One typed `Config`, ENV-driven, no Dev/Prod/Test subclasses
- [ ] Service wrappers extend the `ServiceClient` base class
- [ ] Downstream specs depend on the class interface, not the schema

<!-- Compacted from rigging/stack/python.md on 2026-07-16 (manual update to match python.md V3) -->

# Python — Compact

## Configuration Management

One typed frozen-dataclass `Config` is the only env reader — never read `os.environ` elsewhere. No `Dev`/`Prod`/`Test` subclasses; the environment (`.env`) selects configuration. Never hardcode secrets, ports, or paths. Secret hygiene and `.env.example`: see `stack/env_variables_and_secrets.md`.

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

## Code Style and Understandability

Code must be understandable through naming, structure, small focused units, explicit types, clear interfaces, appropriate abstractions, and tests. Names state intent; one responsibility per module; functions do one thing at one level of abstraction; no speculative abstraction layers. Comments state constraints the code cannot express — never restate mechanics.

## Type Hints and Static Typing

Modern hints on all public interfaces; typed structures across boundaries; run a type checker when practical.

- Built-in generics (`list[str]`, `dict[str, int]`) and `X | None` — never `typing.List`, `Optional`, `Union`
- Type every public function, method, and class attribute
- Schemas/serializers/services/data structures are typed classes: frozen dataclasses internally, Pydantic/`TypedDict` at serialization boundaries
- No bare `dict`, positional tuples, or `Any` crossing a module boundary
- `uv add --dev mypy` then `uv run mypy .` (or pyright) alongside ruff and pytest in CI

## Logging

Use `logging` with named loggers, never `print()`. Configure formatter + console and file handlers at startup (`data/logs/app.log`); level from `APP_DEBUG`.

```python
import logging
logger = logging.getLogger(__name__)
logger.info('Server starting on port %s', port)
```

## Environment Separation

Distinct `.env` per environment; same typed `Config` reads whichever is present. Never run debug in production.

| Setting | Dev | Test | Prod |
|---------|-----|------|------|
| APP_DEBUG | 1 | 0 | 0 |
| DATABASE_PATH | data/app.db | :memory: | data/app.db |
| SECRET_KEY | .env value | .env value | .env value (required) |
| LOGGING | DEBUG | WARNING | INFO |

## Testing

`pytest` with fixtures; fresh in-memory DB per test; test at the boundary. Every Python build must include a complete pytest suite regardless of the specification — no tests, no ACTIVE conformity.

```python
# tests/conftest.py
import pytest

@pytest.fixture
def app(monkeypatch):
    monkeypatch.setenv("SECRET_KEY", "test")
    monkeypatch.setenv("DATABASE_PATH", ":memory:")
    from app import create_app
    from config import Config
    yield create_app(Config.load())

@pytest.fixture
def client(app):
    return app.test_client()
```

**test_smoke.py** — app factory works; `GET /health` returns 200 `{"status": "ok"}`; `GET /` returns 200.

**test_routes.py** — one test per route: `GET` pages assert 200; `POST` APIs assert status in `{200, 201, 204}`; HTMX routes send `HX-Request: true`; `{id}` routes use fixture-created records.

**test_db.py** (only if DATABASE.md exists) — expected tables exist; round-trip per major table; invalid FK raises `IntegrityError` (`PRAGMA foreign_keys=ON`).

Do not test third-party internals, config loading, or private helpers.

```ini
# pytest.ini
[pytest]
testpaths = tests
addopts = -v
```

## Security

Validate all user input; parameterized queries exclusively; never trust client data.

- `?` placeholders, never f-strings, for all DB operations
- `secure_filename()` for user-supplied paths
- Length and type validation on inputs
- Secret key from environment, never hardcoded
- Never expose stack traces to end users

## Dependency Management (uv)

`uv` only; `pyproject.toml` is the manifest; `uv.lock` committed; `.venv/` gitignored. Full toolchain conventions: `stack/uv_ruff.md`.

```bash
uv venv                          # creates .venv/
uv add flask python-dotenv       # runtime deps → pyproject.toml + uv.lock
uv add --dev pytest ruff mypy    # dev deps
uv sync --frozen                 # CI — fail if lock is stale
```

- Never bare `pip install` or `python -m venv`
- Dev deps in `[project.optional-dependencies].dev`; runtime deps minimal

## Startup Validation

`Config.load()` already validates required env vars; startup validation confirms DB connectivity. Crash early on misconfiguration.

```python
def validate_startup(config: Config, db: Database):
    try:
        db.healthcheck()          # SELECT 1 inside the Database class
    except Exception as e:
        raise RuntimeError(f'Database not accessible: {e}')
    logger.info('Startup validation passed')
```

## Directory Layout

```
project-name/
├── app.py              # Entry point / app factory
├── routes.py           # Route handlers
├── models.py           # Data models and type registries
├── db.py               # Database class: typed tables, connection, schema, migrations
├── ops.py              # Business logic and operations
├── config.py           # typed Config class — the only env reader
├── templates/          # base.html + types/ partials
├── static/             # css/, js/
├── tests/              # conftest.py, test_*.py
├── bin/                # (from common.md)
├── data/               # (from common.md)
├── pyproject.toml
├── uv.lock
├── .env                # gitignored; .env.example committed
└── .gitignore
```

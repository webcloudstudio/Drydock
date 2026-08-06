# Python Best Practices

**Version:** 20260716 V3  
**Category:** Technologies
**Description:** Python language conventions and patterns for specification-driven projects

Technology reference for Python development. Framework-agnostic — applies to any Python project. This file does not change between projects.

Prerequisite: `stack/common.md`

---

## 1. Configuration Management

**Rule**: All environment access goes through one typed `Config` class (see `stack/persistence.md`) — never read `os.environ` elsewhere. Every field is inherited from the environment; there are no `Dev`/`Prod`/`Test` subclasses. Never hardcode secrets, ports, or paths.

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

Commit `.env.example` listing every variable `Config` reads, with dummy values. The build creates the local `.env` from it; `.env` itself is never committed.

```bash
# .env.example — committed; every variable Config reads, dummy values only
SECRET_KEY=change-me
DATABASE_PATH=data/app.db
APP_PORT=5001
APP_DEBUG=0
```

Rules:
- `python-dotenv` is a runtime dependency in `pyproject.toml` — not a dev dependency. Nothing in the toolchain loads `.env` on its own: `python run.py`, `uv run`, and `pytest` all leave the environment untouched. The application loads its own configuration or it does not start.
- `load_dotenv()` runs at import of `config.py`, before any `Config.load()` call, so every entry point — `run.py`, `bin/start.sh`, a management command, a worker — reads the same `.env`.
- `.env.example` is committed and lists every variable `Config` reads, no more and no fewer. A variable missing from it never reaches the running application.
- The startup error names the missing variable (`Missing required env var: 'SECRET_KEY'`). A generic message such as `Invalid application configuration` tells the operator nothing and is a defect.
- The entry point must start on a clean shell with nothing exported by hand: `.env` plus the defaults in `Config` are the whole configuration.

**Why**: A single typed `Config` is the only env reader. Typed fields crash on a missing or malformed variable at startup, not at first use. The environment (`.env`) selects configuration — not a Python subclass. A `Config` that reads `os.environ` without loading `.env` passes every test that constructs the app with overrides, then fails on the operator's first real run.

---

## 2. Code Style and Understandability

**Rule**: Code must be understandable on its own through naming, structure, small focused units, explicit types, clear interfaces, appropriate abstractions, and tests. If a reader needs a comment to follow the mechanics, improve the code instead.

Rules:
- **Naming** — names state intent: `load_active_users()`, not `get_data()`; `retry_limit`, not `n`. No abbreviations a new reader must decode.
- **Structure** — modules have one responsibility each (see §10 layout); related code lives together; call depth stays shallow.
- **Small focused units** — functions do one thing at one level of abstraction; a function that needs a section comment ("# now validate…") is two functions.
- **Explicit types** — public interfaces are fully typed (§3); the signature answers "what goes in, what comes out" without reading the body.
- **Clear interfaces** — few parameters, typed returns, no boolean flags that change what a function fundamentally does, no output-by-mutation surprises.
- **Appropriate abstractions** — introduce a layer only to remove real duplication or isolate a boundary (DB, cloud, external API). No speculative generality.
- **Tests** — tests are the executable specification of behavior (§6); a behavior worth keeping is a behavior worth a test.
- Comments state constraints the code cannot express (invariants, external quirks, why-not-the-obvious-way) — never restate what the next line does.

**Why**: Code is read far more often than written. Every hour invested in clarity is repaid at each future read, debug, and review — including by the author six months later.

---

## 3. Type Hints and Static Typing

**Rule**: Use modern type hints on all public interfaces. Model data that crosses module or process boundaries with typed structures — dataclasses, `TypedDict`, or Pydantic models — never bare dicts or tuples of implicit shape. Run a static type checker when practical.

```python
from dataclasses import dataclass

@dataclass(frozen=True)
class User:
    id: int
    email: str
    roles: list[str]

# Public interfaces are fully typed; modern syntax only
def load_users(db: Database, limit: int | None = None) -> list[User]: ...

# Boundary shapes are explicit types, never dict[str, Any]
def to_response(user: User) -> UserResponse: ...
```

Rules:
- Type every public function, method, and class attribute. Module-private helpers may omit hints when the types are obvious.
- Use modern syntax: built-in generics (`list[str]`, `dict[str, int]`) and unions (`X | None`) — never `typing.List`, `Optional`, or `Union`.
- Schemas, serializers, services, and data structures are typed classes where appropriate: frozen dataclasses for internal data, Pydantic models or `TypedDict` at serialization and validation boundaries.
- Never rely on implicit or ambiguous shapes — no bare `dict`, positional tuples, or `Any` crossing a module boundary. If a shape matters, give it a name and a type.
- Run a suitable static type checker when practical: `uv add --dev mypy` then `uv run mypy .` (pyright is an acceptable alternative). Run it alongside ruff and pytest in CI.

**Why**: Typed interfaces make wrong calls fail at check time instead of runtime, and named shapes document intent where docstrings drift. The type checker is the cheapest reviewer the project has.

---

## 4. Logging

**Rule**: Use Python's `logging` module with named loggers, never `print()`. Configure formatters and handlers at startup.

```python
import logging
import os

def setup_logging(level=None):
    level = level or ('DEBUG' if os.getenv('APP_DEBUG') else 'INFO')

    formatter = logging.Formatter(
        '%(asctime)s %(name)s %(levelname)s %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )

    console = logging.StreamHandler()
    console.setFormatter(formatter)

    root = logging.getLogger()
    root.setLevel(level)
    root.addHandler(console)

    # File handler
    os.makedirs('data/logs', exist_ok=True)
    file_handler = logging.FileHandler('data/logs/app.log')
    file_handler.setFormatter(formatter)
    root.addHandler(file_handler)
```

```python
# In any module
import logging
logger = logging.getLogger(__name__)

logger.info('Server starting on port %s', port)
logger.error('Failed to connect: %s', err)
```

**Why**: Named loggers trace messages to source modules. Structured format enables log parsing.

---

## 5. Environment Separation

**Rule**: Maintain distinct `.env` files per environment; the same typed `Config` reads whichever `.env` is present. Never run debug mode in production.

| Setting | Dev | Test | Prod |
|---------|-----|------|------|
| APP_DEBUG | 1 | 0 | 0 |
| DATABASE_PATH | data/app.db | :memory: | data/app.db |
| SECRET_KEY | .env value | .env value | .env value (required) |
| LOGGING | DEBUG | WARNING | INFO |

**Why**: Environment separation lives in `.env` values, not Python config subclasses, so the same code path runs everywhere. This prevents dev shortcuts from reaching production.

---

## 6. Testing

**Rule**: Use `pytest` with fixtures. Isolate each test with a fresh database. Test at the boundary, not internals. Every Python project build must include a complete pytest suite regardless of whether the specification mentions tests — a project without tests does not satisfy ACTIVE conformity.

### Required test files

**`tests/conftest.py`** — fixtures shared across all test modules:
- `app` fixture: `create_app(TestConfig)` — in-memory DB, `TESTING=True`
- `client` fixture: `app.test_client()`
- `db` fixture: fresh `init_db(':memory:')` per test, yielded inside `app.app_context()`

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

@pytest.fixture
def db(app):
    from db import Database
    with app.app_context():
        yield Database(':memory:')
```

**`tests/test_smoke.py`** — liveness checks:
- App factory returns a Flask app without error
- `GET /health` returns 200 and `{"status": "ok"}`
- Root route `GET /` returns 200

**`tests/test_routes.py`** — one test per registered route:
- Every `GET` page route: `assert response.status_code == 200`
- Every `POST` API route: assert status in `{200, 201, 204}` with a minimal valid payload
- HTMX routes: include `HX-Request: true` header; assert 200 and non-empty `response.data`
- Routes with `{id}` params: use a fixture-created record for the ID

**`tests/test_db.py`** — only if project has a DATABASE.md:
- Schema test: after `Database(path)` init, all expected tables exist (`SELECT name FROM sqlite_master WHERE type='table'`)
- Round-trip per major table: insert a minimal valid row, read it back, assert field values match
- FK enforcement: inserting a row with an invalid FK raises `IntegrityError` (requires `PRAGMA foreign_keys=ON`)

### Configuration

**`pytest.ini`** at project root:
```ini
[pytest]
testpaths = tests
addopts = -v
```

Add `pytest` to `pyproject.toml` dev dependencies (see §8).

### What not to test
- Third-party library internals (Flask, SQLite, HTMX)
- Configuration loading — tested implicitly by fixture startup
- Private helper functions — test through the public interface that uses them

**Why**: Fixtures ensure clean state per test. In-memory DB makes tests fast.

---

## 7. Security Basics

**Rule**: Validate all user input. Use parameterized queries exclusively. Never trust client data.

Checklist:
- Parameterized queries for all DB operations (`?` placeholders, never f-strings)
- `secure_filename()` for any file path from user input
- Length and type validation on inputs
- Secret key loaded from environment, not hardcoded in prod
- Never expose stack traces to end users

**Why**: These basics prevent the most common attack vectors with minimal effort.

---

## 8. Dependency Management (uv)

**Rule**: Use `uv` for venv creation and dependency management. `pyproject.toml` is the required manifest; `uv.lock` is committed.

```bash
uv venv                         # creates .venv/
uv add flask python-dotenv      # add runtime deps → updates pyproject.toml + uv.lock
uv add --dev pytest ruff mypy   # add dev deps
uv sync                         # install from uv.lock (standard clone setup)
uv sync --frozen                # strict install (CI — fail if lock is stale)
```

```toml
# pyproject.toml
[project]
name = "my-project"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
    "flask>=3.1",
    "python-dotenv>=1.0",
]

[project.optional-dependencies]
dev = ["pytest>=8.0", "ruff>=0.4", "mypy>=1.10"]

[tool.ruff]
line-length = 88

[tool.ruff.lint]
select = ["E", "F", "I", "UP", "B"]

[tool.ruff.format]
quote-style = "double"
```

Rules:
- Use `uv add` / `uv pip install` — never bare `pip install`
- Use `uv venv` — never `python -m venv`
- Commit `pyproject.toml` and `uv.lock`; `.venv/` is gitignored
- Keep runtime dependencies minimal; dev deps in `[project.optional-dependencies].dev`
- When migrating an existing project: `uv venv`, `uv pip install -r requirements.txt`, `uv lock`, commit `uv.lock`

**Why**: uv resolves and locks dependencies deterministically, eliminating "works on my machine" drift. `uv sync --frozen` in CI guarantees the exact locked versions are installed.

Full toolchain conventions (uv workflow, ruff rulesets, local/CI gates): see `stack/uv_ruff.md`.

---

## 9. Health Check and Startup Validation

**Rule**: Validate required config and DB connectivity at startup. Crash early on misconfiguration.

```python
def validate_startup(config: Config, db: Database):
    """Crash early on misconfiguration. Config.load() already validates required
    env vars; here we confirm the database is reachable."""
    try:
        db.healthcheck()          # runs SELECT 1 inside the Database class
    except Exception as e:
        raise RuntimeError(f'Database not accessible: {e}')

    logger.info('Startup validation passed')
```

**Why**: Required env vars are validated when `Config.load()` constructs the typed config, so startup validation only needs to confirm connectivity. Catches misconfigurations immediately rather than at first user request.

---

## 10. Project Directory Layout (Python-specific)

Python web projects extend the common layout:

```
project-name/
├── app.py              # Entry point / app factory
├── routes.py           # Route handlers
├── models.py           # Data models and type registries
├── db.py               # Database class: typed tables (row dataclass + CRUD), connection, schema, migrations
├── ops.py              # Business logic and operations
├── config.py           # typed Config class — the only env reader (stack/persistence.md)
├── templates/          # Jinja2 or Django templates
│   ├── base.html
│   └── types/          # Type-specific partials
├── static/
│   ├── css/
│   └── js/
├── tests/
│   ├── conftest.py
│   └── test_*.py
├── bin/                # (from common.md)
├── data/               # (from common.md)
├── pyproject.toml      # preferred dependency manifest
├── uv.lock             # committed — reproducible install record
├── .env
├── .gitignore
└── CLAUDE.md           # endpoints/bookmarks live in AGENTS.md — no Links.md
```

---

## Summary Checklist

- [ ] One typed `Config` class is the only env reader; no hardcoded secrets, no Dev/Prod/Test subclasses; `.env.example` maintained (`stack/env_variables_and_secrets.md`)
- [ ] Code understandable through naming, structure, small units, explicit types, clear interfaces, appropriate abstractions, and tests
- [ ] All persistence/services through typed classes (`stack/persistence.md`) — no raw SQL/`os.environ`/`open()`/SDK in app code
- [ ] Modern type hints on all public interfaces; typed schemas/serializers/services; no ambiguous shapes across boundaries; type checker run when practical
- [ ] Logging with named loggers, not `print()`
- [ ] Distinct dev/test/prod configs
- [ ] pytest with fixtures and isolated test DB
- [ ] Input validation, parameterized queries
- [ ] `uv` for venv + deps; `pyproject.toml` + `uv.lock` committed; `.venv/` gitignored
- [ ] Startup validation for required config

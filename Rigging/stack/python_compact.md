<!-- Compacted from RulesEngine/stack/python.md on 2026-04-30 by prompts/compact_file.md — regenerate via bin/rulesengine_compact.sh -->

# Python — Compact

## Configuration Management

Use environment variables loaded via `python-dotenv`. Never hardcode secrets, ports, or paths.

```python
# config.py
import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY', 'dev-key-change-me')
    DATABASE_PATH = os.environ.get('DATABASE_PATH', 'data/app.db')
    DEBUG = False

class DevConfig(Config):
    DEBUG = True

class ProdConfig(Config):
    SECRET_KEY = os.environ['SECRET_KEY']  # Crash if missing in prod

class TestConfig(Config):
    DATABASE_PATH = ':memory:'
    TESTING = True
```

## Logging

Use Python's `logging` module with named loggers, never `print()`.

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
    os.makedirs('data/logs', exist_ok=True)
    file_handler = logging.FileHandler('data/logs/app.log')
    file_handler.setFormatter(formatter)
    root.addHandler(file_handler)
```

```python
import logging
logger = logging.getLogger(__name__)
logger.info('Server starting on port %s', port)
logger.error('Failed to connect: %s', err)
```

## Environment Separation

| Setting | Dev | Test | Prod |
|---------|-----|------|------|
| DEBUG | True | False | False |
| DATABASE | data/app.db | :memory: | data/app.db |
| SECRET_KEY | hardcoded default | hardcoded default | env var (required) |
| LOGGING | DEBUG | WARNING | INFO |

## Testing

Use `pytest` with fixtures. Isolate each test with a fresh database. Every Python project build must include a complete pytest suite regardless of whether the specification mentions tests — a project without tests does not satisfy ACTIVE conformity.

```python
# tests/conftest.py
import pytest

@pytest.fixture
def app():
    from app import create_app
    app = create_app(TestConfig)
    yield app

@pytest.fixture
def client(app):
    return app.test_client()

@pytest.fixture
def db(app):
    from db import get_db, init_db
    with app.app_context():
        init_db(':memory:')
        yield get_db()
```

**test_smoke.py** — `GET /health` returns 200 and `{"status": "ok"}`; root `GET /` returns 200.

**test_routes.py** — one test per registered route: every `GET` page: assert 200; every `POST` API: assert status in `{200, 201, 204}`; HTMX routes: include `HX-Request: true` header; routes with `{id}` params: use fixture-created record.

**test_db.py** (only if DATABASE.md exists) — schema test: all expected tables exist; round-trip per major table; FK enforcement: invalid FK raises `IntegrityError` (requires `PRAGMA foreign_keys=ON`).

```ini
# pytest.ini
[pytest]
testpaths = tests
addopts = -v
```

Add `pytest` to `pyproject.toml` dev dependencies.

## Security

Validate all user input. Use parameterized queries exclusively. Never trust client data.

- Parameterized queries for all DB operations (`?` placeholders, never f-strings)
- `secure_filename()` for any file path from user input
- Length and type validation on inputs
- Secret key loaded from environment, not hardcoded in prod
- Never expose stack traces to end users

## Dependency Management (uv)

Use `uv` for venv creation and dependency management. `pyproject.toml` is the required manifest; `uv.lock` is committed.

```bash
uv venv                         # creates .venv/
uv add flask python-dotenv      # add runtime deps → updates pyproject.toml + uv.lock
uv add --dev pytest ruff        # add dev deps
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
dev = ["pytest>=8.0", "ruff>=0.4"]

[tool.ruff]
line-length = 88

[tool.ruff.lint]
select = ["E", "F", "I", "UP", "B"]

[tool.ruff.format]
quote-style = "double"
```

- Use `uv add` / `uv pip install` — never bare `pip install`
- Use `uv venv` — never `python -m venv`
- Commit `pyproject.toml` and `uv.lock`; `.venv/` is gitignored
- Keep runtime dependencies minimal; dev deps in `[project.optional-dependencies].dev`

## Startup Validation

Validate required config and DB connectivity at startup. Crash early on misconfiguration.

```python
def validate_startup():
    """Crash early if critical config is missing."""
    required_vars = ['PROJECTS_DIR']
    missing = [v for v in required_vars if not os.environ.get(v)]
    if missing:
        raise RuntimeError(f'Missing required env vars: {", ".join(missing)}')

    from db import get_db
    try:
        get_db().execute('SELECT 1')
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
├── db.py               # Database connection, schema, migrations
├── ops.py              # Business logic and operations
├── config.py           # Config classes (Dev/Prod/Test)
├── templates/
│   ├── base.html
│   └── types/
├── static/
│   ├── css/
│   └── js/
├── tests/
│   ├── conftest.py
│   └── test_*.py
├── bin/
├── data/
├── pyproject.toml
├── uv.lock
├── .env
└── .gitignore
```

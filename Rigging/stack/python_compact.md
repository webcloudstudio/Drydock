<!-- Compacted from Rigging/stack/python.md sha256=fae6705fe87b7e1483892f5a7253af9e5902908ff062e481ca80b220598bd11f on 2026-09-20 by drydock rigging compact — regenerate with: drydock rigging compact --include-file {rel_source} -->

## Foundation Contract

The published shape of this foundation. It is built before every other foundation: a web server,
a database, or a CLI is built *into* this tree, this environment, and this test runner. Carried
verbatim into `python_compact.md`.

- source_root: ./
- test_command: pytest -q
- environment: `.venv`, created by `uv venv` and activated by every launcher in `bin/`
- dependencies: `pyproject.toml`

```
project/
  pyproject.toml          # [project] metadata, dependencies, tool.ruff, tool.pytest
  .python-version         # the interpreter uv provisions
  .venv/                  # created by `uv venv`; never committed
  config.py               # the one typed Config; every environment variable is read here
  run.py                  # entry point
  tests/                  # pytest suite; conftest.py holds the published fixtures
  bin/                    # launchers; each activates .venv before running anything
```

Each later foundation adds one package directory at the project root — `app_server/`,
`persistence/`, `cli/` — and restructures nothing. Every launcher, every acceptance criterion,
and every CI job runs the one `test_command` above.

---

# Python Best Practices — Contract Surface

## Configuration

### Config
A frozen typed configuration schema loads application settings from the environment.

| Field | Type | Required |
|---|---|---|
| `secret_key` | `str` | Yes |
| `database_path` | `str` | No; defaults to `data/app.db` |
| `port` | `int` | No; defaults to `5001` |
| `debug` | `bool` | No; enabled when `APP_DEBUG=1` |

Constraints: `.env.example` lists every configuration variable with dummy values; `.env` is not committed. Environment access occurs only through `Config`. Missing required variables raise `RuntimeError` naming the variable. Configuration uses one class across environments.

### Config.load
Loads and validates a `Config` instance from environment variables.

Returns: `Config`.

Constraints: `SECRET_KEY` is required. `APP_PORT` must parse as an integer. `.env` is loaded before configuration is read.

## Typed Interfaces

### User
Represents a user crossing a module boundary.

| Field | Type |
|---|---|
| `id` | `int` |
| `email` | `str` |
| `roles` | `list[str]` |

Constraints: Boundary data uses named typed structures rather than implicit dictionaries, tuples, or `Any`.

### load_users
Loads users from a database.

| Parameter | Type |
|---|---|
| `db` | `Database` |
| `limit` | `int \| None` |

Returns: `list[User]`.

### to_response
Converts a typed user into a response schema.

| Parameter | Type |
|---|---|
| `user` | `User` |

Returns: `UserResponse`.

## Logging

### setup_logging
Configures application logging with formatted console and file handlers.

| Parameter | Type |
|---|---|
| `level` | unspecified optional level |

Constraints: Use Python `logging` with named loggers; application modules must not use `print()`. Startup logging includes timestamp, logger name, severity, and message.

## Validation

### validate_startup
Validates database connectivity during application startup.

| Parameter | Type |
|---|---|
| `config` | `Config` |
| `db` | `Database` |

Returns: None.

Constraints: Database health validation executes a connectivity check. Failure raises `RuntimeError` identifying the database error.

### Rule: public-typing
All public functions, methods, and class attributes have modern type hints.

Constraints: Use built-in generics and `X | None`; avoid `typing.List`, `Optional`, and `Union`.

### Rule: input-validation
All user input is validated for type and length.

Constraints: Database queries are parameterized; user-provided file paths use `secure_filename()`; stack traces are not exposed to users.

### Rule: testing
Every Python project includes a complete pytest suite with isolated test state.

Constraints: Required fixtures include `app`, `client`, and `db`. Smoke tests cover app creation, `GET /health` returning `200` and `{"status": "ok"}`, and `GET /` returning `200`. Route tests cover every registered route with valid payloads and required HTMX headers.

## Dependencies

### pyproject.toml
Defines runtime and development dependencies and project tooling.

Constraints: Use `uv` for environment and dependency management. Commit `pyproject.toml` and `uv.lock`; do not commit `.venv/`. Runtime dependencies include `python-dotenv`; development dependencies include `pytest`, `ruff`, and `mypy`. Minimum Python version is `3.11`.

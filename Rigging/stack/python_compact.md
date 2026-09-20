<!-- Compacted from Rigging/stack/python.md sha256=194fbdfb4f91c311b92e36438861e4db5e1d8fd338ef12a22925d5195bce53e0 on 2026-09-20 by drydock rigging compact — regenerate with: drydock rigging compact --include-file {rel_source} -->

# Python Best Practices — Contract Surface

## Configuration

### Config.load

Loads typed application configuration from `.env` and environment variables.

| Field | Source | Required | Type | Default |
|---|---|---:|---|---|
| `secret_key` | `SECRET_KEY` | Yes | `str` | — |
| `database_path` | `DATABASE_PATH` | No | `str` | `data/app.db` |
| `port` | `APP_PORT` | No | `int` | `5001` |
| `debug` | `APP_DEBUG` | No | `bool` | `False` |

Returns a frozen `Config` instance.

Constraints: Missing required variables raise `RuntimeError` naming the variable. `config.py` calls `load_dotenv()` at import. All environment access goes through this class. `.env.example` lists every read variable with dummy values; `.env` is not committed.

### Rule: dependency-management

Use `uv` with committed `pyproject.toml` and `uv.lock`; runtime dependencies belong in project dependencies and development tools in the `dev` extra.

Constraints: Use `uv venv`, `uv add`, `uv pip install`, `uv sync`, and `uv sync --frozen`; do not use bare `pip` or `python -m venv`.

## Public Interfaces

### load_users

Loads users from a database.

| Parameter | Type | Default |
|---|---|---:|
| `db` | `Database` | — |
| `limit` | `int \| None` | `None` |

Returns `list[User]`.

### to_response

Converts a typed `User` into a typed `UserResponse`.

| Parameter | Type |
|---|---|
| `user` | `User` |

Returns `UserResponse`.

### Rule: typed-boundaries

Public functions, methods, and class attributes have modern type hints. Data crossing module or process boundaries uses named typed structures such as frozen dataclasses, `TypedDict`, or Pydantic models.

Constraints: Do not use bare dictionaries, implicit-shape tuples, `Any`, `typing.List`, `Optional`, or `Union` at boundaries.

## Startup

### validate_startup

Validates database connectivity after configuration loading.

| Parameter | Type |
|---|---|
| `config` | `Config` |
| `db` | `Database` |

Constraints: Database health validation must confirm connectivity; startup failure raises `RuntimeError` identifying the database error. Required environment variables are validated by `Config.load()`.

## Logging

### setup_logging

Configures named logging with timestamped console and file handlers.

| Parameter | Type | Default |
|---|---|---:|
| `level` | unspecified | `DEBUG` when debug mode is enabled, otherwise `INFO` |

Constraints: Use Python’s `logging` module and named loggers; application code must not use `print()`.

## Testing

### Rule: pytest-suite

Every Python project includes a complete pytest suite with isolated test state.

Constraints: Provide `tests/conftest.py` with `app`, `client`, and fresh in-memory `db` fixtures. Provide `tests/test_smoke.py` covering app creation, `GET /health` returning `200` and `{"status": "ok"}`, and `GET /` returning `200`. Provide `tests/test_routes.py` with one test per registered route. Provide `tests/test_db.py` when a `DATABASE.md` exists, covering tables, round trips, and foreign-key enforcement. Configure `pytest.ini` with `testpaths = tests` and `addopts = -v`.

## Security

### Rule: input-validation

Validate all user input, use parameterized database queries, and never trust client data.

Constraints: Use `?` query placeholders, `secure_filename()` for user-derived paths, length and type validation, environment-loaded production secrets, and no exposed stack traces.

## Environment

### Rule: environment-separation

Use the same typed `Config` for distinct development, test, and production `.env` files.

Constraints: Production never runs with debug enabled. Test configuration uses `APP_DEBUG=0` and `DATABASE_PATH=:memory:`.

## Project Contract

### Rule: startup-configuration

The application starts from a clean shell using `.env` and `Config` defaults as its complete configuration.

### Rule: static-verification

Run a suitable type checker when practical alongside Ruff and pytest.

### Rule: project-layout

Python web projects provide `app.py`, `routes.py`, `models.py`, `db.py`, `ops.py`, `config.py`, `templates/`, `static/`, `tests/`, `bin/`, `data/`, `pyproject.toml`, `uv.lock`, `.env`, and `.gitignore`.

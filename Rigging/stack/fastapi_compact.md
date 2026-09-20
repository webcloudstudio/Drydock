<!-- Compacted from Rigging/stack/fastapi.md sha256=422e407dfe2bcf028c3080521bca8baa497de7696206d53f9e824a3fe52f2d22 on 2026-09-20 by drydock rigging compact — regenerate with: drydock rigging compact --include-file {rel_source} -->

## Foundation Contract

The published shape of this foundation. Drydock synthesizes the story that builds it and every
acceptance criterion writes against these names. Carried verbatim into `fastapi_compact.md`.

- package: app_server
- entry: create_app() -> FastAPI
- fixture: web_client
- fixture_source: conftest.py

```python
# app_server/main.py
def create_app() -> FastAPI:
    ...

# conftest.py
import pytest
from fastapi.testclient import TestClient
from app_server.main import create_app

@pytest.fixture
def web_client() -> TestClient:
    return TestClient(create_app())
```

A criterion calls `web_client`; it never constructs a client itself and never calls
`create_app().test_client()`, which is Flask's API and does not exist on a FastAPI application.

---

# FastAPI Best Practices — Contract Surface

## Application

### function create_app()
Creates and returns a configured FastAPI application.

Returns: a `FastAPI` instance.

Constraints: Mount `/static`; include page routes and API routes under `/api`; configure templates and exception handlers; support lifespan startup and shutdown handlers.

### config_key APP_PORT
Configures the port used by the `run.py` entry point.

Constraints: Defaults to `8000`; value is an integer.

### METHOD /health
Verifies that the backing store is reachable.

Returns:

| Status | Body |
|---|---|
| 200 | `{"status": "ok"}` |
| 500 | `{"status": "error", "detail": "<error message>"}` |

### METHOD /static
Serves static files.

Constraints: Static assets are referenced under `/static/...`.

### Rule: application-layout
Application code resides under `app_server/`; `run.py` is the direct entry point and exposes `app_server.main:app`; `config.py` remains at the project root.

## API

### METHOD GET /api/steps
Lists available steps.

Returns: the result of `services.list_steps(store)`.

### METHOD POST /api/steps/{step_id}/decision
Records a decision for a step.

| Input | Type | Required |
|---|---|---|
| `step_id` | integer path parameter | yes |
| `decision` | `Decision` request body | yes |

Returns:

```json
{"ok": true, "step_id": 1}
```

### function list_steps(store)
Returns the steps read from the supplied store.

Returns: `store.read_steps()`.

### function record_decision(store, step_id, decision)
Writes a decision to the supplied store and returns its result.

Constraints: Write `step_id`, `decision.status`, and `decision.feedback` through `store.write_decision`.

Returns: `{"ok": true, "step_id": step_id}`.

## Models

### Decision
Represents a submitted step decision.

| Field | Type | Required | Constraints |
|---|---|---:|---|
| `status` | literal string | yes | Must be `approved`, `revise`, or `rejected` |
| `feedback` | optional string | no | Maximum 4000 characters; defaults to `null` |

### StepView
Represents a step response.

| Field | Type |
|---|---|
| `id` | integer |
| `name` | string |
| `status` | string |
| `evidence_files` | list of strings |

## Pages

### METHOD GET /
Renders the index page with the current steps.

Returns: an HTML template response for `index.html`.

Constraints: The template context includes `request` and `steps`; pages inherit from `base.html`; partial templates use a leading `_`; templates contain no Python logic; auto-escaping remains enabled.

## Dependencies

### function get_settings()
Returns validated application settings.

Returns: a `Settings` instance.

### function get_store(settings)
Creates the backing state store using `settings.workspace_dir`.

| Input | Type | Required |
|---|---|---:|
| `settings` | `Settings` | yes |

Constraints: Shared resources are provided through FastAPI dependency injection and can be replaced through `app.dependency_overrides`.

## Configuration

### Settings
Defines typed configuration loaded from environment variables and `.env`.

| Field | Type | Default |
|---|---|---|
| `app_name` | string | `"My App"` |
| `app_port` | integer | `8000` |
| `workspace_dir` | string | `"./workspace"` |

## Error Handling

### Rule: API-error-response
Expected errors raise `HTTPException`; API errors under `/api/*` return JSON and non-API errors return HTML.

Constraints: Error responses must not expose stack traces; a missing API resource returns HTTP 404 with `{"error": "Not found"}`.

## Testing

### Rule: TestClient
HTTP behavior is tested through `fastapi.testclient.TestClient`.

Constraints: Tests use `create_app()`, override dependencies through `app.dependency_overrides`, and place fixtures in `tests/conftest.py`.

### config_key requirements.txt
The project includes `fastapi`, `uvicorn`, `jinja2`, `pydantic-settings`, `httpx`, and `pytest`.

### config_key pytest.ini
Sets `testpaths = tests` and `addopts = -v`.

## Runtime

### Rule: development-server
Development runs Uvicorn with reload enabled.

Constraints: `--reload` is development-only and is not combined with multiple workers.

### Rule: production-server
Production runs Uvicorn without reload and may use multiple workers.

Constraints: The application binds to the configured host and port.

### Rule: lifecycle
Startup and shutdown behavior is implemented with FastAPI lifespan handlers, not import-time side effects.

### config_key bin/start.sh
Starts `uvicorn app_server.main:app --reload --port "$PORT"` after loading shared shell configuration.

### config_key bin/stop.sh
Stops the `uvicorn app_server.main:app` process and reports when no matching process exists.

### config_key bin/test.sh
Runs `python -m pytest tests/ -v`.

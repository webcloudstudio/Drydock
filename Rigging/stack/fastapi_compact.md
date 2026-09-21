<!-- Compacted from Rigging/stack/fastapi.md sha256=485be8fc2c9aa5b7c0e29116feea585fb230cf375ea54abe53c3471e6c0be4dc on 2026-09-20 by drydock rigging compact — regenerate with: drydock rigging compact --include-file {rel_source} -->

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

### create_app()
Creates and returns a configured FastAPI application.

Returns: A FastAPI instance with static files, routers, templates, exception handlers, and lifespan behavior configured.

Constraints: Expose the created application as module-level `app` for `uvicorn app_server.main:app`.

### config_key
Typed settings are loaded through `pydantic-settings.BaseSettings`.

| Key | Type | Default |
|---|---|---|
| `app_name` | `str` | `"My App"` |
| `app_port` | `int` | `8000` |
| `workspace_dir` | `str` | `"./workspace"` |

Constraints: Environment configuration is centralized; `.env` is supported.

## API

### GET /api/steps
Returns the available steps from the backing store.

| Input | Type | Required |
|---|---|---|
| `store` | dependency-provided store | yes |

Returns: A serialized list of steps.

### POST /api/steps/{step_id}/decision
Records a decision for a step.

| Input | Type | Required |
|---|---|---|
| `step_id` | `int` path parameter | yes |
| `decision` | `Decision` request body | yes |
| `store` | dependency-provided store | yes |

Returns:

| Field | Type |
|---|---|
| `ok` | `bool` |
| `step_id` | `int` |

Constraints: Route handlers validate input, delegate to business logic, and return serializable values.

### GET /health
Verifies that the application can reach its backing store.

Returns on success:

```json
{"status": "ok"}
```

Returns on backing-store failure: HTTP 500 with `{"status": "error", "detail": "<error message>"}`.

## Schemas

### Decision
Represents a submitted step decision.

| Field | Type | Required | Constraints |
|---|---|---:|---|
| `status` | literal string | yes | One of `approved`, `revise`, `rejected` |
| `feedback` | optional string | no | Maximum 4000 characters |

### StepView
Represents a step response.

| Field | Type |
|---|---|
| `id` | `int` |
| `name` | `str` |
| `status` | `str` |
| `evidence_files` | `list[str]` |

## Pages and Errors

### GET /
Renders the index page with the current steps.

Returns: An HTML response rendered from a Jinja2 template.

Constraints: Template response context includes `request`; pages extend `base.html`; static assets use `/static/...`.

### Rule: error-responses
Expected errors use HTTP error responses without leaking stack traces.

Constraints: Requests under `/api/*` receive JSON errors; other requests receive HTML errors. Missing resources return HTTP 404.

## Runtime

### Rule: application-layout
Application code is under the `app_server/` package, with `run.py` as the direct entry point and `config.py` at the project root.

Constraints: `services.py` contains framework-independent business logic; `deps.py` provides injectable shared resources.

### Rule: dependency-injection
Shared resources are provided through FastAPI dependency injection and can be overridden in tests.

Constraints: Tests use `app.dependency_overrides` to replace providers.

### Rule: testing
HTTP behavior is tested through `fastapi.testclient.TestClient`.

Constraints: Required test dependencies include `fastapi`, `uvicorn`, `jinja2`, `pydantic-settings`, `httpx`, and `pytest`.

### Rule: development-server
Development runs Uvicorn with reload enabled; production does not use reload and may run multiple workers.

Constraints: Startup and shutdown behavior uses lifespan handlers, not import-time side effects.

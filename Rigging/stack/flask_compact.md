<!-- Compacted from Rigging/stack/flask.md sha256=5c0bdd0cb6c625d038bcab69f701d293d4f814b5c294ee4d10cf54867a3f5bd2 on 2026-09-20 by drydock rigging compact — regenerate with: drydock rigging compact --include-file {rel_source} -->

## Foundation Contract

The published shape of this foundation. Drydock synthesizes the story that builds it and every
acceptance criterion writes against these names. Carried verbatim into `flask_compact.md`.

- package: app_server
- entry: create_app() -> Flask
- fixture: web_client
- fixture_source: conftest.py

```python
# app_server/__init__.py
def create_app() -> Flask:
    ...

# conftest.py
import pytest
from app_server import create_app

@pytest.fixture
def web_client():
    app = create_app()
    app.config["TESTING"] = True
    return app.test_client()
```

A criterion calls `web_client`; it never constructs a client itself.

---

# Flask Best Practices — Contract Surface

## Application

### create_app

Creates and configures a Flask application.

| Input | Type | Required |
|---|---|---|
| `config` | configuration object or `None` | No |

Returns: configured Flask application.

Constraints: Must load real configuration even when overrides are supplied; initialize the database; register blueprints, error handlers, and startup validation; remain thread-safe for request handling.

### run.py

Provides an importable application entry point and runs the server only when executed directly.

Constraints: Calls `load_dotenv()` before `create_app()`; reads `APP_PORT` with default `5001`; must not start a server on import.

### Rule: application-layout

Constraints: Application Python files live under `app_server/`; root contains `run.py` and `config.py`; `app_server/__init__.py` exposes `create_app()`; templates and static assets live under `app_server/`.

### config_key

`SECRET_KEY` configures Flask sessions and flash messages.

Constraints: Required; read from the environment; never hardcoded or defaulted in production.

### config_key

`FLASK_DEBUG` controls debug mode.

Constraints: Enabled only in development; production value is `0`.

### config_key

`APP_PORT` controls the development server port.

Constraints: Defaults to `5001`.

## Routes

### GET /projects

Renders the projects page with project data.

Returns: Rendered `projects.html` template with `projects`.

### POST /api/project/<int:project_id>/start

Starts the specified project service.

| Input | Type | Required |
|---|---|---|
| `project_id` | integer path parameter | Yes |

Returns: JSON object containing `status` and `pid`.

### POST /api/project/<int:project_id>/toggle

Toggles the specified project status.

| Input | Type | Required |
|---|---|---|
| `project_id` | integer path parameter | Yes |

Returns: Rendered `types/_project_row.html` fragment containing the updated project.

### GET /health

Verifies database connectivity.

Returns: JSON `{"status": "ok"}` with status `200`, or JSON `{"status": "error", "detail": string}` with status `500`.

### Rule: route-handling

Constraints: API routes return JSON or HTML fragments as specified; page routes return rendered templates; handlers parse requests, delegate business logic, and return responses; handlers contain no SQL, file I/O, subprocess calls, or complex logic.

## Errors

### Rule: error-response

Handles HTTP 404 and 500 errors.

Returns: API paths receive JSON `{"error": "Not found"}` or `{"error": "Internal server error"}` with the corresponding status; non-API paths receive `404.html` or `500.html`; stack traces are not exposed.

### Rule: unhandled-exception

Constraints: Unhandled exceptions are logged and return `500.html` with status `500`.

## Template Contracts

### context_processor

Injects global template data.

Returns:

| Field | Type | Default |
|---|---|---|
| `app_name` | string | `"My App"` |
| `running_count` | integer | — |

### inject_nav

Injects navigation zones into all templates.

Returns:

| Field | Type | Default |
|---|---|---|
| `util_links` | list of `{label: string, url: string}` | `[]` |
| `nav_items` | list of `{label: string, url: string}` | `[]` |
| `cta_label` | string or `None` | `None` |
| `cta_url` | string | `/` |

Constraints: Navigation content comes from project UI specification; the CTA is omitted when `cta_label` is `None`.

### Rule: template-structure

Constraints: All pages extend `base.html`; partials begin with `_`; type-specific partials reside under `templates/types/`; static assets use `url_for('static', filename=...)`; Jinja auto-escaping remains enabled; templates contain no Python logic.

### Rule: htmx-fragments

Constraints: HTMX endpoints return HTML fragments; cross-component updates use the `HX-Trigger` response header; out-of-band fragments use `hx-swap-oob="true"`.

## Security

### Rule: input-validation

Constraints: Validate every form input for length, type, and allowed values; use `secure_filename()` for uploaded files.

### Rule: secure-headers

Responses include:

| Header | Value |
|---|---|
| `X-Content-Type-Options` | `nosniff` |
| `X-Frame-Options` | `DENY` |

### Rule: thread-safety

Constraints: Objects created during application construction and used by views must be thread-safe; database connections are owned per request thread.

## Testing

### Rule: flask-test-client

Constraints: Tests use Flask’s test client and fixtures for the application, client, and database; route tests verify status codes, response content types, rendered content, and HTMX behavior.

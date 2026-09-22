<!-- Compacted from Rigging/stack/flask.md sha256=270adfabc0c1105b52da20a12c8c3d096e031dec56c46a6825893b8ab12af871 on 2026-09-20 by drydock rigging compact — regenerate with: drydock rigging compact --include-file {rel_source} -->

## Foundation Contract

The published shape of this foundation. Drydock synthesizes the story that builds it and every
acceptance criterion writes against these names. Carried verbatim into `flask_compact.md`.

- package: app_server
- entry: create_app() -> Flask
- fixture: web_client
- fixture_source: app_server/testing.py

```python
# app_server/__init__.py
def create_app() -> Flask:
    ...

# app_server/testing.py
from app_server import create_app

def web_client():
    app = create_app()
    app.config["TESTING"] = True
    return app.test_client()

# conftest.py
import pytest
from app_server import testing

@pytest.fixture
def web_client():
    return testing.web_client()
```

A criterion imports `web_client` from `app_server.testing` and calls it — `client = web_client()` —
which runs the built application in-process without pytest. The pytest suite receives the same
client through the `conftest.py` fixture. Neither constructs a client of its own.

---

## Application

### create_app(config)
Creates and returns a configured Flask application.

| Input | Type | Required |
|---|---|---|
| `config` | configuration object or import path | No; defaults to `config.DevConfig` |

Returns: Flask application with database, blueprints, error handlers, startup validation, and context processors registered.

Constraints: Must load the real configuration even when overrides are supplied; extensions and shared objects must be thread-safe; `SECRET_KEY` must come from environment configuration and must not be hardcoded or defaulted in production.

### Rule: application-layout
Application code resides in the `app_server/` package; `run.py` is the entry point, `config.py` remains at the project root, and templates/static files reside under `app_server/`.

Constraints: `ops.py` contains Flask-independent business logic; `db.py` provides database initialization and `get_db()`; `run.py` must be importable without starting the server.

### Rule: environment-loading
`.env` values are loaded before `create_app()` executes.

Constraints: `SECRET_KEY` is required; production debug mode is disabled.

### APP_PORT
Controls the development server port.

Returns: Integer port value; default is `5001`.

## Routes

### GET /projects
Renders the projects page using all projects returned by business logic.

Returns: `projects.html` with a `projects` template value.

### POST /api/project/<int:project_id>/start
Starts the specified project service.

| Input | Type | Required |
|---|---|---|
| `project_id` | integer path parameter | Yes |

Returns: JSON result from the service operation.

### POST /api/project/<int:project_id>/toggle
Toggles a project's status and returns its updated row.

| Input | Type | Required |
|---|---|---|
| `project_id` | integer path parameter | Yes |

Returns: Rendered `types/_project_row.html` fragment.

### GET /health
Verifies database connectivity.

Returns:

| Condition | Response | Status |
|---|---|---:|
| Database query succeeds | `{"status": "ok"}` | 200 |
| Database query fails | `{"status": "error", "detail": "<error>"}` | 500 |

### Rule: route-responses
API routes return JSON, page routes return rendered HTML, and route handlers delegate business logic instead of containing SQL, file I/O, subprocess calls, or complex logic.

## Error Handling

### Rule: http-errors
Registers handlers for 404, 500, and unhandled exceptions.

Constraints: API paths beginning with `/api/` return JSON errors; page paths return `404.html` or `500.html`; responses must not expose stack traces.

Returns:

| Error | API response | Page response |
|---|---|---|
| 404 | `{"error": "Not found"}`, status 404 | `404.html`, status 404 |
| 500 or unhandled exception | `{"error": "Internal server error"}`, status 500 | `500.html`, status 500 |

## Templates and Navigation

### Rule: template-contract
All pages extend `base.html`; partials use `_` prefixes; type-specific partials reside under `templates/types/`; static assets use `url_for('static', filename=...)`; auto-escaping remains enabled.

### inject_globals()
Provides global template data.

Returns:

| Field | Type | Default |
|---|---|---|
| `app_name` | string | `APP_NAME` or `"My App"` |
| `running_count` | value | result of running-count operation |

### inject_nav()
Provides navigation zones to all templates.

Returns:

| Field | Type | Default |
|---|---|---|
| `util_links` | list of `{label: string, url: string}` | `[]` |
| `nav_items` | list of `{label: string, url: string}` | `[]` |
| `cta_label` | string or `None` | `None` |
| `cta_url` | string | `/` |

Constraints: `cta_label=None` hides the CTA; navigation content is supplied by project UI configuration rather than hardcoded template content.

## HTMX

### Rule: htmx-fragments
Dynamic endpoints return HTML fragments suitable for HTMX swaps.

Constraints: Cross-component updates use the `HX-Trigger` response header; out-of-band fragments use `hx-swap-oob="true"`.

## Security

### Rule: secure-input
All input is validated for length, type, and allowed values; uploaded filenames use Werkzeug `secure_filename()`.

### Rule: secure-headers
Responses include `X-Content-Type-Options: nosniff` and `X-Frame-Options: DENY`.

### Rule: production-safety
Jinja2 auto-escaping remains enabled, production debug mode is disabled, and `SECRET_KEY` is environment-provided.

## Execution and Testing

### Rule: server-entrypoint
The development server runs on `APP_PORT`, defaulting to `5001`; production WSGI invocation uses `app_server:create_app()`.

Constraints: Startup-only work is guarded against Werkzeug's debug reloader executing it twice.

### Rule: test-client
Tests use Flask's test client with application, client, and database fixtures.

Constraints: Route tests verify status codes, JSON content types, rendered content, and HTMX responses without requiring a running server.

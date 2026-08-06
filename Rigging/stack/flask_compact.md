<!-- Compacted from Rigging/stack/flask.md sha256=b8c03c04dac9186ff6e7ca1fac685236f87c7e5bdf1b9ad54e002d2b93c35c8c on 2026-08-06 by drydock rigging compact — regenerate with: drydock rigging compact --include-file {rel_source} -->

# Flask Best Practices — Contract Surface

## Application Factory

### `create_app(config=None)`

Creates and returns a configured Flask application.

| Input | Type | Required |
|---|---|---|
| `config` | configuration object or `None` | No |

Returns: Flask application instance.

Constraints: Load real configuration even when overrides are supplied; `SECRET_KEY` is required from the environment and must not be hardcoded or defaulted in production.

### `run.py`

Provides an importable application entry point and runs the application only when executed directly.

Constraints: Load `.env` before creating the application. Use `APP_PORT`, defaulting to `5001`, for the development server.

## Routes

### `GET /projects`

Renders the projects page.

Returns: `projects.html` with `projects` data.

### `POST /api/project/<int:project_id>/start`

Starts the specified project service.

| Input | Type |
|---|---|
| `project_id` | integer path parameter |

Returns: JSON object containing at least `status` and `pid`; successful status is `'started'`.

### `POST /api/project/<int:project_id>/toggle`

Toggles the specified project's status.

| Input | Type |
|---|---|
| `project_id` | integer path parameter |

Returns: Rendered `types/_project_row.html` fragment containing the updated project.

Constraints: Support HTMX requests and return HTTP `200` on success.

### `GET /api/projects`

Returns project data as JSON.

Returns: `application/json` response.

### `GET /health`

Checks database connectivity.

Returns on success: `{"status": "ok"}`, HTTP `200`.

Returns on failure: `{"status": "error", "detail": "<error detail>"}`, HTTP `500`.

## Error Responses

### Rule: error-handling

404 and 500 responses use JSON for paths beginning with `/api/` and HTML error templates for other paths.

Constraints: Unhandled exceptions are logged and must not expose stack traces to clients.

| Condition | API response | Page response |
|---|---|---|
| 404 | `{"error": "Not found"}`, HTTP `404` | `404.html`, HTTP `404` |
| 500 | `{"error": "Internal server error"}`, HTTP `500` | `500.html`, HTTP `500` |

## Template Contracts

### Rule: template-inheritance

All pages extend `base.html`; reusable partials use `_` prefixes; type-specific partials reside under `templates/types/`.

Constraints: Static assets use `url_for('static', filename=...)`; auto-escaping remains enabled; templates receive ready-to-render data without Python logic.

### Rule: navigation-context

The navigation context processor provides four template variables.

| Variable | Shape | Required |
|---|---|---|
| `util_links` | list of `{"label": str, "url": str}` | Yes |
| `nav_items` | list of `{"label": str, "url": str}` | Yes |
| `cta_label` | string or `None` | Yes |
| `cta_url` | string | Yes |

Constraints: The CTA is omitted when `cta_label` is `None`; navigation content comes from the project UI specification.

## Configuration and Security

### `SECRET_KEY`

Configures Flask sessions and flash messages.

Constraints: Read from the environment; required in production; never hardcode or default it in production.

### Rule: input-validation

All form input is validated for length, type, and allowed values. File uploads use Werkzeug `secure_filename()`.

### Rule: secure-headers

Responses include:

| Header | Value |
|---|---|
| `X-Content-Type-Options` | `nosniff` |
| `X-Frame-Options` | `DENY` |

### Rule: production-debug

Debug mode is enabled only in development; production runs with `FLASK_DEBUG=0`. Startup-only operations are guarded against duplicate execution under the Werkzeug reloader.

## Database and Concurrency

### `get_db()`

Returns a database connection for the current application context.

Returns: Thread-owned database connection.

Constraints: Connections must not be shared across request threads.

## Testing

### Rule: flask-test-client

Routes are tested through the Flask test client with fixtures for the application, client, and database.

Constraints: Tests must verify HTTP status, response content type, rendered content, and HTMX endpoint behavior.

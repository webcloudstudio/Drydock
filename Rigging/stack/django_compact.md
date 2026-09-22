<!-- Compacted from Rigging/stack/django.md sha256=f20a6883b31343897b71b55bff52887d63bbd88703129c729798bcc153d2f07c on 2026-09-20 by drydock rigging compact — regenerate with: drydock rigging compact --include-file {rel_source} -->

## Foundation Contract

The published shape of this foundation. Drydock synthesizes the story that builds it and every
acceptance criterion writes against these names. Carried verbatim into `django_compact.md`.

- package: app_server
- entry: create_app() -> WSGIHandler
- fixture: web_client
- fixture_source: app_server/testing.py

```python
# app_server/wsgi.py — the Django project package IS app_server
import os
from django.core.wsgi import get_wsgi_application
from django.core.handlers.wsgi import WSGIHandler

def create_app() -> WSGIHandler:
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "app_server.settings")
    return get_wsgi_application()

application = create_app()

# app_server/testing.py
import os
import django
from django.test import Client

def web_client() -> Client:
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "app_server.settings")
    django.setup()
    return Client()

# conftest.py
import pytest
from app_server import testing

@pytest.fixture
def web_client(db):
    return testing.web_client()
```

A criterion imports `web_client` from `app_server.testing` and calls it — `client = web_client()` —
which runs the built application in-process without pytest. The pytest suite receives the same
client through the `conftest.py` fixture. Neither constructs a client of its own.

Django's settings module is the real root of a Django project, so `app_server` is the settings
package — `app_server/settings.py`, `app_server/urls.py`, `app_server/wsgi.py` — and the
application code lives in ordinary Django apps beside it. `create_app()` exists so the entry is
the one every web server publishes: a criterion written against `app_server` and `web_client`
runs unchanged whether the Commander selected Django, FastAPI, or Flask.

`manage.py`, `DJANGO_SETTINGS_MODULE`, and `app_server.settings` are Django's own contract and
are not restated here. What is published is only what a later story must not invent.

---

## Configuration

### `DJANGO_SETTINGS_MODULE`

Selects the active Django settings module.

| Value | Behavior |
|---|---|
| `app_server.settings_dev` | Enables `DEBUG` and permits all hosts. |
| `app_server.settings_prod` | Disables `DEBUG`, requires `SECRET_KEY`, and reads comma-separated `ALLOWED_HOSTS`. |

Constraints: Production secrets must come from environment variables.

### `SECRET_KEY`

Provides Django's secret key.

Constraints: Production configuration must read `SECRET_KEY` from the environment and must not use a fallback.

### `ALLOWED_HOSTS`

Provides production allowed hosts as a comma-separated environment value.

### `INSTALLED_APPS`

Must include Django admin, auth, content types, sessions, messages, staticfiles, and `core`.

### `DATABASES.default`

Uses SQLite at `data/db.sqlite3`.

### `STATIC_URL`

Must be `/static/`.

### `TEMPLATES[0]`

Must use Django templates with `DIRS` containing `templates`, `APP_DIRS=True`, and the debug, request, auth, messages, and `core.context_processors.global_context` context processors.

## Models

### `TimestampMixin`

Provides automatically managed `created_at` and `updated_at` datetime fields.

### `Project`

Represents a project record.

| Field | Type | Constraints |
|---|---|---|
| `name` | `CharField` | Maximum 200 characters; unique. |
| `title` | `CharField` | Maximum 200 characters. |
| `description` | `TextField` | Blank allowed; default `''`. |
| `project_type` | `CharField` | Maximum 50 characters; default `'software'`. |
| `status` | `CharField` | Maximum 50 characters; default `'active'`. |
| `extra` | `JSONField` | Blank allowed; default `{}`. |
| `created_at` | `DateTimeField` | Automatically set on creation. |
| `updated_at` | `DateTimeField` | Automatically updated on save. |

Returns: String representation equal to `title`.

Constraints: Models must use Django's ORM and include creation and update timestamps.

## HTTP Routes

### `GET /projects/`

Renders the project list page using `core/project_list.html` with a `projects` context value containing all projects.

### `POST /api/project/<int:pk>/start/`

Starts the project service identified by its primary key and returns the operation result as JSON.

| Parameter | Type |
|---|---|
| `pk` | Integer path parameter |

Returns: JSON result from the project-start operation.

Constraints: Non-`POST` requests return `{"error": "Method not allowed"}` with HTTP status `405`; an unknown project returns HTTP `404`.

### `POST <configured-toggle-route>`

Toggles a project's status between `active` and `inactive`.

| Parameter | Type |
|---|---|
| `pk` | Integer path parameter |

Returns: For HTMX requests, renders `core/_project_row.html` with the updated project; otherwise redirects to `core:project-list`.

Constraints: HTMX detection requires `django-htmx` middleware. The toggle control uses `hx-post`, `hx-swap="outerHTML"`, and `hx-target="closest tr"`.

## Templates

### `base.html`

Provides the common page structure and static stylesheet loading.

Constraints: All pages extend `base.html`; application templates reside under `templates/<app_name>/`; partials begin with `_`; static assets use `{% load static %}` and `{% static %}`; auto-escaping remains enabled.

## Context

### `global_context`

Provides global template variables.

Returns:

| Key | Value |
|---|---|
| `running_count` | Count of projects whose status is `running`. |
| `app_name` | Application name string. |

Constraints: Register the processor in `TEMPLATES[0]['OPTIONS']['context_processors']`.

## Testing

### `web_client`

Provides a Django test client fixture backed by the database fixture.

Returns: `django.test.Client`.

Constraints: pytest-django tests use the published `web_client` fixture and do not construct clients directly. `DJANGO_SETTINGS_MODULE` must be `app_server.settings_dev`.

## Validation Rules

### Rule: migrations

All model changes require reviewed Django migrations.

Constraints: Run `makemigrations` after model changes, review generated files, commit migration files, never manually edit applied migrations, and use `--name` for descriptive migration names.

### Rule: production-security

Production settings must disable debugging and enable Django deployment protections.

Constraints: Set `DEBUG=False`, `SECURE_BROWSER_XSS_FILTER=True`, `SECURE_CONTENT_TYPE_NOSNIFF=True`, `SESSION_COOKIE_SECURE=True`, and `CSRF_COOKIE_SECURE=True`; run `python manage.py check --deploy`.

### Rule: admin-registration

All models must be registered in Django admin.

Constraints: `ProjectAdmin` displays `title`, `project_type`, `status`, and `created_at`; filters by `project_type` and `status`; searches `title` and `name`; and makes `created_at` and `updated_at` read-only.

### Rule: standard-scripts

Django projects provide standard scripts for service start, stop, migrations, tests, shell access, and static collection.

Constraints: Start binds `0.0.0.0:8000`; migration runs `makemigrations` then `migrate`; tests run `python -m pytest tests/ -v`; static collection runs `collectstatic --noinput`.

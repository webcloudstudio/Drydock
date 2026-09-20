<!-- Compacted from Rigging/stack/django.md sha256=75b6d326913d4b4be756bf4f39395e547102931dceedff4a3017dedaf993550d on 2026-09-20 by drydock rigging compact — regenerate with: drydock rigging compact --include-file {rel_source} -->

## Foundation Contract

The published shape of this foundation. Drydock synthesizes the story that builds it and every
acceptance criterion writes against these names. Carried verbatim into `django_compact.md`.

- package: app_server
- entry: get_wsgi_application() -> WSGIHandler
- fixture: web_client
- fixture_source: conftest.py

```python
# conftest.py
import pytest
from django.test import Client

@pytest.fixture
def web_client() -> Client:
    return Client()
```

A criterion calls `web_client`; it never constructs a client itself.

---

# Django Best Practices — Contract Surface

## Configuration

### config_key

Django settings must use a base settings module with development and production overrides selected through `DJANGO_SETTINGS_MODULE`.

| Key | Contract |
|---|---|
| `SECRET_KEY` | Reads from the environment; production requires it to be present. |
| `DEBUG` | `False` by default and in production; `True` in development. |
| `ALLOWED_HOSTS` | Empty by default, `['*']` in development, and environment-derived in production. |
| `INSTALLED_APPS` | Includes Django admin, auth, contenttypes, sessions, messages, staticfiles, and `core`. |
| `DATABASES['default']` | Uses SQLite at `data/db.sqlite3`. |
| `STATIC_URL` | `/static/`. |
| `STATICFILES_DIRS` | Includes the project `static/` directory. |
| `TEMPLATES[0].DIRS` | Includes the project `templates/` directory. |
| `TEMPLATES[0].APP_DIRS` | `True`. |
| `TEMPLATES[0].OPTIONS.context_processors` | Includes Django debug, request, auth, messages, and `core.context_processors.global_context`. |

Constraints: Secrets are loaded from environment variables. `.env` may define `DJANGO_SETTINGS_MODULE` and `SECRET_KEY`.

### Rule: project-layout

The project provides `manage.py`, a `config` settings package, a `core` app, `templates/`, `static/`, `tests/`, `data/`, `requirements.txt`, and environment configuration.

## Models

### TimestampMixin

Provides `created_at` and `updated_at` timestamp fields.

| Field | Type | Behavior |
|---|---|---|
| `created_at` | `DateTimeField` | Automatically set on creation. |
| `updated_at` | `DateTimeField` | Automatically updated on save. |

Constraints: The mixin is abstract and is applied to models requiring timestamps.

### Project

Represents a project record.

| Field | Type | Constraints / Default |
|---|---|---|
| `name` | `CharField` | Maximum 200 characters; unique. |
| `title` | `CharField` | Maximum 200 characters. |
| `description` | `TextField` | Blank allowed; default `''`. |
| `project_type` | `CharField` | Maximum 50 characters; default `'software'`. |
| `status` | `CharField` | Maximum 50 characters; default `'active'`. |
| `extra` | `JSONField` | Blank allowed; default empty object. |
| `created_at` | `DateTimeField` | Automatically set on creation. |
| `updated_at` | `DateTimeField` | Automatically updated on save. |

Constraints: Default ordering is `project_type`, then `title`. String conversion returns `title`.

## HTTP Routes

### GET /projects/

Renders the project list page with all projects in the template context under `projects`.

### POST /api/project/<int:pk>/start/

Starts the selected project service and returns the operation result as JSON.

| Parameter | Type | Required |
|---|---|---|
| `pk` | Integer path parameter | Yes |

Returns: JSON containing the result of `start_service(project)`.

Constraints: Non-POST requests return JSON `{"error": "Method not allowed"}` with status `405`. A nonexistent project returns Django’s not-found response.

### POST /toggle/<int:pk>/

Toggles a project’s status between `active` and `inactive`.

| Parameter | Type | Required |
|---|---|---|
| `pk` | Integer path parameter | Yes |

Returns: HTMX requests render `core/_project_row.html` with `project`; other requests redirect to `core:project-list`.

Constraints: The route is referenced by the HTMX URL name `core:toggle`. The project is persisted after toggling.

### Rule: root-url-configuration

The root URL configuration exposes `/admin/` through Django admin and includes the `core` routes at `/`.

Constraints: The `core` URL configuration uses `app_name = 'core'`; route names include `project-list` and `api-start`.

## Templates

### Rule: template-structure

All pages extend `base.html`; app templates reside under `templates/<app_name>/`; partials use a leading underscore.

Constraints: Static assets use `{% load static %}` and `{% static %}`. Auto-escaping remains enabled.

### Rule: base-template

`base.html` provides `title`, `head`, `content`, and `scripts` blocks, includes `_nav.html`, and loads `static/css/style.css`.

## Migrations

### Rule: migration-management

Every model change requires `makemigrations`; generated migrations are reviewed and committed.

Constraints: Applied migrations are never manually edited. Migration names use `--name` when clarity is needed.

## HTMX

### Rule: htmx-integration

HTMX support requires `django-htmx` in installed applications and middleware.

Constraints: HTMX requests are detected through `request.htmx`. Toggle responses render a partial with `hx-swap="outerHTML"` and target the closest table row.

## Context

### global_context

Provides global template variables.

Returns:

| Key | Value |
|---|---|
| `running_count` | Count of projects whose status is `running`. |
| `app_name` | `'My App'`. |

Constraints: The processor is registered in the template context processors.

## Testing

### Rule: pytest-django

Tests use pytest-django and the Django test client with `DJANGO_SETTINGS_MODULE=config.settings_dev`.

### client

Provides a Django test client fixture requiring the `db` fixture.

Constraints: Database-dependent tests use `pytest.mark.django_db`.

## Security

### Rule: production-security

Production settings must disable debug mode and enable Django security protections.

| Setting | Required value |
|---|---|
| `DEBUG` | `False` |
| `SECURE_BROWSER_XSS_FILTER` | `True` |
| `SECURE_CONTENT_TYPE_NOSNIFF` | `True` |
| `SESSION_COOKIE_SECURE` | `True` |
| `CSRF_COOKIE_SECURE` | `True` |

Constraints: `python manage.py check --deploy` must be used to validate deployment configuration.

## Admin

### ProjectAdmin

Registers `Project` with Django admin.

| Option | Value |
|---|---|
| `list_display` | `title`, `project_type`, `status`, `created_at` |
| `list_filter` | `project_type`, `status` |
| `search_fields` | `title`, `name` |
| `readonly_fields` | `created_at`, `updated_at` |

## Operations

### bin/start.sh

Starts Django’s development server on `0.0.0.0:8000`.

### bin/stop.sh

Stops processes matching `manage.py runserver`; reports when no process is found.

### bin/migrate.sh

Runs `makemigrations` followed by `migrate`.

### bin/test.sh

Runs `python -m pytest tests/ -v`.

### bin/shell.sh

Opens the Django management shell.

### bin/collectstatic.sh

Runs `python manage.py collectstatic --noinput`.

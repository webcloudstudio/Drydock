<!-- Compacted from Rigging/stack/django.md sha256=02aa2e47d7e6f123737c3397ab2945697cbc79084ddbd6058f665d20fff1c3cc on 2026-10-24 by drydock rigging compact — regenerate with: drydock rigging compact --include-file {rel_source} -->

## Foundation Contract

- package: app_server
- entry: create_app() -> WSGIHandler
- fixture: web_client
- fixture_source: app_server/testing.py

```python
# app_server/wsgi.py
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
```

Programmatic acceptance imports the entry callable from its published module:

```python
from app_server.wsgi import create_app
```

`app_server` is the Django project package containing settings, URLs, and WSGI. Application code
lives in Django apps beside it. `app_server.testing.web_client()` is a plain callable used by
programmatic acceptance; the pytest fixture delegates to it and supplies isolated database state.

# Django Foundation — Contract Surface

### Rule: Blueprint-driven application boundary
Use the Blueprint’s settings, routes, models, and access rules.

Constraints: Keep views focused on HTTP concerns and business behavior in importable services.

### Rule: Production security configuration
Configure secrets through environment-backed settings.

Constraints: Disable `DEBUG` in production, set allowed hosts, and retain Django CSRF and template protections.

### Rule: Database schema changes
Use Django migrations for schema changes.

Constraints: Review generated migrations before committing.

### Rule: Test isolation
Use Django’s test client with isolated database state for tests.

### Rule: Optional Django components
Add admin, templates, HTMX, and static collection only when the Target requires them.

### Rule: Python foundation ownership
The Python foundation defines launchers, dependencies, and the test command.

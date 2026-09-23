# Django Foundation

**Version:** 20260922 V3
**Tier:** platform
**Category:** Web Server
**Foundation:** web-server
**Description:** Django application boundary and test client contract

Prerequisites: `stack/common.md`, `stack/python.md`

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

## Rules

- Use the Blueprint's settings, routes, models, and access rules. Keep views focused on HTTP
  concerns and business behavior in importable services.
- Keep secrets in environment-backed settings. Disable `DEBUG` in production, set allowed hosts,
  and retain Django's CSRF and template protections.
- Use Django migrations for schema changes; review generated migrations before committing.
- Use Django's test client and isolated database state for tests. Add admin, templates, HTMX,
  and static collection only when the Target calls for them.
- The Python foundation owns launchers, dependencies, and the test command.

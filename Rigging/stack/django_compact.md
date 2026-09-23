<!-- Compacted from Rigging/stack/django.md sha256=86e4abefdbde9b0cce93791ec1bc6ee80217cbc1b39ab592f05bc56da99d8f62 on 2026-09-22 by Rigging maintenance — regenerate with: drydock rigging compact --include-file Rigging/stack/django.md -->

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

## Consumer Rules

- Use Blueprint settings, routes, models, and access rules; keep views thin and services importable.
- Keep secrets in environment-backed settings; disable production debug and retain CSRF protection.
- Use reviewed Django migrations and isolated database state in tests.
- Add admin, templates, HTMX, and static collection only when specified.

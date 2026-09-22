# Django Best Practices

**Version:** 20260920 V2  
**Tier:** platform
**Category:** Web Server
**Foundation:** web-server
**Description:** Django web framework patterns: models, views, URLs, and admin

Technology reference for Django web applications. This file does not change between projects.

Prerequisites: `stack/common.md`, `stack/python.md`

---

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

## 1. Project Structure

**Rule**: Use Django's standard layout but keep it flat for small projects. One app for simple services.

```
project-name/
├── manage.py                # Django management CLI
├── app_server/              # Settings package — the published foundation
│   ├── __init__.py
│   ├── settings.py          # Base settings
│   ├── settings_dev.py      # Development overrides
│   ├── settings_prod.py     # Production overrides
│   ├── urls.py              # Root URL configuration
│   └── wsgi.py              # create_app() -> WSGIHandler
├── core/                    # Main app
│   ├── __init__.py
│   ├── models.py
│   ├── views.py
│   ├── urls.py
│   ├── admin.py
│   ├── forms.py
│   └── templatetags/
├── templates/
│   ├── base.html
│   └── core/
├── static/
│   ├── css/
│   └── js/
├── conftest.py              # published fixtures, including web_client
├── tests/
│   └── test_views.py
├── bin/                     # (from common.md)
├── data/                    # (from common.md)
├── requirements.txt
├── .env
└── CLAUDE.md
```

**Why**: One app avoids unnecessary complexity. The `app_server/` package is the settings package the foundation contract publishes.

---

## 2. Settings Management

**Rule**: Use a settings package with base + environment overrides. Load secrets from environment variables.

```python
# app_server/settings.py (base)
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent
SECRET_KEY = os.environ.get('SECRET_KEY', 'dev-key-change-me')
DEBUG = False
ALLOWED_HOSTS = []

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'core',
]

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': BASE_DIR / 'data' / 'db.sqlite3',
    }
}

STATIC_URL = '/static/'
STATICFILES_DIRS = [BASE_DIR / 'static']
TEMPLATES = [{
    'BACKEND': 'django.template.backends.django.DjangoTemplates',
    'DIRS': [BASE_DIR / 'templates'],
    'APP_DIRS': True,
    'OPTIONS': {
        'context_processors': [
            'django.template.context_processors.debug',
            'django.template.context_processors.request',
            'django.contrib.auth.context_processors.auth',
            'django.contrib.messages.context_processors.messages',
            'core.context_processors.global_context',
        ],
    },
}]
```

```python
# app_server/settings_dev.py
from .settings import *
DEBUG = True
ALLOWED_HOSTS = ['*']
```

```python
# app_server/settings_prod.py
from .settings import *
DEBUG = False
SECRET_KEY = os.environ['SECRET_KEY']
ALLOWED_HOSTS = os.environ.get('ALLOWED_HOSTS', '').split(',')
```

```bash
# .env
DJANGO_SETTINGS_MODULE=app_server.settings_dev
SECRET_KEY=your-secret-here
```

**Why**: `DJANGO_SETTINGS_MODULE` is Django's standard for environment switching.

---

## 3. Models

**Rule**: Use Django's ORM. Add `created_at`/`updated_at` to all models. Use JSONField for extensible data.

```python
# core/models.py
from django.db import models

class TimestampMixin(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True

class Project(TimestampMixin):
    name = models.CharField(max_length=200, unique=True)
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True, default='')
    project_type = models.CharField(max_length=50, default='software')
    status = models.CharField(max_length=50, default='active')
    extra = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ['project_type', 'title']

    def __str__(self):
        return self.title
```

**Why**: ORM handles migrations and validation. JSONField stores extensible data without schema changes. Abstract mixin avoids repeating timestamps.

---

## 4. Views and URL Organization

**Rule**: Keep views thin. Function-based views for simple endpoints, class-based for CRUD. Business logic in separate modules.

```python
# core/views.py
from django.shortcuts import render, get_object_or_404
from django.http import JsonResponse
from .models import Project
from . import ops

def project_list(request):
    projects = Project.objects.all()
    return render(request, 'core/project_list.html', {'projects': projects})

def api_start_project(request, pk):
    if request.method != 'POST':
        return JsonResponse({'error': 'Method not allowed'}, status=405)
    project = get_object_or_404(Project, pk=pk)
    result = ops.start_service(project)
    return JsonResponse(result)
```

```python
# core/urls.py
from django.urls import path
from . import views

app_name = 'core'
urlpatterns = [
    path('projects/', views.project_list, name='project-list'),
    path('api/project/<int:pk>/start/', views.api_start_project, name='api-start'),
]
```

```python
# app_server/urls.py
from django.contrib import admin
from django.urls import path, include

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', include('core.urls')),
]
```

**Why**: URL namespacing (`app_name`) prevents collisions. Thin views are testable.

---

## 5. Migrations

**Rule**: Use Django's migration system. Always review generated migrations before committing.

```bash
python manage.py makemigrations
python manage.py migrate
```

Rules:
- Run `makemigrations` after any model change
- Review generated migration files before committing
- Commit migration files to git (they are the schema)
- Never manually edit applied migrations
- Use `--name` for clarity: `makemigrations --name add_priority_field`

**Why**: Django's migration system is the source of truth for schema.

---

## 6. Templates (Django Template Language)

**Rule**: Use template inheritance with `base.html`. Prefix partials with `_`. Keep logic out.

```html
<!-- templates/base.html -->
<!DOCTYPE html>
<html>
<head>
    <title>{% block title %}App{% endblock %}</title>
    {% load static %}
    <link rel="stylesheet" href="{% static 'css/style.css' %}">
    {% block head %}{% endblock %}
</head>
<body>
    {% include '_nav.html' %}
    <main class="container">
        {% block content %}{% endblock %}
    </main>
    {% block scripts %}{% endblock %}
</body>
</html>
```

Rules:
- All pages extend `base.html`
- App-specific templates in `templates/<app_name>/`
- Partials prefixed with `_`
- Use `{% load static %}` and `{% static %}` for static files
- Auto-escaping enabled by default — don't disable

---

## 7. HTMX Integration

**Rule**: Use HTMX with `django-htmx` middleware for request detection.

```python
# pip install django-htmx — add to INSTALLED_APPS and MIDDLEWARE

def toggle_status(request, pk):
    project = get_object_or_404(Project, pk=pk)
    project.status = 'inactive' if project.status == 'active' else 'active'
    project.save()

    if request.htmx:
        return render(request, 'core/_project_row.html', {'project': project})
    return redirect('core:project-list')
```

```html
<button hx-post="{% url 'core:toggle' project.pk %}"
        hx-swap="outerHTML"
        hx-target="closest tr">
    Toggle
</button>
```

**Why**: `django-htmx` adds clean request detection via `request.htmx`.

---

## 8. Context Processors

**Rule**: Use context processors for global template variables.

```python
# core/context_processors.py
from .models import Project

def global_context(request):
    return {
        'running_count': Project.objects.filter(status='running').count(),
        'app_name': 'My App',
    }
```

Register in `settings.py` under `TEMPLATES[0]['OPTIONS']['context_processors']`.

---

## 9. Testing

**Rule**: Use pytest-django. A criterion calls the published `web_client` fixture; it never
constructs a client itself.

```python
# conftest.py
import pytest
from django.test import Client

@pytest.fixture
def web_client(db) -> Client:
    return Client()
```

```python
# tests/test_views.py
import pytest
from core.models import Project

@pytest.mark.django_db
def test_project_list(web_client):
    Project.objects.create(name='test', title='Test')
    response = web_client.get('/projects/')
    assert response.status_code == 200
    assert b'Test' in response.content
```

```ini
# pytest.ini
[tool:pytest]
DJANGO_SETTINGS_MODULE = app_server.settings_dev
```

**Why**: pytest-django handles database setup/teardown per test.

---

## 10. Security

**Rule**: Use Django's built-in protections. Don't disable them.

Production checklist:
```python
# app_server/settings_prod.py
DEBUG = False
SECURE_BROWSER_XSS_FILTER = True
SECURE_CONTENT_TYPE_NOSNIFF = True
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
```

```bash
python manage.py check --deploy
```

**Why**: `check --deploy` catches common misconfigurations.

---

## 11. Admin

**Rule**: Register models in admin for quick data inspection.

```python
# core/admin.py
from django.contrib import admin
from .models import Project

@admin.register(Project)
class ProjectAdmin(admin.ModelAdmin):
    list_display = ['title', 'project_type', 'status', 'created_at']
    list_filter = ['project_type', 'status']
    search_fields = ['title', 'name']
    readonly_fields = ['created_at', 'updated_at']
```

---

## Standard bin/ Scripts for Django

```bash
# bin/start.sh
#!/bin/bash
# CommandCenter Operation
# Name: Service Start
# Type: daemon
# Port: 8000

set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
source venv/bin/activate
python manage.py runserver 0.0.0.0:8000 2>&1
```

```bash
# bin/stop.sh
#!/bin/bash
# CommandCenter Operation
# Name: Service Stop
# Type: batch

pkill -f "manage.py runserver" || echo "No Django process found"
```

```bash
# bin/migrate.sh
#!/bin/bash
# CommandCenter Operation
# Name: Run Migrations
# Type: batch

set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
source venv/bin/activate
echo "=== makemigrations ==="
python manage.py makemigrations 2>&1
echo "=== migrate ==="
python manage.py migrate 2>&1
```

```bash
# bin/test.sh
#!/bin/bash
# CommandCenter Operation
# Name: Run Tests
# Type: batch

set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
source venv/bin/activate
python -m pytest tests/ -v 2>&1
```

```bash
# bin/shell.sh
#!/bin/bash
# CommandCenter Operation
# Name: Django Shell
# Type: daemon

cd "$(dirname "${BASH_SOURCE[0]}")/.."
source venv/bin/activate
python manage.py shell
```

```bash
# bin/collectstatic.sh
#!/bin/bash
# CommandCenter Operation
# Name: Collect Static
# Type: batch

set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
source venv/bin/activate
python manage.py collectstatic --noinput 2>&1
```

---

## Summary Checklist

- [ ] Settings package with base + dev/prod overrides
- [ ] Models with TimestampMixin, JSONField for extensible data
- [ ] Thin views, business logic in separate modules
- [ ] URL namespacing with `app_name`
- [ ] Django migration system for all schema changes
- [ ] Template inheritance from `base.html`, partials prefixed with `_`
- [ ] HTMX with `django-htmx` middleware
- [ ] Context processors for global template data
- [ ] pytest-django with test client fixtures
- [ ] Security verified with `manage.py check --deploy`
- [ ] Admin registered for all models
- [ ] Standard `bin/` scripts: start, stop, migrate, test, shell, collectstatic

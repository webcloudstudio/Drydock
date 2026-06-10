<!-- Compacted from RulesEngine/stack/flask.md on 2026-04-30 by prompts/compact_file.md — regenerate via bin/rulesengine_compact.sh -->

# Flask — Compact

## Directory Layout

```
project/
  run.py                    # Entry point — imports and runs create_app()
  config.py                 # Config classes (Dev, Test, Prod)
  pytest.ini
  requirements.txt
  app/
    __init__.py              # create_app() factory
    routes.py                # Blueprint route handlers
    ops.py                   # Business logic (no Flask imports needed)
    errors.py                # Error handlers
    db.py                    # Database init and get_db()
    startup.py               # Startup validation
    templates/
      base.html
      _nav.html
      types/
    static/
      css/
      js/
  tests/
    conftest.py
    test_smoke.py
    test_routes.py
    test_db.py
  bin/
    common.sh
    start.sh
    stop.sh
    test.sh
```

- `run.py` is the only Python file executed directly
- `ops.py` holds business logic — no Flask imports, pure Python
- `db.py` holds database initialization and `get_db()` helper
- Additional modules go in `app/` — never in root

## Application Factory

```python
# run.py
import os
from dotenv import load_dotenv
load_dotenv()

from app import create_app

application = create_app()

if __name__ == '__main__':
    port = int(os.environ.get('APP_PORT', 5001))
    application.run(port=port, debug=True)
```

```python
# app/__init__.py
from flask import Flask

def create_app(config=None):
    app = Flask(__name__)
    app.config.from_object(config or 'config.DevConfig')

    from app.db import init_db
    with app.app_context():
        init_db()

    from app.routes import bp
    app.register_blueprint(bp)

    from app.errors import register_error_handlers
    register_error_handlers(app)

    from app.startup import validate_startup
    validate_startup(app)

    return app
```

## Blueprints and Routes

Route handlers do: parse request, call business logic, return response. Route handlers don't: contain SQL, file I/O, subprocess calls, or complex logic.

```python
# app/routes.py
from flask import Blueprint, render_template, request, jsonify
from app import ops

bp = Blueprint('main', __name__)

@bp.route('/projects')
def projects_list():
    projects = ops.get_all_projects()
    return render_template('projects.html', projects=projects)

@bp.route('/api/project/<int:project_id>/start', methods=['POST'])
def start_project(project_id):
    result = ops.start_service(project_id)
    return jsonify(result)
```

```python
# app/ops.py — business logic, no Flask imports needed
from app.db import get_db

def get_all_projects():
    db = get_db()
    return db.execute('SELECT * FROM projects ORDER BY title').fetchall()
```

## Error Handling

Register handlers for 404/500. Return JSON for `/api/` routes, HTML for page routes. Never expose stack traces.

```python
# app/errors.py
from flask import render_template, jsonify, request

def register_error_handlers(app):
    @app.errorhandler(404)
    def not_found(e):
        if request.path.startswith('/api/'):
            return jsonify({'error': 'Not found'}), 404
        return render_template('404.html'), 404

    @app.errorhandler(500)
    def server_error(e):
        app.logger.error('Internal error: %s', e, exc_info=True)
        if request.path.startswith('/api/'):
            return jsonify({'error': 'Internal server error'}), 500
        return render_template('500.html'), 500

    @app.errorhandler(Exception)
    def unhandled_exception(e):
        app.logger.error('Unhandled exception: %s', e, exc_info=True)
        return render_template('500.html'), 500
```

## Templates (Jinja2)

- All pages extend `base.html`; partials prefixed with `_`
- Type-specific partials in `templates/types/`
- No Python logic in templates — pass ready-to-render data from routes
- Use `url_for('static', filename=...)` for all static file references
- Auto-escaping is enabled by default — don't disable it

```html
<!-- app/templates/base.html -->
<!DOCTYPE html>
<html>
<head>
    <title>{% block title %}App{% endblock %}</title>
    <link rel="stylesheet" href="{{ url_for('static', filename='css/style.css') }}">
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

## Context Processors

```python
@app.context_processor
def inject_globals():
    return {
        'app_name': app.config.get('APP_NAME', 'My App'),
        'running_count': ops.get_running_count(),
    }
```

## HTMX Integration

Return HTML fragments from API endpoints. Use `HX-Trigger` headers for cross-component updates.

```python
@bp.route('/api/project/<int:project_id>/toggle', methods=['POST'])
def toggle_status(project_id):
    new_status = ops.toggle_status(project_id)
    project = ops.get_project(project_id)
    return render_template('types/_project_row.html', project=project)
```

```html
<button hx-post="/api/project/{{ p.id }}/toggle"
        hx-swap="outerHTML"
        hx-target="closest tr">Toggle</button>
```

OOB swap pattern:

```python
html = render_template('types/_project_row.html', project=project)
html += render_template('_nav_badge.html', count=running_count)
response = make_response(html)
response.headers['HX-Trigger'] = 'projectUpdated'
return response
```

```html
<span id="running-badge" hx-swap-oob="true">{{ count }}</span>
```

## Testing

```python
# tests/conftest.py
import pytest
from app import create_app
from config import TestConfig

@pytest.fixture
def app():
    app = create_app(TestConfig)
    yield app

@pytest.fixture
def client(app):
    return app.test_client()

@pytest.fixture
def db(app):
    from app.db import get_db, init_db
    with app.app_context():
        init_db()
        yield get_db()
```

```python
# tests/test_routes.py
def test_projects_page(client):
    response = client.get('/projects')
    assert response.status_code == 200
    assert b'Projects' in response.data

def test_htmx_endpoint(client):
    response = client.post('/api/project/1/toggle',
                          headers={'HX-Request': 'true'})
    assert response.status_code == 200
```

## Security

```python
@app.after_request
def set_headers(response):
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'DENY'
    return response
```

- Jinja2 auto-escaping enabled (default — don't disable)
- `SECRET_KEY` set from environment variable in production
- `secure_filename()` from werkzeug for file uploads
- Input validation on all form data (length, type, allowed values)
- Debug mode disabled in production (`FLASK_DEBUG=0`)

## Health Check

```python
@bp.route('/health')
def health():
    try:
        db = get_db()
        db.execute('SELECT 1')
        return jsonify({'status': 'ok'}), 200
    except Exception as e:
        return jsonify({'status': 'error', 'detail': str(e)}), 500
```

## Debug Mode

```bash
# Development
FLASK_DEBUG=1 flask run --port 5001

# Production
gunicorn "app:create_app()"
```

- Auto-reloader restarts server on Python file changes
- `WERKZEUG_RUN_MAIN` check required to avoid running startup code twice

```python
if os.environ.get('WERKZEUG_RUN_MAIN') == 'true' or not app.debug:
    run_scanner()
```

## Standard bin/ Scripts

```bash
# bin/start.sh
#!/bin/bash
# CommandCenter Operation
# Name: Service Start
# Type: daemon
# Port: 5001

set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
source venv/bin/activate
FLASK_DEBUG=1 flask run --port 5001 2>&1
```

```bash
# bin/stop.sh
#!/bin/bash
# CommandCenter Operation
# Name: Service Stop
# Type: batch

pkill -f "flask run --port 5001" || echo "No Flask process found"
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

## Two-Tier Navigation

| Zone | Tier | Position | Variable |
|------|------|----------|----------|
| Utility links | 1 — top strip, desktop only | Right-justified | `util_links` list |
| Logo | 2 — primary nav | Far left | `app_name` (styled text) |
| Nav links | 2 — primary nav | Center-left, hamburger on mobile | `nav_items` list |
| CTA button | 2 — primary nav | Far right (optional) | `cta_label`, `cta_url` |

```html
<!-- app/templates/_nav.html -->
{% if util_links %}
<div class="navbar-util py-1 d-none d-lg-block">
  <div class="container-fluid">
    <div class="d-flex justify-content-end gap-4">
      {% for link in util_links %}
      <a href="{{ link.url }}">{{ link.label }}</a>
      {% endfor %}
    </div>
  </div>
</div>
{% endif %}

<nav class="navbar navbar-expand-lg navbar-schwab">
  <div class="container-fluid">
    <a class="navbar-brand sch-logo" href="/">{{ app_name }}</a>
    <button class="navbar-toggler border-0" type="button"
            data-bs-toggle="collapse" data-bs-target="#primaryNav"
            aria-label="Toggle navigation">
      <span class="navbar-toggler-icon" style="filter: invert(1)"></span>
    </button>
    <div class="collapse navbar-collapse" id="primaryNav">
      <ul class="navbar-nav me-auto mb-2 mb-lg-0">
        {% for item in nav_items %}
        <li class="nav-item">
          <a class="nav-link {% if request.path == item.url %}active{% endif %}"
             href="{{ item.url }}">{{ item.label }}</a>
        </li>
        {% endfor %}
      </ul>
      {% if cta_label %}
      <a href="{{ cta_url }}" class="btn btn-cta ms-3">{{ cta_label }}</a>
      {% endif %}
    </div>
  </div>
</nav>
```

```python
# Context processor — populate values from project's UI-GENERAL.md
@app.context_processor
def inject_nav():
    return {
        'util_links': [],   # [{'label': str, 'url': str}, ...]
        'nav_items':  [],   # [{'label': str, 'url': str}, ...]
        'cta_label':  None, # str or None to hide button
        'cta_url':    '/',
    }
```

```html
<!-- base.html head + body -->
<head>
  ...
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link href="https://fonts.googleapis.com/css2?family=Raleway:wght@300;400;700&display=swap" rel="stylesheet">
</head>
<body>
  {% include '_nav.html' %}
  <main class="container-fluid mt-4">
    {% block content %}{% endblock %}
  </main>
</body>
```

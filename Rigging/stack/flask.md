# Flask Foundation

**Version:** 20260922 V3
**Tier:** platform
**Category:** Web Server
**Foundation:** web-server
**Description:** Flask application boundary and test client contract

Prerequisites: `stack/common.md`, `languages/python/python.md`

## Foundation Contract

- package: app_server
- entry: create_app() -> Flask
- fixture: web_client
- fixture_source: app_server/testing.py

```python
# app_server/__init__.py
def create_app() -> Flask: ...

# app_server/testing.py
from app_server import create_app
def web_client():
    app = create_app()
    app.config["TESTING"] = True
    return app.test_client()
```

`app_server.testing.web_client()` is a plain callable used directly by programmatic acceptance.
The pytest `web_client` fixture delegates to it. The application factory registers the selected
Blueprint routes, extensions, and error handlers; it does not invent routes or settings.

## Rules

- Group related routes in Flask Blueprints. Keep handlers focused on HTTP input and output; put
  business behavior in importable services without a Flask dependency.
- Load configuration through the Python foundation's typed boundary before use. Use the Target's
  names and defaults. Keep `SECRET_KEY` out of source control and disable debug mode in production.
- Use the Blueprint's routes, schemas, templates, and error contracts. Return sanitized errors;
  never expose tracebacks to clients. Preserve Jinja autoescaping.
- Keep request-bound resources request-scoped. Do not share a SQLite connection or other
  thread-bound object created in `create_app()` across request threads.
- Keep startup side effects out of imports and account for the development reloader's extra
  process. The Python foundation owns launchers, dependencies, and the test command.

<!-- Compacted from Rigging/stack/flask.md sha256=24a304879e7a0d907b0f9b9cb8c370fde1d7a30d88796cae1a9487156038854a on 2026-09-22 by Rigging maintenance — regenerate with: drydock rigging compact --include-file Rigging/stack/flask.md -->

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

## Consumer Rules

- Use Blueprint routes, schemas, settings, templates, and error contracts; do not invent defaults.
- Keep handlers thin, business services framework-independent, and errors sanitized.
- Keep `SECRET_KEY` out of source control, production debug off, and Jinja autoescaping on.
- Keep request-bound resources request-scoped; never share a SQLite connection across threads.
- Keep startup side effects out of imports and account for the development reloader.

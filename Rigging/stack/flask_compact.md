<!-- Compacted from Rigging/stack/flask.md sha256=e6aea2b4a7bf27d265dd2cfeb7d15af0b26cba083053ced31109d6776f481a63 on 2026-10-24 by drydock rigging compact — regenerate with: drydock rigging compact --include-file {rel_source} -->

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

# Flask Foundation — Contract Surface

### Rule: route-organization
Routes are grouped in Flask Blueprints, with handlers limited to HTTP input/output and business behavior in importable services without Flask dependencies.

Constraints: Use the Blueprint’s routes, schemas, templates, and error contracts.

### config_key
Configuration is loaded through the Python foundation’s typed boundary before use.

Constraints: Use the Target’s names and defaults; keep `SECRET_KEY` out of source control; disable debug mode in production.

### Rule: error-safety
HTTP errors are sanitized for clients and never expose tracebacks.

Constraints: Preserve Jinja autoescaping.

### Rule: request-scoping
Request-bound resources are scoped to individual requests.

Constraints: Do not share a SQLite connection or other thread-bound object created in `create_app()` across request threads.

### Rule: startup-safety
Application imports and startup account for development reloader process behavior.

Constraints: Keep startup side effects out of imports; launchers, dependencies, and the test command follow the Python foundation.

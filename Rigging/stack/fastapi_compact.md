<!-- Compacted from /mnt/c/Users/barlo/projects/drydock/Rigging/stack/fastapi.md sha256=c2123204fd14b966471f62e6af7c0da9e67474cb2797f589f17bcd17276dcc8f on 2026-10-24 by drydock rigging compact — regenerate with: drydock rigging compact --include-file {rel_source} -->

## Foundation Contract

- package: app_server
- entry: create_app() -> FastAPI
- fixture: web_client
- fixture_source: app_server/testing.py

```python
# app_server/main.py
def create_app() -> FastAPI: ...
app = create_app()

# app_server/testing.py
from app_server.main import create_app
def web_client() -> TestClient: ...
```

`app_server.main` exposes `create_app()` and a module-level `app` for
`uvicorn app_server.main:app`. `app_server.testing.web_client()` is a plain callable that
returns `fastapi.testclient.TestClient(create_app())`. Programmatic acceptance imports and calls
it directly. The pytest `web_client` fixture delegates to the same callable.

# FastAPI Foundation — Contract Surface

### Rule: route-boundary

Route handlers reside in `app_server` routers, parse HTTP input, call application services, and return responses.

Constraints: Services own business behavior and have no FastAPI dependency.

### Rule: shared-dependencies

Shared resources are provided through replaceable dependencies.

Constraints: Tests replace dependencies through `app.dependency_overrides`; acceptance code does not create a second application or test client.

### Rule: blueprint-http-contract

HTTP boundaries validate request and response shapes according to the Blueprint.

Constraints: Use the Blueprint’s routes, schemas, configuration names, defaults, and error contracts.

### Rule: server-rendered-pages

Server-rendered pages include `request` in Jinja template context and serve static assets through the application.

Constraints: Errors are sanitized and use the format required by the Blueprint.

### Rule: application-lifecycle

Startup and shutdown work runs in lifespan handlers.

Constraints: Uvicorn reload is used only in development.

### fastapi

The application runtime declares FastAPI dependencies as needed.

Constraints: Declare `fastapi`, `uvicorn`, and `httpx` as needed by runtime and tests; declare `jinja2` when serving templates. Use the Python foundation’s environment and test command.

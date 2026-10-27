<!-- Compacted from Rigging/stack/fastapi.md sha256=e1242918033cb040173e66be7076e2ffefe6f27c45eff9ae14958ecea2c0e498 on 2026-10-26 by drydock rigging compact — regenerate with: drydock rigging compact --include-file {rel_source} -->

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

## FastAPI application boundary

### Rule: route handling
Route handlers parse HTTP input, call application services, and return responses.

Constraints: Keep routes in `app_server` routers; services own business behavior and have no FastAPI dependency.

### Rule: dependency replacement
Shared resources are provided through dependencies replaceable with `app.dependency_overrides`.

Constraints: Acceptance code uses the existing application and test client; it does not create a second application or test client.

### Rule: HTTP validation
Request and response shapes are validated at the HTTP boundary.

Constraints: Use the Blueprint’s routes, schemas, configuration names, defaults, and error contracts; sample routes are not part of this foundation.

### Rule: server-rendered pages
Server-rendered pages include `request` in Jinja template context and serve static assets through the application.

Constraints: Return sanitized errors in the format required by the Blueprint.

### Rule: application lifecycle
Startup and shutdown work runs in lifespan handlers.

Constraints: Uvicorn reload is used only in development.

### fastapi
FastAPI is required for the application boundary.

### uvicorn
Uvicorn is required as needed for runtime server execution.

### jinja2
Jinja2 is required when the application serves templates.

### TestClient transport
The compatible TestClient transport dependency is required for tests.

Constraints: Use `fastapi.testclient.TestClient` as the client API. Declare `fastapi` and `httpx2` in every TestClient acceptance criterion with `Requires: python-package=<name>; scope=test` when using Starlette 1.2 or newer. Use `httpx` with older selected Starlette versions. Resolve and lock the compatible FastAPI, Starlette, and transport set together; do not override FastAPI’s Starlette constraints or suppress deprecation warnings. Verify client construction and a request with deprecations treated as errors before accepting the lockfile.

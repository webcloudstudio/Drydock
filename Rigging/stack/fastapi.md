# FastAPI Foundation

**Type:** web-server
**Version:** 20261025 V3
**Tier:** platform
**Category:** Web Server
**Foundation:** web-server
**Description:** FastAPI application boundary and test client contract

Prerequisites: `stack/common.md`, `languages/python/python.md`

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

## Rules

- Keep routes in `app_server` routers. Route handlers parse HTTP input, call application services,
  and return responses; services own business behavior and have no FastAPI dependency.
- Provide shared resources through dependencies that tests can replace with
  `app.dependency_overrides`. Do not create a second application or test client in acceptance code.
- Validate request and response shapes at the HTTP boundary. Use the Blueprint's routes, schemas,
  configuration names, defaults, and error contracts; sample routes are not part of this foundation.
- For server-rendered pages, include `request` in Jinja template context and serve static assets
  through the application. Return sanitized errors in the format required by the Blueprint.
- Put startup and shutdown work in lifespan handlers. Use Uvicorn reload only in development.
- Declare `fastapi`, `uvicorn`, and the TestClient transport as needed by runtime and tests. Add `jinja2` only when
  the application serves templates. Use the Python foundation's environment and test command.

## Test dependency compatibility

Keep `fastapi.testclient.TestClient` as the client API. Starlette 1.2 and newer prefer `httpx2`;
plain `httpx` is deprecated there. Declare `fastapi` and `httpx2` inside every TestClient acceptance
criterion with `Requires: python-package=<name>; scope=test`. Older selected Starlette versions
use `httpx` instead. Resolve and lock the compatible FastAPI/Starlette/transport set together;
do not override FastAPI's Starlette constraints or suppress deprecation warnings. Verify client
construction and a request with deprecations treated as errors before accepting the lockfile.
Reference: https://www.starlette.io/testclient/

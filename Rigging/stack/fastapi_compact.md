<!-- Compacted from Rigging/stack/fastapi.md sha256=3e886596456e09537b8af7341beb13cc82802b58d596629762714a7c721214d8 on 2026-09-22 by Rigging maintenance — regenerate with: drydock rigging compact --include-file Rigging/stack/fastapi.md -->

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

## Consumer Rules

- Use Blueprint routes, schemas, settings, defaults, and error contracts. Do not invent sample APIs.
- Keep handlers thin; put business behavior in framework-independent services.
- Supply shared resources through overridable FastAPI dependencies.
- Include `request` in Jinja template context when serving pages; sanitize errors.
- Put startup and shutdown work in lifespan handlers.

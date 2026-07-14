# FastAPI Best Practices

**Version:** 20260521 V1
**Category:** Web Server
**Description:** FastAPI web framework patterns: app factory, routers, Pydantic models, dependency injection, templates, and testing

Technology reference for FastAPI web applications. This file does not change between projects.

Prerequisites: `stack/common.md`, `stack/python.md`

---

## 1. Directory Layout

**Rule**: Python application code lives in `app/`. The project root contains only `run.py` (entry point), `config.py`, and infrastructure files.

```
project/
  run.py                    # Entry point — uvicorn runs app.main:app
  config.py                 # Settings (Pydantic BaseSettings)
  pytest.ini
  requirements.txt
  app/
    __init__.py
    main.py                  # create_app() factory → FastAPI instance
    routers/
      __init__.py
      pages.py               # HTML page routes (Jinja2)
      api.py                 # JSON API routes
    models.py                # Pydantic request/response models
    services.py              # Business logic (no FastAPI imports)
    deps.py                  # Dependency-injection providers
    templates/
      base.html
      _nav.html
    static/
      css/
      js/
  tests/
    conftest.py
    test_smoke.py
    test_routes.py
  bin/
    common.sh
    start.sh
    stop.sh
    test.sh
```

Rules:
- `run.py` is the only file invoked directly; everything else is imported
- `app/` is a package; `create_app()` lives in `app/main.py`
- `config.py` stays in root because `run.py` and tests both import it
- `services.py` holds business logic — no FastAPI imports, pure Python, unit-testable
- `deps.py` holds dependency providers (settings, state store, etc.)
- Templates and static files live under `app/`

**Why**: A flat root mixes infrastructure with application code. The `app/` package keeps all application Python in one importable namespace and keeps route handlers thin.

---

## 2. Application Factory

**Rule**: Use a `create_app()` factory in `app/main.py`. Mount static files, configure templates, and include routers inside it. Expose `app` at module level for uvicorn.

```python
# app/main.py
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from pathlib import Path

from app.routers import pages, api

def create_app() -> FastAPI:
    app = FastAPI(title="My App", docs_url="/docs")

    static_dir = Path(__file__).parent / "static"
    app.mount("/static", StaticFiles(directory=static_dir), name="static")

    app.include_router(pages.router)
    app.include_router(api.router, prefix="/api")

    return app

app = create_app()
```

```python
# run.py
import os
import uvicorn

if __name__ == "__main__":
    port = int(os.environ.get("APP_PORT", 8000))
    uvicorn.run("app.main:app", host="127.0.0.1", port=port, reload=True)
```

**Why**: The factory lets tests build an app with overridden dependencies. A module-level `app` keeps the `uvicorn app.main:app` invocation simple for production.

---

## 3. Routers and Route Organization

**Rule**: Keep route handlers thin. Group routes with `APIRouter`. Push logic into `services.py`.

```python
# app/routers/api.py
from fastapi import APIRouter, Depends
from app import services
from app.deps import get_store
from app.models import Decision

router = APIRouter()

@router.get("/steps")
def list_steps(store = Depends(get_store)):
    return services.list_steps(store)

@router.post("/steps/{step_id}/decision")
def record_decision(step_id: int, decision: Decision, store = Depends(get_store)):
    return services.record_decision(store, step_id, decision)
```

```python
# app/services.py — business logic, no FastAPI imports
def list_steps(store):
    return store.read_steps()

def record_decision(store, step_id, decision):
    store.write_decision(step_id, decision.status, decision.feedback)
    return {"ok": True, "step_id": step_id}
```

Rules:
- Handlers parse input, call a service, return a value — FastAPI serializes it
- No file I/O, SQL, or subprocess calls inside handlers
- One `APIRouter` per feature area; mount with a `prefix`
- JSON routes return Pydantic models or dicts; page routes return `HTMLResponse`

**Why**: Thin handlers are testable; logic in `services.py` runs without an app context.

---

## 4. Pydantic Models

**Rule**: Define request and response shapes as Pydantic models. Validate at the boundary; never trust raw dicts from the client.

```python
# app/models.py
from typing import Literal, Optional
from pydantic import BaseModel, Field

class Decision(BaseModel):
    status: Literal["approved", "revise", "rejected"]
    feedback: Optional[str] = Field(default=None, max_length=4000)

class StepView(BaseModel):
    id: int
    name: str
    status: str
    evidence_files: list[str]
```

**Why**: Pydantic gives automatic validation, clear 422 errors, and OpenAPI docs for free. `Literal` constrains enums at the type level.

---

## 5. Dependency Injection

**Rule**: Provide shared resources (settings, state store, db handle) through `Depends`. Define providers in `deps.py`. Override them in tests.

```python
# app/deps.py
from functools import lru_cache
from config import Settings
from app.store import StateStore

@lru_cache
def get_settings() -> Settings:
    return Settings()

def get_store(settings = Depends(get_settings)) -> StateStore:
    return StateStore(settings.workspace_dir)
```

```python
# tests override providers without monkeypatching globals
app.dependency_overrides[get_store] = lambda: StateStore(tmp_workspace)
```

**Why**: DI keeps handlers free of construction logic and makes tests deterministic via `dependency_overrides`.

---

## 6. Configuration

**Rule**: Use `pydantic-settings` (`BaseSettings`) for typed config from environment. No bare `os.environ` reads scattered through the code.

```python
# config.py
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    app_name: str = "My App"
    app_port: int = 8000
    workspace_dir: str = "./workspace"

    class Config:
        env_file = ".env"
```

**Why**: One typed, validated source of configuration; defaults are explicit.

---

## 7. Templates (Jinja2)

**Rule**: For server-rendered pages, use `Jinja2Templates`. Inherit from `base.html`; prefix partials with `_`. Pass the `request` into the context (FastAPI requires it).

```python
# app/routers/pages.py
from fastapi import APIRouter, Request, Depends
from fastapi.templating import Jinja2Templates
from pathlib import Path
from app import services
from app.deps import get_store

router = APIRouter()
templates = Jinja2Templates(directory=Path(__file__).parent.parent / "templates")

@router.get("/")
def index(request: Request, store = Depends(get_store)):
    steps = services.list_steps(store)
    return templates.TemplateResponse("index.html", {"request": request, "steps": steps})
```

Rules:
- Every `TemplateResponse` context must include `"request"`
- All pages extend `base.html`; partials prefixed `_` (`_nav.html`)
- No Python logic in templates — pass ready-to-render data
- Auto-escaping is on by default — don't disable it
- Reference static files with `/static/...` paths

**Why**: Template inheritance removes duplication; the convention keeps includes discoverable.

---

## 8. Error Handling

**Rule**: Raise `HTTPException` for expected errors. Register exception handlers that return JSON for `/api/*` and HTML elsewhere. Never leak stack traces.

```python
# app/main.py (inside create_app)
from fastapi import Request
from fastapi.responses import JSONResponse, HTMLResponse
from fastapi.exceptions import RequestValidationError

@app.exception_handler(404)
async def not_found(request: Request, exc):
    if request.url.path.startswith("/api/"):
        return JSONResponse({"error": "Not found"}, status_code=404)
    return HTMLResponse("<h1>404</h1>", status_code=404)
```

**Why**: Dual JSON/HTML responses keep both API clients and browsers correct without exposing internals.

---

## 9. Testing with TestClient

**Rule**: Test through `fastapi.testclient.TestClient` (httpx under the hood). Override dependencies via `app.dependency_overrides`. Fixtures live in `conftest.py`.

```python
# tests/conftest.py
import pytest
from fastapi.testclient import TestClient
from app.main import create_app
from app.deps import get_store
from app.store import StateStore

@pytest.fixture
def client(tmp_path):
    app = create_app()
    app.dependency_overrides[get_store] = lambda: StateStore(str(tmp_path))
    return TestClient(app)
```

```python
# tests/test_routes.py
def test_health(client):
    assert client.get("/health").status_code == 200

def test_record_decision_roundtrip(client):
    r = client.post("/api/steps/1/decision",
                    json={"status": "approved", "feedback": "looks right"})
    assert r.status_code == 200
    assert r.json()["ok"] is True
```

`requirements.txt` must include `fastapi`, `uvicorn`, `jinja2`, `pydantic-settings`, `httpx`, and `pytest`. `pytest.ini` sets `testpaths = tests` and `addopts = -v`.

**Why**: `TestClient` exercises the full ASGI stack without a running server; `dependency_overrides` isolates tests from real state.

---

## 10. Health Check

**Rule**: Expose `/health` that verifies the app can reach its backing store.

```python
@router.get("/health")
def health(store = Depends(get_store)):
    try:
        store.ping()
        return {"status": "ok"}
    except Exception as e:
        return JSONResponse({"status": "error", "detail": str(e)}, status_code=500)
```

---

## 11. Development and Reloading

**Rule**: Use uvicorn's reloader in development only.

```bash
# Development
uvicorn app.main:app --reload --port 8000

# Production
uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 4
```

- `--reload` restarts on file changes (dev only; never with multiple workers)
- Startup/shutdown logic belongs in lifespan handlers, not import-time side effects

```python
from contextlib import asynccontextmanager

@asynccontextmanager
async def lifespan(app: FastAPI):
    # startup
    yield
    # shutdown

def create_app() -> FastAPI:
    app = FastAPI(lifespan=lifespan)
    ...
```

---

## Standard bin/ Scripts for FastAPI

```bash
# bin/start.sh
#!/bin/bash
# CommandCenter Operation
# Name: Start Service
# Category: Operations
# Port: 8000
source "$(cd "$(dirname "$0")" && pwd)/common.sh"
exec uvicorn app.main:app --reload --port "$PORT"
```

```bash
# bin/stop.sh
#!/bin/bash
# CommandCenter Operation
# Name: Stop Service
# Category: Operations
pkill -f "uvicorn app.main:app" || echo "No uvicorn process found"
```

```bash
# bin/test.sh
#!/bin/bash
# CommandCenter Operation
# Name: Test
# Category: Operations
source "$(cd "$(dirname "$0")" && pwd)/common.sh"
python -m pytest tests/ -v 2>&1
```

---

## Summary Checklist

- [ ] Directory layout: `app/` package, `run.py` entry point, `config.py` in root
- [ ] `create_app()` factory in `app/main.py`; module-level `app` for uvicorn
- [ ] `APIRouter` per feature area, thin handlers, logic in `services.py`
- [ ] Pydantic models for all request/response shapes
- [ ] Dependency injection via `Depends`, providers in `deps.py`, overridable in tests
- [ ] Typed config with `pydantic-settings`
- [ ] Jinja2 templates inherit `base.html`; every context includes `request`
- [ ] Exception handlers: JSON for `/api/*`, HTML elsewhere
- [ ] `TestClient` fixtures in `conftest.py`, `dependency_overrides` for isolation
- [ ] `/health` endpoint verifies the backing store
- [ ] uvicorn `--reload` in dev only; lifespan for startup/shutdown
- [ ] Standard `bin/` scripts: start.sh, stop.sh, test.sh

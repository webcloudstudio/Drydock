<!-- Compacted from fastapi.md on 2026-06-22 by drydock rigging compact — regenerate with: drydock rigging compact --include-file {rel_source} -->

# FastAPI Best Practices — Usage Surface

## Application Factory

### create_app

Returns a configured `FastAPI` instance with static files, routers, and exception handlers registered.

Returns: `FastAPI` — fully configured application instance

---

## Configuration

### app_name

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| app_name | str | no | Application display name; default `"My App"` |

### app_port

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| app_port | int | no | Port uvicorn binds to; default `8000` |

### workspace_dir

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| workspace_dir | str | no | Path to backing state store directory; default `"./workspace"` |

---

## Dependencies

### get_settings

Returns the cached `Settings` instance loaded from environment / `.env`.

Returns: `Settings` — typed configuration object

### get_store

Returns a `StateStore` bound to the configured workspace directory.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| settings | Settings | yes | Injected via `Depends(get_settings)` |

Returns: `StateStore` — backing state store instance

---

## Models

### Decision

Request body for recording a step decision.

| Field | Type | Description |
|-------|------|-------------|
| status | `Literal["approved", "revise", "rejected"]` | Decision outcome |
| feedback | `Optional[str]` | Free-text feedback; max 4000 chars |

### StepView

Response shape for a single step.

| Field | Type | Description |
|-------|------|-------------|
| id | int | Step identifier |
| name | str | Step name |
| status | str | Current status |
| evidence_files | list[str] | Associated file paths |

---

## API Routes

### GET /steps

Returns all steps from the backing store.

Returns: `list[StepView]` — list of step objects

### POST /steps/{step_id}/decision

Records a decision against a specific step.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| step_id | int | yes | Path parameter identifying the step |
| decision | Decision | yes | Request body with status and optional feedback |

| Field | Type | Description |
|-------|------|-------------|
| ok | bool | `true` on success |
| step_id | int | Echo of the updated step ID |

### GET /health

Verifies the application can reach its backing store.

| Field | Type | Description |
|-------|------|-------------|
| status | str | `"ok"` or `"error"` |
| detail | str | Error message; present only when status is `"error"` |

Returns HTTP 500 when the store is unreachable.

---

## Page Routes

### GET /

Renders the index page with all steps.

Returns: `HTMLResponse` — server-rendered HTML via Jinja2 `index.html` template

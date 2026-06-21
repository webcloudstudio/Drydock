# FEATURE: Runtime Platform

| Field       | Value |
|-------------|-------|
| Version     | 20260621 V1 |
| Description | The runtime platform establishes the source tree, packaging skeleton, local Flask app factory, SQLite bootstrap, shared Lambda helpers, and structured logging. |
| Depends On  | COMPASS.md, ARCHITECTURE.md, DATABASE.md |
| Provides    | GET /health, marina-source-tree, shared-lambda-helpers, structured-runtime-logging |
| Phase       | 1 |

## Purpose

This feature establishes the executable foundation for both planes:
- the repository layout
- Python packaging and editable install path
- local control-plane startup
- local database initialization
- shared helper code used by Lambda handlers
- structured logs for local and cloud execution paths

## Trigger

- Local startup invokes the Flask app factory.
- Lambda handlers import shared helper modules.
- Verification scripts and tests rely on the repository skeleton and bootstrap behavior.

## Build Scope

### Source-tree and packaging skeleton

The runtime platform produces:
- `src/marina_app/`
- `src/marina_cloud/`
- `src/marina_common/`
- `infra/`
- `bin/`
- `tests/`
- `.github/workflows/`
- `pyproject.toml`
- `uv.lock`

### Local startup gate

Startup sequence:
1. verify `git rev-parse --git-dir` succeeds
2. verify `git remote get-url origin` succeeds
3. extract the GitHub owner from the origin remote
4. seed `settings.github_username` when it is empty
5. initialize SQLite if missing
6. register routes and return the Flask app
7. expose `GET /health` returning `200`

### Shared Lambda helpers

Shared helper modules provide:
- request parsing
- JSON response shaping
- principal extraction from API Gateway context
- DynamoDB key builders
- timestamp helpers
- structured log helpers
- shared ACL-cache utilities

### Structured logging

Every local service action and Lambda handler emits structured JSON lines containing:
- `event`
- `component`
- `project` when applicable
- `principal` when applicable
- `status`
- `duration_ms` when timing is relevant

## Reads

- current working tree git metadata
- SQLite schema definitions
- environment variables for local runtime configuration
- Lambda event payloads and API Gateway context

## Writes

- `data/marina.db` on first boot and subsequent local writes
- structured local logs
- CloudWatch log lines from Lambda handlers
- seeded `settings.github_username`

## Verification

Primary verification:
- startup in a git repository with `origin` succeeds
- startup outside a git repository fails clearly
- `/health` returns `200`
- SQLite initializes cleanly
- shared helper modules are importable by every handler
- structured logs include stable event keys

## Acceptance Criteria

- The repository skeleton supports local app code, Lambda code, Terraform, tests, and workflows.
- The local app factory enforces the startup gate and exposes `GET /health`.
- Shared Lambda helpers remove duplicated auth, response, key-building, and timestamp logic.
- Runtime logging is structured and reusable across local and cloud flows.

## Guardrails

- `bin/` contains launchers and verification scripts only.
- The startup gate does not silently continue when git or `origin` is missing.
- Logging remains structured JSON, not free-form print output.

## Open Questions

- None.

# SCREEN: Setup Settings

| Field       | Value |
|-------------|-------|
| Version     | 20260621 V1 |
| Description | The Settings screen edits application settings, environment overrides, and the alert profile with per-field save-on-blur behavior. |
| Depends On  | UI-GENERAL.md, FEATURE-SETUP-CONTROL-PLANE.md |
| Provides    | GET /setup/settings |
| Phase       | 5 |
| Route       | /setup/settings |
| Parent      | Main |
| Main Menu   | Setup (1) |
| Sub Menu    | Settings (8) |
| Tab Order   | 8 |
| Consumes    | POST /api/setup/config |

## Layout

Single-column centered layout with three cards:
- Application
- Environment
- Alert Profile

The header KPI area is intentionally empty.

## Interactions

- every field saves individually on blur
- theme saves immediately on click
- restart-required values show an inline restart notice after successful save
- empty environment fields mean "fall back to `.env`"

Editable settings include:
- `app_name`
- `app_theme`
- `PROJECTS_DIR`
- `MARINA_API_URL`
- `AWS_REGION`
- `AWS_PROFILE`
- `PORT`
- `user_email`
- `user_cell`

## Validation

- `app_name` must be non-empty
- `user_email` must contain `@` when present
- `user_cell` normalizes to E.164 when present
- `PORT` must be `1024-65535`
- `MARINA_API_URL` must be HTTPS when present
- `AWS_REGION` must match AWS region syntax

## Acceptance Criteria

- Each field saves independently through the shared config API.
- Settings-table values override `.env` values at runtime when present.
- Restart-required fields show a clear post-save notice.

## Guardrails

- The screen does not write the `.env` file directly.
- There is no page-level Save button in V1.
- Validation failures return field-specific feedback rather than silent rejection.

## Open Questions

- None.

# SCREEN: Setup Summary

| Field       | Value |
|-------------|-------|
| Version     | 20260621 V1 |
| Description | The Setup Summary screen is the default landing page and shows one readiness row per Setup tab with inline `PROJECTS_DIR` editing. |
| Depends On  | UI-GENERAL.md, FEATURE-SETUP-CONTROL-PLANE.md |
| Provides    | GET /setup/summary, GET /setup, GET / |
| Phase       | 5 |
| Route       | /setup/summary |
| Parent      | Main |
| Main Menu   | Setup (1) |
| Sub Menu    | Summary (1) |
| Tab Order   | 1 |
| Consumes    | GET /api/setup/summary/status, POST /api/setup/config |

## Layout

The page renders:
- shared page header with all-good KPI
- optional setup-required banner
- one Setup Status card

The card lists rows for:
- AWS
- Terraform
- GitHub
- Git Scan
- Projects
- Repositories
- Settings

## Interactions

- `GET /` redirects here
- `GET /setup` redirects here
- the Projects row always shows an inline editable `PROJECTS_DIR` field
- blur on the field posts to `/api/setup/config`
- manual refresh uses the summary-status API payload to redraw row states

## Row Semantics

Each row exposes:
- icon
- status icon
- row label
- status text
- detail or action area

Critical rows are:
- AWS
- GitHub
- Projects

If any critical row is `❌`, the banner is shown.

## Acceptance Criteria

- The Summary screen renders one row per Setup tab except itself.
- The Summary route is the application's default landing path.
- `PROJECTS_DIR` is editable inline from this screen and saves through the shared config API.

## Guardrails

- The screen does not add per-row navigation links.
- The banner appears only for critical-row failures, not for every warning.
- The Summary screen remains a high-level overview and does not duplicate the full contents of child tabs.

## Open Questions

- None.

# SCREEN: Setup Git Scan

| Field       | Value |
|-------------|-------|
| Version     | 20260621 V1 |
| Description | The Git Scan screen refreshes GitHub inventory from configured sources and presents count-invariant results for GitHub, downloaded, conformed, and unmatched local projects. |
| Depends On  | UI-GENERAL.md, FEATURE-SETUP-CONTROL-PLANE.md |
| Provides    | GET /setup/scan |
| Phase       | 5 |
| Route       | /setup/scan |
| Parent      | Main |
| Main Menu   | Setup (1) |
| Sub Menu    | Git Scan (5) |
| Tab Order   | 5 |
| Consumes    | POST /api/repositories/sync, GET /api/setup/scan/status |

## Layout

Single-column centered layout with:
- header action button KPI
- last-scan timestamp line
- one results table

Columns:
- one per configured source
- one trailing `Other` column

Rows:
- On GitHub
- Downloaded
- Conformed
- Not Downloaded
- Total Visible

## Interactions

- Scan GitHub Now posts to `/api/repositories/sync`
- the scan updates the timestamp and results fragments
- the tab is disabled until GitHub is configured and `PROJECTS_DIR` exists

## Counting Rules

For named source columns:
- `Downloaded + Not Downloaded = On GitHub`
- `Conformed <= Downloaded`

For the `Other` column:
- only local unmatched projects are counted
- `On GitHub` and `Not Downloaded` are not applicable

## Acceptance Criteria

- The screen renders source columns plus the `Other` column.
- Scan results preserve the documented counting invariants.
- The scan action is the only refresh path for GitHub repo inventory.

## Guardrails

- The screen does not introduce a second repo-refresh entry point.
- The `Other` column does not fabricate GitHub counts.
- The tab remains disabled instead of hidden when prerequisites are missing.

## Open Questions

- None.

# SCREEN: Setup Repositories

| Field       | Value |
|-------------|-------|
| Version     | 20260621 V1 |
| Description | The Repositories screen shows cached GitHub repositories across configured sources, prioritizes downloaded rows, and supports one-click clone with SSH fallback. |
| Depends On  | UI-GENERAL.md, FEATURE-SETUP-CONTROL-PLANE.md |
| Provides    | GET /setup/repositories |
| Phase       | 5 |
| Route       | /setup/repositories |
| Parent      | Main |
| Main Menu   | Setup (1) |
| Sub Menu    | Repositories (6) |
| Tab Order   | 6 |
| Consumes    | GET /api/repositories, POST /api/repositories/download |

## Layout

Full-width layout with:
- search input
- single repository table

Columns:
- On Disk
- Repository
- Source when more than one source is visible
- Visibility
- Last pushed
- Action

## Interactions

- search is client-side only
- table data comes from `/api/repositories`
- Get posts to `/api/repositories/download`
- Open uses the GitHub HTML URL once the repo is downloaded

Default sort:
- downloaded rows first alphabetically
- not-downloaded rows second alphabetically

## Unconfigured State

When GitHub is not configured or `PROJECTS_DIR` is unset, the page shows a full-panel notice linking back to GitHub Setup.

## Acceptance Criteria

- The screen reflects the cached `github_repos` table without adding its own refresh action.
- Download clones into `PROJECTS_DIR` and updates the row state in place.
- SSH failure falls back to HTTPS cloning automatically.

## Guardrails

- The screen does not paginate V1 results.
- The screen does not publish a project to Marina during download.
- Disk-only projects remain on the Projects screen, not this screen.

## Open Questions

- None.

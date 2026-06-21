# SCREEN: Setup GitHub

| Field       | Value |
|-------------|-------|
| Version     | 20260621 V1 |
| Description | The GitHub Setup screen verifies CLI auth and SSH connectivity and manages the persistent source-account list used for repo scans. |
| Depends On  | UI-GENERAL.md, FEATURE-SETUP-CONTROL-PLANE.md |
| Provides    | GET /setup/github |
| Phase       | 5 |
| Route       | /setup/github |
| Parent      | Main |
| Main Menu   | Setup (1) |
| Sub Menu    | GitHub (4) |
| Tab Order   | 4 |
| Consumes    | POST /api/setup/github/check-auth, POST /api/setup/github/check-ssh, POST /api/setup/github/sources, DELETE /api/setup/github/sources/{id} |

## Layout

Single-column centered layout with three cards:
- Authentication
- SSH
- Source Accounts

The header KPI is a status light.

## Interactions

- Re-check Auth posts to `/api/setup/github/check-auth`
- Re-check SSH posts to `/api/setup/github/check-ssh`
- Add source posts to `/api/setup/github/sources`
- Remove source deletes `/api/setup/github/sources/{id}`

## Status Rules

Page KPI:
- green when auth is good, SSH is good, and at least one source exists
- amber when at least one source exists but auth or SSH is failing
- red when sources are missing or GitHub auth is missing

Type detection for added sources:
- URL when the value contains `://`
- User or Org through GitHub API lookup
- Unknown when resolution fails

## Acceptance Criteria

- The screen renders auth, SSH, and source-account states correctly.
- Sources persist in SQLite and drive later scan behavior.
- SSH failure preserves the HTTPS fallback guidance.

## Guardrails

- The screen does not persist GitHub auth tokens.
- The screen does not hide the source list when auth is failing.
- Unsupported hosts remain out of scope for V1.

## Open Questions

- None.

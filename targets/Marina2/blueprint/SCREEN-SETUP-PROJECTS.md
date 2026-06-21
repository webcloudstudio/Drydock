# SCREEN: Setup Projects

| Field       | Value |
|-------------|-------|
| Version     | 20260621 V1 |
| Description | The Projects screen lists qualifying GitHub-backed local projects, rescans disk metadata and conformance state, and runs one-project conform actions. |
| Depends On  | UI-GENERAL.md, FEATURE-SETUP-CONTROL-PLANE.md |
| Provides    | GET /setup/projects |
| Phase       | 5 |
| Route       | /setup/projects |
| Parent      | Main |
| Main Menu   | Setup (1) |
| Sub Menu    | Projects (7) |
| Tab Order   | 7 |
| Consumes    | POST /api/scan, POST /api/projects/{id}/conform |

## Layout

Full-width layout with:
- namespace filter pills
- search field
- rescan button
- sortable project table

Columns:
- Name
- Conform Status
- Status
- Namespace
- Actions

## Qualification Rules

A directory qualifies when:
1. it is not hidden
2. it contains `.git/`
3. `git remote get-url origin` includes `github.com`

Directories failing any rule are excluded silently.

## Interactions

- Rescan posts to `/api/scan`
- Conform posts to `/api/projects/{id}/conform`
- namespace filter is URL-backed
- text search is client-side only

Conform action selection:
- unknown project => initialize
- needs update => update
- conformed => disabled success badge

## Acceptance Criteria

- The table lists only qualifying GitHub-backed directories.
- Rescan refreshes metadata, git state, and Prototyper validation status from disk.
- Conform actions invoke the correct Prototyper path for the row state.

## Guardrails

- The table stays single-row per project.
- Conform All is out of scope for V1.
- Directories without a GitHub origin do not appear on this screen.

## Open Questions

- None.

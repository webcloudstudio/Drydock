# NOTES: General

| Field | Value |
|-------|-------|
| Version | 2026-06-14 V1 |
| Route | general |
| Status | Working notes — not canonical specification |
| Description | Cross-cutting decisions not belonging to a specific command or SAIL phase. |
| Pending spec | 0 recommended items | 0 || Pending impl | 0 unimplemented sections | 0 |
## Goal

Capture design decisions that span multiple commands or relate to the Drydock development process
itself (tooling, notes format, workflow conventions).

## Decisions

### Section Title
`YYYY-MM-DD` · `spec:<value>` · `impl:<value>`

Narrative, tables, diagrams — as much as needed.
```

Three flags per section:

| Flag | Values | Rule |
|------|--------|------|
| date | `YYYY-MM-DD` | Set on write; not updated on edit |
| spec | `na` / `recommended` / `applied` | `recommended` only if decision changes a behavioral contract |
| impl | `implemented` / `unimplemented` | Based on known codebase state |

The file header tracks summary counts (`Pending spec`, `Pending impl`) updated on every write.

# DATABASE: Drydock

| Field | Value |
|-------|-------|
| Version | 2026-06-14 V1 |
| Description | Persistence stores and typed access classes for Drydock. |

<!-- Tables and columns only. Stack conventions applied during conversion. -->
<!-- Delete this file if the project has no database. -->

## table_name

| Column | Type | Notes |
|--------|------|-------|
| id | INTEGER PK | |
| created_at | TEXT | timestamp |
| updated_at | TEXT | timestamp |

## Data Access Classes

<!-- The typed classes that encapsulate each store. Patterns from stack/persistence.md applied during conversion. -->

| Store | Class | Notes |
|-------|-------|-------|
| table_name | Database.table_name | row dataclass + CRUD |

## Config (.env)

| Key | Type | Required | Notes |
|-----|------|----------|-------|
| SECRET_KEY | str | yes | |

## File Stores

| Store | Root dir | Notes |
|-------|----------|-------|

## External Services

| Service | Wrapper | Notes |
|---------|---------|-------|

## Acceptance Criteria

- None.

## Guardrails

- None.

## Open Questions

- None.

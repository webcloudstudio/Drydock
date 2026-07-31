# DATABASE: __PROJECT_NAME__

| Field | Value |
|-------|-------|
| Version | __TODAY__ V1 |
| Description | Persistence stores and typed interfaces for __PROJECT_NAME__. |
| Depends On | ARCHITECTURE.md |
| Provides | |
| Build Order | |

## Questions

- None.

<!-- Store interfaces first. Schema details follow the public persistence boundary. -->
<!-- Delete this file if the project has no database. -->

## Persistence Boundary

| Boundary | Rule |
|----------|------|
| Raw storage access | Only the typed persistence classes access storage internals. |
| Caller dependency | Features depend on class methods, not schemas or provider APIs. |

## Access Patterns

| ID | Caller | Operation | Store | Interface | Notes |
|----|--------|-----------|-------|-----------|-------|
| AP-001 | FEATURE-Example.md | Create item | table_name | Database.table_name.create | |

## Persistence Interfaces

<!-- The typed classes that encapsulate each store. Patterns from stack/persistence.md applied during conversion. -->

| Store | Interface | Module | Allowed Callers | Notes |
|-------|-----------|--------|-----------------|-------|
| table_name | Database.table_name | db.py | FEATURE-Example.md | row dataclass + CRUD |

## Schemas

### table_name

| Column | Type | Notes |
|--------|------|-------|
| id | INTEGER PK | |
| created_at | TEXT | timestamp |
| updated_at | TEXT | timestamp |

## Migrations

| Migration | Trigger | Action |
|-----------|---------|--------|
| initial_schema | startup | Create required stores if absent. |

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

## External Libraries

| Library | Ownership | Distribution | Consumer Contract |
|---------|-----------|--------------|-------------------|

## Programmatic Acceptance

- None.

## User Acceptance

- None.

## Guardrails

- None.

# DATABASE: __PROJECT_NAME__

| Field | Value |
|-------|-------|
| Version | __TODAY__ V1 |
| Description | Persistence stores and typed interfaces for __PROJECT_NAME__. |
| Depends On | ARCHITECTURE.md |
| Provides | |
| Build Order | |

<!-- Store interfaces first. Schema details follow the public persistence boundary. -->
<!-- Delete this file if the project has no database. -->

## Persistence Boundary

| Boundary | Rule |
|----------|------|
| Raw storage access | Only repository implementations access SQLAlchemy models and sessions. |
| Caller dependency | Features depend on named repository calls and DTOs, not schemas or provider APIs. |
| Python relational stack | `sqlalchemy.md` and `alembic.md` are required selections. |

## Access Patterns

| ID | Caller | Operation | Repository call | Input / Output | Compatibility |
|----|--------|-----------|-------|-----------|-------|
| DATA-EXAMPLE-001 | FEATURE-Example.md | Create item | `ItemRepository.create()` | `CreateItem` → `Item` | rebuild |

## Persistence Interfaces

<!-- The typed classes that encapsulate each store. Patterns from stack/persistence.md applied during conversion. -->

| Store | Interface | Module | Allowed Callers | Notes |
|-------|-----------|--------|-----------------|-------|
| table_name | `ItemRepository` | persistence/items.py | Item service | SQLAlchemy models remain private |

## Schemas

### table_name

| Column | Type | Notes |
|--------|------|-------|
| id | INTEGER PK | |
| created_at | TEXT | timestamp |
| updated_at | TEXT | timestamp |

## Migrations

| Revision | Trigger | Action |
|-----------|---------|--------|
| `0001_initial_items` | deployment / explicit migration | Alembic creates required stores. |

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

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

<!-- One `### <FEATURE-DOMAIN-NNN> — <Operation>` section per operation, below this heading. -->
<!-- Never a single table of operations: each pattern is its own section over a | Field | Value | -->
<!-- table carrying Owner, Access (read, write, or read-write), Repository operation, and -->
<!-- Compatibility. Every Blueprint that reaches the database cites these ids in its own -->
<!-- `## Database Interface` section; a citation may claim less access than granted, never more. -->
<!-- Plan appends new patterns as it authors Blueprints; it never rewrites held ones. -->

<!-- drydock:example -->
### FEATURE-EXAMPLE-001 — Create item

| Field | Value |
|-------|-------|
| Owner | FEATURE-Example.md |
| Access | write |
| Repository operation | `ItemRepository.create(CreateItem) -> Item` |
| Compatibility | rebuild |

Input: CreateItem

| Field | Type | Required |
|-------|------|----------|
| name | str | yes |

Output: Item

| Field | Type |
|-------|------|
| id | UUID |
| name | str |
<!-- drydock:end-example -->

## Persistence Interfaces

<!-- The typed classes that encapsulate each store. Patterns from stack/persistence.md applied during conversion. -->

| Store | Interface | Module | Allowed Callers | Notes |
|-------|-----------|--------|-----------------|-------|
<!-- drydock:example -->
| table_name | `ItemRepository` | persistence/items.py | Item service | SQLAlchemy models remain private |
<!-- drydock:end-example -->

## Schemas

<!-- One `## `table_name`` section per table, below this heading. Lowercase snake_case name in -->
<!-- backticks; SQLite types only: INTEGER, TEXT, REAL, NUMERIC, BLOB. `PK` marks a primary key. -->
<!-- Plan appends to these declarations as it authors Blueprints; it never rewrites them. -->

<!-- drydock:example -->
## `table_name`

| Field | Type | Notes |
|--------|------|-------|
| id | INTEGER PK | |
| created_at | TEXT | timestamp |
| updated_at | TEXT | timestamp |
<!-- drydock:end-example -->

## Migrations

Each relational change has one staged record in `migrations/MIGRATION-<AccessPatternId>.md`.
The record carries Alembic `upgrade`/`downgrade` snippets and progresses from `planned` to `built`
only when its DATABASE build story completes. Alembic records deployment application separately.

| Access Pattern | Revision | State |
|----------------|----------|-------|
<!-- drydock:example -->
| FEATURE-EXAMPLE-001 | `0001_initial_items` | planned |
<!-- drydock:end-example -->

## Config (.env)

| Key | Type | Required | Notes |
|-----|------|----------|-------|
<!-- drydock:example -->
| SECRET_KEY | str | yes | |
<!-- drydock:end-example -->

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

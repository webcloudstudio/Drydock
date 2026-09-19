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
<!-- A citation is one bullet on one line: -->
<!--   - `FEATURE-ORDER-001` — write: create an order - supplies: `customer_id` - returns: `id` -->
<!-- and a Blueprint that reaches no repository writes `- None — <who owns persistence>.` -->
<!-- Owner is the file name of the Blueprint that reaches the pattern — FEATURE-Example.md — -->
<!-- never a service or module name. It is compared to the emitted Blueprints, so an Owner -->
<!-- naming no Blueprint fails the plan, as does an Owner that cites nothing. Only a -->
<!-- Blueprint named as Owner nowhere may write `- None`. -->
<!-- Plan appends new patterns as it authors Blueprints; it never rewrites held ones. -->

<!-- Repository operation names one declared table and one verb as `<table>.<verb>`, lowercase: -->
<!-- `settings.get`. The verb is get, list, create, update, or delete, and no other. One pattern -->
<!-- declares one operation, because it carries one Input and one Output; give each operation its -->
<!-- own `### <FEATURE-DOMAIN-NNN>` section. It is the only place the declaration says which -->
<!-- table a pattern reaches, so the form is checked, not advisory. -->
<!-- Every table in `## Schema` is reached by at least one pattern, and every pattern names a -->
<!-- table `## Schema` declares. A table nothing reaches is storage no story can use; an -->
<!-- operation on a table that is not declared builds a repository against nothing. Both fail -->
<!-- the plan. -->

<!-- drydock:example -->
### FEATURE-EXAMPLE-001 — Create item

| Field | Value |
|-------|-------|
| Owner | FEATURE-Example.md |
| Access | write |
| Repository operation | `items.create` |
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
<!-- backticks. A type cell is: -->
<!--   <TYPE> [PK] [NOT NULL] [UNIQUE] [DEFAULT <literal>] [REFERENCES <table>(<column>)] -->
<!-- where <TYPE> is INTEGER, TEXT, REAL, NUMERIC, or VARCHAR(<n>), and <literal> is a -->
<!-- single-quoted string, a number, NULL, CURRENT_TIMESTAMP, CURRENT_DATE, or CURRENT_TIME. -->
<!-- Nothing else is accepted: Drydock renders executable DDL from these cells, so a modifier it -->
<!-- cannot read is a constraint the built database would not have. Postgres enforces -->
<!-- VARCHAR(<n>) and SQLite accepts the same declaration and ignores it, so one spelling serves -->
<!-- both engines. A foreign key names a table and column this same file declares. -->
<!-- A constraint spanning several columns is a bullet under that table's field table, one per -->
<!-- line: `- UNIQUE (a, b)` or `- INDEX (a, b)`, each over two or more declared columns. A -->
<!-- single-column UNIQUE states UNIQUE in its own type cell instead. -->
<!-- Plan appends to these declarations as it authors Blueprints; it never rewrites them. -->

<!-- drydock:example -->
## `table_name`

| Field | Type | Notes |
|--------|------|-------|
| id | INTEGER PK | |
| project_id | INTEGER NOT NULL REFERENCES projects(id) | |
| name | VARCHAR(120) NOT NULL | |
| status | TEXT NOT NULL DEFAULT 'active' | |
| created_at | TEXT DEFAULT CURRENT_TIMESTAMP | timestamp |

- UNIQUE (project_id, name)
- INDEX (project_id, created_at)
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

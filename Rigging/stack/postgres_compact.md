<!-- Compacted from Rigging/stack/postgres.md sha256=a8979b2b6e46fb234f59b15a91724b1e5b43720538c5ae5dca627f55019947e4 on 2026-09-19 by drydock rigging compact — regenerate with: drydock rigging compact --include-file {rel_source} -->

# PostgreSQL — Contract Surface

### config: PostgreSQL DSN

The production database is selected by a `postgresql://` DSN supplied through the typed `Config` class and environment.

Constraints: Do not store credentials in the repository. Add `psycopg[binary]` to project dependencies when using PostgreSQL.

### db.<table>.<verb>(...)

Callers access generated persistence operations through the `db.<table>.<verb>(...)` interface.

Constraints: Do not write hand-coded cursors, connection pools, SQL strings, or access layers. The generated persistence package handles connection management, parameter binding, `RETURNING`, and row mapping.

### Rule: supported-language

Python Targets use the shipped PostgreSQL adapter; Targets in other languages declaring `DATABASE.md` fail before planning.

### Rule: schema-enforcement

PostgreSQL enforces declared column lengths, declared types, and foreign-key creation order.

Constraints: Referenced tables must be created before dependent tables. Foreign-key cycles are refused.

### Rule: schema-lifecycle

The schema is built once during the DATABASE build step and is not migrated within a release.

### Rule: schema-changes

Across releases, widening `varchar(n)` and dropping `NOT NULL` are supported; setting `NOT NULL` scans the table.

### Rule: database-boundaries

PostgreSQL drivers may be imported only within the generated `persistence/` package, values must be parameter-bound rather than formatted into SQL, and applications must not create or alter schema at startup.

<!-- Compacted from Rigging/stack/sqlite.md sha256=d2139b3b055bd309c35d5c63161a833f7ef0bc899e7542d39fa99a7902317b5a on 2026-09-19 by drydock rigging compact — regenerate with: drydock rigging compact --include-file {rel_source} -->

# SQLite — Contract Surface

## Persistence

### config_key

SQLite is selected at runtime using a plain filesystem path or a `sqlite://` DSN.

Constraints: The same build must support SQLite for development and testing and PostgreSQL for production through runtime DSN selection.

### Rule: supported-language

Python Targets with `DATABASE.md` use the shipped SQLite adapter; Targets declaring another language fail before planning.

Constraints: Do not provide or generate a hand-written access layer for unsupported languages.

### Rule: database-access

Callers access generated persistence through `db.<table>.<verb>(...)`.

Constraints: Do not import `sqlite3` outside the generated `persistence/` package, hold a `sqlite3.Connection` on an application object, or create or alter schema at application startup.

### Rule: enforced-constraints

SQLite enforces `PRIMARY KEY`, `NOT NULL`, `UNIQUE`, `DEFAULT`, and `REFERENCES` when foreign-key enforcement is enabled.

### Rule: production-validation

SQLite does not enforce declared column lengths or strict column types.

Constraints: Declare production column lengths and types, and do not treat passing SQLite tests as proof that those constraints hold in production.

### Rule: schema-alteration

Schema changes are limited to `ADD COLUMN` and `RENAME`; type changes and `ADD CONSTRAINT` are unsupported.

Constraints: Build the schema once from `schema.sql` during the DATABASE build step.

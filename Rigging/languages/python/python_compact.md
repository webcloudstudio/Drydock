<!-- Compacted from Rigging/languages/python/python.md sha256=68196bfe920adce646fc68e2528fb116eb6f505999db985f3c26baca51b6e132 on 2026-10-18 by Rigging maintenance -->

## Foundation Contract

- source_root: ./
- test_command: pytest -q
- environment: `.venv`, created by `uv venv` and activated by launchers in `bin/`
- dependencies: `pyproject.toml` and committed `uv.lock`

The language foundation owns the project root, environment, dependency manifest, and test runner.
Later foundations add their packages to this tree without replacing those contracts.

### How do we execute and measure Acceptance Criteria in this language?

An Acceptance Criterion (AC) is an executable check of Blueprint-required behavior. Use the
existing Programmatic Acceptance format: a Python script with assertions against the built
product. Drydock executes each criterion through `languages/python/acceptance/runner.py`; `pytest -q`
runs the project test suite. Retain the criterion ID, observed values, stdout/stderr and result;
an assertion failure fails the check. The harness reports failure operands and available case
counts. Code coverage and persistence interactions require explicit instrumentation; record
available observations as key/value data associated with the criterion. Missing observations
are unknown, not proof that code or an interaction was unused.

### How does this language provide the shared persistence contract?

Use `stack/persistence.md`. Drydock copies `Rigging/languages/python/persistence/{db,sqlite,postgres}.py` and generates
`persistence/{schema,__init__,testing}.py` plus `schema.sql` from `DATABASE.md`. Call
`open_database(dsn)` and `db.<table>.<operation>(...)`; use `persistence.testing.db_session()`
for criteria. Explicit init commands use `persistence.initialize_database(dsn)` to apply generated
creation DDL to the selected store and preserve existing data; close the returned database.
Ordinary opens do not initialize. SQLite uses the standard library; PostgreSQL needs `psycopg[binary]` in the project
dependencies. Both engines ship together and the DSN selects the engine. Library verification
lives in `tests/test_shipped_database.py`; a Target still verifies its own schema and operations.

## Consumer Rules

- Python >=3.11; use modern type hints on public interfaces and named cross-package data shapes.
- Centralize typed runtime settings; use Blueprint names and defaults. Keep secrets out of Git and logs.
- Keep behavior in importable modules; launchers activate `.venv` and invoke modules.
- Use pytest with isolated external state; all test gates run `pytest -q`.

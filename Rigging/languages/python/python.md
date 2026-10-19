# Python Foundation

**Type:** language
**Version:** 20261018 V5
**Foundation:** language
**Tier:** language
**Category:** Language
**Description:** Python project foundation and cross-package contracts

Prerequisite: `stack/common.md`

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
for criteria. SQLite uses the standard library; PostgreSQL needs `psycopg[binary]` in the project
dependencies. Both engines ship together and the DSN selects the engine. Library verification
lives in `tests/test_shipped_database.py`; a Target still verifies its own schema and operations.

## Rules

- Target Python 3.11 or newer. Declare the supported version in `pyproject.toml`.
- Keep runtime settings in one typed configuration boundary. Document supported environment
  variables in `.env.example`; keep `.env` and secrets out of Git. Use project-specific names and
  defaults from the Blueprint rather than examples in Rigging.
- Use modern type hints on public interfaces and named types for data exchanged between packages.
- Put application behavior in importable modules; launchers in `bin/` activate `.venv` and invoke
  those modules. Launchers do not contain business logic.
- Use named Python loggers for application events. Never log secrets.
- Use pytest for behavior and acceptance tests. Isolate external state and dependencies in tests.
  Every launcher and CI test gate runs the published `test_command`.
- Use `uv` for environment and dependency management. Commit `pyproject.toml` and `uv.lock`;
  do not commit `.venv/`.

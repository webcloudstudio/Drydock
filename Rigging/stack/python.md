# Python Foundation

**Version:** 20260922 V4
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

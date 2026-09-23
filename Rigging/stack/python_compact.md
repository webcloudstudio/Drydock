<!-- Compacted from Rigging/stack/python.md sha256=aba487da57dcf23458a0ae18939231b5294172a3f655d5550a705e2405408f11 on 2026-09-22 by Rigging maintenance — regenerate with: drydock rigging compact --include-file Rigging/stack/python.md -->

## Foundation Contract

- source_root: ./
- test_command: pytest -q
- environment: `.venv`, created by `uv venv` and activated by launchers in `bin/`
- dependencies: `pyproject.toml` and committed `uv.lock`

The language foundation owns the project root, environment, dependency manifest, and test runner.
Later foundations add their packages to this tree without replacing those contracts.

## Consumer Rules

- Python >=3.11; use modern type hints on public interfaces and named cross-package data shapes.
- Centralize typed runtime settings; use Blueprint names and defaults. Keep secrets out of Git and logs.
- Keep behavior in importable modules; launchers activate `.venv` and invoke modules.
- Use pytest with isolated external state; all test gates run `pytest -q`.

# AGENTS.md — Drydock

This file describes how AI agents should work within the Drydock repository.

## Project Layout

```
Drydock/
  src/drydock/       Python package source
  Rigging/           Human-editable Rigging (spec templates, stack rules, business rules)
  tests/             Pytest test suite
  bin/               Source-tree launchers (no business logic)
  prompts/           LLM prompts (ported alongside their commands)
  dist/              Build artifacts (not committed)
  .venv/             Virtual environment (not committed)
```

## Development Commands

```bash
# Install in editable mode with dev dependencies
uv pip install -e ".[dev]"

# Run tests
python -m pytest

# Run tests via shell script
bash bin/test.sh

# Lint and format
ruff check src/ tests/
ruff format src/ tests/

# Build wheel
python -m hatchling build
```

## Key Constraints

- Do NOT modify `/mnt/c/Users/barlo/projects/Prototyper` — it is the read-only behavioral reference.
- Never add Typer, Click, Rich, Pydantic, databases, or application frameworks without explicit approval.
- Never call the Anthropic API directly. Use the `claude` CLI.
- `Rigging/` is the human-editable source of truth. `src/drydock/resources/Rigging/` is the installed copy — Hatchling syncs it via `force-include` at build time.
- All configuration is persisted via `drydock config set`; do not read project-local `.env` files.
- Exit codes: `0` success, `1` operational failure, `2` usage error or deferred command.

## Rigging Resolver

When running from source: uses root-level `Rigging/`.
When installed: uses `importlib.resources` to read `drydock/resources/Rigging/`.
Both paths must work. See `src/drydock/paths.py`.

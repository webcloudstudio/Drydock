# uv and ruff Best Practices

**Version:** 20260716 V1  
**Category:** Technologies
**Description:** Python toolchain conventions — uv for environments and dependencies, ruff for linting and formatting

Technology reference for the Python toolchain. Applies to any Python project that selects it. This file does not change between projects.

Prerequisites: `stack/common.md`, `stack/python.md`

---

## 1. uv Owns the Environment

**Rule**: uv is the only tool that creates environments, installs packages, and runs project commands. Never use bare `pip`, `python -m venv`, `pipx`, or `poetry` alongside it.

```bash
uv venv                          # create .venv/ (once per clone)
uv python pin 3.12               # writes .python-version — committed
uv add flask python-dotenv       # runtime dep → updates pyproject.toml + uv.lock
uv add --dev pytest ruff mypy    # dev deps
uv remove flask                  # removal goes through uv too — never hand-edit installs
uv sync                          # install exactly what uv.lock says (clone setup)
uv sync --frozen                 # CI install — fail if lock is stale
uv run pytest                    # run tools inside the project env without activating
uv run python app.py
uvx ruff --version               # one-off tool run, no install into the project
```

Rules:
- `pyproject.toml` is the manifest; `uv.lock` is committed; `.venv/` and `__pycache__/` are gitignored.
- Pin the interpreter with `uv python pin` so `.python-version` is committed and every machine resolves the same Python.
- Prefer `uv run <cmd>` over activating the venv in scripts and CI — it is explicit and cannot pick up the wrong environment.
- Dependency changes always go through `uv add` / `uv remove` so the lock file never drifts from the manifest.
- CI uses `uv sync --frozen`; a stale lock fails the build instead of silently re-resolving.

**Why**: One tool with one lock file makes installs deterministic. `works on my machine` is almost always an environment drift problem, and `uv sync --frozen` makes drift a build failure.

---

## 2. ruff Is Linter and Formatter

**Rule**: ruff replaces flake8, isort, pyupgrade, and black. Configure it once in `pyproject.toml`; do not add a second linter or formatter.

```toml
# pyproject.toml
[tool.ruff]
line-length = 88
target-version = "py312"

[tool.ruff.lint]
select = [
    "E", "W",   # pycodestyle
    "F",        # pyflakes
    "I",        # isort — import ordering
    "UP",       # pyupgrade — modern syntax, incl. modern type hints
    "B",        # bugbear — likely bugs
    "SIM",      # simplify
    "C4",       # comprehension cleanups
]

[tool.ruff.format]
quote-style = "double"
```

```bash
uv run ruff check .              # lint
uv run ruff check . --fix        # apply safe autofixes
uv run ruff format .             # format
uv run ruff format . --check     # CI — verify without rewriting
```

Rules:
- Configuration lives in `pyproject.toml` under `[tool.ruff]` — no `.flake8`, `setup.cfg`, or separate ruff.toml.
- `target-version` matches `requires-python` so `UP` rules upgrade syntax to what the project can actually use.
- Suppressions are per-line `# noqa: <RULE>` with a reason; file-wide and rule-wide ignores require justification in the config next to the ignore.
- Formatting is never debated in review: `ruff format` output is canonical.

**Why**: One fast tool with one config ends linter sprawl. The `UP` ruleset mechanically enforces the modern-syntax rules in `stack/python.md` §3.

---

## 3. Gates: Local and CI

**Rule**: Lint, format, and tests run the same way locally and in CI. CI is `uv sync --frozen` followed by the same three commands a developer runs.

```bash
# bin/check — the single local gate (run before committing)
#!/usr/bin/env bash
set -euo pipefail
uv run ruff check .
uv run ruff format . --check
uv run pytest
```

```yaml
# CI job steps (see stack/github-actions.md for the full workflow)
- run: uv sync --frozen
- run: uv run ruff check .
- run: uv run ruff format . --check
- run: uv run pytest
```

Optional pre-commit hook — keep it to fast, deterministic checks:

```yaml
# .pre-commit-config.yaml
repos:
  - repo: https://github.com/astral-sh/ruff-pre-commit
    rev: v0.5.0
    hooks:
      - id: ruff
        args: [--fix]
      - id: ruff-format
```

**Why**: When the local gate and CI run identical commands, a green local run predicts a green build. Divergent invocations produce "passes here, fails there" churn.

---

## Summary Checklist

- [ ] uv only: `uv venv`, `uv add`/`uv remove`, `uv run` — no bare pip, venv, or second package manager
- [ ] `pyproject.toml`, `uv.lock`, and `.python-version` committed; `.venv/` gitignored
- [ ] CI installs with `uv sync --frozen`
- [ ] ruff configured once in `pyproject.toml` (lint + format); no other linter/formatter
- [ ] `E/W/F/I/UP/B/SIM/C4` rulesets selected; suppressions are per-line with reasons
- [ ] Same check commands locally (`bin/check`) and in CI

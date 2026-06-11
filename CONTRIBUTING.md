# Contributing to Drydock

Drydock is the installable V2 successor to Prototyper. Development happens in this repository against
a typed specification and a strict source-precedence contract.

## Before you start

Read [DRYDOCK_DEVELOPMENT.md](DRYDOCK_DEVELOPMENT.md) in full. It defines the development
architecture, the V1-to-V2 migration map, source precedence, and the verification contract that the
current code cannot yet express through working commands. [AGENTS.md](AGENTS.md) summarizes the
operating rules; [docs/drydock.md](docs/drydock.md) is the authoritative product specification.

## Environment

```bash
uv venv
uv sync --extra dev          # or: uv pip install -e ".[dev]"
uv run pre-commit install    # install the git hooks
```

`python` is reached through the virtual environment (`.venv/bin/python`) or via `uv run`.

## Working agreements

- **Source precedence.** When the specification and V1 disagree, implement the specification. Record
  intentional incompatibilities in tests or documentation rather than silently reproducing V1.
- **Rigging mirror.** `Rigging/` is a governed mirror of Prototyper `RulesEngine/`. Do not edit,
  rename, or reorganize either tree. A rule change requires explicit authorization and must be
  applied identically to both trees. The `rigging-mirror` pre-commit hook guards this locally.
- **Architecture.** Business logic lives in importable `src/drydock/` modules. `bin/` contains
  launchers only. Keep the public interface under `drydock <verb> [<sub-verb>]`.
- **No API-key LLM providers.** Use the subscription-authenticated `claude`/`codex` CLI through the
  `drydock.llm` adapter. Tests must not spend credits or require network access.
- **No new frameworks** (Typer, Click, Rich, Pydantic, databases) without prior approval.
- **Exit codes.** `0` success, `1` operational failure, `2` usage error or deferred command.

## Quality gates

Every change must pass the same checks CI runs:

```bash
uv run ruff check src/ tests/ scripts/
uv run ruff format --check src/ tests/ scripts/
uv run mypy
uv run pytest --cov=drydock
```

Or run everything through nox:

```bash
uv run nox          # lint, type, tests
uv run nox -s build # wheel + sdist + embedded-Rigging verification
```

For packaging or Rigging changes, build the wheel and verify the affected command from an isolated
installation. Add focused unit tests and CLI contract tests for every implemented command, and
preserve working commands while replacing deferred stubs.

## Commits

- Write descriptive commit messages in the imperative mood.
- Keep commits scoped to one coherent capability.
- Update [CHANGELOG.md](CHANGELOG.md) under `## [Unreleased]` for user-visible changes.
- Update [README.md](README.md) when a command moves from deferred to working.

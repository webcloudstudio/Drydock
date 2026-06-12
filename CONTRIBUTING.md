# Contributing to Drydock

Drydock is the installable V2 successor to Prototyper. Development happens in this repository against
a Drydock Blueprint, its Typed Specification, and a strict source-precedence contract.

## Before you start

Read [AGENTS.md](AGENTS.md) in full. It defines the operating rules, development architecture,
source precedence, verification contract, and mandatory decision-capture process.
[docs/Drydock_Specification.md](docs/Drydock_Specification.md) is the sole authoritative Drydock
specification; [docs/SOUNDINGS.md](docs/SOUNDINGS.md) is the authoritative implementation
acceptance/readiness checklist.

## Environment

```bash
uv venv
uv sync --extra dev          # or: uv pip install -e ".[dev]"
bash bin/install_git_hooks.sh # install the repository's guarded Git hooks
```

`python` is reached through the virtual environment (`.venv/bin/python`) or via `uv run`.
Do not run `pre-commit install`; it replaces the outer guard that protects the authoritative
specification before pre-commit's unstaged-change handling begins.

## Working agreements

- **Source precedence.** When the Blueprint and V1 disagree, implement the Blueprint. Record
  intentional incompatibilities in tests or documentation rather than silently reproducing V1.
- **Specification approval.** Obtain Ed's approval before changing `docs/Drydock_Specification.md`;
  approved behavior changes and specification updates land together. Stage approved specification
  edits before committing any work; commits are blocked while the specification has unstaged edits.
- **Completion.** Update the matching `docs/SOUNDINGS.md` row and evidence before declaring a
  capability complete.
- **Ship's Log.** Record material decisions and milestones through `python bin/ships_log.py record`,
  then perform the required final capture review before completing the task.
- **Rigging.** `Rigging/` began as a one-time copy of Prototyper `RulesEngine/` and is now
  Drydock's own source of shared rules and templates. It evolves independently — there is no mirror
  to keep in sync. Prototyper is frozen, read-only V1 (defect fixes only); all rule/template changes
  go to `Rigging/`.
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

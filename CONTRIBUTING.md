# Contributing to Drydock

Drydock is an installable Python CLI for governed, Blueprint-driven software delivery. Development
happens in this repository against a Drydock Blueprint, its Typed Specification, and a strict
source-precedence contract.

## Before you start

Read [AGENTS.md](AGENTS.md) in full. It defines the operating rules, development architecture,
source precedence, verification contract, and mandatory decision-capture process.
[docs/Drydock_Specification.md](docs/Drydock_Specification.md) is the sole authoritative Drydock
specification.

## Environment

```bash
uv venv
uv sync --extra dev          # or: uv pip install -e ".[dev]"
```

`python` is reached through the virtual environment (`.venv/bin/python`) or via `uv run`.
Do not install automatic Git hooks in a working tree shared by multiple development sessions.
Run `uv run pre-commit run --all-files` explicitly when needed.

## Working agreements

- **Source precedence.** When the Blueprint and the implementation disagree, implement the
  Blueprint. Record intentional deviations in tests or documentation.
- **Specification approval.** Obtain the author's explicit approval before changing
  `docs/Drydock_Specification.md`; approved behavior changes and specification updates land together.
- **Concurrent sessions.** Before committing, preserve other writers' changes and commit only the
  active task. If Git state changed, reread affected files, resolve conflicts preserving both
  intents, and retry. Never restore, reset, delete, stage, or commit another writer's changes.
- **Completion.** Add or update focused tests and keep repository documentation truthful before
  declaring a capability complete.
- **Rigging.** `Rigging/` is Drydock's own source of shared rules and templates. All rule and
  template changes go to `Rigging/`.
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
uv run pytest --cov=drydock
```

Or run everything through nox:

```bash
uv run nox          # lint, tests
uv run nox -s build # wheel + sdist + embedded-Rigging verification
```

For packaging or Rigging changes, build the wheel and verify the affected command from an isolated
installation. Add focused unit tests and CLI contract tests for every implemented command, and
preserve working commands while replacing deferred stubs.

## Project-level UAT

`drydock uat [<Project>]` rebuilds known projects unattended under isolated timestamped run
directories. Fixtures live under `tests/uat/<Project>/`: `spec_1.md` drives the initial
init/import/analyze/plan/build lifecycle, and each later `spec_N.md` drives
`import --update` → `refit --sources` → incremental build. The selected model and provider apply
to the whole run.

Each run writes `uat/runs/<run-id>/SUMMARY.md`, `summary.json`, per-project `result.json`, and the
complete stdout/stderr of every child command. Reports include command and LLM elapsed time, input,
cached, fresh-input, and output tokens, build-pass counts, and the exit results from `score ac`,
`score build`, and `score release`. Scoring is advisory in UAT V1: score failures remain visible in
the report but do not override a successfully completed build lifecycle.

## Commits

- Write descriptive commit messages in the imperative mood.
- Keep commits scoped to one coherent capability.
- Update [CHANGELOG.md](CHANGELOG.md) under `## [Unreleased]` for user-visible changes.
- Update [README.md](README.md) when a command moves from deferred to working.

# AGENTS.md — Drydock

## Required First Action

**Always read [DRYDOCK_DEVELOPMENT.md](DRYDOCK_DEVELOPMENT.md) in full before planning, editing,
delegating, or constructing prompts.** Drydock is not yet fully built; that file supplies the
development architecture, V1-to-V2 migration map, source precedence, and verification contract that
the current code cannot yet express.

Every delegated agent prompt must include `DRYDOCK_DEVELOPMENT.md` or instruct the agent to read it
in full before beginning work.

Drydock is the installable V2 successor to Prototyper: a Python CLI that plans, builds, tests,
reviews, and evolves software from Typed Specifications. Development occurs in this repository.
Prototyper is a read-only V1 behavioral reference used to preserve proven workflows while replacing
its repository-bound shell interface with the Drydock command surface and package architecture.

## Required Context

The full product specification is [docs/drydock.md](docs/drydock.md). It is the source of truth for
intended V2 behavior, but do not load the entire document by default. Locate and read the sections
relevant to the requested command, workflow, contract, or artifact. Read the full specification only
for cross-cutting design decisions.

Context precedence:

1. `docs/drydock.md` — intended V2 product behavior and contracts.
2. Current Drydock code and tests — implemented behavior that must remain stable unless changed.
3. `DRYDOCK_DEVELOPMENT.md` — architecture and migration procedure.
4. Prototyper, resolved from `prototyper_directory` in `METADATA.md` — read-only V1 implementation
   evidence. In this checkout it resolves to `/mnt/c/Users/barlo/projects/Prototyper`.

When these conflict, implement the V2 specification. Record intentional incompatibilities in code
tests or documentation rather than silently reproducing V1 behavior.

## Development Rules

- Prototyper may always be read for development reference. Do not modify any Prototyper file unless
  Ed explicitly authorizes that specific change.
- Port one coherent capability at a time. Extract the behavior; do not mechanically copy shell code.
- Keep the public interface under `drydock <verb> [<sub-verb>]`.
- Put business logic in importable `src/drydock/` modules. `bin/` contains launchers only.
- Add focused unit tests and CLI contract tests for every implemented command.
- Preserve working commands while replacing deferred command stubs.
- When delegating work or constructing an agent prompt, include the V2 mission, context precedence,
  relevant specification sections, and applicable V1 reference files. Do not inject the full
  specification unless the task is cross-cutting.
- Test both source-tree and installed-wheel behavior when a change touches Rigging or packaging.
- Never call an API-key-backed LLM provider. Use the subscription-authenticated `claude` CLI through
  a dedicated adapter.
- Do not add Typer, Click, Rich, Pydantic, databases, or application frameworks without approval.
- Exit codes: `0` success, `1` operational failure, `2` usage error or deferred command.

## Project Layout

```text
Drydock/
  src/drydock/       Python package and all command behavior
  Rigging/           Human-editable rules, templates, stack guidance, and branding
  tests/             Pytest unit, CLI, integration, and parity tests
  bin/               Source-tree launchers; no business logic
  prompts/           Versioned LLM prompt contracts used by commands
  docs/drydock.md    Full V2 product specification
  dist/              Build artifacts; not committed
```

`Rigging/` is authoritative in the source tree. The wheel contains its installed copy at
`drydock/resources/Rigging/`, synchronized by Hatchling `force-include`. Both resolution paths must
work; see `src/drydock/paths.py`.

## Development Commands

```bash
uv pip install -e ".[dev]"        # install editable package
python -m pytest                  # run tests
bash bin/test.sh                  # canonical test entry point
ruff check src/ tests/            # lint
ruff format --check src/ tests/   # verify formatting
python -m hatchling build         # build wheel and sdist
```

Before completing a capability, run the narrowest focused tests, then the full test suite and lint.
For packaging or Rigging changes, build the wheel and verify the affected command from an isolated
installation.

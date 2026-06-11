# AGENTS.md — Drydock

## Required First Action

**Always read [DRYDOCK_DEVELOPMENT.md](DRYDOCK_DEVELOPMENT.md) in full before planning, editing,
delegating, or constructing prompts.** Drydock is not yet fully built; that file supplies the
development architecture, V1-to-V2 migration map, source precedence, and verification contract that
the current code cannot yet express.

Every delegated agent prompt must include `DRYDOCK_DEVELOPMENT.md` or instruct the agent to read it
in full before beginning work.

Drydock is the installable V2 successor to Prototyper: a Python CLI that plans, builds, tests,
reviews, and evolves software from Drydock Blueprints expressed as Typed Specifications.
Development occurs in this repository.
Prototyper is a read-only V1 behavioral reference used to preserve proven workflows while replacing
its repository-bound shell interface with the Drydock command surface and package architecture.

## Required Context

The sole authoritative Drydock product specification is
[docs/Drydock_Specification.md](docs/Drydock_Specification.md). It is the source of truth for
intended V2 behavior. Locate and read the sections relevant to the requested command, workflow,
contract, or artifact; read the full document only for cross-cutting decisions. Any behavior change
must update this document in the same change, and an agent must obtain Ed's approval before changing
the specification.

Context precedence:

1. `docs/Drydock_Specification.md` — sole intended V2 product behavior and contract authority.
2. `docs/SOUNDINGS.md` — authoritative implementation acceptance/readiness checklist.
3. Current Drydock code and tests — implemented behavior that must remain stable unless changed.
4. `DRYDOCK_DEVELOPMENT.md` — architecture and migration procedure.
5. Prototyper, resolved from `prototyper_directory` in `METADATA.md` — read-only V1 implementation
   evidence. In this checkout it resolves to `/mnt/c/Users/barlo/projects/Prototyper`.

When these conflict, implement the approved Drydock specification. Record intentional
incompatibilities in code tests or documentation rather than silently reproducing V1 behavior.

### GitHub Spec Kit — external baseline

Spec Kit is a separate, single-file specification language and SDD toolchain. Drydock is a
**superset** of it: every Spec Kit concept maps to a Drydock equivalent, and Drydock adds
capabilities with no Spec Kit counterpart (see `docs/Drydock_Specification.md` § "Spec Kit
Compatibility"). Spec Kit is the canonical reference for `drydock import --format speckit` and the
generated compatibility views. It is an external reference, not a Drydock source of truth.

- GitHub Spec Kit — https://github.com/github/spec-kit
- Spec Kit documentation — https://github.github.com/spec-kit/

## Development Rules

- Prototyper may always be read for development reference. Do not modify any Prototyper file unless
  Ed explicitly authorizes that specific change.
- Drydock `Rigging/` is a **one-time copy** of Prototyper `RulesEngine/`, not a live mirror.
  Prototyper is frozen V1 and read-only; Drydock is V2 and is expected to diverge. There is no
  identity check to maintain and no requirement to apply Rigging changes back to Prototyper. Drydock
  commands (e.g. `drydock rigging compact`) may read and write `Rigging/` derivatives freely.
- Port one coherent capability at a time. Extract the behavior; do not mechanically copy shell code.
- Keep the public interface under `drydock <verb> [<sub-verb>]`.
- Put business logic in importable `src/drydock/` modules. `bin/` contains launchers only.
- Add focused unit tests and CLI contract tests for every implemented command.
- Preserve working commands while replacing deferred command stubs.
- Update `docs/SOUNDINGS.md` when a capability's implementation or verification state changes.
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
  docs/              Authoritative specification, Soundings, Sea Trials, and owned documentation
  dist/              Build artifacts; not committed
```

`Rigging/` began as a one-time copy of Prototyper `RulesEngine/` and is now V2's own source of
shared business/build rules; it evolves independently of Prototyper. The wheel contains an installed
copy at `drydock/resources/Rigging/`, synchronized by Hatchling `force-include`. Versioned task
prompts live in `prompts/` and are packaged the same way to `drydock/resources/prompts/`. Both
source-tree and installed resolution paths must work; see `src/drydock/paths.py`.

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

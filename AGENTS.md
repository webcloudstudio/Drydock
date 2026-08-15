# AGENTS.md — Drydock

Drydock is a specification-driven software design and delivery methodology implemented as an installable Python CLI. It plans, builds, tests, reviews, and evolves software from specifications expressed with typed front matter known as Blueprints.

## Master User Facing Documentation at `docs/Drydock_Specification.md`

IMPORTANT: NO LLM IS AUTHORIZED TO WRITE ANYTHING TO docs/Drydock_Specification.md unless
specifically authorized. Each block edit must be approved individually. There are no exceptions.

The following rules apply only to that document.

**Editing protocol** — Obtain the author's explicit approval before any edits.

**Content** — user-facing normative statements of intended behavior, scope, and contracts. It is
syntactically precise and does not explain how the system works. No rationale, reasoning, open
questions, status, history, alternatives, or hedging ("we could / should probably / might / plan
to").

**Voice** — present-tense, declarative, third-person ("`drydock build` executes the Manifest."). No future, no conditional, no first person.

**Command-entry template** — every command section uses this exact structure and order, with no
added or reordered sections. One section per command; duplicate or overlapping command headings are violations to fix.
1. CLI syntax (synopsis)
2. Behavior description
3. Input files
4. Output files
5. Exit codes

## Git Behavior
At the completion of any operation, all files should be committed in git even if you did not touch it. Other
processes may be working on files so commit the latest copy of the code each run.

Notify and stop on any merge issues.

## Project Layout

```text
Drydock/
  src/drydock/       Python package and all command behavior
  Rigging/           Human-editable rules, templates, stack guidance, and branding
  prompts/           Versioned LLM prompt contracts used by commands
  tests/             Pytest unit, CLI, and integration tests
  bin/               Source-tree launchers; no business logic
  docs/              Authoritative specification and documentation
  logs/              Drydock logs, prompts, and full run history
  notes/             Refit-skill working notes; injected by that skill only, not read by code
  uat/               UAT runs; used only by `drydock uat`
  dist/              Build artifacts; not committed
  targets/<PROJECT>  Generated Target workspace; see Data Locations
```

Shell and PowerShell files in `bin/` only locate the environment and invoke the package entry
point.

`Rigging/` is Drydock's source of shared business rules, templates, stack guidance, and branding.
`Rigging/` and `prompts/` are packaged into the wheel via Hatchling `force-include` at
`drydock/resources/Rigging/` and `drydock/resources/prompts/`, and resolved through
`src/drydock/paths.py`. Both source-tree and installed resolution paths must work. The packaged
copies under `drydock/resources/` are build-generated and are not independently editable sources.

### Boundaries

| Boundary | Responsibility |
|---|---|
| `src/drydock/cli.py` | Parse commands, dispatch to application functions, translate errors to exit codes |
| `src/drydock/<capability>.py` | Importable application behavior; no argument parsing |
| `src/drydock/config.py` | User-scoped configuration and configured root resolution |
| `src/drydock/paths.py` | Source-tree and installed-resource resolution |
| `src/drydock/llm.py` | Single adapter for subscription-authenticated CLI agent execution |
| `Rigging/` | Drydock's own shared governed inputs |
| `prompts/` | Versioned task prompts used by LLM-assisted commands |
| `tests/` | Unit, CLI contract, and integration tests |

### Data Locations

| Data | Location |
|---|---|
| Drydock authoritative product specification | `docs/Drydock_Specification.md` |
| Target Blueprint files | `$DRYDOCK_WORKSPACE/targets/<Target>/blueprint/` |
| Imported User Sources (read-only) | `$DRYDOCK_WORKSPACE/targets/<Target>/blueprint/sources/` |
| `METADATA.md`, `MANIFEST.md`, `BUILD_COMPASS.md`, `SCORECARD.md`, Sea Trials, Soundings, evidence, logs, QuarterDeck state | `$DRYDOCK_WORKSPACE/targets/<Target>/` |
| Drydock distributable rules and templates | `Rigging/` and the packaged resource copy |
| User configuration | User-scoped configuration managed by `drydock config` |

Commands must resolve `<Target>` under `$DRYDOCK_WORKSPACE/targets/` and the Blueprint as that
Target's `blueprint/` subtree. They must not depend on the caller being in the Drydock
repository.

`targets/` and the Build `<TARGET>` directory are the temporary workspace managed by the build
process. Read them freely; do not edit them without a specific instruction. Hand edits are
reserved for avoiding an unneeded rerun. Fix defects in `src/drydock/` with a test, never by
patching generated Target data.

## Development Rules

- Implement one coherent capability at a time.
- Keep the public interface under `drydock <verb> [<sub-verb>]`.
- Add focused unit tests and CLI contract tests for every implemented command.
- Multiple contributors may edit this directory concurrently. Before committing, inspect the
  current diff and preserve changes made by other writers. Never stage or commit changes outside
  the active task.
- When constructing an agent prompt, include only the relevant specification sections. Do not inject the full specification unless the task is cross-cutting.
- Test both source-tree and installed-wheel behavior when a change touches Rigging or packaging.
- Never call an API-key-backed LLM provider. Use a subscription-authenticated CLI agent. Which
  agent and model is configuration, not policy — selected by `--llm-provider` / `--model` or the
  `LLM_PROVIDER` / `DRYDOCK_MODEL` environment and config settings. Do not treat any one vendor as
  required.
- Target Python `>=3.11`. Do not add Typer, Click, Rich, Pydantic, databases, or application
  frameworks without approval.
- Exit codes: `0` success, `1` operational failure, `2` usage error or deferred command.

## Implementing a Capability

Implement commands as vertical slices:

1. Define command syntax, inputs, outputs, side effects, and exit codes from the specification.
2. Separate deterministic logic from filesystem operations and LLM execution.
3. Implement deterministic logic in an importable module.
4. Wire the module into `cli.py`.
5. Replace any deferred-command stub test with behavior tests, and add integration tests for
   filesystem changes and failure handling.
6. Update `README.md` when a command moves from deferred to working.
7. Update repository guidance and tests so implementation status is represented truthfully.

Preserve clear, separate contracts for path resolution, plan parsing, prompt assembly, process
execution, and evidence; do not collapse them into a single module.

### Verification Contract

| Verification | Requirement |
|---|---|
| Unit tests | Deterministic logic, parsing, state transitions, and error cases |
| CLI tests | Syntax, help, output contract, and exit codes |
| Integration tests | Real temporary Blueprint and Target directories |
| Regression tests | Existing working commands remain working |
| Lint | `ruff check src/ tests/` |
| Full suite | `python -m pytest` |
| Package test | Required when changing Rigging resolution, package data, or launch behavior |
| Implementation evidence | Matching tests and user-facing repository documentation updated truthfully |

LLM-assisted commands must isolate process execution behind an adapter so tests can use a fake
runner. Tests must never spend API credits or require network access.

### Development Commands

```bash
uv pip install -e ".[dev]"        # install editable package
python -m pytest                  # run tests
bash bin/test.sh                  # canonical test entry point
ruff check src/ tests/            # lint
ruff format --check src/ tests/   # verify formatting
python -m hatchling build         # build wheel and sdist
```

## LLM-Assisted Command Pattern

Commands that call an LLM follow one shape, first established by `drydock rigging compact`:

1. **Load** the prompt with `prompts.load_prompt("<command>_<subcommand>")`. The loader validates
   frontmatter and exposes metadata including `model`.
2. **Assemble** the final prompt deterministically: the prompt body plus an injected job block
   (source paths, dates, per-item objective, fenced source content). Keep assembly in the module so
   it is unit-testable without a process.
3. **Execute** through `llm.run_prompt(...)`, which persists reproducible evidence
   (`logs/llm.jsonl`, per-run prompt/raw/output/stderr files). Pass an `on_text`/`on_item`
   callback for console progress.
4. **Write outputs in the module**, not from the model. The model emits text; the module
   post-processes and writes files.
5. **Inject the runner.** The capability function takes a `runner` parameter defaulting to
   `run_prompt`, resolved at call time so tests can substitute a fake.

### Prompt Contract Standard

- **Naming:** `prompts/<command>_<subcommand>[_<modifier>].md`, lowercase.
  Example: `drydock rigging compact` → `rigging_compact.md`.
- **Frontmatter:** a leading `---` YAML block with required `name`, `description`, `version`,
  `intent` and optional `command`, `model`, `output`. Parsed by `prompts.load_prompt` (no YAML
  dependency).
- **Registry:** `prompts/prompts.json` maps prompts to their target documentation and is read by
  `prompt_headers.py`. Update it when adding or renaming a prompt.

# Changelog

`CHANGELOG.md` is the maintained high-level project history and a source for technically focused
developer writing. Write for an experienced reader who wants to know what changed, why it matters
to the system, and how the design or operator workflow now differs. Do not simplify into marketing
language.

Record work that materially changes one or more of the following:

- product behavior, command contracts, file formats, schemas, or public interfaces;
- architecture, execution flow, planning or verification policy, or other governing design;
- reliability, safety, determinism, performance, observability, or recovery behavior;
- developer, operator, installation, packaging, or integration workflow;
- a release, milestone, public demonstration, paper, or other project event that materially
  changes what users or contributors can do or understand.

Date each entry with the date the change entered repository history. Describe the resulting
capability, not the commit sequence, and name the affected command, artifact, interface, or
subsystem. Preserve precise names, flags, file names, data formats, state names, and failure
behavior. Group related commits into one entry when they deliver one capability; split them when
their user impact or technical theme differs. Identify a material non-code deliverable as
documentation, research, presentation, release, or publishing work.

Do not record individual commits, routine refactors, formatting, test-only churn, generated-file
updates, intermediate debugging, or implementation mechanics that do not change behavior. Verify
the diff, tests, and release metadata rather than inferring behavior from a commit subject.

Use the Keep-a-Changelog headings (`Added`, `Changed`, `Fixed`, `Removed`) without creating
duplicate category headings, and keep entries reverse chronological within a section. Keep
unreleased work under `## [Unreleased]`; add a version heading, date, and shipped capabilities when
a release is cut. Do not leave a shipped release represented only as `[Unreleased]`, and do not
describe unreleased work as shipped. Releases are cut with `publish_pypi.sh` after the version is
updated manually.

# AGENTS.md — Drydock

Drydock is a specification-driven software design and delivery methodology implemented as an
installable Python CLI. It plans, builds, tests, reviews, and evolves software from specifications
expressed with typed front matter known as Blueprints.

Beta software: no legacy contract. Changes need not be backwards compatible.

## `docs/Drydock_Specification.md` — Master User-Facing Documentation

IMPORTANT: NO LLM IS AUTHORIZED TO WRITE ANYTHING TO `docs/Drydock_Specification.md` unless
specifically authorized. Each block edit must be approved individually. There are no exceptions.

Rules below apply only to that document.

- **Content** — user-facing normative statements of behavior, scope, and contracts. Syntactically
  precise; does not explain how the system works. No rationale, open questions, status, history,
  alternatives, or hedging.
- **Voice** — present-tense, declarative, third-person ("`drydock build` executes the Manifest.").
  No future, conditional, or first person.
- **Command entries** — one section per command, in this exact order, nothing added or reordered:
  CLI syntax, behavior description, input files, output files, exit codes. Duplicate or
  overlapping command headings are violations to fix.

## Git Behavior

Commit all files at the completion of any operation, including files you did not touch — other
processes may be writing concurrently. Notify and stop on any merge issue.

## UAT Evidence

`uat/` is published benchmark evidence. Every `uat/<Kit>/` is a separate git history whose commits
and `SHA256SUMS` attest to completed builds. Any write under it invalidates that evidence.

- No LLM runs `drydock uat` in any form: no run, resume, `--run`, `--stage`, `--from-step`,
  `--report`, or diagnostic invocation. Ed alone runs UAT.
- No LLM writes, stages, commits, deletes, or runs git commands under `uat/`, including clearing
  lock files. Read-only inspection occurs only when Ed requests it.
- A test, script, or command that reaches `uat/` is a defect. Report it and stop; do not run it
  to find out.

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
  design/            Per-command behavior rules and `/ddk-think` working notes (see Design)
  uat/               Published UAT evidence; written only by Ed's `drydock uat` runs (see UAT Evidence)
  dist/              Build artifacts; not committed
  targets/<PROJECT>  Generated Target workspace; see Data Locations
```

`Rigging/` and `prompts/` are packaged into the wheel via Hatchling `force-include` at
`drydock/resources/`, resolved through `src/drydock/paths.py`. Both source-tree and installed
resolution must work; the packaged copies are build-generated, not editable sources.

### Boundaries

| Boundary | Responsibility |
|---|---|
| `src/drydock/cli.py` | Parse commands, dispatch to application functions, translate errors to exit codes |
| `src/drydock/<capability>.py` | Importable application behavior; no argument parsing |
| `src/drydock/config.py` | User-scoped configuration and configured root resolution |
| `src/drydock/paths.py` | Source-tree and installed-resource resolution |
| `src/drydock/llm.py` | Single adapter for CLI agent execution across all supported providers |
| `bin/` | Locate the environment and invoke the package entry point; nothing else |
| `Rigging/` | Drydock's own shared governed inputs |
| `prompts/` | Versioned task prompts used by LLM-assisted commands |
| `tests/` | Unit, CLI contract, and integration tests |

### Data Locations

| Data | Location |
|---|---|
| Authoritative product specification | `docs/Drydock_Specification.md` |
| Target Blueprint files | `$DRYDOCK_WORKSPACE/targets/<Target>/blueprint/` |
| Imported User Sources (read-only) | `$DRYDOCK_WORKSPACE/targets/<Target>/blueprint/sources/` |
| `METADATA.md`, `MANIFEST.md`, `BUILD_COMPASS.md`, `SCORECARD.md`, Sea Trials, Soundings, evidence, logs, QuarterDeck state | `$DRYDOCK_WORKSPACE/targets/<Target>/` |
| Distributable rules and templates | `Rigging/` and the packaged resource copy |
| User configuration | Managed by `drydock config` |

Commands resolve `<Target>` under `$DRYDOCK_WORKSPACE/targets/` and the Blueprint as that Target's
`blueprint/` subtree. They must not depend on the caller being in the Drydock repository.

`targets/` is the build process's temporary workspace. Read freely; edit only on specific
instruction, and only to avoid an unneeded rerun. Fix defects in `src/drydock/` with a test, never
by patching generated Target data.

## Development Rules

- Implement one coherent capability at a time, as a vertical slice: derive syntax, inputs,
  outputs, side effects, and exit codes from the specification; separate deterministic logic from
  filesystem and LLM execution; implement it in an importable module; wire it into `cli.py`;
  replace any deferred-command stub test with behavior and integration tests; update `README.md`
  and repository guidance so implementation status is truthful.
- Keep separate contracts for path resolution, plan parsing, prompt assembly, process execution,
  and evidence. Do not collapse them into one module.
- Keep the public interface under `drydock <verb> [<sub-verb>]`.
- Exit codes: `0` success, `1` operational failure, `2` usage error or deferred command.
- Target Python `>=3.11`. Do not add Typer, Click, Rich, Pydantic, databases, or application
  frameworks without approval.
- Provider and model are configuration, not policy — `--llm-provider` / `--model`, or
  `LLM_PROVIDER` / `DRYDOCK_MODEL`. No vendor is required. Execution runs through a CLI agent
  invoked as a subprocess, never through an in-process provider SDK.
- Prefer subscription-authenticated providers. A metered, API-key-authenticated provider is
  permitted only where this document names it: `gemini`. Adding another requires Ed's explicit
  authorization and an amendment here. A provider that bills per token declares that cost in
  `drydock config`, and its key is read from the environment, never stored in the repository.
- When constructing an agent prompt, include only the relevant specification sections. Inject the
  full specification only for cross-cutting tasks.
- Multiple contributors edit this directory concurrently. Inspect the current diff before
  committing and preserve other writers' changes. Never stage changes outside the active task.

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
| Implementation evidence | Matching tests and user-facing documentation updated truthfully |

LLM-assisted commands isolate process execution behind an adapter so tests use a fake runner. Tests
never spend API credits or require network access.

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

One shape, first established by `drydock rigging compact`:

1. **Load** the prompt with `prompts.load_prompt("<command>_<subcommand>")`; the loader validates
   frontmatter and exposes metadata including `model`.
2. **Assemble** the prompt deterministically in the module (body plus an injected job block of
   source paths, dates, per-item objective, fenced source content) so it is unit-testable.
3. **Execute** through `llm.run_prompt(...)`, which persists evidence (`logs/llm.jsonl`, per-run
   prompt/raw/output/stderr). Pass `on_text`/`on_item` for console progress.
4. **Write outputs in the module**, not from the model. The model emits text; the module
   post-processes and writes files.
5. **Inject the runner** — a `runner` parameter defaulting to `run_prompt`, resolved at call time.

### Prompt Contract Standard

- **Naming:** `prompts/<command>_<subcommand>[_<modifier>].md`, lowercase
  (`drydock rigging compact` → `rigging_compact.md`).
- **Frontmatter:** leading `---` block, required `name`, `description`, `version`, `intent`;
  optional `command`, `model`, `output`. Parsed by `prompts.load_prompt` (no YAML dependency).
- **Registry:** `prompts/prompts.json` maps prompts to their target documentation and is read by
  `prompt_headers.py`. Update it when adding or renaming a prompt.

## Design

`design/` records how each command behaves and why, so the next session does not re-derive it.
`design/README.md` indexes every command and topic to its file, modules, prompts, and tests.

- `design/commands/<command>.md` — one file per top-level `drydock` command.
- `design/topics/<topic>.md` — one file per cross-cutting subject governing several commands.

**Precedence:** code > `design/` > `docs/Drydock_Specification.md`. A design file describes the
code as it runs. Where the specification says otherwise, the file records the difference under
`### Spec divergence`; the specification is not edited to match.

**Before changing a command's module, prompt, or tests, read its design file** and the topics it
links. Update `## Behavior` in the same commit that changes behavior.

Each file carries a metadata table, then these sections in order:

| Section | Owner | Content |
|---|---|---|
| `## Behavior` | Agent — write and keep current without asking | Purpose, Rules, Mechanism, Exit codes, Spec divergence |
| `## Decisions` | `/ddk-think` and its authors | Flagged decisions not yet fully implemented or applied |
| `## Open Questions` | Authors; agents append | Unresolved questions, including conflicts found between code, design, and specification |
| `## Working Notes` | `/ddk-think` | Scratchpad; prune once absorbed into Behavior or Decisions |

Each rule in `### Rules` is dated and states what it costs when broken. `## Behavior` records settled
behavior only; proposals stay in `## Decisions` and `## Open Questions`. Propose changes to
author-owned sections in chat rather than rewriting them; appending a question is permitted. A rule
that governs one command lives in its design file and never in this file. `notes/` is a private,
untracked scratch directory; nothing reads it.

## Changelog

`CHANGELOG.md` is the maintained project history, written for an experienced reader who wants to
know what changed, why it matters, and how the design or operator workflow now differs. Technical,
not marketing.

Record changes to: product behavior, command contracts, file formats, schemas, or public
interfaces; architecture, execution flow, or planning and verification policy; reliability, safety,
determinism, performance, observability, or recovery; developer, operator, installation, packaging,
or integration workflow; releases, milestones, papers, and other events that change what users can
do. Identify material non-code deliverables as documentation, research, presentation, release, or
publishing work.

Do not record individual commits, routine refactors, formatting, test-only churn, generated-file
updates, or implementation mechanics that do not change behavior.

- Date each entry with the date the change entered repository history.
- Describe the resulting capability, not the commit sequence, and name the affected command,
  artifact, interface, or subsystem. Preserve precise names, flags, file names, formats, state
  names, and failure behavior.
- Group related commits delivering one capability; split them when user impact or theme differs.
- Verify the diff, tests, and release metadata; do not infer behavior from a commit subject.
- Use Keep-a-Changelog headings (`Added`, `Changed`, `Fixed`, `Removed`) with no duplicates, newest
  first within a section. Unreleased work stays under `## [Unreleased]`; a release gets a version
  heading and date. Never leave a shipped release as `[Unreleased]` or describe unreleased work as
  shipped. Releases are cut with `publish_pypi.sh` after the version is updated manually.

## Voice and Responses

Answers are terse and technical, ideally one screen. Long answers are not read fully, which lets
errors into the code. Omit no material information; explain nothing the reader already knows.

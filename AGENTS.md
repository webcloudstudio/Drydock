# AGENTS.md — Drydock

Drydock is a specification-driven software design and delivery methodology implemented as an
installable Python CLI. It plans, builds, tests, reviews, and evolves software from Blueprints
expressed as Typed Specifications.

## Authority: `docs/Drydock_Specification.md`

`docs/Drydock_Specification.md` is the sole authoritative product specification and the
target architecture. It defines intended behavior, scope, and contracts. Treat it as canonical.

**Editing protocol** — Obtain the author's explicit approval before any edits.

**Content** — normative statements of intended behavior only. No rationale, reasoning, open
questions, status, history, alternatives, or hedging ("we could / should probably / might /
plan to"). Reasoning, questions, and options belong in `docs/notes_<command>.md`; the
specification is the conclusion, never the deliberation. Never alter already-specified syntax
or behavior. If the specification diverges from implemented behavior, surface the conflict and
let the author decide.

**Voice** — present-tense, declarative, third-person ("`drydock build` executes the
Manifest."). No future, no conditional, no first person.

**Command-entry template** — every command section uses this exact structure and order, with no
added or reordered sections:
1. CLI syntax (synopsis)
2. Behavior description
3. Input files
4. Output files
5. Exit codes

One section per command; duplicate or overlapping command headings are violations to fix.

**Workspace Layout** reflects the current on-disk file set. The Blueprint file inventory states
each file's purpose and whether it is human-editable.

At the completion of any edits, the file should be committed in git.

## Project Layout

```text
Drydock/
  src/drydock/       Python package and all command behavior
  Rigging/           Human-editable rules, templates, stack guidance, and branding
  tests/             Pytest unit, CLI, and integration tests
  bin/               Source-tree launchers; no business logic
  prompts/           Versioned LLM prompt contracts used by commands
  docs/              Authoritative specification, Soundings, Sea Trials, and owned documentation
  dist/              Build artifacts; not committed
```

Business logic belongs in importable `src/drydock/` modules. Shell and PowerShell files in `bin/`
only locate the environment and invoke the package entry point.

`Rigging/` is Drydock's source of shared business rules, templates, stack guidance, and branding.
The wheel contains an installed copy at `drydock/resources/Rigging/` via Hatchling `force-include`.
Versioned prompts in `prompts/` are packaged the same way. Both source-tree and installed resolution
paths must work; see `src/drydock/paths.py`. The packaged copies under `drydock/resources/` are
build-generated and are not independently editable sources.

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
| Drydock implementation acceptance checklist | `docs/SOUNDINGS.md` |
| Target Blueprint files | `$DRYDOCK_WORKSPACE/targets/<Target>/blueprint/` |
| `METADATA.md`, `MANIFEST.md`, `BUILD_COMPASS.md`, `SCORECARD.md`, Sea Trials, Soundings, evidence, logs, QuarterDeck state | `$DRYDOCK_WORKSPACE/targets/<Target>/` |
| Drydock distributable rules and templates | `Rigging/` and the packaged resource copy |
| User configuration | User-scoped configuration managed by `drydock config` |

Commands must resolve `<Target>` under `$DRYDOCK_WORKSPACE/targets/` and the Blueprint as that
Target's `blueprint/` subtree. They must not depend on the caller being in the Drydock
repository.

## Development Rules

- Implement one coherent capability at a time. Keep business logic in importable modules; do not
  introduce shell-only coupling.
- Keep the public interface under `drydock <verb> [<sub-verb>]`.
- Put business logic in importable `src/drydock/` modules. `bin/` contains launchers only.
- Add focused unit tests and CLI contract tests for every implemented command.
- Update `docs/SOUNDINGS.md` when a capability's implementation or verification state changes.
- Multiple contributors may edit this directory concurrently. Before committing, inspect the
  current diff and preserve changes made by other writers. Never stage or commit changes outside
  the active task.
- Follow the Ship's Log process: record material decisions and milestones immediately, then review
  again before committing.
- When constructing an agent prompt, include only the relevant specification sections. Do not
  inject the full specification unless the task is cross-cutting.
- Test both source-tree and installed-wheel behavior when a change touches Rigging or packaging.
- Never call an API-key-backed LLM provider. Use the subscription-authenticated `claude` CLI.
- Do not add Typer, Click, Rich, Pydantic, databases, or application frameworks without approval.
- Exit codes: `0` success, `1` operational failure, `2` usage error or deferred command.

## Implementing a Capability

Implement commands as vertical slices:

1. Define command syntax, inputs, outputs, side effects, and exit codes from the specification.
2. Separate deterministic logic from filesystem operations and LLM execution.
3. Implement deterministic logic in an importable module.
4. Wire the module into `cli.py`.
5. Replace the matching deferred-command stub test with behavior tests.
6. Add integration tests for filesystem changes and failure handling.
7. Update `README.md` when a command moves from deferred to working.
8. Update `docs/SOUNDINGS.md` with final state and verification evidence.

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
| Soundings | Matching row updated to the truthful state with concrete evidence |

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
   (`logs/executions.jsonl`, per-run prompt/raw/output/stderr files). Pass an `on_text`/`on_item`
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

Prompts are packaged via `force-include` to `drydock/resources/prompts/` and resolved by
`paths.get_prompts_root()`; both source-tree and installed paths must work.

## Soundings

Each command or capability has one row in `docs/SOUNDINGS.md`. States:

| State | Meaning |
|---|---|
| `NOT STARTED` | No public command or implementation contract exists |
| `STUBBED` | Command surface exists and returns the tested deferred response |
| `IMPLEMENTED` | Real behavior exists but required acceptance verification is incomplete |
| `DONE` | Approved behavior is implemented and all required verification passes |

Do not mark `DONE` based only on code presence. Record test names and evidence. When behavior
regresses or the specification changes, move the row back to the truthful state.

## Build Order

`docs/SOUNDINGS.md` is the authoritative record of what is working, stubbed, or implemented.
Preferred implementation order:

1. Command surface and shared path/process contracts
2. Planning Session approval, adaptive decomposition, and work grouping
3. Evidence contracts and `drydock build`
4. QuarterDeck review reconciliation
5. `refit`, `analyze`, and score
6. Rigging update, verification, and compaction
7. Documentation workflows
8. Source and Spec Kit import adapters

This is guidance, not authority. A user-requested capability can be implemented earlier when its
dependencies are satisfied.

## Ship's Log

The Ship's Log records material product decisions and delivery milestones as structured,
append-only events. The only canonical artifact is `logs/ships_log.jsonl`. Never create or
maintain a Markdown Ship's Log.

**When to record.** Record an event for:

- an approved specification or product-behavior change
- a feature addition, removal, or material scope change
- an architecture, persistence, interface, governance, or development-process decision
- a meaningful completed delivery milestone
- a reversal or replacement of an earlier recorded decision

Do not record routine file edits, implementation mechanics, commits, test runs, or minor refactors.
If no event qualifies, report that the final review found no material event. Do not add a
placeholder record.

**When to evaluate.** Every agent must evaluate Ship's Log capture: (1) immediately after making or
receiving approval for a material decision or milestone; (2) again before committing, using the
completed diff to catch anything missed during implementation.

**Recording.**

```bash
python bin/ships_log.py record \
  --event-type decision \
  --title "Concise decision title" \
  --summary "What changed or was decided." \
  --rationale "Why this choice was made." \
  --source-type agent \
  --source-command "task or workflow" \
  --source-provider codex \
  --scope "affected area" \
  --alternative "Rejected option::Reason it was rejected" \
  --evidence "path or durable evidence" \
  --tag "classification"
```

Use `--event-type milestone` for delivery milestones. Repeat `--scope`, `--alternative`,
`--evidence`, `--supersedes`, and `--tag` as needed.

Classification tags: `open-item` (material unresolved question), `deferred-item` (accepted but
postponed), `accepted-risk` (known risk explicitly accepted).

To reverse an earlier decision, append a new event with `--supersedes <event_id>`. Never rewrite
or delete an existing record.

Validate the ledger when changing its process, schema, or viewer:

```bash
python bin/ships_log.py audit
```

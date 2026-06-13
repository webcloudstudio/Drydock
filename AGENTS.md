# AGENTS.md — Drydock

Drydock is the installable V2 successor to Prototyper: a Python CLI that plans, builds, tests,
reviews, and evolves software from Drydock Blueprints expressed as Typed Specifications. Development
occurs in this repository.

Prototyper is a read-only V1 behavioral reference. It preserves proven workflows while Drydock
replaces its repository-bound shell interface with a coherent command surface and an installable
package architecture. Prototyper is not enhanced during the migration; it is a source of regression
cases only.

## Source Precedence And Authority

`docs/Drydock_Specification.md` is the sole authoritative product specification — a crafted
definition of the future ideal state, including scope and contracts. It is not a place for status or
deprecation notes. Agents must obtain Ed's approval before changing it; once approved, behavior and
specification change together, and the specification must never knowingly describe stale behavior.

Context precedence, highest first:

1. `docs/Drydock_Specification.md` — intended V2 product behavior and contract authority.
2. `docs/SOUNDINGS.md` — implementation acceptance/readiness checklist (state and evidence).
3. Current `src/drydock/` and `tests/` — implemented behavior and regression contract; stable unless
   intentionally changed.
4. This document — development architecture, migration method, and the V1 reference map.
5. Prototyper, resolved from `prototyper_directory` in `METADATA.md` — read-only V1 evidence. In this
   checkout it resolves to `/mnt/c/Users/barlo/projects/Prototyper`.

When these conflict, implement the approved specification. If the specification is silent, keep
proven V1 behavior unless it conflicts with Drydock's package architecture or command contracts.
Record intentional incompatibilities in tests or documentation rather than silently reproducing V1.

### GitHub Spec Kit — external baseline

Spec Kit is a separate, single-file specification language and SDD toolchain. Drydock is a
**superset** of it: every Spec Kit concept maps to a Drydock equivalent, and Drydock adds
capabilities with no Spec Kit counterpart (see `docs/Drydock_Specification.md` § "Spec Kit
Compatibility"). Spec Kit is the canonical reference for `drydock import --format speckit` and the
generated compatibility views. It is an external reference, not a Drydock source of truth.

- GitHub Spec Kit — https://github.com/github/spec-kit
- Spec Kit documentation — https://github.github.com/spec-kit/

## Development Rules

- Prototyper may always be read for reference. Never modify a Prototyper file unless Ed explicitly
  authorizes that specific change, and never write to Prototyper as a side effect of development or
  tests.
- Never make Drydock runtime behavior depend on Prototyper being installed or present.
- Port one coherent capability at a time. Extract the behavior; do not mechanically copy shell code,
  retain V1 repository assumptions, or carry over implicit current-directory and shell-only coupling.
- Keep the public interface under `drydock <verb> [<sub-verb>]`, and keep V2 command names even where
  V1 used differently named scripts.
- Put business logic in importable `src/drydock/` modules. `bin/` contains launchers only.
- Add focused unit tests and CLI contract tests for every implemented command. Preserve working
  commands while replacing deferred command stubs.
- Update `docs/SOUNDINGS.md` whenever a capability's implementation or verification state changes.
- Multiple agents and Ed may edit this shared working directory concurrently. Before committing,
  inspect the current diff and preserve changes made by other writers. If Git state changed or the
  commit fails due to concurrent activity, reread the affected files, resolve conflicts while
  preserving both intents, and retry. Never restore, reset, delete, stage, or commit changes that
  are not part of the active task.
- `docs/Drydock_Specification.md` has one active writer at a time. Unless explicitly assigned as
  that writer, agents may read it and propose exact replacement text, but must not edit it.
- Follow the Ship's Log Process (below): record material decisions and milestones immediately, then
  perform a final capture review before committing or completing a task.
- When delegating work or constructing an agent prompt, include the V2 mission, source precedence,
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

Business logic belongs in Python modules, not shell launchers or CLI dispatch functions. Shell and
PowerShell files in `bin/` only locate the environment and invoke the package entry point.

`Rigging/` is Drydock's own source of shared business rules, build rules, specification templates,
stack guidance, branding, and project templates. The wheel contains an installed copy at
`drydock/resources/Rigging/`, synchronized by Hatchling `force-include`. Versioned task prompts live
in `prompts/` and are packaged the same way to `drydock/resources/prompts/`. Both source-tree and
installed resolution paths must work; see `src/drydock/paths.py`.

### Boundaries

| Boundary | Responsibility |
|---|---|
| `src/drydock/cli.py` | Parse commands, dispatch to application functions, translate errors to exit codes |
| `src/drydock/<capability>.py` | Importable application behavior; no argument parsing |
| `src/drydock/config.py` | User-scoped configuration and configured root resolution |
| `src/drydock/paths.py` | Source-tree and installed-resource resolution |
| `src/drydock/llm.py` | Single adapter for subscription-authenticated CLI agent execution |
| `Rigging/` | Drydock's own shared governed inputs (seeded once from Prototyper `RulesEngine/`) |
| `prompts/` | Versioned task prompts used by LLM-assisted commands |
| `tests/` | Unit, CLI contract, integration, migration parity, and package tests |

### Data Locations

| Data | Required location |
|---|---|
| Drydock's own authoritative product specification | `docs/Drydock_Specification.md` |
| Drydock's own implementation acceptance checklist | `docs/SOUNDINGS.md` |
| Target-project Blueprint Typed Specification files, `BUILD_CONFIGURATION.md`, and `BUILD_PLAN_COMPASS.md` | `$DRYDOCK_WORKSPACE/targets/<Target>/blueprint/` |
| `METADATA.md` project identity and manifest, `BUILD_PLAN.md`, `SCORECARD.md`, Sea Trials, Soundings, built software, evidence, logs, and QuarterDeck state | `$DRYDOCK_WORKSPACE/targets/<Target>/` |
| Drydock's distributable rules and templates | `Rigging/` and the packaged resource copy |
| User configuration | User-scoped configuration managed by `drydock config` |

Commands must resolve `<Target>` under `$DRYDOCK_WORKSPACE/targets/` and the Blueprint as that
Target's `blueprint/` subtree. They must not depend on the caller being in the Drydock or Prototyper
repository.

## Prototyper V1 Reference

Resolve the V1 reference repository from `prototyper_directory` in Drydock's `METADATA.md`. Relative
paths are relative to the Drydock repository root:

```text
prototyper_directory: ../Prototyper
resolved path: /mnt/c/Users/barlo/projects/Prototyper
```

Agents are always authorized to read this repository and follow direct dependencies within it. Do
not assume V1 behavior is correct merely because it exists.

| Location | V1 evidence provided |
|---|---|
| `AGENTS.md` | V1 architecture, commands, operating rules, and file map |
| `bin/` | Working command implementations, shared libraries, process execution, and orchestration |
| `prompts/` | Working prompt contracts and context assembly rules |
| `RulesEngine/` | V1 governance, specification contract, templates, stack rules, and branding |
| `data/` and `logs/` | Build provenance and execution artifact examples when present |

### Rigging Provenance

Drydock `Rigging/` began as a **one-time copy** of Prototyper `RulesEngine/` and is now V2's own
source of these inputs, **evolving independently** of Prototyper. There is no live mirror and no
identity check between the trees; V2 divergence is expected.

- Prototyper is frozen V1 and read-only. Drydock commands (e.g. `drydock rigging compact`) may read
  and write `Rigging/` derivatives freely. Treat `Rigging/` as the maintained V2 source, not a fork
  to keep in sync.
- Prototyper's backup-only `RulesEngine/BRANDING_EDSVOICE.md` (Ed's personal global instructions) is
  not a Rigging input and must not be copied, packaged, or referenced by shared branding rules.
- The packaged copy at `drydock/resources/Rigging/` is not an independently editable source.

### V1 To V2 Capability Map

Discovery pointers, not required V2 module names. Inspect only the files needed for the capability
being built and follow their direct imports or sourced libraries.

| Drydock command or contract | Primary Prototyper V1 reference |
|---|---|
| `drydock init` | V2 target-baseline initializer; no authoritative V1 implementation |
| `drydock status` | `bin/validate.sh`, `RulesEngine/SPECIFICATION_CONTRACT.md` |
| Typed Specification relationships | `bin/build_spec_relationships.py` |
| Internal planning-input inventory | `bin/build_plan.sh`, `bin/build_plan_auto.py` |
| `drydock plan create` | `bin/build_plan_agile.py`, `bin/lib_agile_plan.py`, `prompts/oneshot_build_rules.md` |
| `drydock build` | `bin/oneshot.sh`, `bin/oneshot_phased.sh`, `bin/lib_prompt.sh`, `bin/lib_phases.py` |
| Build provenance and staleness | `bin/oneshot_phased.sh`, `data/executions.jsonl` behavior |
| `drydock build status` | `bin/build_plan_status.py`, `bin/build_plan.sh` |
| `drydock build score` | `bin/scorecard.sh` |
| `drydock refit` | `bin/iterate.sh`, `bin/build_spec_relationships.py` |
| `drydock analyze` | `bin/spec_iterate.sh`, `bin/update_reference_gaps.sh` |
| `drydock import --format source` | `bin/decompose.sh` |
| `drydock import --format speckit` | V2 Blueprint; no authoritative V1 implementation |
| `drydock rigging compact` | `bin/rulesengine_compact.sh`, `bin/compact_architecture.sh` |
| `drydock rigging update` | `bin/ProjectUpdate.sh`, `bin/project_manager.py` |
| `drydock rigging verify` | `bin/ProjectValidate.sh`, `bin/project_manager.py` |
| `drydock document generate` | `bin/document.sh` |
| `drydock document assemble` | `bin/build_project_docs.py` |
| QuarterDeck evidence/review | `bin/console_sync.py`, `bin/lib_agile_plan.py`, `bin/oneshot.sh` |
| LLM process execution | `bin/run_llm_agent.sh`, `bin/run_llm_agent_report.py`, `bin/stream_claude.py` |
| Rules and templates | `RulesEngine/`, already seeded into Drydock `Rigging/` |

## Migration Procedure

### Capability Slice

Implement commands as vertical slices:

1. Define command syntax, inputs, outputs, side effects, and exit codes from the Blueprint.
2. Identify the V1 algorithm and observable behavior.
3. Separate deterministic logic from filesystem operations and LLM execution.
4. Implement deterministic logic first in an importable module.
5. Wire the module into `cli.py`.
6. Replace the matching deferred-command test with behavior tests.
7. Add integration tests for filesystem changes and failure handling.
8. Compare representative output and artifacts against V1 where parity is intended.
9. Update `README.md` when a command moves from deferred to working.
10. Update `docs/SOUNDINGS.md` with the final state and verification evidence.

Do not port multiple large V1 scripts into one module. Preserve clear contracts for path resolution,
plan parsing, prompt assembly, process execution, evidence, and review state.

### Prompt Context Discipline

The full Drydock specification is intentionally not injected into every agent prompt.

- Search `docs/Drydock_Specification.md` by command, workflow, artifact, or contract heading.
- Read the relevant section plus any directly referenced shared contract sections.
- Load the full specification only when changing cross-cutting architecture or product semantics.
- Read mapped Prototyper files only for the active capability and its direct dependencies.
- Every delegated or generated implementation prompt must state that Drydock is the maintained V2
  target, include this source-precedence contract, and provide the relevant specification excerpts
  and V1 file paths.
- Generated build prompts must include only the specification files, Rigging, and context required
  for the current runnable plan block.

## LLM-Assisted Command Pattern

Commands that call an LLM follow one shape, first established by `drydock rigging compact`:

1. **Load** the prompt with `prompts.load_prompt("<command>_<subcommand>")`. The loader validates
   the prompt's frontmatter contract and exposes its metadata (including `model`).
2. **Assemble** the final prompt deterministically: the prompt `body` plus an injected job block
   (source paths, dates, per-item objective, fenced source content). Keep assembly in the module so
   it is unit-testable without a process.
3. **Execute** through `llm.run_prompt(...)`, which persists reproducible evidence
   (`logs/executions.jsonl`, per-run prompt/raw/output/stderr files, structured events). Pass an
   `on_text`/`on_item` callback for console progress.
4. **Write outputs deterministically in the module**, not from the model. The model emits text; the
   module post-processes and writes files. This keeps execution free of file-write permissions and
   makes results assertable.
5. **Inject the runner.** The capability function takes a `runner` parameter defaulting to
   `run_prompt`, resolved at call time so tests can substitute a fake. Tests must never spend API
   credits or require network access.

### Prompt Contract Standard

Every prompt in `prompts/` obeys two rules:

- **Naming:** `prompts/<command>_<subcommand>[_<modifier>].md`, lowercase. `_<modifier>` is reserved
  for operations needing multiple prompts. Example: `drydock rigging compact` → `rigging_compact.md`.
- **Metadata:** a leading `---` YAML frontmatter block with required `name`, `description`,
  `version`, `intent` and optional `command`, `model`, `output`. Parsed by `prompts.load_prompt`
  (a small scalar parser — Drydock carries no YAML dependency).

Prompts are packaged like Rigging (`force-include` → `drydock/resources/prompts/`) and resolved by
`paths.get_prompts_root()`; both source-tree and installed paths must work.

## Soundings State Contract

Each command or capability has one Soundings row in `docs/SOUNDINGS.md`. Use these states:

| State | Meaning |
|---|---|
| `NOT STARTED` | No public command or implementation contract exists |
| `STUBBED` | Command surface exists and returns the tested deferred response |
| `IMPLEMENTED` | Real behavior exists, but required acceptance verification is incomplete |
| `DONE` | Approved behavior is implemented and all required verification/evidence passes |

Do not mark a row `DONE` based only on code presence. Record test names, integration evidence,
package evidence, or other acceptance proof in the row. When behavior regresses or the specification
changes, move the row back to the truthful state.

## Verification Contract

Every completed capability must demonstrate:

| Verification | Requirement |
|---|---|
| Unit tests | Deterministic logic, parsing, state transitions, and error cases |
| CLI tests | Syntax, help, output contract, and exit codes |
| Integration tests | Real temporary Blueprint and Target directories |
| Parity tests | Representative V1 behavior where compatibility is intended |
| Regression tests | Existing working Drydock commands remain working |
| Lint | `ruff check src/ tests/` |
| Full suite | `python -m pytest` |
| Package test | Required when changing Rigging resolution, package data, or launch behavior |
| Soundings | Matching row updated to the truthful state with concrete evidence |

LLM-assisted commands must isolate process execution behind an adapter so tests can use a fake
runner. Tests must not spend API credits or require network access.

### Development Commands

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

## Build Order

`docs/SOUNDINGS.md` is the authoritative record of which commands are working, stubbed, or
implemented. The preferred implementation order follows the V2 delivery dependency chain:

1. Complete and stabilize the command surface and shared path/process contracts.
2. Stabilize Planning Session approval, adaptive decomposition, and cost-reducing work grouping.
3. Implement evidence contracts and `drydock build`.
4. Implement QuarterDeck review reconciliation.
5. Implement `refit`, `analyze`, and score.
6. Implement Rigging update, verification, and compaction.
7. Implement documentation workflows.
8. Implement source and Spec Kit import adapters.

This order is guidance, not authority. A user-requested coherent capability can be implemented
earlier when its dependencies are satisfied.

## Ship's Log Process

The Ship's Log preserves material product decisions and delivery milestones as structured,
append-only events. It is currently a Drydock-only development proving ground, not a public CLI
workflow and not a rule injected into target projects. The intended future product capability is
agent-driven capture during Drydock-managed design and build workflows; that deployment is deferred
until the decision backend and workflow are validated through Drydock's own development.

The only canonical artifact is `logs/ships_log.jsonl`. QuarterDeck and future publishing tools read
that JSONL directly. Never create or maintain a Markdown Ship's Log.

### Required Agent Behavior

Every agent working in the Drydock repository must evaluate Ship's Log capture:

1. Immediately after making or receiving approval for a material decision or reaching a material
   delivery milestone.
2. Again before committing or declaring the task complete, using the completed diff and discussion
   to catch events missed during implementation.

Record an event for:

- an approved specification or product-behavior change;
- a feature addition, removal, or material scope change;
- an architecture, persistence, interface, governance, or development-process decision;
- a meaningful completed delivery milestone;
- a reversal or replacement of an earlier recorded decision.

Do not record routine file edits, implementation mechanics, commands, commits, test runs, or minor
refactors that do not change product behavior or development governance. If no event qualifies,
report that the final Ship's Log review found no material event. Do not add a placeholder record.

### Recording Events

Use the repository-local utility; do not hand-edit the JSONL:

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

Use `--event-type milestone` for meaningful completed delivery milestones. Repeat `--scope`,
`--alternative`, `--evidence`, `--supersedes`, and `--tag` as needed.

Use these interim classification tags when applicable:

- `open-item` — a material unresolved question or follow-up requiring a future decision;
- `deferred-item` — an accepted capability or action intentionally postponed;
- `accepted-risk` — a known material risk explicitly accepted for the current decision.

When reversing or replacing an earlier decision, append a new event and pass the earlier event ID
with `--supersedes`. Never rewrite or delete an existing record. Validate the ledger when changing
its process, schema, persistence, or viewer:

```bash
python bin/ships_log.py audit
```

Each line is one schema-version-1 JSON object with a generated `event_id` and `recorded_at`; an
`event_type` of `decision` or `milestone`; concise non-empty `title`, `summary`, and `rationale`; a
source object; and optional affected scope, alternatives, evidence, superseded event IDs, and tags.
The utility validates the record before performing one append-only write to `logs/ships_log.jsonl`.

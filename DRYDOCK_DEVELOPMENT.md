# Drydock Development Contract

## Mandatory Use

Read this file in full at the start of every Drydock development session. Include it in every
delegated implementation prompt, or explicitly require the delegated agent to read it before doing
work. This requirement remains in effect while Drydock is being built and cannot yet supply all of
its intended development context through working commands.

Then read:

1. `SHIPS_LOG_PROCESS.md` for the mandatory Drydock decision-capture process.
2. The relevant sections of `docs/Drydock_Specification.md`.
3. `docs/SOUNDINGS.md` to identify the current implementation and acceptance state.

`docs/Drydock_Specification.md` is the authoritative product specification. It is a crafted definition
of the future ideal state for the project - including scope and contracts.  It is not a location
for status or deprication notes.  Agents must ask Ed for approval before changing it.
Once approved, behavior and specification changes land together; the specification must never knowingly
describe stale behavior.

## Purpose

Drydock is V2 of the working Blueprint-driven delivery system currently implemented in
Prototyper. Drydock must preserve proven behavior where it supports the V2 product, while becoming:

- an installable, repository-independent Python CLI;
- a coherent command surface rather than a collection of directly invoked scripts;
- testable through importable modules and deterministic contracts;
- driven by Drydock Blueprints expressed as Typed Specifications and reviewable build evidence;
- usable from any working directory after configuration.

Prototyper is not being enhanced during this migration. It is a read-only reference implementation
and source of regression cases. Drydock is the maintained target.

## Prototyper V1 Reference Repository

Resolve the V1 reference repository from `prototyper_directory` in Drydock's `METADATA.md`. Relative
paths are relative to the Drydock repository root. In this checkout:

```text
prototyper_directory: ../Prototyper
resolved path: /mnt/c/Users/barlo/projects/Prototyper
```

Agents are always authorized to read this repository and follow direct dependencies within it.
Agents are not authorized to modify it unless Ed explicitly authorizes a specific Prototyper change.
Drydock development must never write to Prototyper as a side effect.

Key Prototyper reference locations:

| Location | V1 evidence provided |
|---|---|
| `AGENTS.md` | V1 architecture, commands, operating rules, and file map |
| `bin/` | Working command implementations, shared libraries, process execution, and orchestration |
| `prompts/` | Working prompt contracts and context assembly rules |
| `RulesEngine/` | V1 governance, specification contract, templates, stack rules, and branding |
| `data/` and `logs/` | Build provenance and execution artifact examples when present |

Inspect these locations as needed to understand working V1 behavior. Do not copy repository-bound
assumptions into Drydock, and do not make Drydock runtime behavior depend on Prototyper being
available.

## Rigging Provenance

Drydock `Rigging/` began as a **one-time copy** of Prototyper `RulesEngine/`. It holds V2's shared
business rules, build rules, specification templates, stack guidance, branding, and project
templates. It is now Drydock's own source of these inputs and **evolves independently** of
Prototyper — there is no live mirror and no identity check between the trees. V2 divergence is
expected.

- Prototyper is frozen V1 and read-only. Never write to it during Drydock development or tests.
- Drydock commands (e.g. `drydock rigging compact`) may read and write `Rigging/` derivatives
  freely. Treat `Rigging/` as the maintained V2 source, not a fork to keep in sync.
- Prototyper's backup-only `RulesEngine/BRANDING_EDSVOICE.md` (Ed's personal global instructions) is
  not a Rigging input and must not be copied, packaged, or referenced by shared branding rules.
- Drydock packaging copies `Rigging/` into installed package resources
  (`drydock/resources/Rigging/`); the packaged copy is not an independently editable source.

## Sources, Decisions, And Completion

| Source | Role |
|---|---|
| `docs/Drydock_Specification.md` | Sole authoritative V2 Drydock specification and target behavior |
| `docs/SOUNDINGS.md` | Authoritative checklist of implementation state, acceptance state, and evidence |
| `src/drydock/`, `tests/` | Current implemented behavior and regression contract |
| This file | Migration architecture, method, and V1 reference map |
| `prototyper_directory` from `METADATA.md` | Read-only V1 behavior, algorithms, prompts, and edge cases |

Do not assume V1 behavior is correct merely because it exists. For each capability:

1. Read the relevant section of `docs/Drydock_Specification.md` and the matching Soundings row.
2. If intended behavior must change, obtain Ed's approval and update the specification.
3. Inspect mapped V1 files and direct dependencies where useful.
4. Implement the approved contract as a Drydock Python module and CLI command.
5. Prove the contract with focused tests, relevant parity cases, and full verification.
6. Update `docs/SOUNDINGS.md` with the final state and concrete evidence.
7. Perform the final Ship's Log review required by `SHIPS_LOG_PROCESS.md`.

If the specification and V1 disagree, the specification wins. If the specification is silent, keep
proven V1 behavior unless it conflicts with Drydock's package architecture or command contracts.

### Soundings State Contract

Each command or capability has one Soundings row. Use these states:

| State | Meaning |
|---|---|
| `NOT STARTED` | No public command or implementation contract exists |
| `STUBBED` | Command surface exists and returns the tested deferred response |
| `IMPLEMENTED` | Real behavior exists, but required acceptance verification is incomplete |
| `DONE` | Approved behavior is implemented and all required verification/evidence passes |

Do not mark a row `DONE` based only on code presence. Record test names, integration evidence,
package evidence, or other acceptance proof in the row. When behavior regresses or the
specification changes, move the row back to the truthful state.

## Target Architecture

### Boundaries

| Boundary | Responsibility |
|---|---|
| `src/drydock/cli.py` | Parse commands, dispatch to application functions, translate errors to exit codes |
| `src/drydock/<capability>.py` | Importable application behavior; no argument parsing |
| `src/drydock/config.py` | User-scoped configuration and configured root resolution |
| `src/drydock/paths.py` | Source-tree and installed-resource resolution |
| `src/drydock/llm.py` | Future single adapter for subscription-authenticated CLI agent execution |
| `Rigging/` | Drydock's own shared governed inputs (seeded once from Prototyper `RulesEngine/`) |
| `prompts/` | Versioned task prompts used by LLM-assisted commands |
| `tests/` | Unit, CLI contract, integration, migration parity, and package tests |

Business logic belongs in Python modules, not shell launchers or CLI dispatch functions. Shell and
PowerShell files in `bin/` only locate the environment and invoke the package entry point.

### Data Locations

| Data | Required location |
|---|---|
| Drydock's own authoritative product specification | `docs/Drydock_Specification.md` |
| Drydock's own implementation acceptance checklist | `docs/SOUNDINGS.md` |
| Target-project Blueprint Typed Specification files and internal `BUILD_PLAN_INTENT.md` | Configured Blueprint directory |
| `BUILD_PLAN.md`, built software, execution evidence, logs, and QuarterDeck state | Configured Target directory |
| Drydock's distributable rules/templates | `Rigging/` and packaged resource copy |
| User configuration | User-scoped Drydock configuration managed by `drydock config` |

Commands must resolve `<Blueprint>` and `<Target>` relative to configured roots. They must not depend on
the caller being in the Drydock or Prototyper repository.

## V1 To V2 Capability Map

Use this map to find proven behavior. Inspect only the files needed for the capability being built
and follow their direct imports or sourced libraries as necessary.

| Drydock command or contract | Primary Prototyper V1 reference |
|---|---|
| `drydock init` | V2 target-baseline initializer; no authoritative V1 implementation |
| `drydock validate` | `bin/validate.sh`, `RulesEngine/SPECIFICATION_CONTRACT.md` |
| Typed Specification relationships | `bin/build_spec_relationships.py` |
| Internal planning-input inventory | `bin/build_plan.sh`, `bin/build_plan_auto.py` |
| `drydock plan create` | `bin/build_plan_agile.py`, `bin/lib_agile_plan.py`, `prompts/oneshot_build_rules.md` |
| `drydock build` | `bin/oneshot.sh`, `bin/oneshot_phased.sh`, `bin/lib_prompt.sh`, `bin/lib_phases.py` |
| Build provenance and staleness | `bin/oneshot_phased.sh`, `data/executions.jsonl` behavior |
| `drydock build status` | `bin/build_plan_status.py`, `bin/build_plan.sh` |
| `drydock build score` | `bin/scorecard.sh` |
| `drydock iterate` | `bin/iterate.sh`, `bin/build_spec_relationships.py` |
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

The V1 filenames are discovery pointers, not required V2 module names.

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
9. Update `README.md` when the command moves from deferred to working.
10. Update `docs/SOUNDINGS.md` with the final state and verification evidence.

Do not port multiple large V1 scripts into one module. Preserve clear contracts for path resolution,
plan parsing, prompt assembly, process execution, evidence, and review state.

### Prompt Context Discipline

The full Drydock specification is intentionally not injected into every agent prompt.

- Search `docs/Drydock_Specification.md` by command, workflow, artifact, or contract heading.
- Read the relevant section plus any directly referenced shared contract sections.
- Load the full specification only when changing cross-cutting architecture or product semantics.
- Read mapped Prototyper files only for the active capability and direct dependencies.
- Every delegated or generated implementation prompt must state that Drydock is the maintained V2
  target, include this source-precedence contract, and provide the relevant specification excerpts
  and V1 file paths.
- Generated build prompts must include only the specification files, Rigging, and context required
  for the current runnable plan block.

### Compatibility Rules

- Maintain the V2 Drydock command names even when V1 used differently named scripts.
- Preserve important artifact formats and migration compatibility unless the Blueprint replaces
  them.
- Keep lower-level operations testable and callable internally for debugging.
- Never write to Prototyper during development or tests.
- Never make runtime behavior depend on Prototyper being installed or present.
- Do not retain V1 repository assumptions, implicit current-directory behavior, or shell-only
  coupling.

## LLM-Assisted Command Pattern

Commands that call an LLM follow one shape, first established by `drydock rigging compact`:

1. **Load** the prompt with `prompts.load_prompt("<command>_<subcommand>")`. The loader validates
   the prompt's frontmatter contract and exposes its metadata (including `model`).
2. **Assemble** the final prompt deterministically: the prompt `body` plus an injected job block
   (source paths, dates, per-item objective, fenced source content). Keep assembly in the module so
   it is unit-testable without a process.
3. **Execute** through `llm.run_prompt(...)`, which already persists reproducible evidence
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
  `version`, `intent` and optional `command`, `model`, `output`. Parsed by
  `prompts.load_prompt` (a small scalar parser — Drydock carries no YAML dependency).

Prompts are packaged like Rigging (`force-include` → `drydock/resources/prompts/`) and resolved by
`paths.get_prompts_root()`; both source-tree and installed paths must work.

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

## Current State And Build Order

Working now:

- `drydock config show|set`
- `drydock init`
- `drydock validate`
- `drydock rigging compact`
- `drydock import <Blueprint> <Source> --format markdown`
- `drydock plan create`
- `drydock build status`
- source-tree launchers, package foundation, and Rigging resource resolution

All other visible commands are deferred stubs or partially implemented as recorded in Soundings.
The preferred implementation order follows the V2
delivery dependency chain:

1. Complete and stabilize the command surface and shared path/process contracts.
2. Stabilize Planning Session approval, adaptive decomposition, and cost-reducing work grouping.
3. Implement evidence contracts and `drydock build`.
4. Implement QuarterDeck review reconciliation.
5. Implement `iterate`, `analyze`, and score.
6. Implement Rigging update, verification, and compaction.
7. Implement documentation workflows.
8. Implement source and Spec Kit import adapters.

This order is guidance, not authority. A user-requested coherent capability can be implemented
earlier when its dependencies are satisfied.

# Drydock Development Contract

## Mandatory Use

Read this file in full at the start of every Drydock development session. Include it in every
delegated implementation prompt, or explicitly require the delegated agent to read it before doing
work. This requirement remains in effect while Drydock is being built and cannot yet supply all of
its intended development context through working commands.

## Purpose

Drydock is V2 of the working specification-driven delivery system currently implemented in
Prototyper. Drydock must preserve proven behavior where it supports the V2 product, while becoming:

- an installable, repository-independent Python CLI;
- a coherent command surface rather than a collection of directly invoked scripts;
- testable through importable modules and deterministic contracts;
- driven by Typed Specifications and reviewable build evidence;
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
| `docs/whitepapers/drydock.md` | Origin of the V2 product specification; Drydock's `docs/drydock.md` is authoritative |
| `data/` and `logs/` | Build provenance and execution artifact examples when present |

Inspect these locations as needed to understand working V1 behavior. Do not copy repository-bound
assumptions into Drydock, and do not make Drydock runtime behavior depend on Prototyper being
available.

## RulesEngine And Rigging Mirror Contract

Prototyper `RulesEngine/` was copied to Drydock `Rigging/`. These directories contain the shared
business rules, build rules, specification templates, stack guidance, branding, and project
templates used for applications. They are shared governed inputs, not part of the normal
Prototyper-to-Drydock application-code migration.

The governed contents of these directories must always be identical:

```text
/mnt/c/Users/barlo/projects/Prototyper/RulesEngine/
/mnt/c/Users/barlo/projects/Drydock/Rigging/
```

Rules:

- Do not independently refactor, rename, reorganize, or improve either tree while implementing
  Drydock commands.
- Do not treat Drydock `Rigging/` as a fork or a new source of business/build rules.
- A change to either tree requires Ed's explicit authorization for that rule change and must be
  applied identically to both trees.
- Verify mirror identity after every authorized rule change.
- Identity applies to governed files. Ignore transient, ignored artifacts such as `.ruff_cache/`,
  `__pycache__/`, and generated package/build output.
- Drydock packaging may copy `Rigging/` into installed package resources, but packaged copies do not
  become an independently editable source.

Current verification: the governed trees are identical; only an ignored `.ruff_cache/` exists under
Drydock `Rigging/templates/`.

## Sources And Decisions

| Source | Role |
|---|---|
| `docs/drydock.md` | Authoritative V2 product specification and target behavior |
| `src/drydock/`, `tests/` | Current implemented behavior and regression contract |
| This file | Migration architecture, method, and V1 reference map |
| `prototyper_directory` from `METADATA.md` | Read-only V1 behavior, algorithms, prompts, and edge cases |

Do not assume V1 behavior is correct merely because it exists. For each capability:

1. Read the relevant section of `docs/drydock.md`.
2. Inspect the mapped V1 files and their direct dependencies.
3. State or encode the intended V2 contract.
4. Implement it as a Drydock Python module and CLI command.
5. Prove the contract with tests, including relevant V1 parity cases.

If the specification and V1 disagree, the specification wins. If the specification is silent, keep
proven V1 behavior unless it conflicts with Drydock's package architecture or command contracts.

## Target Architecture

### Boundaries

| Boundary | Responsibility |
|---|---|
| `src/drydock/cli.py` | Parse commands, dispatch to application functions, translate errors to exit codes |
| `src/drydock/<capability>.py` | Importable application behavior; no argument parsing |
| `src/drydock/config.py` | User-scoped configuration and configured root resolution |
| `src/drydock/paths.py` | Source-tree and installed-resource resolution |
| `src/drydock/llm.py` | Future single adapter for subscription-authenticated CLI agent execution |
| `Rigging/` | Drydock-local mirror of Prototyper `RulesEngine/`; shared governed inputs |
| `prompts/` | Versioned task prompts used by LLM-assisted commands |
| `tests/` | Unit, CLI contract, integration, migration parity, and package tests |

Business logic belongs in Python modules, not shell launchers or CLI dispatch functions. Shell and
PowerShell files in `bin/` only locate the environment and invoke the package entry point.

### Data Locations

| Data | Required location |
|---|---|
| Product specification files and `BUILD_PLAN.md` | Configured Specification directory |
| Built software, execution evidence, logs, and QuarterDeck state | Configured Target directory |
| Drydock's distributable rules/templates | `Rigging/` and packaged resource copy |
| User configuration | User-scoped Drydock configuration managed by `drydock config` |

Commands must resolve `<Spec>` and `<Target>` relative to configured roots. They must not depend on
the caller being in the Drydock or Prototyper repository.

## V1 To V2 Capability Map

Use this map to find proven behavior. Inspect only the files needed for the capability being built
and follow their direct imports or sourced libraries as necessary.

| Drydock command or contract | Primary Prototyper V1 reference |
|---|---|
| `drydock init` | `bin/setup.sh`, `RulesEngine/spec_template/` |
| `drydock validate` | `bin/validate.sh`, `RulesEngine/SPECIFICATION_CONTRACT.md` |
| Typed Specification relationships | `bin/build_spec_relationships.py` |
| `drydock plan init` | `bin/build_plan.sh`, `bin/build_plan_auto.py` |
| `drydock plan create` | `bin/build_plan_agile.py`, `bin/lib_agile_plan.py`, `prompts/oneshot_build_rules.md` |
| `drydock plan show` | `bin/lib_agile_plan.py`, `bin/build_plan.sh` |
| `drydock build` | `bin/oneshot.sh`, `bin/oneshot_phased.sh`, `bin/lib_prompt.sh`, `bin/lib_phases.py` |
| Build provenance and staleness | `bin/oneshot_phased.sh`, `data/executions.jsonl` behavior |
| `drydock build status` | `bin/build_plan_status.py`, `bin/build_plan.sh` |
| `drydock build score` | `bin/scorecard.sh` |
| `drydock iterate` | `bin/iterate.sh`, `bin/build_spec_relationships.py` |
| `drydock analyze` | `bin/spec_iterate.sh`, `bin/update_reference_gaps.sh` |
| `drydock import --format source` | `bin/decompose.sh` |
| `drydock import --format speckit` | V2 specification; no authoritative V1 implementation |
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

1. Define command syntax, inputs, outputs, side effects, and exit codes from the specification.
2. Identify the V1 algorithm and observable behavior.
3. Separate deterministic logic from filesystem operations and LLM execution.
4. Implement deterministic logic first in an importable module.
5. Wire the module into `cli.py`.
6. Replace the matching deferred-command test with behavior tests.
7. Add integration tests for filesystem changes and failure handling.
8. Compare representative output and artifacts against V1 where parity is intended.
9. Update `README.md` when the command moves from deferred to working.

Do not port multiple large V1 scripts into one module. Preserve clear contracts for path resolution,
plan parsing, prompt assembly, process execution, evidence, and review state.

### Prompt Context Discipline

The full specification is intentionally not injected into every agent prompt.

- Search `docs/drydock.md` by command, workflow, artifact, or contract heading.
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
- Preserve important artifact formats and migration compatibility unless the specification replaces
  them.
- Keep lower-level operations testable and callable internally for debugging.
- Never write to Prototyper during development or tests.
- Never make runtime behavior depend on Prototyper being installed or present.
- Do not retain V1 repository assumptions, implicit current-directory behavior, or shell-only
  coupling.

## Verification Contract

Every completed capability must demonstrate:

| Verification | Requirement |
|---|---|
| Unit tests | Deterministic logic, parsing, state transitions, and error cases |
| CLI tests | Syntax, help, output contract, and exit codes |
| Integration tests | Real temporary Specification and Target directories |
| Parity tests | Representative V1 behavior where compatibility is intended |
| Regression tests | Existing working Drydock commands remain working |
| Lint | `ruff check src/ tests/` |
| Full suite | `python -m pytest` |
| Package test | Required when changing Rigging resolution, package data, or launch behavior |

LLM-assisted commands must isolate process execution behind an adapter so tests can use a fake
runner. Tests must not spend API credits or require network access.

## Current State And Build Order

Working now:

- `drydock config show|set`
- `drydock init`
- `drydock validate`
- source-tree launchers, package foundation, and Rigging resource resolution

All other visible commands are deferred stubs. The preferred implementation order follows the V2
delivery dependency chain:

1. Complete and stabilize the command surface and shared path/process contracts.
2. Implement `plan init|create|show`.
3. Implement build status, evidence contracts, and `drydock build`.
4. Implement QuarterDeck review reconciliation.
5. Implement `iterate`, `analyze`, and score.
6. Implement Rigging update, verification, and compaction.
7. Implement documentation workflows.
8. Implement source and Spec Kit import adapters.

This order is guidance, not authority. A user-requested coherent capability can be implemented
earlier when its dependencies are satisfied.

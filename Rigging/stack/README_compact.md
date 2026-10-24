<!-- Compacted from Rigging/stack/README.md sha256=6759153863ddcf11ab4b830f8f0f754664cbda0cc3840d21330fe275a66c1974 on 2026-10-24 by drydock rigging compact — regenerate with: drydock rigging compact --include-file {rel_source} -->

# Technology Stack Reference Library — Contract Surface

## Stack Selection

### config_key

The project configuration selects technologies and project metadata through `STACK.yaml` or `METADATA.md`.

| Key | Required shape |
|---|---|
| `language` | Exactly one supported language, such as `python`, `typescript`, or `go` |
| `framework` | Selected framework, such as `flask`, `django`, or `cli` |
| `database` | Zero or more supported persistence engines, such as `sqlite` or `postgres` |
| `frontend` | Selected frontend technology, such as `bootstrap5` |
| `aws_services` | Selected AWS service identifiers |
| `infra` | Selected infrastructure technology |
| `ci` | Selected CI technology |
| `lib` | Selected client library |
| `project.name` | Project name |
| `project.title` | Project title |
| `project.port` | Application port |
| `specifications` | List of specification file names |

Constraints: Select exactly one language. Persistence engines are optional. Each selected technology must reference an existing stack file.

### Rule: foundation-selection

Foundation files declare `**Foundation: <kind>`, `## Foundation Contract`, and `**Tier:**`; a Target selects exactly one file per foundation kind.

Constraints: Foundation tiers execute in order: language, platform, branding, interface, and screen-foundation. Application files have no internal order.

### Rule: mandatory-language-contract

Language files publish `###` answers under `## Foundation Contract` for Acceptance Criteria execution and the shared persistence contract.

Constraints: Answers state AC format, execution command, criterion identity, result and observed-value reporting, measurement limitations, persistence library, supported engines, generated files, dependencies, fixtures, and verification status.

### Rule: mandatory-database-contract

Database files publish `###` answers under `## Foundation Contract` for engine configuration and the shared persistence contract.

Constraints: Answers state driver dependencies, connection settings, schema initialization, schema-change handling, language bindings, fixtures, engine differences, limitations, and verification status.

## Validation and Prompt Generation

### ./validate.sh PROJECT

Validates that the project's referenced stack files exist.

| Input | Required value |
|---|---|
| `PROJECT` | Project identifier |

Constraints: Create the project's `STACK.yaml` before running validation.

### ./generate-prompt.sh PROJECT

Merges the selected stack files into a single prompt.

| Input | Required value |
|---|---|
| `PROJECT` | Project identifier |

Constraints: Run after stack validation and select only existing stack files.

## Stack File Contract

### Rule: stack-file-structure

Each technology file provides a technology name, prerequisites, version or last-updated metadata, prescriptive rules, implementation examples, rationale, and a summary checklist.

Constraints: New technology files use the established structure, document prerequisites, are added to the stack index, and update validation logic when introducing new `STACK.yaml` keys.

### Rule: shared-stack-files

Projects consume shared stack files without forking or modifying them.

Constraints: Project-specific exceptions belong in the project's `CLAUDE.md`; universal improvements update the shared stack file.

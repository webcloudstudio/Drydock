<!-- Compacted from Rigging/stack/README.md sha256=c4c17c0ca46ac6303697a5ae73c5a2500ee3adc78c54de23eb14c9bb5863c060 on 2026-09-20 by drydock rigging compact — regenerate with: drydock rigging compact --include-file {rel_source} -->

# Technology Stack Reference Library — Contract Surface

## Stack Selection

### `STACK.yaml`
Selects the technologies used by a project.

| Field | Shape |
|---|---|
| `language` | Technology identifier |
| `framework` | Framework identifier |
| `database` | Database identifier |
| `frontend` | Frontend identifier |
| `project.name` | Project name |
| `project.title` | Project title |
| `project.port` | Numeric port |
| `specifications` | List of specification filenames |

Constraints: Select exactly one foundation file per foundation kind. `common.md` is always required.

### `stack/<technology>.md`
Defines a reusable technology reference with a header, prerequisites, version metadata, prescriptive rules, implementations, and a summary checklist.

Constraints: New technology files must be added to the catalog and declare their prerequisites.

### `validate.sh <Project>`
Validates that the project's referenced stack files exist.

| Input | Required |
|---|---|
| `Project` | Project directory or project name |

### `generate-prompt.sh <Project>`
Generates a merged prompt from the project's selected stack files.

| Input | Required |
|---|---|
| `Project` | Project directory or project name |

## Stack File Contracts

### Rule: prerequisites
Stack files declare prerequisite files that consumers must read first.

Constraints: Read `common.md` first, followed by the language, framework, database, frontend, and required AWS service files.

### Rule: shared-files
Stack files are shared, version-controlled inputs and must not be forked or modified for project-specific use.

Constraints: Project-specific exceptions belong in the project's `CLAUDE.md`.

### Rule: project-setup
A consuming project creates `STACK.yaml`, validates its references, generates the merged prompt, and follows the selected stack rules.

### Rule: dependency-chain
The standard dependency chain is:

`common.md` → language file → framework and database files; `bootstrap5.md` and AWS service files are optional according to project needs.

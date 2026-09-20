<!-- Compacted from Rigging/stack/README.md sha256=64717647c544159f9acdc70b90da73d8c0d6c77e6e25d2b23a0c9fdb5108b709 on 2026-09-20 by drydock rigging compact — regenerate with: drydock rigging compact --include-file {rel_source} -->

# Technology Stack Reference Library — Contract Surface

## Stack Selection

### config_key `STACK.yaml`

Lists all selected technologies for a project.

| Field | Required | Values |
|---|---:|---|
| `language` | Yes | Technology language such as `python`, `typescript`, or `go` |
| `framework` | No | Framework such as `cli`, `flask`, or `django` |
| `database` | No | Database such as `sqlite` or `postgres` |
| `frontend` | No | Frontend technology such as `bootstrap5` |
| `aws_services` | No | List of AWS service identifiers |
| `infra` | No | Infrastructure technology such as `terraform` |
| `ci` | No | CI technology such as `github-actions` |
| `lib` | No | Library such as `cloud-client` |

### config_key `METADATA.md`

Defines project metadata and specification inputs.

| Field | Required | Shape |
|---|---:|---|
| `language` | Yes | Technology identifier |
| `framework` | No | Framework identifier |
| `database` | No | Database identifier |
| `frontend` | No | Frontend identifier |
| `project.name` | Yes | Project name |
| `project.title` | Yes | String title |
| `project.port` | Yes | Numeric port |
| `specifications` | Yes | List of specification filenames |

### Rule: stack-file-selection

Consumers read stack files in dependency order: `common.md`, language file, framework file, database file, frontend file, then required AWS service files.

Constraints: `common.md` is always required. Framework, database, frontend, infrastructure, CI, library, and AWS files are selected according to `STACK.yaml`.

### Rule: stack-file-structure

Each technology file contains a technology header, prerequisites, version or last-updated information, one to five rules, and a summary checklist.

Each rule contains a prescriptive rule statement, implementation example, rationale, and checklist.

## Validation and Prompt Generation

### `validate.sh MyProject`

Validates that all stack files referenced by the project exist.

| Input | Required | Description |
|---|---:|---|
| `MyProject` | Yes | Project identifier |

Constraints: Run after creating `STACK.yaml`.

### `generate-prompt.sh MyProject`

Generates a merged prompt from the project’s selected stack files.

| Input | Required | Description |
|---|---:|---|
| `MyProject` | Yes | Project identifier |

Constraints: Run after stack-file validation.

## Stack File Governance

### Rule: shared-stack-files

Stack files are shared, version-controlled files. Projects must not fork or modify them for project-specific use.

Constraints: Universal rule changes update the shared file in place. Project-specific exceptions belong in the project’s `CLAUDE.md`.

### Rule: adding-technology-file

A new technology file is created as `stack/technology-name.md`, follows the standard structure, is added to the README catalog, updates `validate.sh` when introducing new `STACK.yaml` keys, and documents prerequisites.

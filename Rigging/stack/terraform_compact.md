<!-- Compacted from Rigging/stack/terraform.md sha256=249c2ebd469628734bd3881be971fca2baf61cd6ae4d7983c3aac44f1c1936ba on 2026-09-20 by drydock rigging compact — regenerate with: drydock rigging compact --include-file {rel_source} -->

# Terraform Best Practices — Contract Surface

## Infrastructure Layout

### Rule: layered-roots

Terraform infrastructure uses independent `backend/`, `foundation/`, and `services/` root modules plus shared `modules/` and `bin/` directories.

Constraints: `backend/` contains one-shot bootstrap resources; `foundation/` contains rarely changed foundational resources; `services/` contains rerunnable application resources.

### Rule: state-isolation

Each root module maintains independent Terraform state.

Constraints: Lambda or service changes must not share state with or risk destroying foundational resources.

## Remote State

### config_key: terraform.backend.s3

`foundation/` and `services/` configure an encrypted S3 backend with DynamoDB locking.

| Key | Required value |
|---|---|
| `bucket` | `{org}-{project}-tfstate` |
| `key` | `{layer}/terraform.tfstate` |
| `region` | Deployment region |
| `dynamodb_table` | `{org}-{project}-tflock` |
| `encrypt` | `true` |

Constraints: The state bucket is versioned and blocks public access. State must not be local for `foundation/` or `services/`; DynamoDB stores only the lock.

### Rule: backend-bootstrap

`backend/` creates the S3 state bucket and DynamoDB lock table with local state.

Constraints: Apply `backend/` once, keep its state local permanently, commit that local state or document re-import, and exclude it from normal pipelines. Initialize `foundation/` and `services/` directly against S3 without state migration.

## Configuration and Resources

### config_key: variable.project

Identifies the project used in resource naming and common tags.

| Field | Type |
|---|---|
| `project` | `string` |

### config_key: variable.org

Identifies the organization used in resource naming and common tags.

| Field | Type |
|---|---|
| `org` | `string` |

### config_key: locals.common_tags

Provides the standard tags applied to every taggable resource.

| Tag | Value |
|---|---|
| `Project` | `var.project` |
| `Owner` | `var.org` |
| `ManagedBy` | `"terraform"` |
| `Phase` | `var.phase` |

### Rule: variable-driven-names

Resource names use the `{org}-{project}-{resource}` convention.

Constraints: Names, regions, and account IDs must not be hardcoded.

### Rule: secret-handling

Terraform configuration and variables must not contain secrets that enter state.

Constraints: Prefer identity-based access. When a value must be referenced, read it from SSM Parameter Store at apply time without writing it into state.

## Tooling and Validation

### function: tf-init.sh

Initializes a named Terraform layer using its consistent working directory, region, and backend configuration.

| Parameter | Required values |
|---|---|
| `layer` | `backend`, `foundation`, or `services` |

### function: tf-plan.sh

Runs Terraform planning for a named layer using `../env.tfvars` and writes `plan.out`.

| Parameter | Required values |
|---|---|
| `layer` | `backend`, `foundation`, or `services` |

### function: tf-apply.sh

Applies Terraform for a named layer using the repository's consistent layer configuration.

| Parameter | Required values |
|---|---|
| `layer` | `backend`, `foundation`, or `services` |

### Rule: provider-pinning

Terraform and AWS provider versions are pinned in `required_providers`.

### Rule: ci-validation

CI runs `terraform fmt -check` and `terraform validate` before any plan.

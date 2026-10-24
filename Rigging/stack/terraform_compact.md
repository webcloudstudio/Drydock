<!-- Compacted from Rigging/stack/terraform.md sha256=3838611f0b7a7637f9f733284bdc88e7af5d28c66958588eb24a441b89330f7f on 2026-10-24 by drydock rigging compact — regenerate with: drydock rigging compact --include-file {rel_source} -->

# Terraform Best Practices — Contract Surface

## Infrastructure Layout

### Rule: layered-root-modules

Infrastructure SHALL use independent Terraform roots:

- `infra/backend/`
- `infra/foundation/`
- `infra/services/`
- `infra/modules/`
- `infra/bin/`

Constraints: `backend` and `foundation` are one-shot or rarely changed layers; `services` is rerunnable; reusable modules reside under `modules`.

## Remote State

### config_key: terraform.backend.s3

Foundation and services SHALL use an S3 backend with DynamoDB locking.

| Key | Required value |
|---|---|
| `bucket` | `{org}-{project}-tfstate` |
| `key` | `{layer}/terraform.tfstate` |
| `region` | Configured deployment region |
| `dynamodb_table` | `{org}-{project}-tflock` |
| `encrypt` | `true` |

Constraints: The S3 bucket SHALL be versioned, encrypted, and deny public access. `foundation` and `services` SHALL never use local state.

### Rule: backend-bootstrap

`infra/backend/` SHALL create the state bucket and lock table using local state and remain on local state permanently.

Constraints: `backend` SHALL be applied once and excluded from normal pipelines. `foundation` and `services` SHALL initialize directly against S3; state migration commands SHALL not be required.

## Configuration

### config_key: terraform.variables

Terraform configurations SHALL define `org` and `project` string variables.

| Variable | Type |
|---|---|
| `org` | `string` |
| `project` | `string` |

Constraints: Resource names SHALL follow `{org}-{project}-{resource}`. Names, regions, and account IDs SHALL not be hardcoded.

### config_key: locals.common_tags

All taggable resources SHALL receive a `common_tags` map.

| Tag | Value |
|---|---|
| `Project` | `var.project` |
| `Owner` | `var.org` |
| `ManagedBy` | `"terraform"` |
| `Phase` | `var.phase` |

## Security

### Rule: secrets-not-in-state

Secrets SHALL NOT appear in `.tf` files or variables that persist them in Terraform state.

Constraints: Prefer identity-based access. Values that must be referenced SHALL be read from SSM Parameter Store at apply time and SHALL not be written into state.

## Terraform Wrappers

### function: tf-init.sh

`infra/bin/tf-init.sh` SHALL initialize a specified Terraform layer with consistent working-directory, region, and backend configuration.

| Parameter | Required values |
|---|---|
| `layer` | `backend`, `foundation`, or `services` |

### function: tf-plan.sh

`infra/bin/tf-plan.sh` SHALL plan a specified Terraform layer using `../env.tfvars` and write `plan.out`.

| Parameter | Required values |
|---|---|
| `layer` | `backend`, `foundation`, or `services` |

### function: tf-apply.sh

`infra/bin/tf-apply.sh` SHALL apply a specified Terraform layer with consistent working-directory, region, and backend configuration.

| Parameter | Required values |
|---|---|
| `layer` | `backend`, `foundation`, or `services` |

Constraints: Wrappers SHALL use strict Bash execution settings and reject missing or invalid layer arguments.

## Provider and CI Validation

### Rule: pinned-versions

Terraform and AWS provider versions SHALL be pinned in `required_providers`.

### Rule: pre-plan-validation

CI SHALL run the following before any Terraform plan:

- `terraform fmt -check`
- `terraform validate`

## Naming

### config_key: resource-names

| Resource | Required convention |
|---|---|
| State bucket | `{org}-{project}-tfstate` |
| Lock table | `{org}-{project}-tflock` |
| State key | `{layer}/terraform.tfstate` |

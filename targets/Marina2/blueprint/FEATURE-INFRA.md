# FEATURE: Infrastructure

| Field       | Value |
|-------------|-------|
| Version     | 20260621 V1 |
| Description | Layered Terraform provisions Marina's S3-backed state, durable AWS foundation, deployable services, reusable modules, wrapper scripts, and GitHub OIDC workflows as working HCL. |
| Depends On  | ARCHITECTURE.md, DATABASE.md, FEATURE-RUNTIME-PLATFORM.md |
| Provides    | terraform-backend-layer, terraform-foundation-layer, terraform-services-layer, github-oidc-deploy |
| Phase       | 2 |

## Purpose

This feature defines the entire deployable AWS broadcast plane and the workflow that applies it safely in dependency order.

## Layers

### `infra/backend/`

This layer remains on local Terraform state and creates:
- versioned S3 state bucket with SSE and public-access block
- DynamoDB lock table
- outputs for bucket and lock-table names

### `infra/foundation/`

This layer initializes directly to the S3 backend and creates:
- DynamoDB catalog table with TTL on `ttl`
- SQS voice queue and DLQ
- S3 voice bucket
- S3 share bucket
- GitHub OIDC provider and deploy role outputs

### `infra/services/`

This layer initializes directly to the S3 backend and creates:
- API Gateway HTTP API with `$default` stage
- one Lambda per handler package
- one route and AWS proxy integration per endpoint
- CloudWatch log groups
- least-privilege execution roles
- `api_url` output

## Reusable Modules

### `lambda_fn`

Inputs:
- `name`
- `source_dir`
- `env`
- `policy_json`

Creates:
- packaged Lambda function
- execution role
- attached inline policy
- CloudWatch log group

### `http_route`

Inputs:
- `api_id`
- `method`
- `path`
- `lambda_arn`

Creates:
- integration
- route with `AWS_IAM`
- invoke permission

## Wrapper Scripts

`infra/bin/` contains:
- `tf-init.sh <layer>`
- `tf-plan.sh <layer>`
- `tf-apply.sh <layer>`

Rules:
- every non-backend plan/apply passes `-var-file=../env.tfvars`
- apply order is `backend -> foundation -> services`
- `backend` never migrates to remote state

## Lambda and Route Matrix

| Lambda | Routes | Core permissions |
|--------|--------|------------------|
| `catalog-publish` | `POST /catalog` | DynamoDB write |
| `catalog-read` | `GET /catalog`, `GET /catalog/{project}` | DynamoDB query and get |
| `capabilities-read` | `GET /capabilities` | DynamoDB query and get |
| `report-ingest` | `POST /heartbeat`, `POST /events` | DynamoDB write |
| `health-read` | `GET /health/{project}` | DynamoDB query |
| `queue-submit` | `POST /queue/{queue}` | SQS send plus DynamoDB ACL read |
| `share-index` | `GET /share`, `POST /share` | DynamoDB share index read/write |

## GitHub Actions

Two workflow families exist:
- CI workflow for lint, unit tests, and Terraform validation
- deploy workflow for layered Terraform apply and Lambda deployment

Both use GitHub OIDC and no static AWS credentials.

## Verification

`bin/test_infra.sh` runs:
- `terraform fmt -check`
- `terraform validate`

Targeted verification applies to:
- `infra/backend`
- `infra/foundation`
- `infra/services`

No layer may contain comment-only stub `.tf` files.

## Acceptance Criteria

- `backend`, `foundation`, and `services` are real HCL and validate cleanly.
- `api_url` is emitted from `infra/services`.
- GitHub Actions use OIDC and do not require static AWS keys.
- Wrapper scripts enforce the documented layer order and `env.tfvars` flow.

## Guardrails

- No secrets are stored in Terraform files or Terraform state.
- `backend` remains intentionally on local state.
- `services` does not reconstruct foundation resource names when remote-state outputs are available.

## Open Questions

- Whether `services` should continue reading the catalog table name from remote state or reconstruct it from naming conventions remains an implementation choice; the V1 default is remote state.

# ARCHITECTURE: Marina

| Field       | Value |
|-------------|-------|
| Version     | 20260621 V1 |
| Description | Marina is a two-plane product with a local Flask control plane, a private AWS broadcast plane, and a single `marina` library boundary between consumers and cloud services. |
| Depends On  | COMPASS.md, DATABASE.md, FEATURE-MARINA-LIB.md |
| Provides    | local-control-plane, cloud-broadcast-plane, marina-library-boundary |
| Phase       | 1 |

## Modules

Marina is decomposed into three implementation areas:

| Area | Responsibility |
|------|----------------|
| Local control plane | Flask setup UI, local SQLite state, Git and GitHub inspection, Terraform guidance, queue drain, and guarded local project operations |
| Cloud broadcast plane | API Gateway, Lambda, DynamoDB, SQS, S3, IAM, and CloudWatch surfaces reachable through SigV4 only |
| `marina` library | The only consumer-facing cloud adapter for catalog, report, queue, and share operations |

## Plane Boundaries

### Local control plane

The local plane runs on the developer workstation and is outbound only.

Responsibilities:
- start the Flask application through an app factory
- enforce the startup git repository and `origin` remote gate
- maintain local SQLite state in `data/marina.db`
- render `/setup/*` screens and serve their backing local APIs
- publish catalog state through the `marina` library
- drain SQS queues when the local agent is alive
- run allow-listed Prototyper operations locally
- run local Whisper transcription for queued voice jobs

The local plane does not expose any inbound listener beyond the workstation-local Flask server.

### Cloud broadcast plane

The cloud plane is private, serverless, and reachable only with IAM-authenticated SigV4 requests.

Responsibilities:
- persist project catalog, capability, heartbeat, event, and ACL data in DynamoDB
- expose read and ingest routes through API Gateway and Lambda
- buffer deferred jobs through SQS
- store share and voice blobs in S3
- emit structured logs to CloudWatch
- deploy through layered Terraform only

The cloud plane does not make authorization decisions through GitHub on request paths.

## Directory Layout

The target repository layout is:

| Path | Responsibility |
|------|----------------|
| `src/marina_app/` | Flask app factory, templates, setup routes, local services, queue drain, and shared runtime code |
| `src/marina_cloud/` | Lambda handlers and shared Lambda helpers |
| `src/marina_common/` | Shared contracts, dataclasses, and configuration used by both planes |
| `infra/backend/` | One-shot local-state Terraform bootstrap for the S3 state bucket and DynamoDB lock table |
| `infra/foundation/` | Rarely changed durable AWS infrastructure |
| `infra/services/` | Routinely deployed Lambdas, API Gateway routes, and integrations |
| `infra/modules/` | Reusable Terraform modules |
| `infra/bin/` | Terraform wrapper scripts only |
| `bin/` | Verification scripts and source-tree launchers only |
| `tests/` | Pytest unit, integration, and contract suites |
| `.github/workflows/` | CI and deploy workflows using GitHub OIDC |

## Runtime Boundaries

### Local Flask boundary

The Flask application owns:
- route registration
- template rendering
- local configuration reads and writes
- subprocess-based verification helpers for Git, GitHub, Terraform, and AWS CLI
- queue-drain orchestration

Business logic stays in importable modules. Route handlers only validate request data, call application services, and shape responses.

### Lambda boundary

Each Lambda is thin:
1. parse request
2. call shared auth gate when the route is protected
3. execute one storage or queue operation
4. emit a structured log event
5. return a JSON response

Shared helper code contains:
- request parsing
- response serialization
- principal extraction
- key builders
- timestamp helpers
- shared authorization cache

### Library boundary

All cloud access goes through the `marina` package. No code outside that package imports `boto3` directly.

The library owns:
- environment resolution
- SigV4 signing
- transport retries
- typed exceptions
- direct SQS and S3 access for local drain and share flows

## Route Groupings

| Surface | Routes |
|---------|--------|
| Local setup shell | `GET /`, `GET /setup`, `GET /setup/summary`, `GET /setup/aws`, `GET /setup/terraform`, `GET /setup/github`, `GET /setup/scan`, `GET /setup/repositories`, `GET /setup/projects`, `GET /setup/settings` |
| Local setup APIs | `/api/setup/summary/status`, `/api/setup/config`, `/api/setup/aws/check-identity`, `/api/setup/aws/check-python`, `/api/setup/terraform/status`, `/api/setup/terraform/check-cli`, `/api/setup/terraform/verify-endpoint`, `/api/setup/terraform/auto-read-url`, `/api/setup/github/check-auth`, `/api/setup/github/check-ssh`, `/api/setup/github/sources`, `/api/setup/scan/status`, `/api/repositories`, `/api/repositories/sync`, `/api/repositories/download`, `/api/scan`, `/api/projects/{id}/conform` |
| Cloud catalog APIs | `POST /catalog`, `GET /catalog`, `GET /catalog/{project}`, `GET /capabilities` |
| Cloud report APIs | `POST /heartbeat`, `POST /events`, `GET /health/{project}` |
| Cloud queue and share APIs | `POST /queue/{queue}`, `GET /share`, `POST /share` |

## Infrastructure Layout

Terraform is layered in dependency order:

1. `backend/`
   Creates the versioned S3 state bucket, SSE configuration, public-access blocks, and DynamoDB lock table. This layer remains on local Terraform state.

2. `foundation/`
   Creates the catalog table with TTL on `ttl`, SQS queues and DLQs, S3 buckets, and GitHub OIDC roles. This layer uses the remote backend from first init.

3. `services/`
   Creates Lambda functions, CloudWatch log groups, API Gateway, routes, integrations, and outputs including `api_url`.

## Security Decisions

- No public inbound path exists on any home or office network.
- API Gateway uses `AWS_IAM` only.
- Identity is AWS Organization membership plus project ACL grants.
- `POST /onboard` is admin-only.
- GitHub tokens are one-time inputs for grant derivation and are never persisted.
- Queue-dispatched local operations use a fixed allow-list and sanitized arguments only.
- No secrets are stored in Terraform files, Terraform state, or repository-tracked configuration.

## Observability

Observability surfaces are:
- structured CloudWatch logs for Lambdas
- local structured logs for setup, queue drain, and local operations
- feature-specific `bin/test_*.sh` verification scripts
- `pytest` suites for the local app, the library, and Lambda handlers

## Acceptance Criteria

- The architecture separates local control-plane work, cloud broadcast work, and the `marina` library boundary.
- All local screen routes are backed by the local setup control-plane feature.
- All cloud routes are backed by named feature specifications and AWS resources.

## Guardrails

- Marina runtime behavior does not depend on modifying Prototyper.
- Application code outside the `marina` package does not import `boto3`.
- Lambda handlers remain thin and reusable helper code stays outside route functions.

## Open Questions

- None.

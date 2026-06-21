# FEATURE: Setup Control Plane

| Field       | Value |
|-------------|-------|
| Version     | 20260621 V1 |
| Description | The Setup control plane serves all `/setup/*` screens and local APIs for AWS checks, Terraform verification, GitHub source management, repository sync, project scan, and settings persistence. |
| Depends On  | FEATURE-RUNTIME-PLATFORM.md, DATABASE.md, UI-GENERAL.md, FEATURE-INFRA.md |
| Provides    | GET /, GET /setup, GET /setup/summary, GET /setup/aws, GET /setup/terraform, GET /setup/github, GET /setup/scan, GET /setup/repositories, GET /setup/projects, GET /setup/settings, GET /api/setup/summary/status, POST /api/setup/config, POST /api/setup/aws/check-identity, POST /api/setup/aws/check-python, GET /api/setup/terraform/status, GET /api/setup/terraform/check-cli, POST /api/setup/terraform/verify-endpoint, POST /api/setup/terraform/auto-read-url, POST /api/setup/github/check-auth, POST /api/setup/github/check-ssh, POST /api/setup/github/sources, DELETE /api/setup/github/sources/{id}, GET /api/setup/scan/status, GET /api/repositories, POST /api/repositories/sync, POST /api/repositories/download, POST /api/scan, POST /api/projects/{id}/conform |
| Phase       | 4 |

## Purpose

This feature is the local operator-facing control plane. It owns screen routes, local API fragments, SQLite-backed state, subprocess checks, and disk scans.

## Route Responsibilities

### Screen routes

- `/` and `/setup` redirect to `/setup/summary`
- `/setup/*` routes render full-page templates using the shared shell
- each screen route assembles its KPI state and view model from local repositories and subprocess checks

### Shared config API

`POST /api/setup/config`:
- persists settings or user-profile values
- validates field-specific rules
- returns toast or fragment feedback
- marks restart-required values in the response when applicable

### AWS checks

- `POST /api/setup/aws/check-identity` shells out to `aws sts get-caller-identity`
- `POST /api/setup/aws/check-python` runs boto3 connectivity and updates `platform_stats.python_aws_ok`

### Terraform checks

- `GET /api/setup/terraform/status` returns the current CLI, URL, and endpoint status payload for page assembly
- `GET /api/setup/terraform/check-cli` reads `terraform version`
- `POST /api/setup/terraform/verify-endpoint` pings `MARINA_API_URL`
- `POST /api/setup/terraform/auto-read-url` runs `terraform -chdir=infra/services output -raw api_url` and persists a valid HTTPS result

### GitHub checks and sources

- `POST /api/setup/github/check-auth` runs `gh auth status`
- `POST /api/setup/github/check-ssh` runs `ssh -T git@github.com`
- `POST /api/setup/github/sources` stores one source after type detection
- `DELETE /api/setup/github/sources/{id}` removes one source with confirmation when cached repos exist

### Repository inventory

- `GET /api/setup/scan/status` returns the last scan timestamp plus per-source and unmatched-local counts
- `POST /api/repositories/sync` queries every configured source and refreshes `github_repos`
- `GET /api/repositories` returns the current table fragment
- `POST /api/repositories/download` clones a repo to `PROJECTS_DIR`, preferring SSH and falling back to HTTPS

### Project scan and conform

- `POST /api/scan` rescans disk, metadata, git state, and Prototyper validation status
- `POST /api/projects/{id}/conform` dispatches the correct Prototyper action for one row

## Data Flow

Reads:
- SQLite repositories
- `PROJECTS_DIR` filesystem
- git metadata
- GitHub CLI and API responses
- Terraform CLI output
- AWS CLI and boto3 responses

Writes:
- SQLite repositories
- cloned local project directories
- local project files touched by Prototyper conform actions
- local logs

## Validation Rules

- `marina_org` matches lowercase alphanumeric plus hyphen
- `PORT` is `1024-65535`
- `MARINA_API_URL` is HTTPS when present
- `AWS_REGION` matches AWS region syntax
- `PROJECTS_DIR` may be empty only when the screen explicitly supports an unconfigured state
- repository download targets stay inside `PROJECTS_DIR`

## Verification

The control plane is verified through:
- Flask route tests for screens and local APIs
- temporary SQLite integration tests
- temp-directory scans for repository and project flows
- stubbed subprocess tests for AWS, Terraform, GitHub, and Prototyper interactions

## Acceptance Criteria

- Every Setup screen route and fragment route named in the Blueprint is implemented by the local control plane.
- Settings, source accounts, repo cache, project registry, and platform stats persist through SQLite repositories.
- GitHub sync, repo download, project scan, and conform actions operate on real local state with clear unconfigured paths.
- Terraform verification and AWS checks are read-only subprocess or library operations from the local app.

## Guardrails

- The control plane does not execute Terraform apply commands server-side.
- Download and conform actions are constrained to validated local paths and allow-listed subprocess calls.
- The control plane does not bypass repository classes for persistent writes.

## Open Questions

- None.

# SCREEN: Setup Terraform

| Field       | Value |
|-------------|-------|
| Version     | 20260621 V1 |
| Description | The Terraform Setup screen documents the layered Terraform workflow, verifies CLI availability, auto-reads `api_url`, and checks endpoint reachability. |
| Depends On  | UI-GENERAL.md, FEATURE-INFRA.md, FEATURE-SETUP-CONTROL-PLANE.md |
| Provides    | GET /setup/terraform |
| Phase       | 5 |
| Route       | /setup/terraform |
| Parent      | Main |
| Main Menu   | Setup (1) |
| Sub Menu    | Terraform (3) |
| Tab Order   | 3 |
| Consumes    | GET /api/setup/terraform/check-cli, POST /api/setup/terraform/verify-endpoint, POST /api/setup/terraform/auto-read-url, POST /api/setup/config |

## Layout

Single-column centered layout with three cards:
- Terraform CLI
- Commands to Run
- Marina API Endpoint

The header KPI is a status light.

## Interactions

- CLI status loads from `/api/setup/terraform/check-cli`
- Verify Endpoint posts to `/api/setup/terraform/verify-endpoint`
- page load may trigger `/api/setup/terraform/auto-read-url` when `MARINA_API_URL` is empty
- the `MARINA_API_URL` field saves through `/api/setup/config`

## Commands Block

The screen shows the exact layered order:
1. `tf-init.sh backend` and `tf-apply.sh backend`
2. `tf-init.sh foundation` and `tf-apply.sh foundation`
3. `tf-init.sh services` and `tf-apply.sh services`
4. `terraform -chdir=services output -raw api_url`

The block is read-only and copyable.

## Acceptance Criteria

- The screen shows Terraform CLI status without attempting installation.
- The commands block matches the documented layer order and `api_url` source.
- The screen can auto-read `api_url` from the services layer and persist it.
- Endpoint verification distinguishes reachable, timeout, and HTTP error states.

## Guardrails

- The screen never executes Terraform apply commands server-side.
- `api_url` is read from `infra/services`, not `infra/foundation`.
- The screen remains a guidance and verification surface, not a deployment runner.

## Open Questions

- None.

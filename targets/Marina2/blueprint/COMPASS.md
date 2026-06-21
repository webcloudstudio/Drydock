# COMPASS: Marina

| Field       | Value |
|-------------|-------|
| Version     | 20260621 V1 |
| Description | Marina is a local-first developer control plane that keeps machine-touching work on the operator workstation while broadcasting catalog, capability, and health state to a private AWS surface through the `marina` library. |
| Depends On  | ARCHITECTURE.md, FEATURE-MARINA-LIB.md |
| Provides    | marina-product-direction |
| Phase       | 1 |

## Compass

Marina is a local-first developer control plane for managing many conformed project repositories while broadcasting their last-known catalog, capabilities, and health to a private AWS surface that trusted organization members can read and use continuously.

All machine-touching work stays local. The cloud plane exists to publish durable read and ingest surfaces, not to run repository operations or expose inbound paths into home or office networks.

All cloud interaction is encapsulated behind the `marina` Python library so backend technology can evolve without changing local or consumer-facing callers.

## Constraints

- Local control-plane work is outbound only and runs on the developer's machine.
- The cloud plane is private, serverless, and built on API Gateway, Lambda, DynamoDB, SQS, S3, IAM, and Terraform.
- Project code outside the `marina` package does not import `boto3` directly.
- Terraform is layered into `backend/`, `foundation/`, and `services/`, with `backend/` remaining on local state and the other layers using S3 remote state with DynamoDB locking.
- Event data persists in DynamoDB with a 30-day TTL. Heartbeats are latest-only per program in Phase 1 and Phase 2.
- The setup UI is desktop-first, HTMX plus Bootstrap 5 based, and uses the shared shell and component rules in `UI-GENERAL.md`.
- Prototyper is a read-only local reference for project operations and Marina runtime behavior does not depend on modifying it.

## Acceptance Criteria

- Marina preserves the local-first split between workstation operations and cloud-broadcast state.
- Every cloud interaction reachable by application code goes through the `marina` library boundary.
- The Blueprint remains aligned to a private AWS broadcast plane and an outbound-only local control plane.

## Guardrails

- No public inbound path exists on any member local network.
- API Gateway uses IAM and SigV4 authorization only, with no anonymous access, API keys, WAF dependency, or Secrets Manager dependency.
- Identity is AWS Organization membership and per-project authorization mirrors git-repo access through ACL records plus a shared gate.
- `POST /onboard` is admin-only, GitHub tokens are one-time use, and authorization decisions are not delegated to GitHub on request paths.
- Queue-dispatched local operations use a fixed allow-list and sanitized arguments only.
- Terraform output is real working HCL and validation plus formatting checks are mandatory.
- No secrets are stored in Terraform files or Terraform state. Non-secret deploy variables live in `infra/env.tfvars`.

## Open Questions

- None.

# FEATURE: Access Control

| Field       | Value |
|-------------|-------|
| Version     | 20260621 V1 |
| Description | Marina authorizes cloud reads and writes by mirroring git-repo access into project ACL items checked through a shared cached gate. |
| Depends On  | DATABASE.md, FEATURE-MARINA-LIB.md, FEATURE-INFRA.md |
| Provides    | POST /onboard, marina-authz-gate, nightly-grant-resync |
| Phase       | 3 |

## Purpose

The access-control feature defines:
- project ACL persistence
- per-request authorization checks
- onboarding-time grant derivation
- nightly grant re-synchronization

## Request Path

Shared gate sequence:
1. API Gateway authenticates the caller with IAM.
2. The Lambda extracts `principal`, `org`, `project`, and required access.
3. The gate checks an in-process cache keyed by `(org, project, principal)`.
4. Cache misses issue `GetItem` for `PROJECT#{project}#ACL#{principal}`.
5. `readwrite` satisfies both write and read; `readonly` satisfies read only.
6. Unauthorized access returns `403` and logs a structured denial event.

Cache TTL is 5 minutes.

Org-wide `GET /catalog` is readable to any Org principal. Project detail and all writes require a grant.

## Onboarding

`POST /onboard` is admin-only.

Sequence:
1. accept a one-time GitHub token
2. call the GitHub API to enumerate accessible repos
3. map repo permissions to `readonly` or `readwrite`
4. write one ACL item per Marina project mapping
5. discard the token

No request-path GitHub call is allowed after onboarding.

## Re-Sync

A nightly scheduled job re-derives grants from repo access and updates ACL items. This keeps access current without requiring manual re-onboarding.

## Reads

- API Gateway request context
- DynamoDB ACL items
- GitHub repo-access results during onboarding and nightly re-sync only

## Writes

- DynamoDB ACL items
- structured denial logs

## Verification

`bin/test_access_control.sh` proves:
- onboarding writes correct grants
- readable project access is enforced
- non-readable project detail returns `403`
- an un-onboarded Org principal sees only the org-wide index
- no GitHub call occurs in the request path

## Acceptance Criteria

- The shared gate enforces `readonly` and `readwrite` correctly.
- ACL lookups use a 5-minute in-process cache.
- Onboarding derives grants from GitHub access and never persists GitHub tokens.
- A nightly re-sync refreshes grants outside request paths.

## Guardrails

- Members cannot self-onboard or self-grant access.
- GitHub is never consulted on protected read or write requests.
- Cache staleness does not exceed five minutes.

## Open Questions

- None.

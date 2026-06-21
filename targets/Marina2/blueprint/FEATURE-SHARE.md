# FEATURE: Share

| Field       | Value |
|-------------|-------|
| Version     | 20260621 V1 |
| Description | Marina provides a private S3-backed file share with per-user write prefixes, cross-company read access, and a DynamoDB index surface. |
| Depends On  | DATABASE.md, FEATURE-MARINA-LIB.md, FEATURE-ACCESS-CONTROL.md |
| Provides    | GET /share, POST /share, share-index |
| Phase       | 4 |

## Purpose

The share feature provides a simple company file share without passing bytes through Lambda.

## Put Flow

1. the caller uploads bytes directly to S3 through the `marina` library
2. the object key is placed under the caller-owned prefix
3. the caller registers the object through `POST /share`
4. the route writes an index row containing owner, key, size, content type, and timestamp

## List and Get Flows

### `GET /share`

Returns readable share index rows for the current project with optional prefix filtering.

### `mar.share.get(key, dest)`

Downloads bytes directly from S3 through the library.

## Access Model

- any trusted Org member may read visible share objects
- a member may write only under that member's own prefix
- public access is blocked at the bucket level
- object bytes never traverse Lambda handlers

## Reads

- DynamoDB share index rows
- S3 objects through the library
- Org membership and project ACL context

## Writes

- S3 objects through the library
- DynamoDB share index rows

## Verification

`bin/test_s3_share.sh` proves:
- member A can upload an object
- member B can read it
- member B cannot write into member A's prefix
- public reads are blocked
- the index reflects the object

## Acceptance Criteria

- Objects are stored privately in S3 and indexed separately.
- Reads work across the trusted company boundary.
- Writes are scoped to the caller-owned prefix.
- The feature does not proxy object bytes through Lambda.

## Guardrails

- No public S3 access is permitted.
- Prefix write restrictions are enforced by IAM, not by client convention alone.
- Lambda handlers manage metadata only.

## Open Questions

- Whether V1 should add a shared company-wide prefix in addition to per-user prefixes remains open.

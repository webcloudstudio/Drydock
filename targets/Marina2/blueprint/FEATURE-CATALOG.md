# FEATURE: Catalog

| Field       | Value |
|-------------|-------|
| Version     | 20260621 V1 |
| Description | Marina publishes project projections and serves private catalog and capability reads from DynamoDB through IAM-authorized routes. |
| Depends On  | DATABASE.md, FEATURE-MARINA-LIB.md, FEATURE-ACCESS-CONTROL.md |
| Provides    | POST /catalog, GET /catalog, GET /catalog/{project}, GET /capabilities |
| Phase       | 3 |

## Purpose

The catalog feature is the durable read-mostly projection of:
- project identity
- project metadata
- declared capabilities

## Publish Flow

1. The caller assembles `project_meta` and `capabilities`.
2. `POST /catalog` validates the payload.
3. The route checks `readwrite` access for the target project.
4. The handler upserts one project row and one row per capability.
5. The handler prunes capability rows that are no longer present in the payload.
6. The handler returns `{project, published_capabilities, updated_at}`.

Publish is full-projection-with-prune and idempotent.

## Read Flows

### `GET /catalog`

Returns the org-wide project index assembled from `type=project` items. This route is readable by any Org principal.

### `GET /catalog/{project}`

Returns one project subtree:
- project row
- capability rows
- latest heartbeat rows
- recent event rows

The route requires `read` access to the project.

### `GET /capabilities`

Returns readable capability rows with optional client-side tag filtering. Results are restricted to projects visible to the caller.

All read responses include `generated_at`.

## Reads

- DynamoDB project, capability, heartbeat, and event rows
- ACL grants through the shared gate

## Writes

- DynamoDB project rows
- DynamoDB capability rows
- DynamoDB capability deletes for pruned capabilities

## Verification

`bin/test_catalog_publish.sh` proves:
- initial publish writes the project and capability rows
- republish prunes dropped capabilities
- older timestamps do not overwrite newer rows
- non-write callers receive `403`

`bin/test_catalog_read.sh` proves:
- `GET /catalog` lists projects
- `GET /catalog/{project}` returns the subtree
- `GET /capabilities` filters by tags
- unreadable project detail returns `403`

## Acceptance Criteria

- Publish writes project and capability rows and prunes removed capabilities.
- Read routes return the correct catalog shapes for org index, project detail, and capabilities.
- Catalog reads use Query and GetItem patterns only.
- All catalog responses include a generation timestamp.

## Guardrails

- Publish is not diff-based in V1.
- Request-path logic does not use Scan.
- Unauthorized callers never receive project-detail or capability rows they cannot read.

## Open Questions

- Whether `GET /catalog/{project}` should inline all recent events or cap them to a bounded window remains open for delivery.

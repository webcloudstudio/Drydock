<!-- Compacted from Rigging/stack/aws-dynamodb.md sha256=45a1127f0b305082866b3ad04175b7b425e4a23a9a1fd4f3cd53990b0fc287f7 on 2026-10-24 by drydock rigging compact — regenerate with: drydock rigging compact --include-file {rel_source} -->

# AWS DynamoDB Best Practices — Contract Surface

## DynamoDB Table and Keys

### Rule: single-table-hierarchy

Use one DynamoDB table per environment with composite string keys `PK` and `SK`, encoding organization, project, and child hierarchy.

Constraints:

- `PK = ORG#{org_id}`
- `SK = PROJECT#{project}`
- `SK = PROJECT#{project}#CAP#{capability}`
- `SK = PROJECT#{project}#HB#{program}`
- `SK = PROJECT#{project}#EVT#{ts}#{ulid}`
- `SK = PROJECT#{project}#ACL#{principal}`
- Access uses `GetItem` or `Query`; no `Scan` or server-side joins.
- Project subtree queries use `PK=ORG#{org}` and `begins_with(SK,"PROJECT#{p}#")`.

### Rule: documented-access-patterns

Document every read and write with its exact key condition in `DATABASE.md`.

| Access pattern | Operation | Key condition |
|---|---|---|
| Read project and children | `Query` | `PK=ORG#{org} AND begins_with(SK,"PROJECT#{p}#")` |
| List projects in organization | `Query` | `PK=ORG#{org} AND begins_with(SK,"PROJECT#")` |
| Read capability | `GetItem` | `PK=ORG#{org}, SK=PROJECT#{p}#CAP#{c}` |
| Read latest heartbeat per program | `Query` | `PK=ORG#{org} AND begins_with(SK,"PROJECT#{p}#HB#")` |
| Read recent events newest-first | `Query` | `begins_with(SK,"PROJECT#{p}#EVT#")`, `ScanIndexForward=False` |

Constraints: Every required pattern must be served by `GetItem`, `Query`, or optionally one GSI.

## Table Configuration

### Rule: on-demand-table

Configure the table for on-demand billing with recovery and encryption enabled.

| Configuration | Required value |
|---|---|
| `billing_mode` | `PAY_PER_REQUEST` |
| `hash_key` | `PK` |
| `range_key` | `SK` |
| `PK` attribute type | `S` |
| `SK` attribute type | `S` |
| Point-in-time recovery | Enabled |
| Server-side encryption | Enabled |
| Auto-scaling | Disabled |

### Rule: ttl-expiration

Enable DynamoDB TTL for high-volume expirable items.

| Field | Requirement |
|---|---|
| Table TTL attribute | `ttl` |
| `ttl` type | Unix epoch seconds |
| Events and audit lines | Carry `ttl` |
| Durable items | Do not carry `ttl` |
| TTL value | `updated_at_epoch + retention_window` |

## Item Schema

### Rule: typed-items

Every item is JSON-serializable, self-describing, and includes required identity metadata.

| Field | Requirement |
|---|---|
| `PK` | Composite partition key |
| `SK` | Composite sort key |
| `type` | One of `project`, `capability`, `heartbeat`, `event`, `acl` |
| `updated_at` | ISO-8601 string |
| Item size | Well under 400 KB |
| Large blobs | Stored in S3; only the S3 key is stored in the item |

## Writes

### Rule: conditional-idempotent-writes

Use full-item upserts with conditions that prevent overwriting newer records.

| Operation | Constraint |
|---|---|
| Full-item upsert | Use `PutItem` |
| Ordering guard | `attribute_not_exists(SK) OR updated_at <= :now` |
| New-item test | Use `attribute_not_exists(SK)` |
| Unrelated batch writes | Use `BatchWriteItem`, maximum 25 items |
| Atomic multi-item writes | Use `TransactWriteItems` only when required |

## Indexes

### Rule: demand-driven-gsis

Add a GSI only when a documented access pattern cannot be served by the base table.

Constraints:

- Use a purpose-based name such as `gsi-{purpose}`.
- Project only required attributes with `KEYS_ONLY` or a narrow `INCLUDE`.
- Do not add speculative GSIs.

## Client Access

### Rule: cloud-client-library

Application and project code accesses DynamoDB only through the cloud client library.

Constraints:

- Do not import or call `boto3` directly for DynamoDB.
- Use cloud-client-library interfaces such as `client.catalog` and `client.report`.
- The library owns client access, key construction, retries, and pagination.

## Resource Naming

### Rule: resource-naming

Name and tag DynamoDB resources according to the project and organization conventions.

| Resource | Convention | Example |
|---|---|---|
| Table | `{project}-catalog` | `market-catalog` |
| Terraform lock table | `{org}-{project}-tflock` | `acme-market-tflock` |
| GSI | `gsi-{purpose}` | `gsi-tag` |

Constraints:

- Every resource name includes the project name.
- Every table carries `Project`, `Owner`, `ManagedBy=terraform`, and `Phase` tags.

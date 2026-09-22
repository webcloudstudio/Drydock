<!-- Compacted from Rigging/stack/aws-dynamodb.md sha256=c31f63374ec8ff19309c8c86a16f353e26d8acc0f98efcd8f00c11cd6710877c on 2026-09-20 by drydock rigging compact — regenerate with: drydock rigging compact --include-file {rel_source} -->

# AWS DynamoDB Best Practices — Contract Surface

## DynamoDB table

### Rule: single-table-hierarchy

Every environment uses one DynamoDB table with composite string keys `PK` and `SK`.

Constraints:

- `PK = ORG#{org_id}`.
- Project: `SK = PROJECT#{project}`.
- Capability: `SK = PROJECT#{project}#CAP#{capability}`.
- Heartbeat: `SK = PROJECT#{project}#HB#{program}`.
- Event: `SK = PROJECT#{project}#EVT#{ts}#{ulid}`.
- ACL: `SK = PROJECT#{project}#ACL#{principal}`.
- Hierarchical reads use `Query` with `PK` equality and `begins_with(SK, prefix)`.
- No `Scan` or server-side joins.

### Rule: documented-access-patterns

Every read and write must be documented with an exact key condition and served by `GetItem` or `Query`, optionally through one GSI.

| Access pattern | Operation | Key condition |
|---|---|---|
| Read one project and all children | `Query` | `PK=ORG#{org} AND begins_with(SK,"PROJECT#{p}#")` |
| List all projects in an organization | `Query` | `PK=ORG#{org} AND begins_with(SK,"PROJECT#")` |
| Read one capability | `GetItem` | `PK=ORG#{org}, SK=PROJECT#{p}#CAP#{c}` |
| Read heartbeats for a program | `Query` | `PK=ORG#{org} AND begins_with(SK,"PROJECT#{p}#HB#")` |
| Read recent events newest-first | `Query` | `begins_with(SK,"PROJECT#{p}#EVT#")`, `ScanIndexForward=False` |

### config_key: billing_mode

The table uses on-demand billing, point-in-time recovery, and server-side encryption.

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

### Rule: item-schema

Every item is a small JSON-serializable object with a type discriminator and update timestamp.

| Field | Required shape |
|---|---|
| `PK` | `ORG#{org_id}` |
| `SK` | Item-specific hierarchical key |
| `type` | One of `project`, `capability`, `heartbeat`, `event`, `acl` |
| `updated_at` | ISO-8601 string |
| Other attributes | JSON-serializable |
| Large blobs | Stored in S3; item contains the S3 key |

Items must remain well below DynamoDB’s 400 KB item limit.

### Rule: conditional-writes

Full-item upserts use `PutItem` with a condition preventing replacement by an older record.

Constraints:

- Condition: `attribute_not_exists(SK) OR updated_at <= :now`.
- The existence check uses `SK`, never `PK`.
- Unrelated writes may use `BatchWriteItem` with at most 25 items.
- Use `TransactWriteItems` when multiple item changes must be atomic.
- Do not perform read-modify-write without a condition.

### Rule: ttl

Expirable high-volume items carry a `ttl` Unix epoch-seconds attribute, and table TTL is enabled for `ttl`.

Constraints:

- Set `ttl = updated_at_epoch + retention_window`.
- Events and audit lines may use TTL.
- Projects, capabilities, latest heartbeats, and ACLs do not carry `ttl`.
- DynamoDB TTL configuration: `attribute_name = "ttl"`, `enabled = true`.

### Rule: secondary-indexes

A GSI exists only for a documented access pattern that the base table cannot serve.

Constraints:

- Do not add speculative GSIs.
- Use `KEYS_ONLY` or a minimal `INCLUDE` projection.
- GSI names follow `gsi-{purpose}`.

### Rule: cloud-client-access

Application and project code accesses DynamoDB only through the cloud client library.

Constraints:

- Call the cloud client library through interfaces such as `client.catalog` and `client.report`.
- Do not import or call raw `boto3` for DynamoDB.
- The client library owns key construction, retries, and pagination.

### Rule: resource-naming

DynamoDB resources use project-qualified names and standard tags.

| Resource | Convention | Example |
|---|---|---|
| Table | `{project}-catalog` | `market-catalog` |
| Terraform lock table | `{org}-{project}-tflock` | `acme-market-tflock` |
| GSI | `gsi-{purpose}` | `gsi-tag` |

Every table must include the standard tags `Project`, `Owner`, `ManagedBy=terraform`, and `Phase`.

# AWS DynamoDB Best Practices

**Version:** 20260528 V1
**Description:** DynamoDB single-table design for hierarchical catalog/state data accessed through a cloud client library (never raw boto3)

Technology reference for Amazon DynamoDB with Python. This file does not change between projects.

Prerequisites: `stack/python.md`, `stack/cloud-client-library.md`

DynamoDB is correct here because the data is **simple, hierarchical, and never joined on the server**.
It is one tree of objects per organization, read as a subtree and assembled client-side. Used this way
it costs cents per month on-demand and never idles. Used wrong — scans, ad-hoc cross-entity joins,
hot partitions — it is painful and expensive. The rules below keep it on the right side of that line.

---

## 1. Single-Table, Hierarchical Keys

**Rule**: One table per environment. Every item carries a composite primary key `PK` (partition) and
`SK` (sort). Model the hierarchy in the keys so a single `Query` returns a whole subtree in `SK` order.
Never design an access pattern that requires a `Scan` or a server-side join.

```
PK = ORG#{org_id}                         # partition = one organization (the tenant boundary)
SK = PROJECT#{project}                    # a project under the org
SK = PROJECT#{project}#CAP#{capability}   # a capability under a project
SK = PROJECT#{project}#HB#{program}       # latest heartbeat for a program
SK = PROJECT#{project}#EVT#{ts}#{ulid}    # an event, time-sortable
SK = PROJECT#{project}#ACL#{principal}    # access-control grant
```

A `Query` on `PK = ORG#acme` with `begins_with(SK, "PROJECT#market#")` returns that project and all of
its children in one call. The client assembles the tree; the database never joins.

**Why**: Co-locating a tree under one partition key turns "read everything about this project" into a
single, cheap, strongly-orderable query. Hierarchy in the `SK` is what makes `begins_with` prefix reads
the primary access pattern and removes any need for scans.

---

## 2. Document Every Access Pattern Before Modeling Keys

**Rule**: A `DATABASE.md` must list every read and write as an access pattern with the exact key
condition it uses. If a required pattern cannot be served by `GetItem` or `Query` (with optionally one
GSI), the model is wrong — fix the keys, do not reach for `Scan`.

| # | Access pattern | Operation | Key condition |
|---|---|---|---|
| 1 | Read one project + all children | Query | `PK=ORG#{org} AND begins_with(SK,"PROJECT#{p}#")` |
| 2 | List all projects in an org | Query | `PK=ORG#{org} AND begins_with(SK,"PROJECT#")` |
| 3 | Read one capability | GetItem | `PK=ORG#{org}, SK=PROJECT#{p}#CAP#{c}` |
| 4 | Latest heartbeat per program | Query | `PK=ORG#{org} AND begins_with(SK,"PROJECT#{p}#HB#")` |
| 5 | Recent events newest-first | Query | `... begins_with(SK,"PROJECT#{p}#EVT#"), ScanIndexForward=False` |

**Why**: DynamoDB rewards designs derived from known access patterns and punishes relational habits.
Writing the patterns first guarantees the keys serve them with `Query`/`GetItem` only.

---

## 3. On-Demand Billing, No Provisioned Capacity

**Rule**: Use `PAY_PER_REQUEST` (on-demand). Do not provision RCUs/WCUs at this scale. Enable
point-in-time recovery (PITR) on the table; leave auto-scaling off (it does not apply to on-demand).

```hcl
# Terraform (see stack/terraform.md)
resource "aws_dynamodb_table" "catalog" {
  name         = "${var.project}-catalog"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "PK"
  range_key    = "SK"

  attribute { name = "PK" type = "S" }
  attribute { name = "SK" type = "S" }

  point_in_time_recovery { enabled = true }
  server_side_encryption { enabled = true }

  tags = local.common_tags
}
```

**Why**: On-demand has zero idle cost and absorbs sporadic bursts without capacity planning. At a few
projects and light traffic the bill is cents. PITR is the cheap insurance against a bad write.

---

## 4. Items Are Small, Typed, Self-Describing

**Rule**: Every item has a `type` attribute (`project`, `capability`, `heartbeat`, `event`, `acl`) and
an `updated_at` ISO-8601 string. Keep items well under the 400 KB limit — a catalog item is a few KB.
Store JSON-serializable attributes only. Large blobs (audio, files) go in S3; store the S3 key here.

```json
{
  "PK": "ORG#acme",
  "SK": "PROJECT#market#CAP#download_prices",
  "type": "capability",
  "project": "market",
  "name": "download_prices",
  "description": "Download historical market prices",
  "tags": ["finance", "etl"],
  "transports": ["cli", "rest"],
  "owners": ["ed"],
  "access": "readwrite",
  "updated_at": "2026-05-28T14:00:00Z"
}
```

**Why**: A `type` discriminator lets the client route items without parsing keys. Keeping blobs in S3
keeps items small, queries fast, and write costs low (write cost scales with item size).

---

## 5. Idempotent Writes With Condition Expressions

**Rule**: Use `PutItem` for full-item upserts (publish overwrites the current projection). Use condition
expressions to enforce invariants (e.g. do not overwrite a newer record). Never read-modify-write
without a condition. Batch unrelated writes with `BatchWriteItem` (≤25 items); use `TransactWriteItems`
only when several items must change atomically.

```python
# Access is ALWAYS through the cloud client library — shown here for the rule only.
table.put_item(
    Item=item,
    ConditionExpression="attribute_not_exists(SK) OR updated_at <= :now",
    ExpressionAttributeValues={":now": item["updated_at"]},
)
```

Use `attribute_not_exists(SK)` — the unique key within the partition — for the "item does not yet exist"
test. `attribute_not_exists(PK)` is wrong: `PK` is shared across every item in the partition and is
always present once any item exists, so it silently disables the guard.

**Why**: Publish is naturally a full-projection overwrite; conditions make it safe under concurrent
publishers and out-of-order retries without a read step.

---

## 5a. TTL for High-Volume, Expirable Items

**Rule**: Items that accumulate and have a natural lifetime (events, audit lines) carry a `ttl`
attribute — Unix epoch seconds — and the table has DynamoDB TTL enabled against it. Set `ttl =
updated_at_epoch + retention_window` on write (e.g. 30 days for events). Durable items (project,
capability, latest-heartbeat, ACL) carry no `ttl`.

```hcl
ttl { attribute_name = "ttl" enabled = true }
```

**Why**: TTL deletes expired items at no cost, bounding item count and read cost without a cleanup job.
Scoping `ttl` to high-volume items keeps the catalog itself permanent.

---

## 6. GSIs Only When an Access Pattern Demands One

**Rule**: Add a Global Secondary Index only to serve a documented pattern the base table cannot
(e.g. "all capabilities across all projects with tag X"). Project only the attributes that pattern
needs (`KEYS_ONLY` or a tight `INCLUDE`). At Phase 1/2 the base table serves everything — do not add a
GSI speculatively.

**Why**: Each GSI is a second copy of (part of) the table with its own write cost. Unused GSIs are pure
overhead. The hierarchical base key already serves the Phase 1/2 patterns.

---

## 7. Access Only Through the Cloud Client Library

**Rule**: Application and project code never imports `boto3` for DynamoDB. It calls the cloud client
library (`client.catalog`, `client.report`), which owns the client, key construction, retries, and
pagination. This is the swap layer (see `stack/cloud-client-library.md`).

**Why**: Centralizing key construction prevents key-format drift across callers and lets the storage
backend change (DynamoDB → another store) without touching consumers.

---

## Naming Standard

| Resource | Convention | Example |
|---|---|---|
| Table | `{project}-catalog` | `market-catalog` |
| Lock table (Terraform state) | `{org}-{project}-tflock` | `acme-market-tflock` |
| GSI | `gsi-{purpose}` | `gsi-tag` |

Every resource includes the project name. Tag every table with the standard tag set
(`Project`, `Owner`, `ManagedBy=terraform`, `Phase`).

---

## Summary Checklist

- [ ] Single table, composite `PK`/`SK`, hierarchy encoded in keys
- [ ] Every access pattern documented; served by `GetItem`/`Query` only — no `Scan`, no server join
- [ ] `PAY_PER_REQUEST` billing; PITR and SSE enabled
- [ ] Items carry `type` + `updated_at`; blobs in S3, not in items
- [ ] Writes idempotent via condition expressions (existence test on `SK`, never `PK`)
- [ ] `ttl` attribute + DynamoDB TTL on high-volume expirable items (events); durable items carry none
- [ ] GSIs added only for a documented pattern, with minimal projection
- [ ] All access through the cloud client library, never raw boto3
- [ ] Table name includes project; standard tags applied

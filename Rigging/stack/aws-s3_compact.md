<!-- Compacted from Rigging/stack/aws-s3.md sha256=a561b82502340d92052a54485a37225a3c5271c14df839d4fa5d7436bc253eb5 on 2026-09-20 by drydock rigging compact — regenerate with: drydock rigging compact --include-file {rel_source} -->

# AWS S3 Best Practices — Contract Surface

## S3 Access

### Rule: public-access-block

Every S3 bucket must block all public access.

Constraints: Set `block_public_acls`, `block_public_policy`, `ignore_public_acls`, and `restrict_public_buckets` to `true`; allow access only through IAM and SigV4; do not expose public buckets, objects, or anonymous presigned URLs.

### Rule: encryption-versioning

S3 buckets must use server-side encryption and required recovery controls.

Constraints: Enable SSE-S3 or SSE-KMS by default; enable versioning on the share bucket; expire noncurrent versions through a lifecycle rule.

### Rule: share-prefix-layout

The company share must use one bucket partitioned by member and shared prefixes.

Constraints: Use `users/{member}/...` for member files and optionally `shared/...` for company-wide files.

### client.share.put

Stores an object in the current member’s share prefix.

| Input | Requirement |
|---|---|
| Object data and key | Written under `users/{current_member}/` |

Constraints: Writes must be confined to the current member’s prefix and enforced by IAM.

### client.share.list

Lists readable objects in the company share.

Constraints: May read keys under any `users/*` or `shared/*` prefix.

### client.share.get

Retrieves a readable object from the company share.

Constraints: May read keys under any `users/*` or `shared/*` prefix.

### Rule: iam-scope

Member IAM permissions must allow bucket-wide reads but restrict writes to the member’s own prefix.

Constraints: Allow `s3:GetObject` and `s3:ListBucket` for the whole share bucket; allow `s3:PutObject` and `s3:DeleteObject` only on `users/${aws:username}/*`.

### Rule: object-key-indexing

S3 object keys must be stored in the relevant DynamoDB item.

Constraints: Use DynamoDB to discover object keys, then retrieve objects from S3; do not scan or parse S3 listings for discovery.

### Rule: cloud-client-library

Project code must access S3 through the cloud client library.

Constraints: Use `client.share.put`, `client.share.get`, and `client.share.list`; keep bucket names and the S3 client inside the library.

## Bucket Configuration

### config_key: share-bucket-name

The share bucket name identifies the organization and project.

Constraints: Use `{org}-{project}-share`.

### config_key: blob-bucket-name

Blob bucket names identify the organization, project, and purpose.

Constraints: Use `{org}-{project}-{purpose}`.

### config_key: state-bucket-name

Terraform state bucket names identify the organization and project.

Constraints: Use `{org}-{project}-tfstate`.

### Rule: bucket-tags

Every bucket must use standard tags.

### Rule: bucket-name-uniqueness

Bucket names must be globally unique.

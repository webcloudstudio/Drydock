<!-- Compacted from Rigging/stack/aws-s3.md sha256=ebc3716d1d6f5b1a9c85e216970288adde6d9baeede4d1f32730f074a057cfc0 on 2026-10-24 by drydock rigging compact — regenerate with: drydock rigging compact --include-file {rel_source} -->

# AWS S3 Best Practices — Contract Surface

## Cloud Client Library

### client.share.put

Writes an object under the current member's user prefix.

Constraints: Keys must use `users/{current_member}/`; writes outside the current member's prefix are prohibited.

### client.share.list

Lists objects in the company share.

Returns: Objects under any `users/*` or `shared/*` key.

### client.share.get

Reads an object from the company share.

Returns: Object data for keys under any `users/*` or `shared/*` key.

### Rule: access-through-cloud-client-library

Project code accesses S3 through `client.share.put`, `client.share.get`, and `client.share.list`; bucket names and the S3 client are not exposed to project code.

## Storage Configuration

### config_key: share_bucket

Configures the share bucket name.

Constraints: The name follows `{org}-{project}-share`.

### config_key: blob_bucket

Configures a blob storage bucket name.

Constraints: The name follows `{org}-{project}-{purpose}`.

### config_key: state_bucket

Configures the Terraform state bucket name.

Constraints: The name follows `{org}-{project}-tfstate`.

### Rule: bucket-security

Every bucket enables `block_public_acls`, `block_public_policy`, `ignore_public_acls`, and `restrict_public_buckets`.

Constraints: Access is exclusively through IAM and SigV4; no public website, public object, or anonymous presigned URL is permitted.

### Rule: encryption-versioning

Buckets use SSE-S3 or SSE-KMS by default; the share bucket enables versioning and expires noncurrent versions through a lifecycle rule.

### Rule: iam-scope

Members have bucket-wide `s3:GetObject` and `s3:ListBucket` access, while `s3:PutObject` and `s3:DeleteObject` are restricted to `users/${aws:username}/*`.

### Rule: object-catalog

S3 object keys are stored in the relevant DynamoDB item and retrieved through DynamoDB lookup followed by `GetObject`; bucket scans are not used for discovery.

### Rule: share-layout

The share bucket uses `users/{member}/...` prefixes and may include a `shared/...` prefix.

### Rule: bucket-tags

Standard tags are applied to every bucket.

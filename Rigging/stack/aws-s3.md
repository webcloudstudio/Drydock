# AWS S3 Best Practices

**Version:** 20260528 V1
**Description:** S3 for blob storage and a simple per-user company file share — private, encrypted, prefix-scoped

Technology reference for Amazon S3 with Python (via the `marina` library). This file does not change
between projects.

Prerequisites: `stack/python.md`, `stack/marina-library.md`

S3 plays two small roles in Marina: it holds blobs that do not belong in DynamoDB (e.g. VoiceForward
audio), and it backs a deliberately simple "company share" — each member has a prefix, and members can
read each other's shared files. Nothing in S3 is ever public.

---

## 1. Block All Public Access, Always

**Rule**: Every bucket sets `block_public_acls`, `block_public_policy`, `ignore_public_acls`, and
`restrict_public_buckets` all `true`. Access is exclusively via IAM and SigV4. There is no public
website, no public object, no presigned URL handed to anonymous users.

```hcl
resource "aws_s3_bucket_public_access_block" "share" {
  bucket                  = aws_s3_bucket.share.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}
```

**Why**: Public S3 buckets are the canonical cloud data leak. Marina's no-public-inbound rule applies to
storage as much as to the API.

---

## 2. Encryption and Versioning On

**Rule**: Enable server-side encryption (SSE-S3 or SSE-KMS) by default and enable versioning on the
share bucket so an overwrite or delete is recoverable. Add a lifecycle rule to expire noncurrent
versions (e.g. 90 days) to cap cost.

**Why**: Encryption-at-rest is table stakes. Versioning turns "I overwrote my colleague's file" into a
recoverable event; lifecycle expiry keeps version sprawl from accumulating cost.

---

## 3. Prefix-Per-User Layout

**Rule**: The company share uses one bucket partitioned by member prefix. Reads across the company are
allowed; writes are confined to your own prefix.

```
marina-{project}-share/
  users/{member}/...        # member writes only here
  shared/...                # optional company-wide drop space
```

`marina.share.put()` writes under `users/{current_member}/`; `marina.share.list()` and `get()` may read
any `users/*` or `shared/*` key.

**Why**: One bucket with prefixes is the simplest model that still isolates write authority. It matches
the "lame/simple share with your company" requirement without per-user buckets.

---

## 4. IAM Scopes Write to Own Prefix, Read to the Bucket

**Rule**: The member's IAM policy grants `s3:GetObject`/`s3:ListBucket` on the whole share bucket but
`s3:PutObject`/`s3:DeleteObject` only on `users/${aws:username}/*`. Enforce write confinement in IAM,
not just in library code.

```json
{
  "Effect": "Allow",
  "Action": ["s3:PutObject", "s3:DeleteObject"],
  "Resource": "arn:aws:s3:::marina-market-share/users/${aws:username}/*"
}
```

**Why**: Library-side checks are convenience; IAM is the real boundary. A member cannot overwrite
another's files even if they bypass the library.

---

## 5. Keys Are Opaque; Metadata Lives in DynamoDB

**Rule**: Store the S3 object key in the relevant DynamoDB item (e.g. a VoiceForward job references its
audio key). S3 holds bytes; DynamoDB holds the catalog/index. Do not list-and-parse S3 to find things —
query DynamoDB for the key, then `GetObject`.

**Why**: S3 `LIST` is slow and eventually consistent for discovery; DynamoDB is the index. Keeping the
key in the item avoids scanning the bucket.

---

## 6. Access Through the Marina Library

**Rule**: Project code calls `mar.share.put/get/list`; VoiceForward and other features call the same
library for blob storage. Bucket names and the boto3 S3 client live inside `marina`.

**Why**: Same swap-layer rule as everywhere — one place owns the bucket name and client.

---

## Naming Standard

| Resource | Convention | Example |
|---|---|---|
| Share bucket | `marina-{project}-share` | `marina-market-share` |
| Blob bucket | `marina-{project}-{purpose}` | `marina-market-voice` |
| State bucket (Terraform) | `marina-{project}-tfstate` | `marina-market-tfstate` |

Bucket names are globally unique — the project prefix helps. Apply standard Marina tags to every bucket.

---

## Summary Checklist

- [ ] Public access fully blocked on every bucket
- [ ] SSE and versioning on; lifecycle expiry for noncurrent versions
- [ ] Share bucket partitioned by member prefix (`users/{member}/`)
- [ ] IAM allows bucket-wide read but write only to own prefix
- [ ] Object keys indexed in DynamoDB; no bucket scans for discovery
- [ ] All access through `marina.share`; bucket names not in project code
- [ ] Bucket name includes project; standard tags applied

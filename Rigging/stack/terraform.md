# Terraform Best Practices

**Version:** 20260528 V1
**Description:** Layered Terraform with an S3 + DynamoDB remote backend, bash wrappers, and one-shot vs rerun-anytime separation

Technology reference for provisioning AWS with Terraform. This file does not change between projects.

Prerequisites: `stack/aws-dynamodb.md` (lock table), `stack/aws-s3.md` (state bucket)

All cloud infrastructure is Terraform. Nothing is created in the console. The layout separates
**one-shot foundational** state (networking, the DynamoDB table, IAM/OIDC roles, buckets) from
**rerun-anytime** state (Lambdas, API Gateway) so routine code deploys never risk the foundation.

---

## 1. Layered Directory Structure

**Rule**: Split infrastructure into independent root modules, each with its own state. Foundational
layers change rarely and are applied deliberately; the services layer is applied on most deploys.

```
infra/
  backend/        # one-shot bootstrap: S3 state bucket + DynamoDB lock table (LOCAL state here only)
  foundation/     # rare: DynamoDB catalog table, IAM/OIDC roles, SQS queues, S3 buckets, networking
  services/       # rerun-anytime: Lambdas, API Gateway, integrations, wiring
  modules/        # reusable modules (lambda_fn, http_route, ...)
  bin/            # tf-init.sh / tf-plan.sh / tf-apply.sh <layer>
```

**Why**: Separate state per layer means a Lambda change cannot accidentally destroy the catalog table,
and `plan` diffs stay small and readable. Reusable modules keep the per-function boilerplate in one
place.

---

## 2. Remote Backend: S3 State, DynamoDB Lock

**Rule**: State lives in S3 (versioned, encrypted, public-access blocked); locking uses a DynamoDB
table. State is **never** local for `foundation/` or `services/`. (The state itself is the S3 object;
DynamoDB holds only the lock — this is the canonical pattern behind "state must not be local.")

```hcl
# infra/services/backend.tf
terraform {
  backend "s3" {
    bucket         = "acme-market-tfstate"
    key            = "services/terraform.tfstate"
    region         = "us-east-1"
    dynamodb_table = "acme-market-tflock"
    encrypt        = true
  }
}
```

**Why**: Remote state enables collaboration and pipelines; the DynamoDB lock prevents two applies from
corrupting state. S3 versioning lets you recover a clobbered state file.

---

## 3. The Bootstrap Chicken-and-Egg

**Rule**: `infra/backend/` creates the state bucket and lock table using **local** state and is applied
once; it **stays on local state permanently** (never migrated). `foundation/` and `services/` configure
the S3 backend from their very first `init`, pointing at the bucket/lock `backend/` created — so there is
**no `terraform state mv` / `terraform init -migrate-state` step**. Commit the `backend/` local state or
document re-import; do not let normal pipelines run `backend/`.

```
1. cd infra/backend && terraform init && terraform apply   # local state, one time, kept local
2. cd infra/foundation && terraform init -backend-config=...  # S3 backend from first init
3. cd infra/services   && terraform init -backend-config=...  # S3 backend from first init
```

**Why**: The backend cannot store its own creation in a backend that does not yet exist. Keeping
`backend/` on local state and initialising the other layers directly against S3 resolves the cycle with
no migration step to get wrong.

---

## 4. Variables, Locals, and the Standard Tag Set

**Rule**: No hardcoded names, regions, or account IDs. An `org` + `project` variable pair feeds the
`{org}-{project}-{resource}` naming convention. A `locals.common_tags` map is applied to every
taggable resource.

```hcl
variable "project" { type = string }
variable "org"     { type = string }

locals {
  common_tags = {
    Project   = var.project
    Owner     = var.org
    ManagedBy = "terraform"
    Phase     = var.phase
  }
}
```

**Why**: Variable-driven naming makes the same modules serve every project; a uniform tag set makes
cost allocation and cleanup possible.

---

## 5. No Secrets in State or Code

**Rule**: Never put secrets in `.tf` files or variables that land in state. Prefer identity-based access
(SigV4 identity, no API keys) where the system permits it. Where a value must be referenced, read it
from SSM Parameter Store at apply time — do not write it into state.

**Why**: Terraform state is plaintext JSON in S3. Anything in it is readable by anyone with state
access. Identity-based auth often removes the need for stored secrets.

---

## 6. Bash Wrappers, Pinned Versions, Format/Validate Gates

**Rule**: Drive Terraform through `infra/bin/` wrappers (`tf-init.sh`, `tf-plan.sh`, `tf-apply.sh`) that
take a layer name and set the working directory, region, and backend config consistently. Pin the
Terraform and AWS provider versions in `required_providers`. CI runs `terraform fmt -check` and
`terraform validate` before any plan.

```bash
# infra/bin/tf-plan.sh
#!/bin/bash
set -euo pipefail
layer="${1:?usage: tf-plan.sh <backend|foundation|services>}"
cd "$(dirname "$0")/../$layer"
terraform plan -var-file=../env.tfvars -out=plan.out
```

**Why**: Wrappers stop "ran apply in the wrong directory" mistakes; version pinning prevents provider
drift; fmt/validate gates catch errors before they reach a plan.

---

## Naming Standard

| Resource | Convention | Example |
|---|---|---|
| State bucket | `{org}-{project}-tfstate` | `acme-market-tfstate` |
| Lock table | `{org}-{project}-tflock` | `acme-market-tflock` |
| State key | `{layer}/terraform.tfstate` | `services/terraform.tfstate` |

---

## Summary Checklist

- [ ] Layered roots: `backend/`, `foundation/`, `services/`, shared `modules/`
- [ ] S3 backend (versioned, encrypted) + DynamoDB lock; no local state beyond `backend/`
- [ ] `backend/` bootstrapped once with local state; excluded from normal pipelines
- [ ] All names variable-driven via `{org}-{project}-{resource}`; standard tags applied
- [ ] No secrets in state or `.tf`; SSM read at apply time if needed
- [ ] `infra/bin/` wrappers used; provider versions pinned; `fmt -check` + `validate` in CI

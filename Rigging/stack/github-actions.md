# GitHub Actions Best Practices

**Version:** 20260528 V1
**Description:** CI/CD pipelines that assume AWS roles via OIDC (no static keys), gate on lint/test, and run Terraform plan-on-PR / apply-on-merge

Technology reference for GitHub Actions pipelines deploying a project to AWS. This file does not change
between projects.

Prerequisites: `stack/terraform.md`, `stack/python.md`

Pipelines are GitHub Actions because they are transparent to the members reading the repo. The hard rule
is **no static AWS keys** anywhere — workflows assume a least-privilege role via OIDC. Every change is
linted and tested before a plan; applies are gated.

---

## 1. OIDC Role Assumption, No Static Keys

**Rule**: Never store `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` as secrets. Configure a GitHub OIDC
identity provider in AWS and a deploy role with a trust policy scoped to this repo (and ideally a
specific branch/environment). Workflows assume it with `aws-actions/configure-aws-credentials`.

```yaml
permissions:
  id-token: write        # required for OIDC
  contents: read

steps:
  - uses: aws-actions/configure-aws-credentials@v4
    with:
      role-to-assume: arn:aws:iam::${{ vars.AWS_ACCOUNT_ID }}:role/${{ vars.PROJECT }}-deploy
      aws-region: ${{ vars.AWS_REGION }}
```

**Why**: OIDC issues short-lived credentials per run with no long-lived secret to leak or rotate. The
trust policy scoped to the repo (`token.actions.githubusercontent.com:sub =
repo:{org}/{repo}:ref:refs/heads/main` for deploys) means only this repository's `main` workflows can
assume the role. Confirmed sufficient — no static keys anywhere.

---

## 2. Lint and Test Gate Before Any Deploy

**Rule**: A `ci` job runs `ruff check`, `ruff format --check`, and `pytest` (with `uv sync --frozen`) on
every push and PR. Deploy jobs `needs: ci` — code that fails lint or tests never reaches a plan.

```yaml
jobs:
  ci:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v5
      - run: uv sync --frozen
      - run: uv run ruff check . && uv run ruff format --check .
      - run: uv run pytest -v
```

**Why**: Gating deploys on green CI keeps broken code out of AWS. `uv sync --frozen` guarantees the
locked dependency set, matching local builds exactly.

---

## 3. Terraform: Plan on PR, Gated Apply on Merge

**Rule**: On a PR, run `terraform plan` per changed layer and post the plan as a PR comment for review.
`terraform apply` runs only on merge to the default branch, and only for the `services/` layer
automatically — `foundation/` applies require a manual `workflow_dispatch` with an environment approval.

```yaml
  plan:
    needs: ci
    if: github.event_name == 'pull_request'
    steps:
      - run: ./infra/bin/tf-plan.sh services

  apply:
    needs: ci
    if: github.ref == 'refs/heads/main' && github.event_name == 'push'
    environment: production            # requires reviewer approval
    steps:
      - run: ./infra/bin/tf-apply.sh services
```

**Why**: Plan-on-PR makes infrastructure changes reviewable as diffs. Auto-applying only `services/`
(Lambdas, API routes) keeps routine deploys fast while protecting the foundation behind a manual gate
with approval.

---

## 4. One Workflow Concern Per File; Least-Privilege Permissions

**Rule**: Keep `ci.yml`, `deploy.yml`, and any `bootstrap.yml` separate. Set top-level `permissions` to
the minimum (`contents: read`, add `id-token: write` only where OIDC is used, `pull-requests: write`
only where commenting). Pin actions to a major version or SHA.

**Why**: Separate files keep triggers and permissions legible. Minimal token permissions limit what a
compromised action can do; pinning prevents a hijacked tag from running arbitrary code.

---

## 5. Concurrency Control and Required Status Checks

**Rule**: Use a `concurrency` group keyed on the workflow + ref to cancel superseded runs and prevent
overlapping applies. Mark `ci` (and `plan`) as required status checks on the default branch in repo
settings.

```yaml
concurrency:
  group: deploy-${{ github.ref }}
  cancel-in-progress: false      # never cancel an in-flight apply
```

**Why**: Concurrency control stops two applies racing on the same state (even with the DynamoDB lock,
serialize at the pipeline). Required checks make the green-CI gate unbypassable.

---

## Naming Standard

| Item | Convention | Example |
|---|---|---|
| Deploy role | `{project}-deploy` | `market-deploy` |
| Workflow files | `ci.yml`, `deploy.yml`, `bootstrap.yml` | — |
| Repo variables | `AWS_ACCOUNT_ID`, `AWS_REGION`, `PROJECT` | — |

---

## Summary Checklist

- [ ] OIDC role assumption; zero static AWS keys in secrets
- [ ] `ci` job runs ruff + pytest with `uv sync --frozen`; deploys `needs: ci`
- [ ] `terraform plan` on PR (posted as comment); `apply` only on merge
- [ ] `foundation/` apply behind manual dispatch + environment approval; `services/` auto on merge
- [ ] One concern per workflow; least-privilege `permissions`; actions pinned
- [ ] `concurrency` group prevents overlapping applies; CI is a required check
- [ ] Deploy role name includes project

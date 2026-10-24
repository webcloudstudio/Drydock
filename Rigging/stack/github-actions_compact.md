<!-- Compacted from Rigging/stack/github-actions.md sha256=bb9a0a58f9280196377196a8489acd2d1d14376ac38031f86efc41f2172dcbd1 on 2026-10-24 by drydock rigging compact — regenerate with: drydock rigging compact --include-file {rel_source} -->

# GitHub Actions Best Practices — Contract Surface

## AWS Authentication

### Rule: OIDC-role-assumption

GitHub Actions workflows assume AWS deploy roles through GitHub OIDC.

Constraints: Do not store `AWS_ACCESS_KEY_ID` or `AWS_SECRET_ACCESS_KEY` as secrets. Configure `id-token: write` and `contents: read` permissions, and use `aws-actions/configure-aws-credentials@v4` with `role-to-assume: arn:aws:iam::${{ vars.AWS_ACCOUNT_ID }}:role/${{ vars.PROJECT }}-deploy` and `aws-region: ${{ vars.AWS_REGION }}`. Scope the AWS trust policy to the repository and deploy branch or environment.

## CI

### Rule: ci-gate

A `ci` job validates every push and pull request before deployment.

Constraints: Run on `ubuntu-latest`; check out with `actions/checkout@v4`; install with `astral-sh/setup-uv@v5`; run `uv sync --frozen`, `uv run ruff check .`, `uv run ruff format --check .`, and `uv run pytest -v`. Deploy jobs must declare `needs: ci`.

## Terraform Deployment

### Rule: pull-request-plan

Pull requests run `terraform plan` for each changed infrastructure layer and post the plan as a pull-request comment.

Constraints: The plan job must depend on `ci` and run only when `github.event_name == 'pull_request'`. Use `./infra/bin/tf-plan.sh services` for the services layer.

### Rule: merge-apply

Terraform apply runs after a merge to the default branch.

Constraints: The apply job must depend on `ci`, run only when `github.ref == 'refs/heads/main' && github.event_name == 'push'`, and use the `production` environment. Apply `services/` automatically with `./infra/bin/tf-apply.sh services`; apply `foundation/` only through `workflow_dispatch` with environment approval.

## Workflow Configuration

### Rule: workflow-separation

Workflow concerns are separated into `ci.yml`, `deploy.yml`, and optional `bootstrap.yml`.

Constraints: Set top-level permissions to the minimum required: `contents: read`, `id-token: write` only for OIDC, and `pull-requests: write` only for plan commenting. Pin actions to a major version or SHA.

### Rule: concurrency-control

Workflows serialize deployments by ref and cancel superseded runs according to the workflow policy.

Constraints: Configure `concurrency.group` as `deploy-${{ github.ref }}` and `cancel-in-progress: false`.

### Rule: required-status-checks

The default branch requires `ci` and `plan` as status checks.

## Naming

### config_key: AWS_ACCOUNT_ID

Repository variable containing the AWS account identifier.

### config_key: AWS_REGION

Repository variable containing the AWS region.

### config_key: PROJECT

Repository variable containing the project name.

Constraints: The deploy role name must be `{project}-deploy`; workflow files must use `ci.yml`, `deploy.yml`, and `bootstrap.yml`.

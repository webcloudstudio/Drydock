<!-- Compacted from Rigging/stack/github-actions.md sha256=088fa1f912cda2495df0d584a941b0700fd2f631ff6ef4ce6e42c49a37e64ae1 on 2026-09-20 by drydock rigging compact — regenerate with: drydock rigging compact --include-file {rel_source} -->

# GitHub Actions Best Practices — Contract Surface

## AWS OIDC

### config_key `permissions`

GitHub Actions workflows configure permissions required for repository access and OIDC authentication.

| Key | Value | Required when |
|---|---|---|
| `id-token` | `write` | Assuming an AWS role through OIDC |
| `contents` | `read` | All workflows |
| `pull-requests` | `write` | Posting Terraform plans as PR comments |

Constraints: Do not store `AWS_ACCESS_KEY_ID` or `AWS_SECRET_ACCESS_KEY` as secrets. AWS trust policy scopes deployment access to this repository and deployment branch or environment.

### config_key `aws-actions/configure-aws-credentials`

Workflows assume the project deployment role using GitHub OIDC.

| Input | Value |
|---|---|
| `role-to-assume` | `arn:aws:iam::${{ vars.AWS_ACCOUNT_ID }}:role/${{ vars.PROJECT }}-deploy` |
| `aws-region` | `${{ vars.AWS_REGION }}` |

Constraints: The deployment role uses the `{project}-deploy` naming convention.

## CI Workflow

### Rule: ci-gate

A `ci` job validates every push and pull request before deployment.

Constraints: The job runs on `ubuntu-latest`, checks out the repository, runs `uv sync --frozen`, executes `uv run ruff check .`, `uv run ruff format --check .`, and `uv run pytest -v`. Deploy and plan jobs declare `needs: ci`.

## Terraform Deployment

### Rule: pull-request-plan

Pull requests run `terraform plan` for each changed infrastructure layer and post the plan as a PR comment.

Constraints: The plan runs only when `github.event_name == 'pull_request'` and uses `./infra/bin/tf-plan.sh services` for the services layer.

### Rule: merge-apply

Merges to the default branch apply the `services/` Terraform layer after CI succeeds.

Constraints: The apply runs only when `github.ref == 'refs/heads/main' && github.event_name == 'push'`, requires the `production` environment approval, and uses `./infra/bin/tf-apply.sh services`.

### Rule: foundation-approval

Applying the `foundation/` Terraform layer requires manual `workflow_dispatch` and environment approval.

## Workflow Organization

### Rule: workflow-separation

Workflow concerns are separated into `ci.yml`, `deploy.yml`, and any `bootstrap.yml`.

Constraints: Each workflow has one concern; actions are pinned to a major version or SHA.

### config_key `concurrency`

Workflows serialize runs for the same deployment reference.

| Key | Value |
|---|---|
| `group` | `deploy-${{ github.ref }}` |
| `cancel-in-progress` | `false` |

Constraints: Mark `ci` and `plan` as required status checks on the default branch.

## Repository Variables

### config_key `AWS_ACCOUNT_ID`

Stores the AWS account identifier used to construct the deployment role ARN.

### config_key `AWS_REGION`

Stores the AWS region used by AWS credential configuration.

### config_key `PROJECT`

Stores the project name used in the deployment role name.

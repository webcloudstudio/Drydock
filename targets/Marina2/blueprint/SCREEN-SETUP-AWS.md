# SCREEN: Setup AWS

| Field       | Value |
|-------------|-------|
| Version     | 20260621 V1 |
| Description | The AWS Setup screen configures AWS profile and org settings, runs identity and boto3 checks, and shows four collapsible readiness cards. |
| Depends On  | UI-GENERAL.md, FEATURE-SETUP-CONTROL-PLANE.md |
| Provides    | GET /setup/aws |
| Phase       | 5 |
| Route       | /setup/aws |
| Parent      | Main |
| Main Menu   | Setup (1) |
| Sub Menu    | AWS (2) |
| Tab Order   | 2 |
| Consumes    | POST /api/setup/config, POST /api/setup/aws/check-identity, POST /api/setup/aws/check-python |

## Layout

Single-column centered layout with four collapsible cards:
- AWS Identity
- Organisation
- Python Connectivity
- IAM Reachability Check

The header KPI is a status light.

## Interactions

- AWS Profile saves through `/api/setup/config`
- Marina Org saves through `/api/setup/config`
- Check AWS Identity posts to `/api/setup/aws/check-identity`
- Test Connection posts to `/api/setup/aws/check-python`
- Re-check reuses the identity endpoint

## Status Rules

Card open state:
- expanded when not OK
- collapsed when OK

Page KPI:
- green when profile is set and Python connectivity passed
- amber when the profile is set but connectivity is untested or failing
- red when the profile is empty or IAM is unreachable

## Acceptance Criteria

- The screen renders the four documented cards with collapsible state based on status.
- Identity and boto3 checks update the page with fragment responses.
- Marina Org validation rejects invalid slugs before persisting.

## Guardrails

- AWS Region remains read-only on this screen.
- The screen does not run Terraform or mutate cloud resources.
- The Python connectivity check persists `python_aws_ok` for downstream screens.

## Open Questions

- None.

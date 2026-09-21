<!-- Compacted from Rigging/stack/aws-api-gateway.md sha256=70b65fe6e90e7190de8b3aa1a111829786545ce7a861ef5e1cc8cb46a1f94c8d on 2026-09-20 by drydock rigging compact — regenerate with: drydock rigging compact --include-file {rel_source} -->

# AWS API Gateway Best Practices — Contract Surface

## HTTP API

### METHOD GET /catalog

The API exposes an HTTP API v2 route integrated with the catalog-read Lambda.

Constraints: Use `aws_apigatewayv2_route`; set `authorization_type = "AWS_IAM"`; require SigV4-signed requests from an allowed AWS Organization principal with `execute-api:Invoke` permission.

## Lambda Integration

### config_key integration_type

The route uses a Lambda proxy integration.

Constraints: Set `integration_type = "AWS_PROXY"` and `payload_format_version = "2.0"`; the Lambda must accept the full request and return the Lambda proxy response shape.

## API Stage

### config_key stage

The API uses one auto-deployed `$default` stage.

Constraints: Set `name = "$default"` and `auto_deploy = true`; use separate APIs or accounts for separate environments.

## Authorization

### Rule: iam-only-access

All routes require AWS IAM authorization through SigV4.

Constraints: Do not configure anonymous access, API keys, Cognito authorization, Lambda authorizers, resource policies, IP allow-lists, or VPC endpoints.

## CORS

### Rule: no-cors

The machine-client API does not configure CORS.

Constraints: Configure CORS only if a browser UI is introduced, with tightly scoped origins.

## Access Logging

### config_key access_log_settings

The default stage emits JSON access logs to a CloudWatch log group with bounded retention.

Constraints: Include `requestId`, `route`, `status`, `principal`, and `latencyMs`.

## Throttling

### Rule: default-throttle

The stage applies conservative default route throttling.

Constraints: Use approximately burst `20` and rate `10` requests per second unless a documented workload requires higher limits.

## Naming

### Rule: resource-naming

Resources and stages use project-scoped names and standard tags.

Constraints: Name the API `{project}-api`, integrations `{project}-{route}`, and the access log group `/aws/apigw/{project}`; apply standard tags to the API and stage.

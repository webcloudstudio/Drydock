<!-- Compacted from Rigging/stack/aws-api-gateway.md sha256=db8a09662a455caaf0bf58e006e4275863a95212cd1f064a5fdb5a44c109c675 on 2026-10-24 by drydock rigging compact — regenerate with: drydock rigging compact --include-file {rel_source} -->

# AWS API Gateway Best Practices — Contract Surface

## HTTP API

### Rule: API type

The API uses Amazon API Gateway HTTP API v2 resources.

Constraints: Use `aws_apigatewayv2_*`; do not use REST API v1 unless an unavailable HTTP API feature is required.

### Rule: API naming

The API resource name follows `{project}-api`.

Constraints: Apply standard tags to the API.

## Routes and Authorization

### Rule: route authorization

Every route requires AWS IAM authorization with SigV4-signed requests.

| Configuration | Required value |
|---|---|
| `authorization_type` | `AWS_IAM` |

Constraints: Do not configure anonymous access, API keys, Cognito authorization, Lambda authorizers, IP allow-lists, or VPC endpoints. Allowed principals require `execute-api:Invoke` on the route ARN.

### Rule: invoke role

Each member account assumes a `{project}-invoke` role granting `execute-api:Invoke` on the API route ARNs.

## Lambda Integration

### Rule: proxy integration

Each route integrates with its Lambda function through an AWS proxy integration.

| Configuration | Required value |
|---|---|
| `integration_type` | `AWS_PROXY` |
| `payload_format_version` | `2.0` |
| `integration_uri` | Lambda function invoke ARN |

Constraints: Lambda handlers consume and return the AWS Lambda proxy payload shape defined by `stack/aws-lambda.md` §2.

## Stage and Deployment

### Rule: default stage

The API uses one auto-deployed `$default` stage.

| Configuration | Required value |
|---|---|
| `name` | `$default` |
| `auto_deploy` | `true` |

Constraints: Separate environments use separate APIs or accounts, not separate stages.

### Rule: CORS

The API does not configure CORS.

Constraints: Add CORS only for a browser client, with tightly scoped origins.

## Access Logging

### Rule: access logging

The `$default` stage writes JSON access logs to a CloudWatch log group with bounded retention.

| Log field | Value |
|---|---|
| `requestId` | `$context.requestId` |
| `route` | `$context.routeKey` |
| `status` | `$context.status` |
| `principal` | `$context.identity.userArn` |
| `latencyMs` | `$context.responseLatency` |

### Rule: access log naming

The access log group follows `/aws/apigw/{project}`.

## Throttling

### Rule: default route throttling

The stage applies conservative default route throttle limits.

| Limit | Default |
|---|---:|
| Burst | 20 |
| Rate | 10 requests per second |

Constraints: Raise limits only deliberately when required by an actual usage pattern.

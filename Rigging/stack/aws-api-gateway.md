# AWS API Gateway Best Practices

**Version:** 20260528 V1
**Category:** AWS
**Description:** API Gateway HTTP API with IAM (SigV4) authorization — a private, no-public-anonymous encapsulation boundary for Lambda

Technology reference for Amazon API Gateway (HTTP API) with Lambda integration. This file does not
change between projects.

Prerequisites: `stack/aws-lambda.md`, `stack/terraform.md`

The API is the **encapsulation boundary**, not a public website. There is no anonymous access and no
public IP on the caller side: every request is SigV4-signed by an AWS Organization principal. Clients
are the cloud client library or the AWS CLI — never a browser.

---

## 1. HTTP API (v2), Not REST API (v1)

**Rule**: Use HTTP API (`aws_apigatewayv2_*`). It is ~70% cheaper, lower latency, and supports IAM
authorization. Reserve REST API only if you need a feature HTTP API lacks (request validation models,
usage plans).

**Why**: At this scale and access model, HTTP API is cheaper and simpler with no missing feature.

---

## 2. IAM (SigV4) Authorization — No Anonymous Access

**Rule**: Every route uses `authorization_type = "AWS_IAM"`. There is no API key, no Cognito, no Lambda
authorizer at Phase 1. Only callers holding valid AWS credentials for an allowed Org principal and a
matching invoke policy can call the API. This is the "simple security from a registered developer
workstation" model.

```hcl
resource "aws_apigatewayv2_route" "catalog_read" {
  api_id             = aws_apigatewayv2_api.main.id
  route_key          = "GET /catalog"
  target             = "integrations/${aws_apigatewayv2_integration.catalog_read.id}"
  authorization_type = "AWS_IAM"
}
```

The caller (the cloud client library) signs with SigV4; the principal needs `execute-api:Invoke` on the
route ARN, granted by the IAM access model.

**Org perimeter = per-member invoke role, not a resource policy.** Each member account assumes a
`{project}-invoke` role whose policy grants `execute-api:Invoke` on the API's route ARNs; that role
membership *is* the Org boundary. HTTP API v2 does not support resource policies, and this pattern does
**not** need one — the IAM authorizer plus the invoke role fully enforce "only Org principals." Do **not**
switch to REST API v1 for a resource policy, and do **not** add an IP allow-list or VPC endpoint: the
endpoint URL is public but unsigned requests are rejected at the API, so network origin is irrelevant and
the API works from any member's home network.

**Why**: SigV4 means there is nothing to leak (no shared key) and no anonymous surface — identity is the
AWS principal. It satisfies "no public inbound" without a VPC, working across members' home networks.

---

## 3. Lambda Proxy Integration

**Rule**: Use `AWS_PROXY` integration with `payload_format_version = "2.0"`. The Lambda receives the
full request and returns the proxy response shape (see `stack/aws-lambda.md` §2).

```hcl
resource "aws_apigatewayv2_integration" "catalog_read" {
  api_id                 = aws_apigatewayv2_api.main.id
  integration_type       = "AWS_PROXY"
  integration_uri        = aws_lambda_function.catalog_read.invoke_arn
  payload_format_version = "2.0"
}
```

**Why**: Proxy integration keeps routing in Terraform and logic in Lambda, with no per-route mapping
templates to maintain.

---

## 4. Single Auto-Deployed Stage

**Rule**: Use the `$default` stage with `auto_deploy = true`. Do not hand-manage deployments. Separate
environments are separate APIs/accounts, not separate stages.

**Why**: One auto-deployed stage removes a class of "forgot to deploy" errors. Account-level separation
is cleaner than stage-level for this IAM model.

---

## 5. No CORS for Machine Clients

**Rule**: Do **not** configure CORS. The callers are the cloud client library and the AWS CLI, not
browsers. Adding permissive CORS would only widen the surface. Revisit only if a browser UI ships, and
then scope origins tightly.

**Why**: CORS exists for browsers; enabling it for a machine-only API adds risk with no benefit.

---

## 6. Access Logging to CloudWatch

**Rule**: Enable JSON access logging on the stage to a CloudWatch log group with bounded retention.
Include requestId, route, status, principal, and latency. This is part of the screen-less verification
surface.

```hcl
resource "aws_apigatewayv2_stage" "default" {
  api_id      = aws_apigatewayv2_api.main.id
  name        = "$default"
  auto_deploy = true
  access_log_settings {
    destination_arn = aws_cloudwatch_log_group.api.arn
    format = jsonencode({
      requestId = "$context.requestId", route = "$context.routeKey",
      status = "$context.status", principal = "$context.identity.userArn",
      latencyMs = "$context.responseLatency"
    })
  }
  tags = local.common_tags
}
```

**Why**: Access logs prove who called what and how it responded — essential when there is no UI to watch.

---

## 7. Throttling Caps Cost and Abuse

**Rule**: Set conservative default route throttle limits (e.g. burst 20, rate 10 rps) on the stage. This
caps runaway cost and accidental hammering from a misbehaving script. Raise deliberately if a real
pattern needs it.

**Why**: Even behind IAM, a buggy client can loop. Throttling is the cheap cost guardrail that replaces
WAF for a private API.

---

## Naming Standard

| Resource | Convention | Example |
|---|---|---|
| API | `{project}-api` | `market-api` |
| Integration | `{project}-{route}` | `market-catalog-read` |
| Access log group | `/aws/apigw/{project}` | `/aws/apigw/market` |

Standard tags on the API and stage.

---

## Summary Checklist

- [ ] HTTP API (v2), not REST API
- [ ] Every route `authorization_type = AWS_IAM` (SigV4); no anonymous access, no API key
- [ ] `AWS_PROXY` integration, payload format 2.0
- [ ] Single `$default` stage, `auto_deploy = true`
- [ ] No CORS (machine clients only)
- [ ] JSON access logging to CloudWatch with bounded retention
- [ ] Conservative throttle limits set on the stage
- [ ] API name includes project; standard tags applied

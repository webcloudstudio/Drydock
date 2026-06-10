# AWS Lambda Best Practices

**Version:** 20260528 V1
**Description:** AWS Lambda (Python) patterns: handlers, IAM least privilege, CloudWatch logging, and Terraform packaging

Technology reference for AWS Lambda functions in Python. This file does not change between projects.

Prerequisites: `stack/python.md`, `stack/terraform.md`

In Marina, Lambdas are thin: they sit behind an IAM-authorized API Gateway, validate the event, call
one storage operation (DynamoDB/SQS/S3), and return. They hold no business logic that belongs in the
`marina` library, and they are provisioned by Terraform, never the console.

---

## 1. Handler Signature and Structure

**Rule**: Export `def handler(event, context)`. Keep the handler thin: parse, validate, dispatch to a
module-level function, return. Initialize clients **outside** the handler so they are reused across warm
invocations.

```python
import json, logging, os
import boto3                       # boto3 is allowed INSIDE a Lambda — it is the backend, not project code

log = logging.getLogger()
log.setLevel(os.environ.get("LOG_LEVEL", "INFO"))
_table = boto3.resource("dynamodb").Table(os.environ["TABLE_NAME"])

def handler(event, context):
    try:
        body = json.loads(event.get("body") or "{}")
    except json.JSONDecodeError:
        return _resp(400, {"error": "invalid_json"})
    return _resp(200, _read_catalog(body))
```

**Why**: A thin handler is easy to test and reason about. Module-scope client init reuses connections on
warm starts, cutting latency and cost.

---

## 2. Lambda Proxy Response Format

**Rule**: Behind API Gateway (proxy integration) every return must be a dict with `statusCode`,
`headers`, and a JSON-string `body`. Centralize it in one helper.

```python
def _resp(status, payload):
    return {
        "statusCode": status,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(payload),
    }
```

**Why**: API Gateway rejects malformed proxy responses with a 502. One helper guarantees the shape.

---

## 3. Configuration via Environment, Never `.env`

**Rule**: Lambda has no `.env` file. All configuration arrives as environment variables set by
Terraform (`TABLE_NAME`, `QUEUE_URL`, `LOG_LEVEL`, ...). Read them with `os.environ[...]` and crash on
missing required vars at import time.

```python
TABLE_NAME = os.environ["TABLE_NAME"]   # KeyError at cold start if Terraform forgot it — fail loud
```

**Why**: Failing at cold start surfaces misconfiguration immediately in CloudWatch instead of at first
request. Terraform-managed env vars keep config in version control.

---

## 4. IAM Least Privilege, Scoped to ARNs

**Rule**: Each function gets its own execution role with an inline policy scoped to the exact resource
ARNs and actions it uses — never `"Resource": "*"`, never `dynamodb:*`. A read Lambda gets
`GetItem`/`Query` on the table ARN; an ingest Lambda gets `PutItem` only.

```hcl
data "aws_iam_policy_document" "catalog_read" {
  statement {
    actions   = ["dynamodb:GetItem", "dynamodb:Query"]
    resources = [aws_dynamodb_table.marina.arn]
  }
}
```

**Why**: A scoped role caps the blast radius if a function is ever compromised, and documents exactly
what each function touches.

---

## 5. CloudWatch Structured Logging With Retention

**Rule**: Use the `logging` module (never `print`); emit one structured JSON line per request so
CloudWatch Logs Insights can query it. Set the log group retention in Terraform (e.g. 30 days) — never
leave it at "never expire". Log groups are how Marina features are observed without a UI.

```python
log.info(json.dumps({"event": "catalog_read", "org": org, "project": project, "items": n}))
```

```hcl
resource "aws_cloudwatch_log_group" "fn" {
  name              = "/aws/lambda/marina-${var.project}-catalog-read"
  retention_in_days = 30
  tags              = local.marina_tags
}
```

**Why**: Structured logs are queryable; bounded retention controls cost. Because Marina ships no screens
in Phase 1/2, these log groups and metric filters are the primary verification surface.

---

## 6. Error Handling and Dead Letter Queues

**Rule**: Catch expected errors in the handler and return a typed JSON error with the right status.
Let truly unexpected errors raise (CloudWatch records the stack trace). For async/SQS-triggered
functions, configure a DLQ so poison messages are captured, not lost.

**Why**: Returning typed errors keeps the API contract honest; a DLQ prevents an endlessly-retried bad
message from silently disappearing.

---

## 7. Packaging and Deployment via Terraform

**Rule**: Package as a zip built by the pipeline; deploy with Terraform (`aws_lambda_function` +
`archive_file`). Pin the runtime (`python3.12`). Put shared dependencies in a Lambda **layer** when more
than one function needs them; bundle tiny per-function deps inline. Never hand-edit a function in the
console.

```hcl
data "archive_file" "fn" {
  type        = "zip"
  source_dir  = "${path.module}/../../src/catalog_read"
  output_path = "${path.module}/build/catalog_read.zip"
}

resource "aws_lambda_function" "catalog_read" {
  function_name    = "marina-${var.project}-catalog-read"
  runtime          = "python3.12"
  handler          = "handler.handler"
  filename         = data.archive_file.fn.output_path
  source_code_hash = data.archive_file.fn.output_base64sha256
  timeout          = 10
  memory_size      = 256
  role             = aws_iam_role.catalog_read.arn
  environment { variables = { TABLE_NAME = aws_dynamodb_table.marina.name, LOG_LEVEL = "INFO" } }
  tags             = local.marina_tags
}
```

**Why**: Terraform deployment is reproducible and reviewable; `source_code_hash` triggers redeploys only
when code changes. Console edits create drift that Terraform will silently revert.

---

## Naming Standard

| Resource | Convention | Example |
|---|---|---|
| Function | `marina-{project}-{purpose}` | `marina-market-catalog-read` |
| Execution role | `marina-{project}-{purpose}-role` | `marina-market-catalog-read-role` |
| Log group | `/aws/lambda/marina-{project}-{purpose}` | `/aws/lambda/marina-market-catalog-read` |

Apply the standard Marina tag set (`Project`, `Owner`, `ManagedBy=terraform`, `Phase`) to every function.

---

## Summary Checklist

- [ ] Handler is thin; clients initialized at module scope for warm reuse
- [ ] Proxy responses go through one `_resp()` helper
- [ ] Config from Terraform-set env vars; crash on missing required vars at cold start
- [ ] Per-function execution role scoped to exact ARNs/actions (no `*`)
- [ ] Structured JSON logging via `logging`; log-group retention set in Terraform
- [ ] DLQ configured for async/SQS-triggered functions
- [ ] Packaged + deployed by Terraform; runtime pinned; no console edits
- [ ] Function name includes project; standard tags applied

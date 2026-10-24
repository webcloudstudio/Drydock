<!-- Compacted from Rigging/stack/aws-lambda.md sha256=68a47f8924d79efbe17c1c48823827423531060ff0b2bbe59df8785a2092191b on 2026-10-24 by drydock rigging compact — regenerate with: drydock rigging compact --include-file {rel_source} -->

# AWS Lambda Best Practices — Contract Surface

### handler

Processes an API Gateway or event invocation and returns a Lambda proxy response.

| Input | Required shape |
|---|---|
| `event` | Event object; API Gateway requests may contain a JSON-string `body`. |
| `context` | Lambda invocation context. |

Returns a dict containing `statusCode`, `headers`, and a JSON-string `body`.

Constraints: Invalid JSON request bodies return status `400` with `{"error": "invalid_json"}`. Expected errors return typed JSON errors with appropriate statuses; unexpected errors raise.

### _resp

Creates an API Gateway Lambda proxy response.

| Input | Type |
|---|---|
| `status` | HTTP status code |
| `payload` | JSON-serializable response payload |

Returns:

| Field | Shape |
|---|---|
| `statusCode` | Input status |
| `headers` | Includes `Content-Type: application/json` |
| `body` | JSON-stringified payload |

### Rule: lambda-configuration

Configures Lambda exclusively through Terraform-managed environment variables.

Constraints: Required variables such as `TABLE_NAME`, `QUEUE_URL`, and `LOG_LEVEL` must be present; missing required variables cause failure at cold start. Lambda must not depend on `.env` files.

### Rule: iam-least-privilege

Assigns each function an execution role scoped to the exact resource ARNs and actions it uses.

Constraints: Policies must not use `"Resource": "*"` or wildcard service actions. Read functions use only required read actions such as `dynamodb:GetItem` and `dynamodb:Query`; ingest functions use only required actions such as `dynamodb:PutItem`.

### Rule: structured-logging

Uses the `logging` module to emit one structured JSON log line per request.

Constraints: Do not use `print`. Terraform must configure CloudWatch log-group retention, such as `retention_in_days = 30`; retention must not be unlimited.

### Rule: async-dead-letter-queue

Configures a dead-letter queue for asynchronous or SQS-triggered functions.

Constraints: Poison messages must be captured by the DLQ rather than silently lost.

### Rule: terraform-deployment

Packages and deploys functions through Terraform.

Constraints: Use `aws_lambda_function` with `archive_file`, pin the runtime to `python3.12`, set the handler, source-code hash, timeout, memory size, execution role, and Terraform-managed environment variables. Use a Lambda layer when multiple functions share dependencies. Do not hand-edit functions in the AWS console.

### Rule: resource-naming

Names AWS resources using the project and purpose.

| Resource | Convention |
|---|---|
| Function | `{project}-{purpose}` |
| Execution role | `{project}-{purpose}-role` |
| Log group | `/aws/lambda/{project}-{purpose}` |

Constraints: Every function must have tags `Project`, `Owner`, `ManagedBy=terraform`, and `Phase`.

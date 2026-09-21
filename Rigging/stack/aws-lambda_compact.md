<!-- Compacted from Rigging/stack/aws-lambda.md sha256=daf97248f792bf5dc0f2d589b9398add702866bea5657060001b176ae3edb4c7 on 2026-09-20 by drydock rigging compact — regenerate with: drydock rigging compact --include-file {rel_source} -->

# AWS Lambda Best Practices — Contract Surface

### function_name: handler

Processes an API Gateway Lambda event, validates its JSON body, dispatches the request, and returns a proxy response.

| Input | Required shape |
|---|---|
| `event` | Event object with optional `body` containing a JSON object |
| `context` | Lambda invocation context |

Returns an API Gateway proxy response with `statusCode`, `headers`, and JSON-string `body`.

Constraints: Exported signature must be `handler(event, context)`. Invalid JSON returns status `400` with `{"error": "invalid_json"}`. Expected errors return typed JSON errors with appropriate status; unexpected errors raise.

### function_name: _resp

Constructs an API Gateway proxy response.

| Input | Type |
|---|---|
| `status` | HTTP status code |
| `payload` | JSON-serializable response payload |

Returns:

| Field | Value |
|---|---|
| `statusCode` | Input status |
| `headers` | `{"Content-Type": "application/json"}` |
| `body` | JSON-stringified input payload |

### TABLE_NAME

Identifies the DynamoDB table used by the function.

Constraints: Required configuration is supplied through Terraform-managed environment variables and read with `os.environ[...]`; missing required variables must fail at cold start. `.env` files are not used. Other function-specific variables may include `QUEUE_URL` and `LOG_LEVEL`.

### Rule: handler-structure

The handler parses and validates input, dispatches to a module-level function, and returns the response.

Constraints: Backend clients are initialized at module scope for reuse across warm invocations.

### Rule: IAM-least-privilege

Each function uses its own execution role with actions scoped to exact resource ARNs.

Constraints: Do not use `Resource: "*"` or wildcard service actions. Read functions use only required actions such as `dynamodb:GetItem` and `dynamodb:Query`; ingest functions use only required actions such as `dynamodb:PutItem`.

### Rule: structured-logging

The function emits one structured JSON log line per request through Python’s `logging` module.

Constraints: Do not use `print`. Terraform must configure CloudWatch log-group retention, such as `retention_in_days = 30`; retention must not be unlimited.

### Rule: dead-letter-queue

Asynchronous or SQS-triggered functions capture poison messages in a configured dead-letter queue.

### Rule: terraform-deployment

The function is packaged as a pipeline-built ZIP and deployed through Terraform.

Constraints: Use `aws_lambda_function` with `archive_file`, pin runtime to `python3.12`, set `handler` to the exported handler, provide `filename` and `source_code_hash`, and never hand-edit functions in the AWS console. Shared dependencies used by multiple functions belong in a Lambda layer.

### Rule: resource-naming

AWS resources use the project-purpose naming standard.

| Resource | Convention |
|---|---|
| Function | `{project}-{purpose}` |
| Execution role | `{project}-{purpose}-role` |
| Log group | `/aws/lambda/{project}-{purpose}` |

### Rule: standard-tags

Every function uses the standard tags.

Constraints: Tags include `Project`, `Owner`, `ManagedBy=terraform`, and `Phase`.

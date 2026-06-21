# FEATURE: Marina Library

| Field       | Value |
|-------------|-------|
| Version     | 20260621 V1 |
| Description | The `marina` Python package is Marina's only cloud boundary and exposes typed catalog, report, queue, and share clients with SigV4 transport and direct SQS and S3 support. |
| Depends On  | ARCHITECTURE.md |
| Provides    | marina.catalog, marina.report, marina.queue, marina.share |
| Phase       | 1 |

## Purpose

The `marina` package isolates all AWS integration and gives both local and external callers a single stable contract.

## Configuration

`Marina()` resolves:
- `MARINA_ORG`
- `MARINA_ENDPOINT`
- `MARINA_PROJECT`
- AWS credentials through the standard boto3 chain

It lazily constructs:
- `catalog`
- `report`
- `queue`
- `share`

## Client Surfaces

### `marina.catalog`

Methods:
- `publish(project_meta, capabilities)`
- `read(project=None)`
- `read_capabilities(tags=None)`

### `marina.report`

Methods:
- `heartbeat(state, message="", project=None, program=None)`
- `event(severity, message, project=None)`

Behavior:
- best effort
- never raises transport failures into callers

### `marina.queue`

Methods:
- `submit(queue, service, tool, payload, priority="normal", ttl_seconds=86400)`
- `drain(queue=None)`

Behavior:
- direct SQS access for local drain
- delete only after successful handler completion
- honor message TTL and retry semantics

### `marina.share`

Methods:
- `put(local_path, key=None)`
- `get(key, dest)`
- `list(prefix=None)`

Behavior:
- direct S3 data path
- index registration and reads go through the Marina API

## Transport Rules

- API calls are SigV4-signed for `execute-api`
- network retries use exponential backoff and jitter
- transport failures raise typed exceptions for catalog, queue, and share
- report calls swallow transport failures
- no caller outside this package imports `boto3`

## Typed Exceptions

The package exposes:
- `MarinaAuthError`
- `MarinaNotFound`
- `MarinaTransportError`
- `MarinaValidationError`

## Verification

- moto-backed tests cover DynamoDB, SQS, and S3 behavior
- a grep gate proves `boto3` is confined to the `marina` package
- a live smoke read can call `mar.catalog.read()` against a deployed endpoint

## Acceptance Criteria

- The package exposes the documented resource-grouped methods.
- Report operations are best effort and do not break caller workflows.
- Queue and share surfaces handle direct SQS and S3 interactions inside the library.
- No code outside the package imports `boto3`.

## Guardrails

- No raw escape hatch is added to bypass typed client methods.
- Consumers do not sign API Gateway calls themselves.
- Direct AWS SDK usage stays inside the `marina` package.

## Open Questions

- None.

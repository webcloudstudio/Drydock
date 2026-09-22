<!-- Compacted from Rigging/stack/cloud-client-library.md sha256=0c7e6a43b9b2ae9164a644af2dd2b68ebbdf7b85c847cd3e032ab6cdd3b2eee5 on 2026-09-20 by drydock rigging compact — regenerate with: drydock rigging compact --include-file {rel_source} -->

# Cloud Client Library Best Practices — Contract Surface

## Cloud boundary

### Rule: single-cloud-boundary
Project and platform code access cloud capabilities only through `CloudClient` and never import `boto3`, construct AWS clients, build DynamoDB keys, sign requests, or store API Gateway URLs.

## Client API

### CloudClient
Provides resource clients for catalog, reporting, queues, and file sharing.

Returns:

| Attribute | Type |
|---|---|
| `catalog` | `CatalogClient` |
| `report` | `ReportClient` |
| `queue` | `QueueClient` |
| `share` | `ShareClient` |

### CatalogClient.publish
Publishes project metadata and capabilities.

| Parameter | Type |
|---|---|
| `project_meta` | `dict` |
| `capabilities` | `list[dict]` |

Returns: `None`.

### CatalogClient.read
Reads the whole organization tree or one project subtree.

| Parameter | Type |
|---|---|
| `project` | `str \| None` |

Returns: `dict`.

### CatalogClient.read_capabilities
Reads capabilities, optionally filtered by tags.

| Parameter | Type |
|---|---|
| `tags` | `list[str] \| None` |

Returns: `list[dict]`.

### ReportClient.heartbeat
Reports a workload heartbeat as best-effort telemetry.

| Parameter | Type | Required |
|---|---|---|
| `state` | `str` | Yes |
| `message` | `str` | No; defaults to `""` |

Returns: `None`.

Constraints: `state` is one of `OK`, `WARNING`, `ERROR`, or `CRITICAL`. Transport errors are swallowed and never raised.

### ReportClient.event
Reports a severity-level event as best-effort telemetry.

| Parameter | Type |
|---|---|
| `severity` | `str` |
| `message` | `str` |

Returns: `None`.

Constraints: `severity` is one of `INFORMATION`, `WARNING`, `ERROR`, or `CRITICAL`. Transport errors are swallowed and never raised.

### QueueClient.submit
Submits a payload to an asynchronous queue.

| Parameter | Type | Required |
|---|---|---|
| `queue` | `str` | Yes |
| `service` | `str` | Yes |
| `tool` | `str` | Yes |
| `payload` | `dict` | Yes |
| `priority` | `str` | No; defaults to `"normal"` |

Returns: `str`.

### QueueClient.drain
Drains queued work locally.

| Parameter | Type |
|---|---|
| `queue` | `str \| None` |

Returns: `dict` containing drain counts.

### ShareClient.put
Uploads a local file to the object/file share.

| Parameter | Type |
|---|---|
| `local_path` | `str` |
| `key` | `str \| None` |

Returns: `str` share key.

### ShareClient.get
Downloads a shared file to a destination.

| Parameter | Type |
|---|---|
| `key` | `str` |
| `dest` | `str` |

Returns: `None`.

### ShareClient.list
Lists shared files, optionally filtered by prefix.

| Parameter | Type |
|---|---|
| `prefix` | `str \| None` |

Returns: `list[dict]`.

## Configuration and authentication

### CLOUD_ORG
Identifies the tenant or organization.

### CLOUD_API_ENDPOINT
Provides the API Gateway base URL.

### PROJECT_SLUG
Identifies the calling project.

### AWS_PROFILE
Selects the AWS profile used for credential resolution.

### Rule: environment-configuration
`CloudClient()` resolves organization, API endpoint, project slug, and AWS identity from the workstation environment; these values must not be hardcoded.

### Rule: sigv4-authentication
Requests use the resolved AWS identity with SigV4 for the `execute-api` service and do not use a separate API key.

## Errors and reliability

### Rule: typed-data-operation-errors
`catalog.*`, `queue.*`, and `share.*` raise `CloudAuthError`, `CloudNotFound`, or `CloudTransportError` when operations fail.

### Rule: retry-policy
All network calls retry with exponential backoff and jitter.

## Distribution

### Rule: pinned-consumer-dependency
Consumers install the independently versioned library as a pinned git dependency, for example `cloud-client @ git+https://github.com/{org}/cloud-client.git@v0.2.0`.

### Rule: semantic-versioning
Breaking API changes require a major version increment, and each release is tagged.

### Rule: library-quality
The library repository provides `pyproject.toml`, uses `uv`, passes `ruff`, and ships a pytest suite backed by local DynamoDB/SQS mocks.

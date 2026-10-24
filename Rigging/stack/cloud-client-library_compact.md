<!-- Compacted from Rigging/stack/cloud-client-library.md sha256=5b95cd21b7027222aae8b56a13e912a4febaa775386ae2ab577f25213041e0dc on 2026-10-24 by drydock rigging compact — regenerate with: drydock rigging compact --include-file {rel_source} -->

# Cloud Client Library Best Practices — Contract Surface

## CloudClient

### CloudClient

Creates a cloud client exposing resource-oriented catalog, report, queue, and share interfaces.

Constraints: Resolve organization, AWS identity, API endpoint, and project slug from environment; use SigV4 authentication and no API keys.

### CLOUD_ORG

Identifies the tenant or organization.

### CLOUD_API_ENDPOINT

Provides the API Gateway base URL.

### PROJECT_SLUG

Identifies the calling project.

### AWS_PROFILE

Selects the AWS profile or role through the standard credential chain.

## Catalog

### CloudClient.catalog.publish

Publishes project metadata and capabilities.

| Parameter | Type |
|---|---|
| `project_meta` | `dict` |
| `capabilities` | `list[dict]` |

Returns: `None`.

### CloudClient.catalog.read

Reads the whole organization tree or one project subtree.

| Parameter | Type | Required |
|---|---|---|
| `project` | `str \| None` | No |

Returns: `dict`.

### CloudClient.catalog.read_capabilities

Reads capabilities, optionally filtered by tags.

| Parameter | Type | Required |
|---|---|---|
| `tags` | `list[str] \| None` | No |

Returns: `list[dict]`.

Constraints: Catalog operations raise `CloudAuthError`, `CloudNotFound`, or `CloudTransportError` on failure.

## Reporting

### CloudClient.report.heartbeat

Submits a best-effort heartbeat report.

| Parameter | Type | Required |
|---|---|---|
| `state` | `str` | Yes |
| `message` | `str` | No; defaults to `""` |

Returns: `None`.

Constraints: `state` is one of `OK`, `WARNING`, `ERROR`, or `CRITICAL`. Transport errors are swallowed.

### CloudClient.report.event

Submits a best-effort event report.

| Parameter | Type |
|---|---|
| `severity` | `str` |
| `message` | `str` |

Returns: `None`.

Constraints: `severity` is one of `INFORMATION`, `WARNING`, `ERROR`, or `CRITICAL`. Transport errors are swallowed.

## Queue

### CloudClient.queue.submit

Submits a payload to an asynchronous queue.

| Parameter | Type | Required |
|---|---|---|
| `queue` | `str` | Yes |
| `service` | `str` | Yes |
| `tool` | `str` | Yes |
| `payload` | `dict` | Yes |
| `priority` | `str` | No; defaults to `"normal"` |

Returns: `str`.

### CloudClient.queue.drain

Drains queued work locally.

| Parameter | Type | Required |
|---|---|---|
| `queue` | `str \| None` | No |

Returns: `dict`.

Constraints: Queue operations raise `CloudAuthError`, `CloudNotFound`, or `CloudTransportError` on failure.

## Share

### CloudClient.share.put

Uploads a local file to the object or file share.

| Parameter | Type | Required |
|---|---|---|
| `local_path` | `str` | Yes |
| `key` | `str \| None` | No |

Returns: `str` share key.

### CloudClient.share.get

Downloads a shared file to a destination.

| Parameter | Type |
|---|---|
| `key` | `str` |
| `dest` | `str` |

Returns: `None`.

### CloudClient.share.list

Lists shared files, optionally filtered by prefix.

| Parameter | Type | Required |
|---|---|---|
| `prefix` | `str \| None` | No |

Returns: `list[dict]`.

Constraints: Share operations raise `CloudAuthError`, `CloudNotFound`, or `CloudTransportError` on failure.

## Integration Rules

### Rule: cloud-boundary

Project and platform code use the cloud client library for all cloud operations and do not import `boto3`, construct AWS clients, build DynamoDB keys, sign requests, or store API Gateway URLs.

### Rule: retry-policy

All network calls retry with exponential backoff and jitter.

### Rule: package-distribution

Consumers install the library as a pinned git dependency using a version tag.

```toml
"cloud-client @ git+https://github.com/{org}/cloud-client.git@v0.2.0"
```

Constraints: Releases use semantic versioning; breaking API changes increment the major version.

### Rule: library-quality

The library provides a `pyproject.toml`, is managed with `uv`, passes `ruff`, and ships a pytest suite using a local DynamoDB/SQS mock such as `moto`.

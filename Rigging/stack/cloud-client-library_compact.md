<!-- Compacted from cloud-client-library.md on 2026-06-22 by drydock rigging compact — regenerate with: drydock rigging compact --include-file {rel_source} -->

# Cloud Client Library — Usage Surface

## Configuration

### CLOUD_ORG
Environment variable that sets the tenant/org identifier resolved by `CloudClient()`.

Returns: N/A — read at construction time.

### CLOUD_API_ENDPOINT
Environment variable that sets the API Gateway base URL resolved by `CloudClient()`.

Returns: N/A — read at construction time.

### PROJECT_SLUG
Environment variable that sets the calling project slug resolved by `CloudClient()`.

Returns: N/A — read at construction time.

### AWS_PROFILE
Environment variable that selects the boto3 credential profile for SigV4 signing.

Returns: N/A — read at construction time.

## Client

### CloudClient
Constructs the cloud client, resolving org, profile, and endpoint from environment variables.

`Returns: CloudClient — instance exposing `.catalog`, `.report`, `.queue`, `.share` sub-clients`

## Catalog

### CatalogClient.publish
Publishes project metadata and capabilities to the catalog.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| project_meta | dict | yes | Project-level metadata |
| capabilities | list[dict] | yes | List of capability descriptors |

`Returns: None`

### CatalogClient.read
Reads the catalog, returning the whole org tree or a single project subtree.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| project | str \| None | no | Project slug; omit for the full org tree |

`Returns: dict — org tree or project subtree`

### CatalogClient.read_capabilities
Reads capabilities, optionally filtered by tags.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| tags | list[str] \| None | no | Tags to filter by; omit for all capabilities |

`Returns: list[dict] — matching capability records`

## Report

### ReportClient.heartbeat
Posts a heartbeat signal; best-effort, never raises on transport error.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| state | str | yes | One of: `OK`, `WARNING`, `ERROR`, `CRITICAL` |
| message | str | no | Human-readable detail; defaults to `""` |

`Returns: None`

### ReportClient.event
Posts a structured event; best-effort, never raises on transport error.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| severity | str | yes | One of: `INFORMATION`, `WARNING`, `ERROR`, `CRITICAL` |
| message | str | yes | Human-readable detail |

`Returns: None`

## Queue

### QueueClient.submit
Submits a job to an async queue.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| queue | str | yes | Queue name |
| service | str | yes | Target service name |
| tool | str | yes | Tool to invoke |
| payload | dict | yes | Job payload |
| priority | str | no | `"normal"` (default) or other priority value |

`Returns: str — job/message identifier`

### QueueClient.drain
Drains a queue locally and returns message counts.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| queue | str \| None | no | Queue name; omit to drain all queues |

`Returns: dict — counts of drained messages`

## Share

### ShareClient.put
Uploads a local file to object storage.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| local_path | str | yes | Filesystem path of the file to upload |
| key | str \| None | no | Storage key; derived from filename if omitted |

`Returns: str — share key for the uploaded object`

### ShareClient.get
Downloads an object from object storage to a local destination.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| key | str | yes | Share key of the object to retrieve |
| dest | str | yes | Local filesystem path to write the file |

`Returns: None`

### ShareClient.list
Lists objects in object storage, optionally filtered by key prefix.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| prefix | str \| None | no | Key prefix to filter by; omit for all objects |

`Returns: list[dict] — object descriptors`

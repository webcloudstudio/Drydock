# AGENTS: Marina Surfaces

| Field       | Value |
|-------------|-------|
| Version     | 20260621 V1 |
| Description | Marina exposes local setup routes, private cloud API routes, and callable capabilities for catalog, reporting, queue, share, and guarded local operations. |
| Depends On  | ARCHITECTURE.md, FEATURE-MARINA-LIB.md, FEATURE-CATALOG.md, FEATURE-REPORTING.md, FEATURE-ASYNC-OPERATIONS.md, FEATURE-SHARE.md, FEATURE-SETUP-CONTROL-PLANE.md |
| Provides    | marina-http-surfaces, marina-capability-catalog |
| Phase       | 4 |

## Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | /health | Local control-plane health check |
| GET | / | Redirect to setup summary |
| GET | /setup | Redirect to setup summary |
| GET | /setup/summary | Setup summary screen |
| GET | /setup/aws | AWS setup screen |
| GET | /setup/terraform | Terraform setup screen |
| GET | /setup/github | GitHub setup screen |
| GET | /setup/scan | Git scan screen |
| GET | /setup/repositories | Repositories screen |
| GET | /setup/projects | Projects screen |
| GET | /setup/settings | Settings screen |
| GET | /api/setup/summary/status | Summary status payload |
| POST | /api/setup/config | Persist a local setting or profile value |
| POST | /api/setup/aws/check-identity | Run AWS CLI identity check |
| POST | /api/setup/aws/check-python | Run boto3 connectivity check |
| GET | /api/setup/terraform/status | Read Terraform screen status payload |
| GET | /api/setup/terraform/check-cli | Read Terraform CLI install status |
| POST | /api/setup/terraform/verify-endpoint | Verify the deployed API endpoint |
| POST | /api/setup/terraform/auto-read-url | Read `api_url` from Terraform state and persist it |
| POST | /api/setup/github/check-auth | Run `gh auth status` |
| POST | /api/setup/github/check-ssh | Run `ssh -T git@github.com` |
| POST | /api/setup/github/sources | Add a GitHub source |
| DELETE | /api/setup/github/sources/{id} | Remove a GitHub source |
| GET | /api/setup/scan/status | Read per-source scan-count status payload |
| GET | /api/repositories | Read repository table fragment |
| POST | /api/repositories/sync | Refresh GitHub repositories from configured sources |
| POST | /api/repositories/download | Clone a repository into `PROJECTS_DIR` |
| POST | /api/scan | Rescan local projects and conformance state |
| POST | /api/projects/{id}/conform | Run the correct Prototyper conform action for one project |
| POST | /catalog | Publish project metadata and capabilities |
| GET | /catalog | Read the org-wide project index |
| GET | /catalog/{project} | Read one project subtree |
| GET | /capabilities | Read capability rows visible to the caller |
| POST | /heartbeat | Ingest a latest-only heartbeat |
| POST | /events | Ingest an event row |
| GET | /health/{project} | Compute aggregate health for one project |
| POST | /queue/{queue} | Submit a queue message |
| GET | /share | List share index rows |
| POST | /share | Record a share index row |

## Capabilities

```json
{
  "capabilities": [
    {
      "name": "marina_catalog_publish",
      "description": "Publish a project's metadata and capabilities to the Marina catalog.",
      "tags": ["catalog", "metadata", "publish"],
      "invoke": {
        "rest": { "method": "POST", "path": "/catalog" }
      },
      "input": {
        "project_meta": { "type": "object", "required": true },
        "capabilities": { "type": "array", "required": true }
      },
      "output": {
        "project": { "type": "string" },
        "published_capabilities": { "type": "integer" },
        "updated_at": { "type": "string" }
      },
      "permissions": {
        "access": "readwrite"
      },
      "lifecycle": "on-demand"
    },
    {
      "name": "marina_catalog_read",
      "description": "Read the Marina project catalog or one project subtree.",
      "tags": ["catalog", "read"],
      "invoke": {
        "rest": { "method": "GET", "path": "/catalog" }
      },
      "input": {
        "project": { "type": "string", "required": false }
      },
      "output": {
        "generated_at": { "type": "string" },
        "items": { "type": "array" }
      },
      "permissions": {
        "access": "readonly"
      },
      "lifecycle": "on-demand"
    },
    {
      "name": "marina_capabilities_read",
      "description": "List readable capabilities with optional tag filtering.",
      "tags": ["catalog", "capabilities", "read"],
      "invoke": {
        "rest": { "method": "GET", "path": "/capabilities" }
      },
      "input": {
        "tags": { "type": "array", "required": false }
      },
      "output": {
        "generated_at": { "type": "string" },
        "capabilities": { "type": "array" }
      },
      "permissions": {
        "access": "readonly"
      },
      "lifecycle": "on-demand"
    },
    {
      "name": "marina_report_heartbeat",
      "description": "Write a latest-only heartbeat for a program.",
      "tags": ["report", "heartbeat"],
      "invoke": {
        "rest": { "method": "POST", "path": "/heartbeat" }
      },
      "input": {
        "project": { "type": "string", "required": true },
        "program": { "type": "string", "required": true },
        "state": { "type": "string", "required": true },
        "message": { "type": "string", "required": false }
      },
      "output": {
        "accepted": { "type": "boolean" }
      },
      "permissions": {
        "access": "readwrite"
      },
      "lifecycle": "on-demand"
    },
    {
      "name": "marina_report_event",
      "description": "Append a TTL-bounded event row for a project.",
      "tags": ["report", "event"],
      "invoke": {
        "rest": { "method": "POST", "path": "/events" }
      },
      "input": {
        "project": { "type": "string", "required": true },
        "severity": { "type": "string", "required": true },
        "message": { "type": "string", "required": true }
      },
      "output": {
        "accepted": { "type": "boolean" }
      },
      "permissions": {
        "access": "readwrite"
      },
      "lifecycle": "on-demand"
    },
    {
      "name": "marina_health_read",
      "description": "Read aggregate health for one project from latest heartbeats and recent events.",
      "tags": ["report", "health", "read"],
      "invoke": {
        "rest": { "method": "GET", "path": "/health/{project}" }
      },
      "input": {
        "project": { "type": "string", "required": true }
      },
      "output": {
        "aggregate": { "type": "string" },
        "heartbeats": { "type": "array" },
        "recent_events": { "type": "array" }
      },
      "permissions": {
        "access": "readonly"
      },
      "lifecycle": "on-demand"
    },
    {
      "name": "marina_queue_submit",
      "description": "Submit a durable queue message for later local execution.",
      "tags": ["queue", "async"],
      "invoke": {
        "rest": { "method": "POST", "path": "/queue/{queue}" }
      },
      "input": {
        "queue": { "type": "string", "required": true },
        "service": { "type": "string", "required": true },
        "tool": { "type": "string", "required": true },
        "payload": { "type": "object", "required": true }
      },
      "output": {
        "id": { "type": "string" },
        "status": { "type": "string" }
      },
      "permissions": {
        "access": "readwrite"
      },
      "lifecycle": "on-demand"
    },
    {
      "name": "marina_queue_drain",
      "description": "Drain queued work locally and dispatch the allow-listed handler.",
      "tags": ["queue", "async", "local"],
      "invoke": {
        "cli": "bin/drain_queue.sh"
      },
      "input": {
        "queue": { "type": "string", "required": false }
      },
      "output": {
        "processed": { "type": "integer" },
        "succeeded": { "type": "integer" },
        "failed": { "type": "integer" },
        "expired": { "type": "integer" }
      },
      "permissions": {
        "owners": ["operator"],
        "access": "readwrite"
      },
      "lifecycle": "scheduled"
    },
    {
      "name": "marina_share_put",
      "description": "Upload a private object to S3 and register its share index row.",
      "tags": ["share", "s3"],
      "invoke": {
        "rest": { "method": "POST", "path": "/share" }
      },
      "input": {
        "key": { "type": "string", "required": true },
        "size": { "type": "integer", "required": true },
        "content_type": { "type": "string", "required": false }
      },
      "output": {
        "owner": { "type": "string" },
        "key": { "type": "string" }
      },
      "permissions": {
        "access": "readwrite"
      },
      "lifecycle": "on-demand"
    },
    {
      "name": "marina_share_list",
      "description": "List readable share index rows for the caller.",
      "tags": ["share", "s3", "read"],
      "invoke": {
        "rest": { "method": "GET", "path": "/share" }
      },
      "input": {
        "prefix": { "type": "string", "required": false }
      },
      "output": {
        "items": { "type": "array" }
      },
      "permissions": {
        "access": "readonly"
      },
      "lifecycle": "on-demand"
    },
    {
      "name": "marina_prototyper_project_ops",
      "description": "Dispatch allow-listed Prototyper operations through the local queue-drain path.",
      "tags": ["project-ops", "prototyper", "local"],
      "invoke": {
        "rest": { "method": "POST", "path": "/queue/project-ops" }
      },
      "input": {
        "tool": { "type": "string", "required": true },
        "project": { "type": "string", "required": true },
        "args": { "type": "array", "required": false }
      },
      "output": {
        "id": { "type": "string" },
        "status": { "type": "string" }
      },
      "permissions": {
        "access": "readwrite"
      },
      "lifecycle": "on-demand"
    },
    {
      "name": "marina_voice_transcribe",
      "description": "Drain a queued voice job, run local Whisper transcription, and append text to the mapped target file.",
      "tags": ["voice", "transcription", "local"],
      "invoke": {
        "rest": { "method": "POST", "path": "/queue/voice" }
      },
      "input": {
        "audio_key": { "type": "string", "required": true },
        "label": { "type": "string", "required": true }
      },
      "output": {
        "chars_written": { "type": "integer" },
        "target_file": { "type": "string" }
      },
      "permissions": {
        "access": "readwrite"
      },
      "lifecycle": "scheduled"
    }
  ]
}
```

## Links

| Label | URL |
|-------|-----|
| Prototyper Reference | ../Prototyper |
| Blueprint Sources | ./sources/ |

## Acceptance Criteria

- The endpoint inventory covers all local setup, cloud catalog, cloud report, queue, and share routes defined in the Blueprint.
- Capability contracts are transport-agnostic and JSON-serializable.
- Project-ops and voice processing remain explicitly local capabilities.

## Guardrails

- The capability catalog does not declare any free-form shell execution capability.
- Setup-only local routes are not exposed as cloud capabilities.
- Permissions in the catalog do not bypass the shared authorization gate.

## Open Questions

- None.

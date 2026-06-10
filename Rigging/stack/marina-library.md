# Marina Client Library Best Practices

**Version:** 20260528 V1
**Description:** The `marina` Python library — the single indirection layer between project code and AWS. Projects call `marina`, never boto3.

Technology reference for the `marina` client library. This file does not change between projects.

Prerequisites: `stack/python.md`

`marina` is the **swap layer**. Every cloud touch — publishing the catalog, reading it, reporting
heartbeats and events, the async queue, the S3 share — goes through one small, stable, typed Python
API. The backend (DynamoDB / SQS / S3 / API Gateway today) can change without any consumer changing a
line. This is the core architectural decision: encapsulate so the platform is not welded to AWS.

---

## 1. The Library Is the Only Cloud Boundary

**Rule**: Project and platform code import `marina`. It must **never** import `boto3`, construct AWS
clients, build DynamoDB keys, sign requests, or hold an API Gateway URL. All of that lives inside
`marina`. A code review that finds `import boto3` outside the `marina` package fails.

```python
# CORRECT
from marina import Marina
mar = Marina()                       # resolves org, profile, endpoint from environment
mar.report.heartbeat("OK", "daily batch starting")

# WRONG — never in project code
import boto3
boto3.client("dynamodb").put_item(...)
```

**Why**: One boundary means one place to change transport, add retries, fix auth, or migrate clouds.
Scattered boto3 calls weld every project to AWS and to today's key format.

---

## 2. Stable, Resource-Oriented API

**Rule**: The public surface is grouped by resource, not by AWS service. Method names describe intent
("publish the catalog"), never mechanism ("put_item"). The Phase 1/2 surface:

```python
class Marina:
    catalog: CatalogClient
    report:  ReportClient
    queue:   QueueClient
    share:   ShareClient

# Catalog (Phase 1)
mar.catalog.publish(project_meta: dict, capabilities: list[dict]) -> None
mar.catalog.read(project: str | None = None) -> dict          # whole org tree, or one project subtree
mar.catalog.read_capabilities(tags: list[str] | None = None) -> list[dict]

# Report / ingest (Phase 1)
mar.report.heartbeat(state: str, message: str = "") -> None    # state: OK|WARNING|ERROR|CRITICAL
mar.report.event(severity: str, message: str) -> None          # severity: INFORMATION|WARNING|ERROR|CRITICAL

# Async queue (Phase 2)
mar.queue.submit(queue: str, service: str, tool: str, payload: dict, priority: str = "normal") -> str
mar.queue.drain(queue: str | None = None) -> dict              # local consumer; returns counts

# Company share (Phase 2)
mar.share.put(local_path: str, key: str | None = None) -> str  # returns share key
mar.share.get(key: str, dest: str) -> None
mar.share.list(prefix: str | None = None) -> list[dict]
```

**Why**: Intent-named, resource-grouped methods are what make the boto3 backend swappable and the API
learnable. The names are the contract; the AWS calls behind them are an implementation detail.

---

## 3. Configuration and Identity From the Environment

**Rule**: A `Marina()` instance resolves everything from the workstation environment — never hardcoded:
`MARINA_ORG` (tenant), the AWS profile/role (standard boto3 credential chain), `MARINA_ENDPOINT` (the
API Gateway base URL), and `MARINA_PROJECT` (the calling project slug, defaulting to the directory
name). Calls are SigV4-signed by the resolved AWS identity; there is no separate API key.

```python
# .env (workstation) — read by marina, never by project code directly
MARINA_ORG=acme
MARINA_ENDPOINT=https://abc123.execute-api.us-east-1.amazonaws.com
AWS_PROFILE=marina-acme        # standard boto3 credential resolution
```

Requests are signed with `botocore`'s SigV4 for the `execute-api` service — no third-party auth, no
stored key:

```python
from botocore.auth import SigV4Auth
from botocore.awsrequest import AWSRequest
import boto3, requests

creds = boto3.Session(profile_name=os.getenv("AWS_PROFILE")).get_credentials().get_frozen_credentials()
req = AWSRequest(method=method, url=f"{endpoint}{path}", data=body)
SigV4Auth(creds, "execute-api", region).add_auth(req)
resp = requests.request(method, req.url, headers=dict(req.headers), data=body)
```

This works from any outbound-HTTPS network (members' home connections included); the network origin is
irrelevant because authentication is credential-based, not IP-based.

**Why**: Identity is the AWS Organization principal. SigV4 means "only signed Org members can call,"
with no key to leak. Reading config from the environment keeps the same code working on every member's
workstation.

---

## 4. Fail Safe, Never Crash the Caller

**Rule**: `report.heartbeat` and `report.event` are **best-effort** — they swallow transport errors and
return without raising, so a reporting outage never breaks a batch job. `catalog.*`, `queue.*`, and
`share.*` **do** raise typed exceptions (`MarinaAuthError`, `MarinaNotFound`, `MarinaTransportError`)
because callers act on their results. All network calls retry with exponential backoff and jitter
(reuse boto3's standard retry config inside the library).

**Why**: Telemetry must never take down the workload it observes; data operations must surface failure.
The split mirrors the existing `common.sh`/`common.py` heartbeat contract.

---

## 5. Packaging, Distribution, and Versioning

**Rule**: `marina` lives in **its own git repository**, is `uv`-managed and `ruff`-clean, and ships a
`pyproject.toml`. Consumers add it as a pinned git dependency; they never vendor or copy it.

```toml
# consumer pyproject.toml
dependencies = [
    "marina @ git+https://github.com/{org}/marina-lib.git@v0.2.0",
]
```

```bash
uv add "git+https://github.com/{org}/marina-lib.git@v0.2.0"
uv sync --frozen      # CI
```

Semantic versioning; tag every release; a breaking API change bumps the major version. The library
carries its own pytest suite that runs against a local DynamoDB/SQS mock (`moto`) so consumers trust the
contract.

**Why**: An independently versioned, git-distributed library is the "publish location in git, projects
pull it in" model. Pinning to a tag makes consumer builds reproducible; `moto` tests make the swap layer
trustworthy without touching real AWS.

---

## Naming Standard

| Item | Convention | Example |
|---|---|---|
| Package / import name | `marina` | `from marina import Marina` |
| Library repo | `marina-lib` | `github.com/{org}/marina-lib` |
| Exception classes | `Marina{Reason}Error` | `MarinaAuthError` |
| Env vars | `MARINA_{NAME}` | `MARINA_ENDPOINT` |

---

## Summary Checklist

- [ ] No `import boto3` anywhere outside the `marina` package
- [ ] Public API grouped by resource (`catalog`/`report`/`queue`/`share`), intent-named methods
- [ ] Config + identity resolved from environment; SigV4, no API keys
- [ ] `report.*` best-effort (never raises); `catalog`/`queue`/`share` raise typed errors
- [ ] All calls retry with backoff
- [ ] Own git repo, `uv` + `ruff`, pinned git dependency in consumers
- [ ] `moto`-backed pytest suite ships with the library

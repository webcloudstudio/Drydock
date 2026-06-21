# FEATURE: Reporting

| Field       | Value |
|-------------|-------|
| Version     | 20260621 V1 |
| Description | Marina ingests best-effort heartbeats and events, stores them durably, and computes per-project aggregate health at read time. |
| Depends On  | DATABASE.md, FEATURE-MARINA-LIB.md, FEATURE-ACCESS-CONTROL.md |
| Provides    | POST /heartbeat, POST /events, GET /health/{project} |
| Phase       | 3 |

## Purpose

The reporting feature makes last-known project state readable even when the source machine is offline.

## Ingest Flows

### `POST /heartbeat`

- resolves the project and program
- checks `readwrite` access
- overwrites the latest heartbeat row for that program
- returns success even when library-side transport errors are swallowed upstream

### `POST /events`

- resolves the project
- checks `readwrite` access
- appends an event row with a ULID sort key
- writes `ttl` for 30-day expiry

## Health Read

`GET /health/{project}`:
1. checks `read` access
2. queries latest heartbeats
3. queries recent events
4. computes aggregate state at read time
5. returns `project`, `aggregate`, `heartbeats`, `recent_events`, and `checked_at`

Aggregate rules:
- all latest heartbeats `OK` and no critical recent events => `healthy`
- any `ERROR` or `CRITICAL` recent event => `degraded`
- no usable signals => `unknown`

## Reads

- DynamoDB heartbeat and event rows
- ACL grants through the shared gate

## Writes

- heartbeat rows
- event rows
- structured reporting log lines

## Verification

`bin/test_report_ingest.sh` proves:
- latest-only heartbeat overwrite semantics
- event append semantics
- TTL presence on event rows
- read-time aggregate health computation

## Acceptance Criteria

- Heartbeats are latest-only per program.
- Events are append-only and expire through TTL.
- Health aggregation is computed at read time.
- Best-effort reporting behavior does not break caller jobs.

## Guardrails

- Reporting never stores a precomputed aggregate row in DynamoDB.
- Reporting transport failures are not surfaced into external caller jobs through `marina.report`.
- Event retention stays bounded by TTL.

## Open Questions

- Whether degraded health should enqueue an alert message for downstream notification is deferred beyond V1.

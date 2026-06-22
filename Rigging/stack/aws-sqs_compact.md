<!-- Compacted from aws-sqs.md on 2026-06-22 by drydock rigging compact — regenerate with: drydock rigging compact --include-file {rel_source} -->

# AWS SQS — Usage Surface

## Queue Client

### client.queue.submit

Submits a work item to the durable queue for asynchronous processing.

No parameters documented in source.

`Returns: void`

---

### client.queue.drain

Drains all available messages from the queue, skipping already-processed messages and expiring stale ones; safe to run multiple times.

No parameters documented in source.

| Field | Type | Description |
|-------|------|-------------|
| processed | int | Total messages received |
| succeeded | int | Messages handled without error |
| failed | int | Messages that raised an error |
| expired | int | Messages discarded due to exceeded `ttl_seconds` |

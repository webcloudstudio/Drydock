<!-- Compacted from Rigging/stack/aws-sqs.md sha256=bbc3020de24d7d672bfd38db00063d545b97e9b80331ba7e62b0e99c9657d68e on 2026-09-20 by drydock rigging compact — regenerate with: drydock rigging compact --include-file {rel_source} -->

# AWS SQS Best Practices — Contract Surface

## Queue

### client.queue.submit(...)

Submits work to the project queue through the cloud client library.

Constraints: Project code does not access raw boto3 clients or hold queue URLs.

### client.queue.drain(...)

Drains queued messages through the cloud client library and processes each message idempotently.

Returns: `{processed, succeeded, failed, expired}`.

Constraints: Honor `ttl_seconds`; expire stale messages rather than processing them. Delete messages only after successful processing. Failed messages remain available for retry.

### Rule: queue-receive

Receives messages using long polling.

Constraints: `WaitTimeSeconds = 20`; `MaxNumberOfMessages = 10`; queue default `ReceiveMessageWaitTimeSeconds = 20`; short polling is not permitted.

### Rule: queue-visibility

Keeps messages invisible while processing.

Constraints: `VisibilityTimeout` exceeds the longest expected processing time; extend visibility with `change_message_visibility` for long-running jobs.

### Rule: queue-redrive

Routes repeatedly failing messages to a dead-letter queue.

Constraints: Every Standard queue has a DLQ with `maxReceiveCount = 3`; DLQ depth is monitored.

### Rule: queue-type

Uses a Standard queue unless strict ordering or exactly-once delivery is required.

Constraints: FIFO is used only for a specifically ordered workflow.

### Rule: queue-naming

Names queues and dead-letter queues using the project prefix.

Constraints: Queue name is `{project}-{queue}`; DLQ name is `{project}-{queue}-dlq`; standard tags apply to every queue and DLQ.

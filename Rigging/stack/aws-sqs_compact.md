<!-- Compacted from Rigging/stack/aws-sqs.md sha256=acb49745b1337dc4986e19c1817205d6783e334fdb8e02abbf2fdff937a10760 on 2026-10-24 by drydock rigging compact — regenerate with: drydock rigging compact --include-file {rel_source} -->

# AWS SQS Best Practices — Contract Surface

## Queue Configuration

### Rule: queue-type

Use a Standard queue unless strict ordering or exactly-once processing is required.

Constraints: Use FIFO only for a specifically ordered workflow.

### config_key: receive_wait_time_seconds

Set the queue default receive wait time to `20` seconds.

### config_key: VisibilityTimeout

Set visibility timeout greater than the longest expected processing time; extend it during long-running jobs when necessary.

### config_key: redrive_policy

Configure every Standard queue with a dead-letter queue and `maxReceiveCount = 3`.

### Rule: queue-naming

Name queues `{project}-{queue}` and dead-letter queues `{project}-{queue}-dlq`.

Constraints: Apply standard tags to every queue and dead-letter queue.

## Queue Client

### client.queue.submit

Submit a message through the cloud client library.

Constraints: Project code must not access raw boto3 clients, queue URLs, or regions.

### client.queue.drain

Drain queued messages through the cloud client library.

| Input | Description |
|---|---|
| message `id` | Identifier used by handlers for idempotency |
| `ttl_seconds` | Message lifetime; stale messages expire instead of being processed |

Returns counts with the following fields:

| Field | Description |
|---|---|
| `processed` | Number of messages considered |
| `succeeded` | Number of messages processed successfully |
| `failed` | Number of messages that failed |
| `expired` | Number of stale messages not processed |

Constraints: Receive with `WaitTimeSeconds = 20` and `MaxNumberOfMessages = 10`. Drain must be safe to run repeatedly and concurrently. Log the summary to CloudWatch.

### Rule: message-deletion

Delete a message only after its handler succeeds, using its `ReceiptHandle`.

Constraints: On processing failure, do not delete the message; allow the visibility timeout to lapse so it can be retried.

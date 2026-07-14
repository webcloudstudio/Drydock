# AWS SQS Best Practices

**Version:** 20260528 V1
**Category:** AWS
**Description:** SQS as the durable store-and-forward queue — producers submit 24×7, a local consumer drains when alive

Technology reference for Amazon SQS with Python (boto3, inside a cloud client library). This file does not
change between projects.

Prerequisites: `stack/python.md`, `stack/cloud-client-library.md`

SQS is the durable store-and-forward queue: a producer (a phone inside the firewall, a remote cron job,
a failed script) submits work at any time, even when the local consumer is off; the local agent drains
the queue when it next runs. Producers and consumers both go through the cloud client library — never
raw boto3.

---

## 1. Standard Queue, FIFO Only If Ordering Is Required

**Rule**: Use a Standard queue (at-least-once, best-effort ordering) unless strict ordering or
exactly-once is a hard requirement. Independent jobs fit Standard. Choose FIFO only for a specific
ordered workflow, accepting its throughput limits.

**Why**: Standard queues are cheaper, higher-throughput, and simpler. Independent work items do not depend
on each other, so at-least-once with idempotent handlers is the right trade.

---

## 2. Long Polling Always On

**Rule**: Always receive with `WaitTimeSeconds = 20` (long poll) and `MaxNumberOfMessages = 10`. Set the
queue's default `ReceiveMessageWaitTimeSeconds = 20` too. Never short-poll in a loop.

```python
# Inside the cloud client library's queue drain — shown for the rule only
resp = sqs.receive_message(QueueUrl=url, MaxNumberOfMessages=10, WaitTimeSeconds=20)
```

**Why**: Long polling cuts empty receives (and their cost) and lowers latency. Short polling burns money
and API calls returning nothing.

---

## 3. Delete Only After Successful Processing

**Rule**: Delete a message by its `ReceiptHandle` **only** after the handler succeeds. On failure, do
not delete — let the visibility timeout lapse so the message reappears and retries. This is the outbox
pattern; combined with idempotent handlers it makes drain safe to run repeatedly.

```python
process(msg)                 # raises on failure → message reappears after visibility timeout
sqs.delete_message(QueueUrl=url, ReceiptHandle=msg["ReceiptHandle"])
```

**Why**: Deleting before processing loses work on a crash. Deleting after guarantees at-least-once
delivery; idempotent handlers absorb the duplicate.

---

## 4. Visibility Timeout Exceeds Worst-Case Processing

**Rule**: Set `VisibilityTimeout` greater than the longest expected processing time (e.g. Whisper
transcription). For long jobs, extend mid-flight with `change_message_visibility`. Too short → the same
message is processed twice concurrently.

**Why**: A visibility timeout shorter than processing causes duplicate concurrent work and wasted effort.

---

## 5. Dead Letter Queue With maxReceiveCount = 3

**Rule**: Every Standard queue has a DLQ with a redrive policy `maxReceiveCount = 3`. A message that
fails three times moves to the DLQ for inspection instead of looping forever. Monitor DLQ depth.

```hcl
resource "aws_sqs_queue" "voice_dlq" { name = "${var.project}-voice-dlq" tags = local.common_tags }

resource "aws_sqs_queue" "voice" {
  name                       = "${var.project}-voice"
  receive_wait_time_seconds  = 20
  visibility_timeout_seconds = 300
  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.voice_dlq.arn, maxReceiveCount = 3
  })
  tags = local.common_tags
}
```

**Why**: A DLQ turns "poison message loops forever" into "poison message parked for a human," with a
clear redrive count.

---

## 6. Idempotent Drain, Counts Returned

**Rule**: `client.queue.drain()` is safe to run twice — handlers key on the message `id` and skip
already-applied work. Drain returns `{processed, succeeded, failed, expired}` and logs the summary to
CloudWatch. Honour a `ttl_seconds` on messages: expire rather than process stale work.

**Why**: Idempotent drain means the startup drain, a scheduled drain, and a manual drain cannot corrupt
state by overlapping. Returned counts make drains observable without a UI.

---

## 7. Access Through the Cloud Client Library

**Rule**: Producers call `client.queue.submit(...)`; the local consumer calls `client.queue.drain(...)`.
Queue URLs, regions, and boto3 clients live inside the cloud client library. Project code never holds a
queue URL.

**Why**: Centralizing the SQS client and URL keeps the queue swappable and prevents URL drift across
callers.

---

## Naming Standard

| Resource | Convention | Example |
|---|---|---|
| Queue | `{project}-{queue}` | `market-voice` |
| Dead letter queue | `{project}-{queue}-dlq` | `market-voice-dlq` |

Standard tags on every queue and DLQ.

---

## Summary Checklist

- [ ] Standard queue unless ordering truly required
- [ ] Long polling (`WaitTimeSeconds = 20`), `MaxNumberOfMessages = 10`
- [ ] Messages deleted only after successful processing
- [ ] `VisibilityTimeout` > worst-case processing time
- [ ] DLQ with `maxReceiveCount = 3`; DLQ depth monitored
- [ ] Drain idempotent, honours TTL, returns + logs counts
- [ ] All access through the cloud client library; no queue URL in project code
- [ ] Queue name includes project; standard tags applied

# FEATURE: Async Operations

| Field       | Value |
|-------------|-------|
| Version     | 20260621 V1 |
| Description | Marina accepts queued work through SQS and drains it locally for guarded project operations and voice transcription while preserving retry, TTL, and DLQ behavior. |
| Depends On  | FEATURE-MARINA-LIB.md, FEATURE-ACCESS-CONTROL.md, FEATURE-REPORTING.md, FEATURE-SHARE.md |
| Provides    | POST /queue/{queue}, local-queue-drain, prototyper-project-ops, voice-transcription-drain |
| Phase       | 4 |

## Purpose

Async operations decouple remote submission from local execution and make machine-touching work durable when the local agent is offline.

## Submit Flow

`POST /queue/{queue}`:
1. validates queue name and message contract
2. checks caller access
3. assigns message id and submitted timestamp
4. writes the message to the correct SQS queue
5. returns pending status

Supported queue families:
- `voice`
- `project-ops`
- future allow-listed queues only

## Drain Flow

The local agent calls `mar.queue.drain(queue=None)`.

For each received message:
1. skip expired messages using `ttl_seconds`
2. resolve `service` and `tool`
3. dispatch to an allow-listed handler
4. delete only after success
5. leave failed messages for visibility-timeout retry
6. rely on the DLQ after `maxReceiveCount=3`

Return counters:
- `processed`
- `succeeded`
- `failed`
- `expired`

## Project Operations

Supported tools:
- `validate`
- `update`
- `initialize`
- `document`

Rules:
- `tool` indexes a fixed allow-list only
- `project` must match a safe identifier pattern
- `args` are sanitized and limited to approved flags
- the handler shells out to Prototyper locally
- the result is reported as a Marina event

## Voice Transcription

Voice jobs:
- download the queued audio object from S3
- run local Whisper
- append dated transcribed text to the mapped target file
- report result counts or failure

No cloud transcription is allowed.

## Reads

- SQS queue messages
- local service registry
- local Prototyper checkout
- local voice target mappings
- share objects through the library

## Writes

- SQS queue submissions and deletes
- project-operation result events
- local project files for voice output and Prototyper actions

## Verification

`bin/test_asyncqueue.sh` proves:
- queue submit returns pending
- drain deletes only after success
- poison messages reach the DLQ
- idempotent re-drain processes nothing

`bin/test_project_ops.sh` proves:
- only allow-listed tools execute
- exit codes and output are captured
- unknown tools do not execute

`bin/test_voice_capture.sh` proves:
- an S3-backed voice job drains locally
- transcription appends text
- failed jobs retry and then DLQ

## Acceptance Criteria

- Submit and drain semantics preserve at-least-once delivery with delete-on-success.
- Project operations remain allow-listed and local only.
- Voice transcription remains local and durable through SQS plus S3.
- Queue metrics and result events make remote submissions observable.

## Guardrails

- No free-form command execution is permitted.
- No queue handler runs project code in the cloud.
- Messages are never deleted before handler success.

## Open Questions

- The default local drain cadence and whether to add application-level backoff beyond SQS-native retry remain open for delivery.
- Whether long-running local operations should emit incremental progress events is deferred.

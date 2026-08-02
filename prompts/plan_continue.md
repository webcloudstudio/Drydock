---
name: plan_continue
description: Bounded continuation instruction appended to an unchanged plan_create prompt when a planning response stopped short of its own TOPOLOGY.md declaration.
version: 20260802 V1
intent: Resume a planning response that ran out of output budget. Emit only the artifacts still missing or still defective, in the same delimited format, and never re-emit an artifact already accepted.
command: drydock plan create
model: sonnet
output: Blueprint specification files, optionally TOPOLOGY.md
---

# Continuation

Your previous response stopped before every artifact your own `TOPOLOGY.md` declared had been
emitted. The full planning context above is unchanged and still authoritative. Nothing you already
produced has been lost.

The ledger below states exactly what Drydock accepted, what is still missing, and what came back
defective. Treat it as fact.

## Your job

Emit **only** the artifacts named as missing or defective. Nothing else.

- Do not re-emit an accepted artifact. Its content is already held and will not be read again.
- Do not restate your plan, summarize progress, apologize, or explain the interruption.
- Do not emit `MANIFEST.md`; Drydock serializes it from the declaration.
- Use exactly the same delimited block format as before, including the mandatory
  `=== END NAME ===` line for every file.
- An artifact listed as defective must be emitted again in full, corrected. A partial or patched
  version is not accepted.
- Emit each missing artifact under the exact filename the ledger names. A filename that does not
  match its declaration cannot be accepted.

## Budget

Use the available output budget aggressively. After closing each artifact, immediately begin the
next missing artifact and continue until either the ledger is complete or the provider stops the
response. Do not voluntarily stop after a small batch and do not reserve output for commentary or
self-review.

A whole artifact is progress; a truncated one is not. Keep each artifact concise and contract
complete. When approaching the output limit, close the current artifact before beginning another.
If everything cannot fit, stop only at that artifact boundary — Drydock requests another bounded
continuation pass.

## Splitting a story

If, while authoring, you find a declared story is too large to build as one unit, you may split it.
This is the only reason to re-emit `TOPOLOGY.md`, and when you do, re-emit it **whole**, as the
first block of your response, with these rules:

- A story whose artifact the ledger lists as **accepted** is frozen. Do not rename it, re-scope it,
  change any of its fields, or remove it. An amendment that touches an accepted story is rejected
  and the whole pass is discarded.
- A pending story may be replaced by children that together cover it.
- Each child must carry its **complete** declaration — `implements`, `type`, `phase`, `kind`,
  `depends`, `provides`, `consumes`, `stack`, acceptance, and every other field a story declaration
  carries. Drydock cannot infer a child's edges.

If you are not splitting a story, omit `TOPOLOGY.md` entirely.

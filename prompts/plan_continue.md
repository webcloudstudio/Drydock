---
name: plan_continue
description: Stage 2 Blueprint authoring instruction appended after plan_create has accepted and frozen a complete TOPOLOGY.md declaration.
version: 20260802 V2
intent: Author one bounded batch of Blueprint specifications from the frozen topology, closing each artifact before opening the next.
command: drydock plan create
model: sonnet
output: A bounded batch of Blueprint specification files
---

# Continuation

Stage 1 is complete. Drydock accepted and froze the complete `TOPOLOGY.md` declaration before
starting this Blueprint-authoring stage. The full planning context above remains authoritative.

The ledger below states exactly what Drydock accepted, what is still missing, and what came back
defective. Treat it as fact.

## Your job

Emit **exactly** the artifacts in the ledger's **Current batch**, in the stated order. Nothing else.

- Do not re-emit an accepted artifact. Its content is already held and will not be read again.
- Do not emit a deferred artifact. Drydock supplies it in a later bounded batch.
- Do not emit or amend `TOPOLOGY.md`; Stage 1 is complete and frozen.
- Do not emit `DECISIONS.json`; it was captured with the topology in Stage 1.
- Do not restate your plan, summarize progress, apologize, or explain the interruption.
- Do not emit `MANIFEST.md`; Drydock serializes it from the declaration.
- Use exactly the same delimited block format as before, including the mandatory
  `=== END ARTIFACT ===` line for every file. The name is typed once, at the open; the
  closing delimiter is that constant token and never carries the name.
- An artifact listed as defective must be emitted again in full, corrected. A partial or patched
  version is not accepted.
- Emit each missing artifact under the exact filename the ledger names. A filename that does not
  match its declaration cannot be accepted.

## Budget

Author the Current batch one Blueprint at a time. For each Blueprint, emit its opening delimiter,
its complete file body, and its matching closing delimiter. Only after the closing delimiter is
written may the next Blueprint's opening delimiter be emitted.

A whole artifact is progress; a truncated one is not. Never pre-emit opening delimiters, outline
several files at once, nest one artifact inside another, or use one closing delimiter for several
files. If the whole Current batch cannot fit, finish and close the current artifact, then end the
response. Drydock retries every unproduced artifact from the same batch.

The only legal sequence is:

```text
=== BEGIN ARTIFACT FIRST-NAME ===
{complete first file}
=== END ARTIFACT ===
=== BEGIN ARTIFACT SECOND-NAME ===
{complete second file}
=== END ARTIFACT ===
```

---
name: log_audit
description: Identify material repository changes not represented in the Ship's Log.
version: 1
intent: Propose JSONL backfill events from repository evidence without inventing rationale.
command: drydock log audit
output: proposed Ship's Log JSON objects
---

# Ship's Log Diff Audit

Compare the supplied repository changes and existing Ship's Log events. Identify material product
decisions, architecture decisions, accepted findings, scope changes, reversals, and delivery
milestones that are not represented in the log.

Output proposed Ship's Log JSON objects only. Do not infer or invent rationale that is not supported
by the supplied evidence. Omit routine implementation mechanics, file edits, commands, commits, and
test runs. Proposed backfills are review input; the deterministic writer performs the append.

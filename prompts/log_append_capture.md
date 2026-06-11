---
name: log_append_capture
description: Capture material product and delivery events in the target Ship's Log.
version: 1
intent: Ensure Drydock-controlled agents record decisions and milestones without logging mechanics.
command: drydock log append
output: <Target>/logs/ships_log.jsonl
---

# Ship's Log Capture Contract

Record a Ship's Log event immediately after making a material product or architecture decision,
accepting a spike finding, materially changing scope, rejecting a meaningful alternative, reversing
an earlier decision, or reaching a material delivery milestone.

Use `drydock log append <Target>` and provide a concise title, summary, and rationale. Include
affected scope, evidence, alternatives, tags, and superseded event IDs when applicable.

Do not record routine implementation mechanics, file edits, commands, commits, or test runs. Those
belong in execution logs. Never rewrite or delete an existing Ship's Log record; append a new event
with `supersedes` when a decision changes.

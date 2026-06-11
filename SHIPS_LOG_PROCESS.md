# Ship's Log Process

## Purpose

The Ship's Log preserves material product decisions and delivery milestones as structured,
append-only events. It is currently a Drydock-only development proving ground, not a public CLI
workflow and not a rule injected into target projects.

The intended future product capability is standard agent-driven capture during Drydock-managed
design and build workflows, producing decision records that users can review and publish. That
deployment is deferred until the decision backend and workflow have been validated through
Drydock's own development.

The only canonical artifact is `logs/ships_log.jsonl`. QuarterDeck and future publishing tools read
that JSONL directly. Never create or maintain a Markdown Ship's Log.

## Required Agent Behavior

Every agent working in the Drydock repository must evaluate Ship's Log capture:

1. Immediately after making or receiving approval for a material decision or reaching a material
   delivery milestone.
2. Again before committing or declaring the task complete, using the completed diff and discussion
   to catch events missed during implementation.

Record an event for:

- an approved specification or product-behavior change;
- a feature addition, removal, or material scope change;
- an architecture, persistence, interface, governance, or development-process decision;
- a meaningful completed delivery milestone;
- a reversal or replacement of an earlier recorded decision.

Do not record routine file edits, implementation mechanics, commands, commits, test runs, or minor
refactors that do not change product behavior or development governance.

If no event qualifies, report that the final Ship's Log review found no material event. Do not add a
placeholder record.

## Recording Events

Use the repository-local utility; do not hand-edit the JSONL:

```bash
python bin/ships_log.py record \
  --event-type decision \
  --title "Concise decision title" \
  --summary "What changed or was decided." \
  --rationale "Why this choice was made." \
  --source-type agent \
  --source-command "task or workflow" \
  --source-provider codex \
  --scope "affected area" \
  --alternative "Rejected option::Reason it was rejected" \
  --evidence "path or durable evidence" \
  --tag "classification"
```

Use `--event-type milestone` for meaningful completed delivery milestones. Repeat `--scope`,
`--alternative`, `--evidence`, `--supersedes`, and `--tag` as needed.

Use these interim classification tags when applicable:

- `open-item` — a material unresolved question or follow-up requiring a future decision;
- `deferred-item` — an accepted capability or action intentionally postponed;
- `accepted-risk` — a known material risk explicitly accepted for the current decision.

These are prompt-level classifications stored in the existing `tags` list. Do not add placeholder
events solely to populate a category, and do not treat this interim taxonomy as a replacement for
the future decision backend.

When reversing or replacing an earlier decision, append a new event and pass the earlier event ID
with `--supersedes`. Never rewrite or delete an existing record.

Validate the ledger when changing its process, schema, persistence, or viewer:

```bash
python bin/ships_log.py audit
```

## Record Contract

Each line is one schema-version-1 JSON object with:

- generated `event_id` and `recorded_at`;
- `event_type`: `decision` or `milestone`;
- concise non-empty `title`, `summary`, and `rationale`;
- a source object identifying the event's origin;
- optional affected scope, alternatives, evidence, superseded event IDs, and tags.

The utility validates the record before performing one append-only write to
`logs/ships_log.jsonl`.

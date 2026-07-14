---
name: Manifest Contract
description: Contract governing the format, block types, field semantics, lifecycle states, and execution rules for `MANIFEST.md` — the single generated executable build plan for a Drydock Target.
version: 20260714 V9
---

## Overview

`MANIFEST.md` is the single generated execution view of the Blueprint. It determines build order,
selects required context, keeps work within useful context limits, identifies stale work, and
preserves unaffected accepted work. It is not a second product definition.

**Location:** `$DRYDOCK_WORKSPACE/targets/<Target>/MANIFEST.md`

The Manifest manages the full product lifecycle:

- specifications for individual components can be changed, resulting in context-minimized
  incremental builds
- new files (such as change tickets) can be discovered and applied

---

## Plan Header

```markdown
# MANIFEST: {ProjectName}
updated:     2026-06-08T12:00:00
plan_hash:   abc123456789
applied_specs: |
  DATABASE.md sha256=<content_sha256> commit=<file_commit_sha> applied_by=foundation applied_at=2026-06-26T14:22:00Z
```

Build execution evidence lives in the execution log. The Manifest preamble carries build-state
provenance required to detect stale previously applied Blueprint Specifications. `applied_specs`
records one line per Blueprint Specification file applied by a successful story or spike. The path
is relative to `blueprint/`. `sha256` is the authoritative dirty signal. `commit` is the latest git
commit that touched that file, or `-` when unavailable. `applied_by` identifies the story or spike
that last applied the file. `applied_at` is the UTC application timestamp.

---

## Block Types

The Manifest contains four block types: `feature`, `story`, `spike`, `ac`.

### Feature

A feature is an optional non-executable parent ticket. It groups substantial workflows and owns
feature-level acceptance gates. Small plans do not require features. A feature closes only after
all required child stories, spikes, and feature-level `ac` blocks are `closed/verified`.

```markdown
## feature N: {Name}
id:      feature-catalog
summary: One-line description.
state:   pending
```

### Story

A story builds something. It is an enriched unit of work with states, dependencies, Blueprint
acceptance, and prompt-assembly fields.

Stories and Blueprint specification files are one-to-one: every story implements exactly one
Blueprint file, and every Blueprint file is implemented by exactly one story. The story is the
atomic build primitive. Context economy comes from grouping, not from bundling files into one
story: a `feature` block builds as one combined prompt with the shared stack deduped across its
stories, so atomic stories cost no extra context while preserving per-file build state,
incremental rebuild via `applied_specs`, failure attribution, and evidence.

```markdown
## story N: {Name}
id:           foundation
parent:       feature-catalog
summary:      One-line description.
implements:   FEATURE-CATALOG.md
context:      ARCHITECTURE.md, DATABASE.md
stack:        common.md, python.md, sqlite.md
rules:        CLAUDE_RULES.md
copy:         Rigging/templates/common.sh -> bin/common.sh
instructions: |
  Build persistence and the catalog service.
depends:      select-parser
state:        pending
evidence:     <Target>/evidence/<id>.md
scope:        blueprint | target | both
```

**Field reference:**

| Field | Required | Description |
|-------|----------|-------------|
| `id` | Yes | Stable unique slug within the Manifest |
| `parent` | No | Parent feature id for hierarchy and QuarterDeck display |
| `summary` | Yes | One-line description |
| `implements` | Yes | The single Blueprint spec file this story builds — exactly one file; stories and Blueprint files are one-to-one |
| `context` | No | Read-only support context files |
| `stack` | No | Rigging stack files to inject |
| `rules` | No | Rigging rules files to inject |
| `copy` | No | `source -> destination` file copies applied before build |
| `instructions` | Yes | Freeform build instructions for the agent |
| `depends` | No | Space-separated ids that must be `closed/verified` first |
| `state` | Yes | Current block state |
| `evidence` | No | Path to the evidence file written after execution |
| `scope` | No | `blueprint` \| `target` \| `both` — what this story changes |

When `implements` is `DATABASE.md`, `stack` must include `persistence.md` and the selected
backend stack file, such as `sqlite.md`, `postgres.md`, or `aws-dynamodb.md`.

### Spike

A spike answers a question. Results feed future iterations. The `finding` field is written by
the agent when the spike runs.

```markdown
## spike N: {Name}
id:       select-parser
summary:  One-line description.
context:  FEATURE-IMPORT.md
question: Which parser satisfies the Blueprint?
parent:   feature-import
finding:  ← text answer written here by the agent
depends:  foundation
state:    pending
evidence: <Target>/evidence/<id>.md
```

| Field | Required | Description |
|-------|----------|-------------|
| `id` | Yes | Stable unique slug |
| `summary` | Yes | One-line description |
| `context` | No | Read-only context files |
| `question` | Yes | The question this spike must answer |
| `parent` | No | Parent feature id |
| `finding` | No | Agent-written answer after execution |
| `depends` | No | Space-separated prerequisite ids |
| `state` | Yes | Current block state |
| `evidence` | No | Path to evidence file |

### Acceptance Check (ac)

An `ac` block checks that something works. A failed AC blocks plan progress.

```markdown
## ac N: {Name}
id:       system-starts
parent:   foundation
summary:  One-line description.
kind:     smoke | assertion
check:    test -f bin/start.sh && curl -sf http://localhost:${PORT}/health
depends:
state:    pending
evidence: <Target>/evidence/<id>.md
```

| Field | Required | Description |
|-------|----------|-------------|
| `id` | Yes | Stable unique slug |
| `parent` | Yes | Story or feature this AC gates |
| `summary` | Yes | One-line description |
| `kind` | Yes | `smoke` — runs a command; `assertion` — checks behavior from evidence or review |
| `check` | If smoke | Shell command to execute |
| `depends` | No | Prerequisite ids |
| `state` | Yes | Current block state |
| `evidence` | No | Path to evidence file |

A compact single-line form is also accepted and is equivalent to the field body
above:

```markdown
## ac N: {Summary} (smoke|assertion: {check})
```

The reader derives `id` (a slug of the summary), `kind`, and `check` from the
header, sets `state: pending`, and assigns `parent` to the nearest preceding
`story`, `spike`, or `feature`. Use the explicit field body when an `ac` must
gate a block other than its immediate predecessor or needs `depends`/`evidence`.

---

## Block States

All four block types use the same four states:

| State | Meaning |
|-------|---------|
| `pending` | Not run yet |
| `implemented` | Work done, waiting to be accepted |
| `closed/verified` | Passed or accepted |
| `closed/failed` | Failed or rejected |

---

## Execution Rules

A block runs only when everything in `depends:` is `closed/verified`. Features are never directly
executable.

An `ac` runs only after its `parent` is `implemented`. Feature-level `ac` blocks are the
exception: they become runnable after all executable child stories and spikes are
`closed/verified`.

A `story` or `spike` cannot become `closed/verified` until its child `ac` blocks are
`closed/verified`. If a story or spike has no child `ac` blocks, it may close automatically when
it reaches `implemented`.

If an `ac` becomes `closed/failed`, the parent does not close and later dependent work stays
blocked.

`closed/failed` is not terminal. The product owner reopens failed work from the QuarterDeck —
revising instructions, acceptance, or scope interactively — and the decision writer
returns it to `pending` with the revision recorded. Recovery never requires hand-editing the
Manifest.

Guardrails and `Programmatic Acceptance` assertions embedded in Blueprint Specification files run
after each successful story build. Failing programmatic acceptance marks the story `closed/failed`
and blocks dependent work. `User Acceptance` entries are Commander review signals and do not block
ordinary downstream build unless modeled as explicit dependencies.

---

## Plan State Writer

The **decision writer** is the only mutator of Manifest block state. It is invoked by:

- the QuarterDeck review controls (approve, revise, reject, add defect on individual blocks)
- the `drydock build` engine (state transitions during execution)

Review decisions written in the QuarterDeck write back to `MANIFEST.md` through the same
decision writer used by the CLI.

---

## Relationship to Blueprint

The Manifest is generated from the Blueprint; it is not a second product definition. `drydock plan
create` reads all Blueprint inputs and writes `MANIFEST.md` — the single work graph carrying build
order, grouping, and per-step prompt-assembly fields. It regenerates after each planning cycle.

The Blueprint remains the source of truth for what the project is and must do. The Manifest is
the source of truth for build state. The QuarterDeck renders Manifest state and records decisions
through the plan writer — the console can be deleted and regenerated at any time.

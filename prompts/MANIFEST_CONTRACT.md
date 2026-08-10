---
name: Manifest Contract
description: Contract governing the format, story types, field semantics, lifecycle states, block grouping, and execution rules for `MANIFEST.md` — the single generated executable build plan for a Drydock Target.
version: 20260801 V14
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
planning_feedback: |
  decision-0123456789abcdef applied FEATURE-CATALOG.md
  decision-fedcba9876543210 retained
```

Build execution evidence lives in the execution log. The Manifest preamble carries build-state
provenance required to detect stale previously applied Blueprint Specifications. `applied_specs`
records one line per Blueprint Specification file applied by a successful story. The path
is relative to `blueprint/`. `sha256` is the authoritative dirty signal. `commit` is the latest git
commit that touched that file, or `-` when unavailable. `applied_by` identifies the story
that last applied the file. `applied_at` is the UTC application timestamp.

---

## Story Types

The Manifest is a list of stories. A `type` field is the only variation.

| Type | Contains | Runs |
|---|---|---|
| `foundational` | Foundation and scaffolding | Early; work depends on it |
| `service` | Everything that does work | Reorderable |
| `feature` | Acceptance criteria plus assembly and intent; no implementation instructions | After its members |

Foundational work is structure and scaffolding. Standing up S3 and proving the connection is
architecture. Everything S3 subsequently does is a service. Everything that is not architecture is
a service, and services are reorderable because they carry no structural debt. Much of what source
material labels architecture is service work: the web server and the database are foundation; a
voice service interpreter is a service wearing an architecture filename.

Foundation status derives from the dependency graph, not from a filename prefix. The rule is
*build the foundation that is needed*, not *build all foundation first*.

There is no fourth type. A "foundational service" — voice-to-text, for example — is foundational to
whatever depends on it, which the edges already state more precisely than a label could.

`spike` is not a story type. Research questions are handled by questionnaires before Plan and by the
owning story's `## Questions` section after. `ac` is not a story type: Programmatic Acceptance is
verification the build runs to prove a story is complete. A story is not "built and failed" — it is
built or it is not, so acceptance is a field the story owns and passing is part of the story's own
state transition.

### Feature is an assembly story

A feature is a story that depends on its member stories, carries acceptance criteria, and carries
assembly and intent instructions instead of implementation instructions. Same node, same execution
path, different content shape. When its member stories complete, the feature story runs and is made
to pass like any other story, so integration testing is a real build step rather than an implicit
hope. A feature story is preferably placed in the same block as its members.

### Story

```markdown
## story N: {Name}
id:           foundation
summary:      One-line description.
type:         foundational
kind:         capability
phase:        1
block:        1
implements:   ARCHITECTURE.md
covers:       CATALOG-001
accepts:      st-001
context:      DATABASE.md
stack:        common.md, python.md, fastapi.md
stack_mode:   builder
provides:     GET /health
consumes:
instructions: |
  Stand up the application factory and health check.
acceptance:   yes
depends:
state:        pending
```

**Field reference:**

| Field | Required | Authored by | Description |
|-------|----------|-------------|-------------|
| `id` | Yes | Model | Stable unique slug within the Manifest |
| `summary` | Yes | Model | One-line description |
| `origin` | No | `drydock refit` | Provenance of a story authored from a source change, as `<source>@<commit>`. Absent on stories authored by `plan`. |
| `created` | No | `drydock refit` | ISO date the story was appended to the graph. |
| `type` | Yes | Model | `foundational` \| `service` \| `feature` |
| `kind` | Yes | Model | Delivery kind: `capability` \| `integration` \| `migration` \| `test harness` |
| `phase` | Yes | Model | Commander build sequencing; see below |
| `block` | Generated | Drydock | Context-optimization group; computed, never authored |
| `implements` | Yes | Model | The single governed specification this story builds |
| `covers` | No | Model | `ANALYSIS.md` Story IDs this story delivers. Every analyzed Story ID is named by exactly one story, whatever its `type`; a story with no analyzed counterpart omits the field |
| `accepts` | No | Model | `SEA_TRIALS.md` IDs this story implements |
| `context` | No | Model | Read-only support context files. Never a Compass file |
| `stack` | No | Model | Rigging stack files this story builds with |
| `stack_mode` | Generated | Drydock | `builder` \| `consumer`; computed from first use in build order |
| `provides` | No | Model | Routes, commands, symbols, datasets, queues, or events this story defines |
| `consumes` | No | Model | Interface points this story calls |
| `rules` | No | Model | Rigging rules files to inject |
| `copy` | No | Model | `source -> destination` file copies applied before build |
| `instructions` | Yes | Model | Freeform build instructions. A `feature` carries assembly and intent, not implementation |
| `acceptance` | Yes | Model | `yes` when the story has real acceptance to honor |
| `depends` | No | Model | Story ids that must be `closed/verified` first |
| `state` | Yes | Drydock | Current block state |
| `evidence` | No | Drydock | Path to the evidence file written after execution |
| `scope` | No | Model | `blueprint` \| `target` \| `both` — what this story changes |

Stories and governed specifications are one-to-one: every story implements exactly one
specification, and every specification is implemented by exactly one story. The story is the atomic
build primitive.

**Story sizing.** A story is a normal Agile story: 1 to 5 story points. Never a half point — that is
a task, folded into the story it serves. Never twelve — that is split. A story does one thing
completely, carries test criteria, and is releasable on its own; a task is not releasable and is
therefore not a story. A story has no token dimension. Token cost is measured against the block a
story is built in, never against the story. Story count is not capped: it is an output of correct
decomposition, not a target.

### Authorship versus verification

The model authors relationships, the actual topology (the story dependency graph), the high-level
topology (phases), and Programmatic Acceptance. Drydock verifies all of it, groups blocks, orders
the work, and serializes the Manifest.

The model never sorts, never checks its own consistency, and never reasons about a position in an
order it has not computed. It states what each story requires and provides; Drydock does the rest.
Contradictions become a deterministic error with a precise message instead of a shape failure.

`drydock plan create` therefore does not emit this file. It emits a flat `TOPOLOGY.md` declaration
carrying the Model-authored fields below — one `## story <id>` heading per governed specification,
no ordering, no `block:`, no `stack_mode:`, no `state:` — and Drydock serializes `MANIFEST.md` from
it. The field semantics in this contract govern both forms.

**Two-topology check.** The high-level and actual topologies must agree: a story in phase 2 cannot
depend on a story in phase 3.

### Phase

`Phase` is Commander instruction on how to build: *build Feature X, then Feature Y*. It is not a
layer chain. The layer stack repeats inside each phase rather than running once across the project —
foundational / database / service / ui, then service / ui, then foundational / service / service /
ui. Commander ordering direction is input the model weighs, not an override applied afterward.

`Phase` describes when a file is built, not the file, so it lives in the Manifest and never in a
Blueprint header.

### Blocks

A **block** is a set of stories optimized for context: sized to amortize fixed stack-file cost
across one build run, never crossing stacks. Blocks are an optimization output, not a taxonomy. UI
stories group together whether or not they belong to the same Agile feature. Context economy comes
from blocks, not from feature grouping.

Blocks are ephemeral, Manifest-only, regenerated every run, and computed by Drydock:

- **Hard:** one topology type per block; never cross a phase boundary; never violate the edges
- **Objective:** amortize stack-file cost across the most stories that still fit one build pass

The mechanism behind the no-cross-stack guardrail is stack creep from Rigging. Mixing topology types
in one block forces every stack file each type needs into the block, so it pays for context neither
half uses and the build agent reads instructions for work it is not doing. This is the reason story
types exist: they are the block-partition key.

### Builder and consumer mode

The model authors the foundational story that stands a stack up. Drydock assigns the
builder/consumer flag from first use in the computed order: by definition the first story using a
stack is the builder and later ones are consumers. Ordering is build-order-global, as compact
substitution already is — not per-block, not phase-based. A builder story receives the full stack
file; a consumer story receives the interface view.

If the model assigned the flag it would be asserting a position in an order it has not computed.
Disagreement is a defect signal, not a tie to break: if the first user of a stack is not a
`foundational` story, an edge or a foundational story is missing and Drydock reports it. Ambiguity
defaults to builder, because consumer-when-it-should-be-builder starves the build agent while
builder-when-it-should-be-consumer merely costs tokens.

---

## Acceptance

Acceptance lives in one place per audience:

- **Programmatic Acceptance** — executable assertions carrying pass/fail state. Lives in
  `MANIFEST.md`. Not human-readable, not human-editable, regenerated wholly by every plan run.
- **User Acceptance** — human-readable intent. Lives in the Blueprint specification.

The discriminator for every other fact is the same question: **does the fact describe the artifact
or the schedule?**

| Fact | Home | Why |
|---|---|---|
| `Provides`, `Consumes`, `Depends On` | Blueprint header | Describe the file — what it offers and requires |
| Story `type` | Manifest | Computed, machine-focused |
| `Phase` | Manifest | Describes when the file is built, not the file |
| Programmatic Acceptance | Manifest | Machine-focused; nobody should hand-edit it |
| User Acceptance, `## Questions` | Blueprint | Human intent |

Durability is not a discriminator: the Blueprint does not survive a replan. Only the `## Questions`
section, harvested deterministically beforehand, survives.

---

## Block States

Every story uses the same four states:

| State | Meaning |
|-------|---------|
| `pending` | Not run yet |
| `implemented` | Work done, waiting to be accepted |
| `closed/verified` | Passed or accepted |
| `closed/failed` | Failed or rejected |

---

## Execution Rules

A story runs only when everything in `depends:` is `closed/verified`.

Programmatic Acceptance runs after the story build and is part of the story's own state
transition: a story that fails its acceptance becomes `closed/failed` and blocks dependent work.
There is no separate acceptance node with independent state.

A `feature` story runs after its member stories close. Its assembly and intent instructions are
made to pass like any other story's, which is what turns integration testing into a real build step
covering the seams between stories where multi-story builds actually break.

`closed/failed` is not terminal. The product owner reopens failed work from the QuarterDeck —
revising instructions, acceptance, or scope interactively — and the decision writer returns it to
`pending` with the revision recorded. Recovery never requires hand-editing the Manifest.

An open `Blocking` Blueprint question projects the story state as `blocked/questions`. That story
and its dependents are unavailable, while independent frontier stories remain buildable. Open `Low`
and `Material` decisions remain visible without gating.

`User Acceptance` entries are Commander review signals and do not block ordinary downstream build
unless modeled as explicit dependencies.

---

## Sea Trials Traceability

`accepts:` lists stable project-acceptance IDs from `SEA_TRIALS.md` that the story implements.
Every required technical or behavioral Sea Trial is referenced by at least one story or by a
Blueprint Programmatic Acceptance proof. Unknown IDs are invalid.

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

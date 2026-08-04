---
title: "SDD: Optimal Path to Managing Changed Specifications"
title_sub:
eyebrow: Drydock White Paper Series
subtitle: Why a changed specification must not rebuild the product, and what a source-driven refit does instead.
logo: ../drydock_logo.png
author: Ed Barlow
studio: Web Cloud Studio
year: August 2026
header_title: Drydock
copyright: Copyright © 2026 Web Cloud Studio. Licensed under CC BY 4.0 for this paper.
---

## Abstract

In specification-driven development the specification is the source of truth and the product is
generated from it. That property is what makes the method work, and it is also what makes change
expensive. If the specification is the input to the build, then editing the specification is, by
default, an instruction to build the whole thing again.

Early in a project you edit constantly. That is the point of the phase. A method that answers every
edit with a full rebuild makes the most valuable period of the project the most expensive one.

This paper states the problem precisely, rejects the obvious fixes, and documents the solution I
implemented in Drydock: the specification the product was built from is frozen, and change arrives
as an ordered ticket appended to it.

**Keywords:** specification-driven development, source-driven refit, immutable blueprints, change
tickets, lineage, dependency graph

## The Problem

A specification-driven build has one input and one output. Change the input and the honest answer is
to rerun the output. That answer is correct and unaffordable.

Three properties of real projects make it unaffordable.

**Edits are frequent and small.** The first weeks of a project are a stream of corrections: a field
becomes required, a screen loses a control, a rule changes. Each is a sentence. None of them justify
regenerating a product.

**Edits are unevenly weighted.** A wording change in a feature specification touches one artifact. A
change to the foundational or persistence layer is context for every artifact and legitimately
invalidates everything. A method that treats both the same is wrong twice — it over-builds the small
change and under-explains the large one.

**Detecting a file change is not detecting an impact.** A content hash tells you a file differs. It
does not tell you whether the contract that dependent artifacts consume differs. Rebuilding on file
difference rebuilds work that did not need doing.

There is a fourth problem, and it is the one that makes the first three hard to fix cleanly.

**The specification you edit is not the specification the product was built from.** Drydock imports
your authoring material into the Target and plans Blueprints from that snapshot. The Blueprint is a
derived, typed artifact — decomposed, cross-referenced, and graph-connected. Your source document is
prose you own. Editing the prose does not edit the Blueprint, and rewriting the Blueprint to match
the prose destroys the graph that the build depends on.

> Two documents describe the same product: the source you author and the Blueprint the build reads.
> Any change method that does not name which one is authoritative will drift.

## What Does Not Work

**Rebuild everything.** Correct, and rejected on cost. It also discards working, reviewed, scored
code to reproduce it, which is a reliability loss, not just a time loss.

**Edit the Blueprint in place.** This makes the Blueprint the source of truth and the authored
document a stale copy. It also destroys the property that matters most: that the product can be
regenerated from the authoritative source at any time. A hand-amended Blueprint holds decisions that
exist nowhere else.

**Mine the change out of the session.** Reading the LLM transcript for what changed produces slop.
A working session is exploration, dead ends, and thinking. See *Managing Changes in Specification-
Driven Development* [1] for that experiment and its failure.

**Queue changes in a change log.** A queue is latency. For as long as an entry sits described but
not applied, the specification lies about the system.

## The Solution — Source-Driven Refit

Four rules produce the whole design.

**The imported snapshot is the unit Drydock operates on.** Drydock reads
`targets/<Target>/blueprint/sources/`. Your external authoring directory is never implicitly live.
Changes become visible to Drydock only through `drydock import <Target> <Source> --update`. The
explicit refresh is the boundary between drafting and committing.

**Blueprints are immutable.** Once planned, a Blueprint is never edited. `drydock plan` is the only
path that changes one, and it does so by regenerating it. Refit never opens a Blueprint file.

**Change arrives as an ordered ticket.** `drydock refit <Target> --sources` reads the source delta,
resolves lineage to the affected Blueprints, and writes one ticket per affected Blueprint:
`<Blueprint-name>_refit_<number>.md`. A ticket is a Manifest story with state, so it inherits the
existing build, review, and scoring machinery and needs no new node type.

**The effective specification is the Blueprint read together with its chain, in order.** Ticket
`001` depends on the Blueprint and is ordered after every story implementing it. Ticket `002`
depends on `001`. A ticket declares that it supersedes its Blueprint and all preceding tickets, and
that the implementer follows the ticket on conflict. Ordering is what lets you contradict yourself
next week without editing anything you wrote last week.

### The loop

```mermaid
%%{init: {'theme': 'neutral', 'flowchart': {'curve': 'linear'}, 'themeVariables': {'fontSize': '14px'}}}%%
flowchart LR
  classDef dir    fill:#0a5c38,stroke:#2cb67d,color:#fff,font-weight:bold
  classDef md     fill:#d4a017,stroke:#a07810,color:#111,font-weight:bold
  classDef script fill:#1e40af,stroke:#3b5fc0,color:#fff,font-weight:bold
  classDef prompt fill:#c2410c,stroke:#ea580c,color:#fff,font-weight:bold
  classDef output fill:#6d28d9,stroke:#8b5cf6,color:#fff,font-weight:bold
  classDef web    fill:#be123c,stroke:#fb7185,color:#fff,font-weight:bold

  SRC(["authored source"]):::dir
  IMP["import --update"]:::script
  SNAP(["sources/"]):::dir
  REF["refit --sources"]:::script
  TIX{{"refit ticket"}}:::md
  BLD["build"]:::script
  PROD(["working software"]):::output

  SRC --> IMP --> SNAP --> REF --> TIX --> BLD --> PROD
```

*The authored source stays authoritative; the snapshot is what Drydock reads; the ticket is what
build implements.*

### Why the Blueprint survives

```mermaid
%%{init: {'theme': 'neutral', 'flowchart': {'curve': 'linear'}, 'themeVariables': {'fontSize': '14px'}}}%%
flowchart LR
  classDef dir    fill:#0a5c38,stroke:#2cb67d,color:#fff,font-weight:bold
  classDef md     fill:#d4a017,stroke:#a07810,color:#111,font-weight:bold
  classDef script fill:#1e40af,stroke:#3b5fc0,color:#fff,font-weight:bold
  classDef prompt fill:#c2410c,stroke:#ea580c,color:#fff,font-weight:bold
  classDef output fill:#6d28d9,stroke:#8b5cf6,color:#fff,font-weight:bold
  classDef web    fill:#be123c,stroke:#fb7185,color:#fff,font-weight:bold

  BP(["Blueprint"]):::dir
  T1{{"refit 001"}}:::md
  T2{{"refit 002"}}:::md
  T3{{"refit 003"}}:::md
  BLD["build in order"]:::script
  PROD(["current product"]):::output

  BP --> T1 --> T2 --> T3 --> BLD --> PROD
```

*A linear chain per Blueprint. Nothing is edited; everything is appended and applied in sequence.*

### Knowing what a change touches

Impact is a graph query, not a guess. `drydock plan` persists source lineage while it authors
Blueprints, in an isolated JSON block in the Manifest:

```text
source_lineage: |
  { ... versioned JSON ... }
```

The block records the imported source path, its content hash for the current transaction, the
Blueprint files it informs, and the tickets produced from it. The relationship is many-to-many: one
source can inform several Blueprints. When a changed source maps to several Blueprints, refit
partitions the change so every ticket is associated with exactly one Blueprint.

The Manifest stays the only graph. A second `SOURCE_MAP.json` would be a second truth and would
drift.

```mermaid
%%{init: {'theme': 'neutral', 'flowchart': {'curve': 'linear'}, 'themeVariables': {'fontSize': '14px'}}}%%
flowchart LR
  classDef dir    fill:#0a5c38,stroke:#2cb67d,color:#fff,font-weight:bold
  classDef md     fill:#d4a017,stroke:#a07810,color:#111,font-weight:bold
  classDef script fill:#1e40af,stroke:#3b5fc0,color:#fff,font-weight:bold
  classDef prompt fill:#c2410c,stroke:#ea580c,color:#fff,font-weight:bold
  classDef output fill:#6d28d9,stroke:#8b5cf6,color:#fff,font-weight:bold
  classDef web    fill:#be123c,stroke:#fb7185,color:#fff,font-weight:bold

  CHG(["changed source"]):::dir
  LIN{{"source_lineage"}}:::md
  BP1(["Blueprint A"]):::dir
  BP2(["Blueprint B"]):::dir
  T1{{"ticket A-003"}}:::md
  T2{{"ticket B-001"}}:::md

  CHG --> LIN
  LIN --> BP1 --> T1
  LIN --> BP2 --> T2
```

*Lineage turns "what did I just invalidate" into a lookup. One source, two Blueprints, two tickets.*

## Division of Labor

The LLM writes the ticket body — the exact specification of the required change, as a buildable
story. Everything structural is Python.

| Concern | Owner |
|---|---|
| Ticket body: what changed and what must now be true | LLM, via `prompts/refit_sources.md` |
| Ticket numbering and filename | Drydock |
| Manifest node creation and dependency edges | Drydock |
| Source content hashes | Drydock |
| Partition validation against the lineage candidate set | Drydock |
| Approval to apply | The Commander, by running `drydock build` |

A ticket citing a Blueprint outside the lineage-derived candidate set is rejected. Partitioning is
the last place a model can silently mis-scope, so it is validated rather than trusted.

## Boundaries That Make It Safe

**Refit is an atomic transaction.** It commits fully or rolls back. A partially applied refit is a
corrupt build graph. On failure no tickets remain on disk and the recorded source hashes stay
unadvanced, so a rerun reproduces the whole transaction instead of allocating orphan ticket numbers.
Each Target is its own Git repository, and that repository is the rollback mechanism.

**Foundational material cannot be refitted.** A changed Compass-owned source fails
`import --update` with a named-file error stating that a replan is required. Constitution-level
change legitimately invalidates everything; pretending otherwise is the error the ticket model is
designed to avoid. Silently skipping the changed file would turn a hard architectural constraint
into an invisible no-op.

**Deletion is a decision, never an inference.** A file present in the snapshot and absent from a
full-root re-import is a deletion, and it raises a blocking keep-or-remove choice recorded in the
resulting ticket. A file-scoped update never infers deletion: absence there means "not in scope,"
not "removed." Drydock never deletes a Blueprint automatically.

**Compact derivatives are never contracts.** Compaction output is derived context. LLM wording or
ordering differences in a compact file are not evidence that the product is stale, and compact
differences never reset a story.

**Supersession is an instruction, not a mechanism.** A superseded ticket is never skipped. Whether
a later ticket fully overrides an earlier one cannot be determined mechanically, and ordered
application is always correct. Building work that a later ticket overrides is accepted cost.

## The Reset Path

Tickets are never merged back into Blueprints. Merging is harder and less reliable than
regenerating. Reimport the authoritative source and replan the Target, and you get clean Blueprints
with no chain.

That makes the ticket chain a disposable convenience layer, which is why Drydock does not warn on
chain depth or nag the Commander to consolidate. Regeneration is cheap and always available, so
sprawl is self-limiting.

One invariant makes the reset lossless, and it is the discipline the method demands of you:

> No design decision may exist only in a Blueprint or a refit ticket. Every decision is written back
> to the authoritative external source.

Violate that and the reset stops being safe, because regenerating would discard decisions recorded
nowhere else. Hold it, and you can throw away the entire ticket chain at any time and rebuild from
prose you own.

## Result

| Property | Before | After |
|---|---|---|
| Cost of a small edit | Full rebuild | One ticket, one story |
| Blueprint stability | Rewritten on change | Immutable after planning |
| Impact analysis | Inspection | Lineage lookup in the Manifest |
| Foundational change | Indistinguishable from a typo | Explicit replan, refused by refit |
| Failure mode | Partial rebuild | Atomic transaction, Git rollback |
| Consolidation | Merge | Reimport and replan |

The specification is still the source of truth. What changed is the mechanism by which a change to
it reaches the product: not a rebuild of the specification, but an ordered ticket appended to a
frozen one.

## References

[1] E. Barlow. *Managing Changes in Specification-Driven Development.* Web Cloud Studio, 2026.

[2] E. Barlow. *Drydock Specification: Agile Specification-Driven Design — The SAIL Methodology for
Governed Software Delivery.* Web Cloud Studio, 2026.
https://github.com/webcloudstudio/Drydock

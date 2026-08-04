# NOTES: Source-Driven Refit

| Field | Value |
|-------|-------|
| Version | 2026-08-04 V2 |
| Route | `drydock refit --sources` |
| Status | Working notes — not canonical specification |
| Description | Source-driven refit that converts imported source changes into ordered, per-Blueprint refit tickets built as Manifest stories, leaving Blueprints immutable. |
| Pending spec | 15 approved items |
| Pending impl | 15 unimplemented sections |

## Goal

Allow the Commander to edit the authoring source material, explicitly refresh the Target's imported
source snapshot, and convert the resulting source change into ordered refit tickets that the build
implements. Blueprints are immutable and already built; the refit ticket carries the delta and is
itself a Manifest story. Replanning from the authoritative external source is the reset path.

The intended user loop is:

```text
edit authoring source
    → drydock import <Target> <Source> --update
    → drydock refit <Target> --sources
    → drydock build <Target>
```

## Decisions

### Target repositories are independent Git repositories
`2026-08-04` · `spec:approved` · `impl:unimplemented`

Each Drydock Target is its own Git repository. The Target repository is the unit of change
detection and rollback for Blueprints, imported sources, Manifest state, and refit tickets.

`drydock init` creates the Target repository when it creates a Target, but only after verifying
that the workspace repository ignores `targets/`. If `targets/` is not ignored, initialization does
not silently create a nested repository, because the parent and Target repositories would have
competing ownership and ambiguous change detection.

The initialization and diagnostics path reports the workspace repository root, whether `targets/`
is ignored, the Target repository root, and the Git root used for change detection.

Commands resolve the Target repository from the configured workspace and Target name. They do not
depend on the caller's current directory. Source refit fails with an actionable error when the
Target repository cannot be resolved; it does not fall back to an unrelated Git root or to
filesystem-only comparison.

Any command that modifies files under `targets/` commits the Target repository itself. `import` and
`refit` are the commands that matter for this workflow, but the rule is universal. The parent
Drydock repository's `git add -A` convention does not recurse into a nested Target repository, so
Target commits are the command's responsibility and cannot be delegated to the parent.

### Imported source snapshot is the Drydock source item
`2026-08-04` · `spec:approved` · `impl:unimplemented`

Drydock operates on the imported snapshot under:

```text
targets/<Target>/blueprint/sources/
```

The external authoring directory is not implicitly live. Changes to the external source become
available to Drydock only after an explicit `drydock import <Target> <Source> --update`.

The external authoring source remains the authoritative source of truth for the product. The
imported snapshot is Drydock's working copy of it. Import metadata continues to identify the
original source root and import format.

### `import --update` refresh scope, Compass immutability, and deletion detection
`2026-08-04` · `spec:approved` · `impl:unimplemented`

The import command gains an `--update` option. It refreshes files previously imported as ordinary
Markdown, source, Spec Kit, or other non-Compass material.

`--update`:

- compares incoming files with `blueprint/sources/`;
- copies added and changed files;
- leaves unchanged files untouched;
- preserves relative paths;
- records the per-file source content hash in the Manifest;
- reports added, changed, deleted, and unchanged files;
- commits the Target repository.

The source content hash is recorded per imported source file, not per Target, because one source
can feed several Blueprints. The hash advances only when the consuming refit transaction commits.

**Compass-owned material is immutable after setup.** A Compass-owned source file that has changed
causes `import --update` to fail with an actionable error naming the files and stating that a
replan is required. This is a deterministic check with no LLM involvement. `--update` never copies
Compass-owned files and never modifies `COMPASS.md`. Silently excluding a changed Compass source is
prohibited: it would turn a hard architectural constraint into an invisible no-op.

The source-role table in `ANALYSIS.md` is the authority for Compass classification. A source file
not present in the source-role table defaults to ordinary imported material for compatibility with
older Targets; `--update` does not invoke the LLM to rediscover roles.

**Deletion detection.** A file present in the imported snapshot and absent from the incoming source
tree is a deletion. This is mechanically detectable by comparing the two trees and requires no
history. Deletion may be inferred only on a **full-root** re-import; a file-scoped or subtree-scoped
update must never infer deletion, because absence there means "not in scope," not "removed."

A detected deletion is a blocking decision presented to the Commander: keep the feature, or remove
it. The choice is recorded in the resulting refit ticket. Drydock never deletes a Blueprint
automatically.

### Lineage is stored in an isolated JSON block in the Manifest
`2026-08-04` · `spec:approved` · `impl:unimplemented`

The Manifest remains the graph database and owns the semantic source lineage. A second
`SOURCE_MAP.json` graph is not created because it could drift from the Manifest's story-to-Blueprint
graph.

The Manifest contains a dedicated top-level block, separate from ordinary story syntax and from
`applied_specs`:

```text
source_lineage: |
  { ... versioned JSON ... }
```

The block records, at minimum: imported source relative path; source content hash for the current
transaction; associated Blueprint file(s); source scope or relationship; and the refit tickets
associated with the relationship.

The Manifest's normal graph owns stories, `implements`, dependencies, context, and state.
`source_lineage` owns source-to-Blueprint relationships. `applied_specs` owns Blueprint-to-build
application hashes. Dedicated parser and writer functions update the JSON block; LLM-generated
Manifest output does not author or reproduce it.

Lineage is mandatory. Without it, `refit --sources` has no candidate set.

### Planning persists lineage; no bootstrap capability is built
`2026-08-04` · `spec:approved` · `impl:unimplemented`

`drydock plan` persists source lineage while authoring Blueprint files. Lineage is derived from the
analyzed source citations, relationship model, source roles, and Story Realization Map, then
validated against actual Blueprint and Manifest paths. Because each Blueprint originates from a
named specification, the mapping is available at planning time.

The relationship may be many-to-many: one source can inform several Blueprints.

No one-time lineage bootstrap capability is implemented for Targets planned before `source_lineage`
existed. Those Targets are replanned once, as an operator action, **after** `plan` persists lineage.
Replanning earlier produces no lineage and is wasted work.

### Blueprints are immutable
`2026-08-04` · `spec:approved` · `impl:unimplemented`

A Blueprint, once planned, is never modified — foundational Blueprints included. `drydock plan` is
the only path that changes a Blueprint, and it does so by regenerating it.

Source-driven refit therefore never edits Blueprint files. It appends refit tickets.

### Refit tickets are Manifest stories chained per Blueprint
`2026-08-04` · `spec:approved` · `impl:unimplemented`

A refit ticket is a Manifest story with state. Blueprints and stories are effectively the same node
class, so a ticket requires no new node type and inherits existing build, review, and scoring
machinery.

Tickets are per Blueprint and numbered sequentially in application order, for example
`blueprint_refit_001.md`. Ordering is critical: it is what allows the Commander to contradict an
earlier decision.

The chain is linear per Blueprint. Ticket `001` depends on the Blueprint node, ordered after every
story implementing it. Ticket `002` depends on `001`, and so on. Dependency edges are inherited
deterministically from the Blueprint in Python; the graph is already known and nothing is
recomputed. The LLM never authors or recomputes Manifest edges.

One `refit --sources` run creates **at most one ticket per affected Blueprint**. It never creates
multiple tickets for the same Blueprint in a single run.

Every ticket is associated with exactly one Blueprint. No ticket spans Blueprints.

### Refit ticket shape and conflict authority
`2026-08-04` · `spec:approved` · `impl:unimplemented`

A refit ticket declares its identity and authority in its header: that it is change ticket `NNN` for
Blueprint `XYZ`, that it supersedes that Blueprint's specification and all preceding tickets in the
chain, and that in case of conflict the implementer follows this ticket. The body explains the
change as a buildable story with the elements any story requires.

Supersession is a **conflict-resolution instruction to the implementer**, resolved by chain order.
It is not a field the build planner acts on, and there is no supersession detection: a superseded
ticket is never skipped. Redundant work from building a ticket that a later ticket overrides is
accepted, because supersession cannot be determined mechanically and ordered application is always
correct.

Each `refit --sources` run reconciles against the Blueprint plus its prior tickets, so the effective
specification is the Blueprint read together with its chain in order.

### Source refit authors tickets and requires its own prompt
`2026-08-04` · `spec:approved` · `impl:unimplemented`

`drydock refit <Target> --sources` reads the source delta since the recorded hashes, resolves
lineage to the affected Blueprints, and authors one ticket per affected Blueprint. It does not
modify Blueprints, does not re-run full project planning, and does not rebuild the dependency graph.

Ticket authoring uses a dedicated prompt, `prompts/refit_sources.md`, separate from the existing
change-ticket refit prompts.

Drydock validates and writes the result. The LLM emits ticket content only; node creation,
dependency edges, numbering, and hashes are Python.

### Refit is an atomic transaction
`2026-08-04` · `spec:approved` · `impl:unimplemented`

A refit either commits fully or rolls back. There is no partial-success path, because a partially
applied refit is a corrupt build graph.

On failure, refit leaves no tickets on disk and leaves the recorded source hashes unadvanced, so a
rerun reproduces the full transaction rather than allocating orphan ticket numbers. The Target Git
repository is the rollback mechanism.

### One source feeding many Blueprints is partitioned
`2026-08-04` · `spec:approved` · `impl:unimplemented`

When a changed source file maps to several Blueprints, refit partitions the change so that each
resulting ticket is associated with exactly one Blueprint.

This partition is the last remaining place the LLM can silently mis-scope, so it is validated:
every changed source region lands in exactly one ticket, and no ticket cites a Blueprint outside
the lineage-derived candidate set.

### Compact derivatives remain non-authoritative
`2026-08-04` · `spec:approved` · `impl:unimplemented`

Compact Blueprint files are derived context and are never independent product specifications.
Compact output differences never independently reset a story and are never used as a contract hash.
Nondeterministic LLM wording or ordering in a compact file is not evidence that the built product is
stale. Compact provenance may record the source hash, prompt version, model, and output hash for
diagnostics only.

### Build is the approval boundary and respects chain order
`2026-08-04` · `spec:approved` · `impl:unimplemented`

Source refit requires no separate Commander approval step. `drydock build <Target>` is the approval
and execution boundary.

Build implements the refit tickets. It does not rebuild the Blueprints, which are already built. All
stories are built in order; refit tickets are the ordered nodes. Build must never parallelize a
single Blueprint's ticket chain.

```text
drydock import <Target> <Source> --update
    → refresh ordinary imported sources, record hashes, commit

drydock refit <Target> --sources
    → resolve lineage to affected Blueprints
    → author one refit ticket per affected Blueprint
    → chain each ticket onto its Blueprint's existing chain
    → commit atomically

drydock build <Target>
    → implement the refit tickets in order
```

### No merge story; reimport and replan is reconsolidation
`2026-08-04` · `spec:approved` · `impl:unimplemented`

Refit tickets are not merged back into Blueprints. Merging is harder and less reliable than
regenerating: the authoritative external source can be reimported and the Target replanned to
produce clean Blueprints with no ticket chain.

The ticket chain is therefore a disposable convenience layer. The reset is always available and
cheap.

### No chain-depth signalling in MVP
`2026-08-04` · `spec:approved` · `impl:unimplemented`

Drydock does not warn on ticket chain depth and does not prompt the Commander to replan. Because
the external source is authoritative and regeneration is cheap, chain sprawl is self-limiting and
does not warrant a mechanism in the minimum viable product.

## Acceptance Criteria

- A newly initialized Target has an independent Git repository when and only when the workspace
  repository ignores `targets/`.
- Git diagnostics identify the exact workspace and Target repository roots used for change
  detection, regardless of caller directory.
- Commands that modify `targets/` commit the Target repository.
- `drydock import --update` refreshes ordinary imported sources, records per-file source hashes,
  and reports added, changed, deleted, and unchanged files.
- `drydock import --update` fails with a named-file error when a Compass-owned source has changed.
- Deletion of a source file is detected on full-root re-import only, and raises a blocking
  keep-or-remove decision rather than deleting a Blueprint.
- `drydock plan` persists validated source lineage in the isolated Manifest JSON block.
- `drydock refit --sources` creates at most one refit ticket per affected Blueprint per run.
- Refit tickets are Manifest stories, numbered per Blueprint, chained linearly onto the Blueprint
  node with deterministically inherited edges.
- Refit tickets declare the Blueprint and preceding tickets they supersede and the conflict rule.
- `drydock refit --sources` never modifies a Blueprint file.
- A failed refit leaves no tickets on disk and no advanced source hash.
- Every ticket maps to exactly one Blueprint within the lineage-derived candidate set.
- `drydock build` implements ticket chains in order and never parallelizes one Blueprint's chain.
- Compact-only differences never reset a story.

## Guardrails

- **No design decision may exist only in a Blueprint or a refit ticket.** Every decision must be
  written back to the authoritative external source. This is the invariant that keeps regeneration
  lossless and keeps the ticket chain disposable.
- Never allow the parent Drydock repository and a Target repository to ambiguously own the same
  Target files.
- Never infer the Target Git root from the caller's current directory when the configured workspace
  identifies the Target.
- Never modify a Blueprint outside `drydock plan`.
- Never silently skip a changed Compass-owned source.
- Never infer source deletion from a scope-limited import.
- Never create a second independent source-to-Blueprint graph outside the Manifest.
- Never let an LLM author Manifest edges, ticket numbering, or hashes.
- Never allow an LLM to produce a ticket citing a Blueprint outside the lineage candidate set.
- Never leave a partially applied refit transaction.
- Never use compact output byte differences as contract evidence.
- Never make source refit require an additional approval gate before build.

## Open Questions

- Exact on-disk filename pattern and directory for refit tickets. Working example
  `blueprint_refit_001.md`; the per-Blueprint qualifier and containing directory are unresolved.
- The detailed body contract for a refit ticket beyond the header and authority statement, to be
  specified when `prompts/refit_sources.md` is authored.

## Future work

- On failure applying a refit ticket during build, fall back to rebuilding the Blueprint. Not
  required for MVP.
- One-time replan of the existing Target after `plan` persists lineage. Operator action; Target name
  required at execution time.

## Not in scope yet

- Editing `docs/Drydock_Specification.md`.
- Implementing the CLI, prompt, or Manifest schema changes.
- Updating Compass-owned material through any source-refresh path.
- Automatically deleting Blueprints when source files disappear.
- Making compact derivatives independently authoritative.
- Eliminating external Jira or other-system change tickets, which remain a separate free-form
  workflow and are not graph-inheriting.

## Superseded decisions

The V1 notes are superseded on three points, retained here so the history is legible:

- **Refit amends Blueprints.** V1 had `refit --sources` reconcile the source change into the current
  Blueprint. Blueprints are now immutable and refit appends tickets instead.
- **Semantic downstream invalidation.** V1 required the LLM to issue an explicit
  `invalidate`/`retain` disposition with a concrete contract impact for every candidate downstream
  story. Nothing is invalidated under the ticket model — a ticket is a new story appended to the
  chain and built in order — so this decision and its dispositions are deleted. This removed the
  hardest LLM judgment from the workflow.
- **Refit records as audit artifacts.** V1 treated the generated record as history, with the amended
  Blueprint carrying current truth. The refit ticket is now the unit of implementation and a
  first-class Manifest node.

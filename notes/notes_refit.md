# NOTES: Source-Driven Refit

| Field | Value |
|-------|-------|
| Version | 2026-08-04 V1 |
| Route | `drydock refit --sources` |
| Status | Working notes — not canonical specification |
| Description | Source-driven refit of an existing Target while preserving the current Blueprint view and minimizing rebuild scope. |
| Pending spec | 10 approved items |
| Pending impl | 10 unimplemented sections |

## Goal

Allow the Commander to edit the authoring source material, explicitly refresh the Target's
imported source snapshot, and run a source-driven refit that updates the current Blueprints with
the smallest justified change. The workflow preserves the source change as a durable refit record,
uses the Manifest as the graph and lineage authority, invalidates only stories with concrete
contract impact, and uses `drydock build` as the approval and execution step.

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
detection for Blueprints, imported sources, Manifest state, and source-refit records.

`drydock init` creates the Target repository when it creates a Target, but only after verifying
that the workspace repository ignores `targets/`. If `targets/` is not ignored, initialization
does not silently create a nested repository because the parent and Target repositories would
have competing ownership and ambiguous change detection.

The initialization and diagnostics path reports:

- the workspace repository root;
- whether `targets/` is ignored;
- the Target repository root;
- the Git root used for change detection.

Commands resolve the Target repository from the configured workspace and Target name. They do not
depend on the caller's current directory. Source refit fails with an actionable error when the
Target repository cannot be resolved; it does not silently fall back to an unrelated Git root or
filesystem-only comparison.

The Target repository owns its own history and `.gitignore`. The parent Drydock repository remains
responsible for Drydock source code and continues to ignore `targets/`.

### Imported source snapshot is the Drydock source item
`2026-08-04` · `spec:approved` · `impl:unimplemented`

Drydock operates on the imported snapshot under:

```text
targets/<Target>/blueprint/sources/
```

The external authoring directory is not implicitly live. Changes to the external source become
available to Drydock only after an explicit `drydock import <Target> <Source> --update`.

The existing import metadata continues to identify the original source root and import format.
The Target Git repository then provides the authoritative diff between the previous imported
snapshot and the updated snapshot.

### `import --update` refreshes ordinary imported material only
`2026-08-04` · `spec:approved` · `impl:unimplemented`

The import command gains an `--update` option. It refreshes files previously imported as ordinary
Markdown, source, Spec Kit, or other non-Compass material.

`--update`:

- compares incoming files with `blueprint/sources/`;
- copies added and changed files;
- removes previously imported files that no longer exist in the incoming source, subject to a
  deterministic safety check;
- leaves unchanged files untouched;
- preserves relative paths;
- reports added, changed, deleted, and unchanged files;
- creates the Target Git diff consumed by source refit.

Files classified as Compass-owned are excluded. `--update` does not copy them, does not update
their imported snapshot, and does not modify `COMPASS.md`. Compass-owned material is handled by an
explicit Compass/intent workflow because its update requires a separate LLM transformation.

The source-role table in `ANALYSIS.md` is the authority for Compass classification. A source file
not present in the source-role table defaults to ordinary imported material for compatibility with
older Targets; `--update` does not invoke the LLM to rediscover roles.

### Lineage is stored in an isolated JSON block in the Manifest
`2026-08-04` · `spec:approved` · `impl:unimplemented`

The Manifest remains the graph database and owns the semantic source lineage. A second
`SOURCE_MAP.json` graph is not created because it could drift from the Manifest's story-to-
Blueprint graph.

The Manifest contains a dedicated top-level block, separate from ordinary story syntax and from
`applied_specs`:

```text
source_lineage: |
  { ... versioned JSON ... }
```

The isolated JSON block records, at minimum:

- imported source relative path;
- source content hash used for the current planning/refit transaction;
- associated Blueprint file(s);
- source scope or relationship;
- source-refit record(s) associated with the relationship.

The Manifest's normal graph owns stories, `implements`, dependencies, context, and state.
`source_lineage` owns source-to-Blueprint relationships. `applied_specs` owns Blueprint-to-build
application hashes. Dedicated parser and writer functions update the JSON block; LLM-generated
Manifest output does not author or reproduce it.

### Planning persists lineage
`2026-08-04` · `spec:approved` · `impl:unimplemented`

`drydock plan` persists source lineage while authoring or preserving Blueprint files. The lineage
is derived from the analyzed source citations, relationship model, source roles, and Story
Realization Map, then validated against actual Blueprint and Manifest paths.

The relationship may be many-to-many. One source can inform several Blueprints, and one Blueprint
can derive from several sources. Lineage identifies candidate scope; it does not by itself imply
that every consumer must be rebuilt.

Existing Targets without reliable historical lineage require a one-time bootstrap from available
`ANALYSIS.md`, Manifest context, Blueprint citations, source headings, and planning evidence.
Ambiguous mappings are surfaced rather than silently invented.

### Source refit produces a distinct, mechanistic refit record
`2026-08-04` · `spec:approved` · `impl:unimplemented`

Source-driven refit and external change tickets are separate concepts.

Source-driven refit records are generated by Drydock from the imported-source Git diff. They are
mechanistic, source-backed, structured, and repeatable. External tickets may originate in Jira or
another system, remain free-form, and continue through the normal change-ticket refit process.

Source-driven records are stored separately from external tickets:

```text
blueprint/source-refits/
    SOURCE-REFIT-<sequence>-<name>.md

blueprint/changes/
    TICKET-<number>-<name>.md
```

The exact source-refit filename sequence remains an implementation detail, but generated records
must be distinguishable from human or external tickets. The source-refit record includes source
paths and old/new hashes, source diff, Blueprint baseline hashes, amended Blueprint files,
contract-impact decisions, and Manifest stories invalidated or retained.

The source-refit record is an audit/history artifact. The amended Blueprint remains the current
effective product definition; the system does not require the LLM or build process to interpret a
permanent stack of deltas to determine current behavior.

### Source refit reconciles the current Blueprint rather than regenerating the whole graph
`2026-08-04` · `spec:approved` · `impl:unimplemented`

`drydock refit <Target> --sources` begins with the source diff and uses Manifest lineage to derive
the candidate Blueprint set. It supplies the LLM with the current Blueprint, source baseline,
current source, source diff, relevant graph context, dependencies, and acceptance criteria.

The LLM reconciles the source change into the current Blueprint and emits a bounded change result.
The operation updates only affected Blueprint files and preserves unaffected Blueprint content.
It does not re-run full project planning or rebuild the entire dependency graph by default.

Drydock validates and writes the LLM result. The LLM does not write files directly and may not
modify files outside the lineage-derived candidate set without an explicit validated expansion.

### Downstream invalidation is semantic and concrete
`2026-08-04` · `spec:approved` · `impl:unimplemented`

The source-refit operation evaluates downstream Manifest consumers of changed Blueprints, but a
shared dependency alone does not invalidate a story.

The LLM must provide an explicit disposition for each candidate downstream story:

```text
story              disposition       contract impact
screen-setup       invalidate        route target changed
screen-dashboard   retain             dashboard contract unchanged
screen-help        retain             wording-only shared navigation change
```

A story is invalidated only when the LLM states a concrete contract impact and identifies the
affected surface. Accepted impact surfaces include route, interaction, layout, data shape,
interface, acceptance criterion, guardrail, security behavior, performance behavior, and
user-visible workflow.

Vague statements such as “related,” “uses `UI-GENERAL.md`,” or “the wording changed” are not
sufficient. Every disposition requires a specific reason and evidence from the relevant Blueprint
or source section. Every candidate downstream story appears exactly once as `invalidate` or
`retain`.

Drydock mechanically validates that:

- changed Blueprint implementing stories always reset;
- invalidated stories exist in the Manifest;
- invalidated stories are graph-related to changed Blueprints;
- unrelated stories are not invalidated;
- retained stories preserve their current state;
- the invalidation record includes a concrete impact surface and reason.

The dependency graph identifies candidates and supplies context. It is not a blunt transitive
invalidation cascade.

### Full Blueprint contracts, not compact derivatives, control invalidation
`2026-08-04` · `spec:approved` · `impl:unimplemented`

Compact Blueprint files are derived context and are never independent product specifications.

When a full Blueprint changes, its compact derivative is regenerated. Compact output differences do
not independently reset stories and are not used as the contract invalidation hash. Nondeterministic
LLM wording or ordering in a compact file is therefore not treated as evidence that the built
product is stale.

The full Blueprint contract hash and the source-refit semantic impact decision control rebuild
scope. Compact provenance may record the source full-spec hash, compaction prompt/version, model,
and compact output hash for diagnostics only.

### Build is the approval boundary
`2026-08-04` · `spec:approved` · `impl:unimplemented`

Source refit does not require a separate Commander approval step. The validated refit transaction
updates the current Blueprints and Manifest state. `drydock build <Target>` is the approval and
execution boundary.

The intended workflow is:

```text
drydock import <Target> <Source> --update
    → refresh ordinary imported sources

drydock refit <Target> --sources
    → generate source-refit record
    → reconcile affected Blueprints
    → determine concrete downstream contract impacts
    → update lineage and Manifest state

drydock build <Target>
    → execute the approved current Blueprint frontier
```

## Acceptance Criteria

- A newly initialized Target has an independent Git repository when and only when the workspace
  repository ignores `targets/`.
- Git diagnostics identify the exact workspace and Target repository roots used for change
  detection, regardless of caller directory.
- `drydock import --update` refreshes ordinary imported sources and reports the resulting file
  changes.
- `drydock import --update` excludes Compass-owned files without modifying `COMPASS.md`.
- `drydock plan` persists validated source lineage in the isolated Manifest JSON block.
- `drydock refit --sources` generates a source-refit record separate from external `changes/`
  tickets.
- Source refit updates only lineage-derived affected Blueprints and preserves the current view of
  unaffected Blueprints.
- Source refit resets implementing stories for changed Blueprints and only downstream stories for
  which the LLM supplies a concrete contract impact.
- Compact-only differences never independently invalidate a story.
- `drydock build` remains the only approval and execution boundary for the source-refit workflow.

## Guardrails

- Never allow the parent Drydock repository and a Target repository to ambiguously own the same
  Target files.
- Never infer the Target Git root from the caller's current directory when the configured workspace
  identifies the Target.
- Never update Compass-owned source material through ordinary `import --update`.
- Never create a second independent source-to-Blueprint graph outside the Manifest.
- Never allow an LLM to modify an unbounded set of Blueprint files during source refit.
- Never invalidate a downstream story solely because it depends on a changed Blueprint.
- Never use compact output byte differences as contract invalidation evidence.
- Never make source refit require an additional approval gate before build.

## Open Questions

- Confirm the final directory name for generated source records: recommended `blueprint/source-refits/`.
- Define the safety behavior for source files deleted from the external authoring tree: recommended
  mark the lineage and Blueprint for reconciliation rather than automatically deleting a Blueprint.
- Define the exact structured artifact format for the LLM's Blueprint reconciliation and per-story
  `invalidate`/`retain` decisions.
- Define the one-time lineage bootstrap and Commander-facing ambiguity report for existing Targets.

## Not in scope yet

- Editing `docs/Drydock_Specification.md`.
- Implementing the CLI or Manifest schema changes.
- Automatically updating Compass-owned material during ordinary source refresh.
- Automatically deleting Blueprints when source files disappear.
- Making compact derivatives independently authoritative.
- Eliminating external Jira or other-system change tickets.

## Prior refit note retained

The earlier refit notes considered a separate merge process versus Git diff as the mechanism for
integrating refit outputs. The source-driven design now treats the Target's independent Git history
and the validated source-refit transaction as the merge and audit mechanism.

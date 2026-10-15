# DESIGN: drydock refit

| Field | Value |
|---|---|
| Version | 2026-10-15 V1 |
| Route | refit |
| Modules | `refit.py`, `refit_ticket.py`, `change_ticket.py`, `manifest_edit.py`, `lineage.py` |
| Prompts | `refit.md`, `refit_sources.md`, `refit_sources_route.md` |
| Tests | `tests/test_refit*.py`, `tests/test_change_ticket.py`, `tests/test_normalized_ticket.py` |
| Topics | — |
| Pending spec | 0 |
| Pending impl | 3 |

## Behavior

### Purpose

Turn a change to a built Target into ordered work the build implements. Every change becomes a
per-Blueprint REFIT ticket that is itself a Manifest story, so a later ticket can overrule an earlier
one and Build applies them in chain order. Refit never builds.

### Syntax

```text
drydock refit <Target> [--model <model>] [--llm-provider <p>]
drydock refit add <Target> <Blueprint> <File|->
drydock refit <Target> --add <Blueprint> <File|->
```

### Rules

`2026-09-22` · **A change is a REFIT ticket; its filename is its identity.** A change to a built Target is a **REFIT ticket**,
`blueprint/<Blueprint>_refit_<NNN>.md`. The filename is its identity: the stem names the one
Blueprint it amends, and the number fixes order and parent. Breaking the naming loses the order,
which is what lets a later ticket overrule an earlier one.

`2026-09-22` · **`refit add` is deterministic and never builds.** `drydock refit add <Target> <Blueprint> <File>` (`src/drydock/refit_ticket.py`) is the
deterministic `add_ticket()`. It resolves an authored Blueprint (never a compact or a ticket),
numbers the ticket after the chain's last, writes it with a header naming Blueprint and parent,
and appends one `pending` story. The story depends on the previous ticket's story, or on every
story implementing the Blueprint for `001`. It inherits type, kind, stack, stack_mode, context, and explicit Rigging rules from the
Blueprint's story, adds the Blueprint and earlier tickets to context, and sets `acceptance: yes`
when the ticket carries `=== AC` blocks. It then optimizes pending work and never builds. A Blueprint no
story implements is rejected, because the ticket would have no place in the build order.

`2026-09-22` · **`/ddk-refit` resolves ownership before writing a ticket.** `/ddk-refit` is the only shipped skill (`Rigging/skills/ddk-refit/`). `drydock init`
syncs it into the workspace by version. A change request may identify a page URL, API route, CLI
command, screen, feature, file, error, or only desired behavior. The skill uses Blueprint routes
and contracts to find the owner; a page change adds a Feature or database ticket only when the
requested behavior needs one. Unclear ownership costs a wrong ticket, so it asks one focused
question rather than guessing. It writes ticket bodies as acceptance criteria and calls
`drydock refit add`, printing only the command output.

`2026-09-22` · **Refit optimizes pending work and keeps context.** Successful `refit` and `refit add` call the shared optimizer for computed
Manifests. Manifest projection preserves context, rules, instructions, build state, and existing
block identity. Shared files count once, compact context is preferred, and full implementation
inputs take precedence. The dependency frontier admits consecutive tickets into one block when
savings and the existing budgets permit; no filename-prefix grouping is needed. Dropping context
would hide the principal savings from grouping refits of the same Blueprint.

`2026-09-22` · **Started blocks are frozen; optimization failure rolls back.** A block with any non-pending story is frozen as an execution unit. Its membership,
number, state, and recorded fields remain intact; pending groups receive numbers above retained
blocks. The full dependency graph remains available to preserve order across frozen units.
Legacy Manifests retain their grouping. Optimization failure rolls back the refit transaction,
including removing a newly added ticket so retry reuses its number.

`2026-09-22` · **A changed Blueprint resets what consumed it.** Drift reconciliation compares
every `applied_specs` record against current Blueprint content. A changed Blueprint resets its
consumer blocks and their transitive dependents to `pending` and drops stale provenance;
`DATABASE.md` resets only the blocks whose cited operations changed. Drift that cannot be
reconciled is reported `[blocked]`. Cost when broken: code built against a Blueprint that no
longer says it closes as verified.

`2026-09-22` · **A refit voids every rung above the plan.** A conform or a reset re-authors the
specification the build was made against, so project status is voided above `PLAN REPAIRED`.
`refit add` voids the same way. Cost when broken: a release verdict standing over a Target that no
longer exists.

### Mechanism

1. **Add** (`refit add`) — `add_ticket()` writes `blueprint/<Blueprint>_refit_<NNN>.md`, appends one
   `pending` story chained to the previous ticket, runs `optimize_build_blocks(pending_only=True)`,
   and voids rungs above `PLAN REPAIRED`.
2. **Conform** (`refit`) — each `blueprint/changes/TICKET-*.md` is normalized (`Amends:`,
   `Depends On:`, `Version:`) by one LLM call and patched into `MANIFEST.md` as story rows; a
   ticket with no `Amends:` is skipped.
3. **Reconcile** — `applied_specs` drift resets consumer blocks and transitive dependents.
4. **Optimize** — pending work is regrouped; started blocks are frozen.
5. **Report** — one line per ticket and reset, then a `RESULT:` tally.

### Exit codes

| Code | Condition |
|---|---|
| `0` | All tickets conformed or skipped and no drift blocked; nothing to do. |
| `1` | A ticket failed to conform, or drift was blocked. |
| `2` | Usage error, including a missing `refit add` ticket file. |

### Spec divergence

- The specification names `blueprint/changes/TICKET-NNN-{Name}.md` as the change form and does not
  describe REFIT tickets (`blueprint/<Blueprint>_refit_<NNN>.md`), `drydock refit add`, or
  `/ddk-refit`.
- The specification says Feature-ticket Blueprint comments are a change source; any authored
  Blueprint accepts REFIT tickets.

## Decisions

### Three ways in, one ticket form
`2026-09-22` · `spec:approved` · `impl:unimplemented`

Chat (`/ddk-refit`), a direct Blueprint edit, and a CHANGE ticket all produce REFIT tickets through
the deterministic `add_ticket()`. Chat is implemented. `drydock refit` still writes normalized
`TICKET-NNN-slug.md` files to `blueprint/changes/` for Blueprint edits and CHANGE tickets and must
move to `add_ticket()`.

### Blueprints are editable; internally they are a table plus a transaction log
`2026-09-22` · `spec:approved` · `impl:unimplemented`

Users edit Blueprints directly. Refit diffs the edit against the Manifest snapshot, records it as
a REFIT ticket, and advances the snapshot. Internally a Blueprint plus its chain is immutable
state plus an ordered log. This supersedes "Blueprints are immutable" as a user rule.

### Source refit is dropped; replan reads the chains
`2026-09-22` · `spec:approved` · `impl:unimplemented`

`refit --sources` is dropped: planning stands between sources and Blueprints, and the enriched
Blueprint cannot be recovered from a source edit. A replan's analyze step reads each Blueprint's
REFIT chain so regeneration does not lose it. Backfilling the original sources from the tickets is
a one-off operator LLM call, not part of refit. The guardrail "every decision is written back to
the authoritative external source" is withdrawn.

*2026-10-15 code state:* `--sources` is absent from the parser; a replan does not yet read REFIT chains.

## Open Questions

- Deferred: two branches or developers each allocate the same `<Blueprint>_refit_<NNN>`.
  Git reports an add/add conflict; renumbering changes the parent and the story id. Who renumbers
  (a deterministic refit pass, or the developer) is undecided.

Future work carried from notes:

- On failure applying a refit ticket during build, fall back to rebuilding the Blueprint. Not
  required for MVP.
- One-time replan of the existing Target after `plan` persists lineage. Operator action; Target name
  required at execution time.

## Working Notes

-

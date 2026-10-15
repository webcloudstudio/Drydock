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

`2026-09-22` · **A change is a REFIT ticket; its filename is its identity.**
`blueprint/<Blueprint>_refit_<NNN>.md` names the one Blueprint it amends; the number fixes order and
parent, so a later ticket overrules an earlier one. Ticket bodies are acceptance criteria in the
Blueprint's own vocabulary, never narrative.

`2026-09-22` · **`refit add` is deterministic and never builds.** It resolves an authored Blueprint
(never a compact or ticket), numbers the ticket, and appends one `pending` story depending on the
previous ticket's story (or every story implementing the Blueprint for `001`). The story inherits
type, kind, stack, context, and rules, adds the Blueprint and earlier tickets to context, and sets
`acceptance: yes` when the ticket has `=== AC` blocks. A Blueprint no story implements is rejected.

`2026-09-22` · **`/ddk-refit` resolves ownership before writing.** It maps a URL, route, command,
screen, or behavior to the owning Blueprint, asks one question when ownership is unclear, and calls
`refit add`. `drydock init` syncs it into the workspace.

`2026-09-22` · **Refit optimizes pending work without breaking chains.** Shared files count once,
compact context is preferred, consecutive tickets may share a block. A block with any non-pending
story is frozen; optimization failure rolls back the transaction, including a newly added ticket.

`2026-09-12` · **Change tickets are normalized, not applied.** `blueprint/changes/TICKET-*.md`
(the `change_ticket_directory`, Target-relative) is normalized by one call per ticket with exactly
one `Amends:` home; Blueprint content is not modified. An unincorporated source ticket is recorded
in `BLOCKERS.md` and fails the refit.

`2026-09-22` · **A changed Blueprint resets what consumed it.** `applied_specs` drift resets consumer
blocks and transitive dependents to `pending`; only already-built work resets. `DATABASE.md`
resets per changed operation: `compatibility: rebuild` rebuilds owner, callers, and dependents;
`data` rebuilds database work; `unchanged` rebuilds nothing.

`2026-09-22` · **A refit voids every rung above `PLAN REPAIRED`**, and every artifact written is
committed to the Target repository.

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

## Open Actions

- **Failing test:** `tests/test_manifest_edit.py::test_computed_manifest_normalization_uses_shared_build_block_optimizer`. Seen 2026-10-15; not investigated.

## Working Notes

-

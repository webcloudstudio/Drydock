# Ship's Log

## Purpose

The Ship's Log is Drydock's append-only product and design decision ledger. It records decisions,
not implementation mechanics:

```text
## YYYY-MM-DD - Decision title
source:     spike <id> | iterate | QuarterDeck review
decision:   What was decided.
why:        The compelling reason and material rejected alternatives.
evidence:   <Target>/evidence/<id>.md
supersedes: <earlier entry title>   # optional
```

## First-Cut Status

The authoritative Blueprint defines `SHIPS_LOG.md`, a single decision writer, and three sources:

1. Accepted spike findings from `drydock build`.
2. Blueprint-scoped change rationale from `drydock iterate`.
3. Product-owner decisions from the QuarterDeck.

The writer and reconciliation path are not implemented yet. This page deliberately does not invent
entries or create a second source of truth.

## Decisions Available In This Console

- **Choose Next Slice** captures structured product-owner direction in a questionnaire artifact.
- **Initial Console Review** records Approve, Revise, or Reject in QuarterDeck state.
- **Drydock Delivery Plan** supports plan-level sign-off and per-ticket acceptance checks.

These controls let the interaction be tested now. A later capability must consume their state,
update `BUILD_PLAN.md`, and append the decision of record to `SHIPS_LOG.md`.

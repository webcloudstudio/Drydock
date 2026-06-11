# Drydock Commander's View

## Mission

Drydock is the installable V2 successor to Prototyper: a governed, Blueprint-driven Python CLI
that plans, builds, tests, reviews, and evolves software.

## Current State

| Area | State | What is true now |
|---|---|---|
| Foundation | Done | Package foundation, configuration, launchers, Rigging resolution |
| Blueprint intake | Done | `drydock init` and `drydock validate` |
| Plan workflow | Next | `drydock plan init`, `create`, and `show` are the next coherent capability |
| Build and evidence | Backlog | Build status, execution, evidence, and score remain deferred |
| QuarterDeck loop | Prototype | This authored console proves the review surface; automated projection and write-back remain to build |
| Ship's Log | Designed | The Blueprint defines the append-only decision ledger; the writer remains to build |

## Use This QuarterDeck

1. Open **Drydock Delivery Plan** to inspect the first-cut roadmap and acceptance criteria.
2. Open **Choose Next Slice** and save answers to give the next agent structured direction.
3. Open **Initial Console Review** and record Approve, Revise, or Reject with feedback.
4. Open **Ship's Log** to inspect the proposed decision record and its current implementation gap.

## Control Boundary

This first cut is an authored project cockpit. It does not claim that QuarterDeck decisions already
write back to `BUILD_PLAN.md` or `SHIPS_LOG.md`. Those contracts are represented on the board as
work to implement and prove.

The authoritative product behavior remains `specs/001-drydock/spec.md`. The high-level delivery
exit criteria remain `DRYDOCK_ACCEPTANCE_CRITERIA.md`.

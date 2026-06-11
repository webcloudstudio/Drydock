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
| Ship's Log | Working foundation | JSONL writer, audit, and QuarterDeck viewer are implemented; workflow integrations remain |

## Use This QuarterDeck

1. Open **Soundings** to inspect authoritative implementation acceptance and evidence.
2. Open **Choose Next Slice** and save answers to give the next agent structured direction.
3. Open **Initial Console Review** and record Approve, Revise, or Reject with feedback.
4. Open **Ship's Log** to inspect canonical JSONL decision and milestone events.
5. Open **Drydock Specification** for the sole authoritative behavior contract.

## Control Boundary

This first cut is an authored project cockpit. It does not claim that QuarterDeck decisions already
write back to `BUILD_PLAN.md` or append workflow decisions to `logs/ships_log.jsonl`. Those
contracts are represented on the board as
work to implement and prove.

The sole authoritative product behavior is `docs/Drydock_Specification.md`. Implementation
acceptance and completion evidence are authoritative in `docs/SOUNDINGS.md`; strategic product
proof remains in `docs/SEA_TRIALS.md`.

# Drydock Commander's View

Orientation and current state for the Drydock build. Source of truth lives in the Core Docs; this
page only orients.

Drydock is the installable V2 successor to Prototyper: a governed, Blueprint-driven Python CLI that
plans, builds, tests, reviews, and evolves software.

## Current State

| Area | State | What is true now |
|---|---|---|
| Foundation | Done | Package foundation, configuration, launchers, Rigging resolution |
| Blueprint intake | Done | `drydock init` and `drydock validate` |
| Plan workflow | Next | `drydock plan init`, `create`, and `show` are the next coherent capability |
| Build and evidence | Backlog | Build status, execution, evidence, and score remain deferred |
| QuarterDeck loop | Prototype | This console proves the review surface; automated projection and write-back remain to build |
| Ship's Log | Working foundation | JSONL writer, audit, and viewer are implemented; workflow integrations remain |

## Where To Go

- **Soundings** — acceptance criteria, current state, and evidence.
- **Sea Trials** — objectives and success criteria for delivery.
- **Drydock Specification** — the sole authoritative behavior contract.
- **Choose Next Slice** / **Initial Console Review** — give direction and record sign-off.
- **Ship's Log** — canonical JSONL decision and milestone events.

## Control Boundary

This is an authored cockpit: QuarterDeck decisions do not yet write back to `BUILD_PLAN.md` or
append to `logs/ships_log.jsonl` — those are board items to build. Authority stays in
`docs/Drydock_Specification.md` (behavior), `docs/SOUNDINGS.md` (acceptance), and
`docs/SEA_TRIALS.md` (objectives).

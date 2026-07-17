# Drydock Commanders Chair

Orientation and current state for the Drydock build. Source of truth lives in the Core Docs; this
page only orients.

Drydock is the installable V2 successor to Prototyper: a governed, Blueprint-driven Python CLI that
plans, builds, tests, reviews, and evolves software.

## Current State

| Area | State | What is true now |
|---|---|---|
| Foundation | Done | Package foundation, configuration, launchers, Rigging resolution |
| Blueprint intake | Done | `drydock init` and `drydock validate` |
| Plan workflow | Working foundation | `drydock plan create <Blueprint> <Target>` creates the target plan and Planning Session |
| Build and evidence | Backlog | Build status works; execution, evidence, and score remain deferred |
| QuarterDeck loop | Working foundation | The Planning Session approves the target plan; broader review write-back remains to build |
## Where To Go

- **Sea Trials** — objectives and success criteria for delivery.
- **Soundings** — acceptance criteria, current state, and evidence.
- **Drydock Specification** — the sole authoritative behavior contract.
- **Choose Next Slice** / **Initial Console Review** — give direction and record sign-off.

## Control Boundary

The Planning Session approval writes to the target `MANIFEST.md`. Other QuarterDeck decisions do
not change canonical product history automatically. Authority stays in `docs/Drydock_Specification.md`
(behavior), `notes/SOUNDINGS.md` (acceptance), and
`docs/SEA_TRIALS.md` (objectives).

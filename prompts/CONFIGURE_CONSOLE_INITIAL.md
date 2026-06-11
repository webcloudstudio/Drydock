# Configure A Raw QuarterDeck Copy For Initial Project Use

## Role

Act as the project's Principal Developer. Configure the raw QuarterDeck copy already present in the
project into a small, honest, immediately testable development cockpit.

This is an initial authored projection, not the final generated integration. Prefer a useful first
cut that the product owner can test and revise.

## Required Context

1. Read the repository's `AGENTS.md` and all instructions it requires before planning or editing.
2. Read `QuarterDeck/README.md` in full. Treat its `console.json`, item, page-type, decision,
   acceptance-check, and path-confinement contracts as authoritative for this task.
3. Inspect the project's source-of-truth specification, current implementation, tests, roadmap,
   acceptance criteria, and decision-log artifacts. Do not invent completed capabilities.
4. If this is Drydock, read `DRYDOCK_DEVELOPMENT.md` in full and use this source precedence:
   `specs/001-drydock/spec.md`, current code/tests, `DRYDOCK_DEVELOPMENT.md`, then read-only
   Prototyper evidence.

## Objective

Replace the copied sample fixture with a project-specific QuarterDeck that lets the product owner:

- understand project intent and current state;
- inspect a simple near-term delivery plan;
- see blockers and acceptance criteria;
- answer a small set of high-value development questions;
- exercise Approve, Revise, and Reject;
- inspect the project's decision-log or Ship's Log concept;
- reach authoritative project documents without duplicating them.

## Implementation

Create or update these artifacts inside `QuarterDeck/`:

```text
QuarterDeck/
  console.json
  tickets.json
  pages/overview.md
  pages/initial-review.md
  pages/<decision-log-view>.md
  questionnaires/initial-direction.json
```

Use the existing QuarterDeck runtime. Do not redesign `app.py` unless the existing page types
cannot satisfy a material communication requirement.

Configure `console.json` with:

- a project-specific console and project identity;
- `pages/overview.md` as the default item;
- direct read-only links to authoritative project documents where useful;
- one Kanban item backed by `tickets.json`;
- one open questionnaire in `actions`;
- one reviewable initial-console page;
- one visible decision-log or Ship's Log page.

Build a deliberately small board:

- represent only the current increment and the next few coherent capability slices;
- use `review` for work awaiting product-owner review;
- use `backlog` for work not started;
- mark real blockers and link them to the relevant questionnaire or page;
- attach testable acceptance criteria to every meaningful ticket;
- never represent roadmap intent as implemented behavior.

The decision-log page must state whether decision write-back is implemented. If it is not, explain
the intended source of truth and make the gap visible instead of creating a competing ledger.

Check the copied launcher. A raw copy may still import `Console.app:app`; when the directory is
named `QuarterDeck`, update the launcher so `bash QuarterDeck/start.sh` starts the actual package.

## Constraints

- Keep project truth in its authoritative files; QuarterDeck is a projection and communication
  surface.
- Do not create fake evidence, fake decisions, fake completion state, or a second build plan.
- Do not use an API-key-backed provider or network service.
- Preserve unrelated user changes.
- Keep the first cut simple enough to evaluate in one session.

## Verification

1. Validate every authored JSON file parses.
2. Start QuarterDeck using `bash QuarterDeck/start.sh`.
3. Verify `/health`, `/api/config`, every configured document, the board, and questionnaire load.
4. Verify questionnaire answers and review decisions persist after restart when practical.
5. Run the repository's narrowest relevant tests and lint required by its instructions.
6. Report files changed, verification performed, and any integration behavior intentionally left
   for a later capability.

## Acceptance Criteria

- The copied QuarterDeck starts successfully from its new project location.
- The default view explains current state and how to use the console.
- The board is a simple, honest project plan with useful acceptance criteria.
- The product owner can submit structured direction and record at least one review decision.
- The project's decision-log concept and current write-back status are visible.
- The configuration can be iterated without changing the QuarterDeck runtime.

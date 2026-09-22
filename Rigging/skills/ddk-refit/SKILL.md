---
name: ddk-refit
description: Turn a plain-text change request for a built Drydock Target into REFIT tickets (blueprint/<Blueprint>_refit_<NNN>.md) and update the Manifest. Invoke with "/ddk-refit <Target> <change text>". One-shot; never builds. Trigger: "/ddk-refit".
version: 1.0.0
---

# ddk-refit — plain text to REFIT tickets

`/ddk-refit <Target> <change text>` records a change to a built Target as REFIT tickets and
stops. The user runs `drydock build <Target>` when ready. This skill never builds.

## Terms

- **REFIT ticket:** `targets/<Target>/blueprint/<Blueprint-stem>_refit_<NNN>.md`. It amends one
  Blueprint. The number fixes its order and parent. A later ticket governs an earlier ticket and
  the Blueprint where they conflict.
- **CHANGE ticket:** raw input in `targets/<Target>/blueprint/changes/`. This skill does not
  write CHANGE tickets.

## Procedure

1. Resolve the workspace with `drydock config show` and the Target under `targets/<Target>/`. If
   the Target is missing or ambiguous, ask once and stop.
2. Split the change text into items. Match each item to exactly one authored Blueprint in
   `blueprint/`, ignoring `*_compact.md` and `*_refit_*.md`. Use each Blueprint's `Provides`,
   `Description`, and `Layout`. A screen item belongs to the `SCREEN-*` Blueprint whose `Provides`
   route renders it. If an item also requires an API, data, or schema change the screen cannot
   deliver, add an item for the owning `FEATURE-*` or `DATABASE.md` Blueprint. If an item cannot be
   matched with confidence, ask one question and stop.
3. For each Blueprint, read it and its existing `_refit_` chain in order, then write one ticket
   body covering all its items.
4. Write the body as acceptance criteria in the Blueprint's own form, never as narrative:

   ```markdown
   # <Short imperative title>

   ## Programmatic Acceptance

   === AC <blueprint-stem>-<slug> ===
   Intent: <one sentence stating what must hold>
   <executable assertions in the style of the Blueprint's existing AC blocks>
   === END AC <blueprint-stem>-<slug> ===

   ## User Acceptance

   - <observable condition that must hold>
   ```

   Each criterion states an end state that holds on every later build, for example "The button
   reads Process Raw". Quote required text exactly as the user gave it. State removals as absence.
   Never write "the user wants". Add a `## Layout` section only when element order or composition
   changes, and restate the full layout it replaces.
5. Save each body to a temporary file and run, once per Blueprint:

   ```bash
   drydock refit add <Target> <Blueprint> <file>
   ```

6. Print only the command output, for example:

   ```text
   Ticket SCREEN-SETUP-WORKSPACE_refit_001 created
   Manifest updated
   ```

Do not show drafts, do not ask for confirmation, and do not run `drydock build`. A wrong ticket is
corrected by the next `/ddk-refit`.

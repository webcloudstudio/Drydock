---
name: ddk-refit
description: 'Turn a change request for a built Drydock Target into REFIT tickets, resolving a page URL, API route, command, error, or plain description to its owning Blueprints. Invoke with "/ddk-refit <Target> <change request>" (Claude Code) or "$ddk-refit <Target> <change request>" (Codex). One-shot; never builds. Trigger: "/ddk-refit", "$ddk-refit".'
version: 1.2.0
---

# ddk-refit — plain text to REFIT tickets

`/ddk-refit <Target> <change request>` (`$ddk-refit` in Codex) records a change to a built Target as REFIT tickets and
stops. The user runs `drydock build <Target>` when ready. This skill never builds.
The request may identify a page URL, API method and route, CLI command, screen, feature, Blueprint,
file, error message, or only the desired behavior. The user need not identify the underlying API
or Blueprint.

## Terms

- **REFIT ticket:** `targets/<Target>/blueprint/<Blueprint-stem>_refit_<NNN>.md`. It amends one
  Blueprint. The number fixes its order and parent. A later ticket governs an earlier ticket and
  the Blueprint where they conflict.
- **CHANGE ticket:** raw input in `targets/<Target>/blueprint/changes/`. This skill does not
  write CHANGE tickets.

## Procedure

1. Resolve the workspace with `drydock config show` and the Target under `targets/<Target>/`. If
   the Target is missing or ambiguous, ask once and stop.
2. Split the request into changes and resolve each change to exactly one authored Blueprint in
   `blueprint/`, ignoring `*_compact.md` and `*_refit_*.md`. Use `Provides`, `Consumes`, `Route`,
   `Description`, and relevant content as the ownership index. For a URL, match its path to the
   screen's provided route; host, port, and query string are context, not Target identity. For an
   API call, match method and path to its provider. For a CLI command, match the verb and behavior.
   A feature name, file, or error message is a clue to trace to the owning contract, not a required
   input format. Start with the Blueprints; inspect implementation or the page only when needed to
   establish ownership or the requested end state. Do not run a broad diagnostic workflow by
   default. A page request belongs to its `SCREEN-*` Blueprint; use `UI-GENERAL.md` or a UI
   component Blueprint for a shared presentation change. Split out a `FEATURE-*` or `DATABASE.md`
   item only when the requested behavior requires an API, service, data, or schema change. Do not
   assume a page change requires an API change. If the Target or owner cannot be matched with
   confidence, ask one focused question and stop.
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

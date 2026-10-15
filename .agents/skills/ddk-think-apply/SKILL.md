---
name: ddk-think-apply
description: Surface impl:unimplemented (code) and spec:approved (doc) items from a think notes file as a selectable list, then implement the chosen ones. Invoke with "/ddk-think-apply <subject>" (e.g. "/ddk-think-apply analyze" or a feature name). Use when the user is ready to implement decisions captured in a /ddk-think notes file. Trigger: "/ddk-think-apply", "apply notes for <X>", "implement from notes".
version: 2.0.0
---

# ddk-think-apply — implement decisions from a think notes file

Read the notes file for the given subject, surface all flagged items as a selectable
numbered list, wait for the user to choose, then implement the selected items.

The argument after `/ddk-think-apply` is the subject. Resolve the notes file the same way as
`/ddk-think`: `targets/<Target>/notes_<feature>.md` when the subject is a feature of a
Drydock-managed project (`$DRYDOCK_WORKSPACE/targets/<Target>/`); in the Drydock repository,
`design/commands/<command>.md` or `design/topics/<topic>.md` via the AGENTS.md §Design Manifest; otherwise
`notes/notes_<subject>.md`. Below, "the notes file" means the resolved file.

**Drydock-managed projects:** when the notes file lives in a Target directory, selected CODE
items are not implemented by direct code edits. Instead, write one change ticket per selected
item into the Target's `blueprint/changes/` directory so `drydock refit` can conform it to the
build process. DOC items amend the Target's Blueprint the same way.

---

## On invocation (first turn only)

0. **Retire terminal sections** — before surfacing any items, scan the notes file
   for sections in terminal state: both `impl` and `spec` flags are done
   (`impl:implemented` or `impl:na`, **and** `spec:applied` or `spec:na`).

   - In a `design/` file, fold each terminal section's settled behavior into `## Behavior`
     as a dated rule, then remove the section. Elsewhere, append it verbatim to
     `notes_<subject>_done.md` (create it with `# DONE: <subject>` and today's date) and remove it.
   - Update the header counts (`Pending spec`, `Pending impl`) to reflect the removals.
   - Report how many sections were retired before proceeding. If none, say nothing and continue.

1. **Read** the notes file. If it does not exist, stop and say so.

2. **Extract flagged sections** — scan every `### Section` block for its flag line
   (`` `YYYY-MM-DD` · `spec:X` · `impl:Y` ``):
   - **CODE items**: sections where `impl:unimplemented`
   - **DOC items**: sections where `spec:approved`
   - A section can appear in both lists.

3. **Surface as a numbered list** — two groups, CODE first:

   ```
   CODE CHANGES  (impl:unimplemented)
   ───────────────────────────────────
   1. [Section title] — one-line summary of what needs to be built
   2. ...

   DOC CHANGES  (spec:approved — reconcile into Drydock_Specification.md)
   ──────────────────────────────────────────────────────────────────────────
   A. [Section title] — one-line summary of the spec change needed
   B. ...

   Reply with the numbers/letters to implement, or "all code", "all docs", "all".
   ```

4. **Wait for the user's selection.** Do not implement anything yet.

---

## On selection

The user replies with numbers, letters, ranges, or keywords (`all code`, `all docs`, `all`).

**For each selected CODE item:**
- Read the relevant source files (use the notes section content to identify what to change).
- Implement the behavior described in the section.
- Follow all rules in `AGENTS.md` (LLM-assisted command pattern, test requirements, etc.).
- After implementing, flip the section's flag in the notes file from `impl:unimplemented`
  to `impl:implemented` and update the `Pending impl` count in the header.

**For each selected DOC item:**
- Propose the exact replacement or addition text for `docs/Drydock_Specification.md`.
- Do NOT edit the spec without explicit confirmation — show the diff first and ask.
  (The spec has one active writer at a time per AGENTS.md.)
- After confirmation and edit, flip `spec:approved` to `spec:applied` in the notes
  file and update the `Pending spec` count in the header.

**After all selected items are implemented:**
- Run `ruff check src/ tests/` and `python -m pytest` (or `bash bin/test.sh`).
- In a `design/` file, update `## Behavior` for every implemented item.
- Commit with a descriptive message per AGENTS.md rules.
- Report: files changed, tests passed, residual risk.

---

## Rules

- Never implement an item that was not selected.
- Never edit `docs/Drydock_Specification.md` without showing the diff and getting confirmation.
- Always implement CODE before DOC in the same selection — code is ground truth.
- After each item, update the flag in the notes file immediately (don't batch flag updates).
- If an item depends on another unimplemented item, say so before starting.
- If the notes file references files that don't exist yet (e.g. a new Rigging template),
  create them.

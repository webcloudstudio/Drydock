---
name: apply-refit
description: Surface impl:unimplemented (code) and spec:approved (doc) items from a refit notes file as a selectable list, then implement the chosen ones. Invoke with "/apply-refit <subject>" (e.g. "/apply-refit analyze" or a feature name). Use when the user is ready to implement decisions captured in a /refit (thinkthrough) notes file. Trigger: "/apply-refit", "/apply-notes", "apply refit for <X>", "apply notes for <X>", "implement from notes".
version: 2.0.0
---

# apply-refit — implement decisions from a refit notes file

Read the notes file for the given subject, surface all flagged items as a selectable
numbered list, wait for the user to choose, then implement the selected items.

The argument after `/apply-refit` is the subject. Resolve the notes file the same way as
`/refit`: `targets/<Target>/notes_<feature>.md` when the subject is a feature of a
Drydock-managed project (`$DRYDOCK_WORKSPACE/targets/<Target>/`), otherwise
`docs/notes_<subject>.md`.

**Drydock-managed projects:** when the notes file lives in a Target directory, selected CODE
items are not implemented by direct code edits. Instead, write one change ticket per selected
item into the Target's `blueprint/changes/` directory so `drydock refit` can conform it to the
build process. DOC items amend the Target's Blueprint the same way.

---

## On invocation (first turn only)

0. **Archive terminal sections** — before surfacing any items, scan `docs/notes_<subject>.md`
   for sections in terminal state: both `impl` and `spec` flags are done
   (`impl:implemented` or `impl:na`, **and** `spec:applied` or `spec:na`).

   - If any terminal sections exist, move them (append) to `docs/archive_<subject>.md`,
     preserving their full `### Section` block verbatim.
   - Remove those sections from `docs/notes_<subject>.md`.
   - Update the header counts (`Pending spec`, `Pending impl`) in `docs/notes_<subject>.md`
     to reflect the removals.
   - If `docs/archive_<subject>.md` does not exist, create it with a minimal header:
     `# ARCHIVE: <subject>` and today's date.
   - Report how many sections were archived before proceeding (e.g. "Archived 3 terminal
     sections to archive_<subject>.md."). If none, say nothing and continue.

1. **Read** `docs/notes_<subject>.md`. If it does not exist, stop and say so.

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
- Update `docs/SOUNDINGS.md` for any capability whose state changed.
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

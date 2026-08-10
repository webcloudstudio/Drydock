# Technology Stack

**Approved:** 2026-08-07

Technology decisions of record for this Target. One row per technology, naming the
Rigging best-practice file that governs building it.

A `—` in the Rigging column means no Rigging guidance exists for that
technology; the builder applies general best practice instead. Adding a row never
requires a matching Rigging file.

`drydock analyze` proposes this file once. It is owned by the Commander thereafter and
is never overwritten. `drydock plan` reads it to assign per-story `stack:` guidance.

| Technology | Rigging | Notes |
|---|---|---|
| Python | `python.md` | Proposed conventional implementation language; the source is silent. |
| Flask | `flask.md` | Proposed conventional web framework for the described web application. |
| SQLite | `sqlite.md` | Proposed local persistence store because the product retains a reading list and no database is named. |
| pytest | `python.md` | Proposed test runner for the required automated tests. |
| HTML/CSS | — | Browser interface technology implied by the web application; styling approach is otherwise unspecified. |

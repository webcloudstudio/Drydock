# Technology Stack

**Approved:** 2026-08-10

Technology decisions of record for this Target. One row per technology, naming the
Rigging best-practice file that governs building it.

A `—` in the Rigging column means no Rigging guidance exists for that technology; the
builder applies general best practice instead. Adding a row never requires a matching
Rigging file.

This file is owned by the UAT kit. It is seeded into the Target before `analyze`, which
never overwrites it, and `drydock plan` reads it to assign per-story `stack:` guidance.

| Technology | Rigging | Notes |
|---|---|---|
| Python 3 | python.md | Implementation language. |
| Python standard library | common.md | No third-party runtime dependencies. |
| POSIX shell | common.md | `full_test.sh` is required to be POSIX-compatible. |

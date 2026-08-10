# Technology Stack

**Approved:** 2026-08-09

Technology decisions of record for this Target. One row per technology, naming the
Rigging best-practice file that governs building it.

A `—` in the Rigging column means no Rigging guidance exists for that
technology; the builder applies general best practice instead. Adding a row never
requires a matching Rigging file.

`drydock analyze` proposes this file once. It is owned by the Commander thereafter and
is never overwritten. `drydock plan` reads it to assign per-story `stack:` guidance.

| Technology | Rigging | Notes |
|---|---|---|
| Go | go.md | Go 1.22 or newer; toolchain minimum pinned in go.mod. |
| Shell | common.md | POSIX sh for the supplied scoring entry point and the conformance harness. |

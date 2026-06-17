# ARCHIVE: general
Archived from notes_general.md

### Notes File Structure and Lifecycle
`2026-06-14` · `spec:na` · `impl:implemented`

One notes file per command or SAIL workflow phase. Files are the working scratchpad; the spec
remains the sole source of truth. Notes do not replicate the spec — they capture design thinking
and implementation state as it morphs.

File naming:
- `docs/notes_<command>.md` — command-specific design thinking
- `docs/notes_sail_<phase>.md` — SAIL workflow phase notes (setup, analyze, iterate, loop)
- `docs/notes_general.md` — cross-cutting decisions, default routing target

### Section-Level Tagging Format
`2026-06-14` · `spec:na` · `impl:implemented`

Every decision block is a named `###` section with a flag line immediately below the heading:

```
### Two-Step Application Model: Close Out and Apply
`2026-06-14` · `spec:na` · `impl:implemented`

**Close Out** — end of session, in-context. Compact discussion into the appropriate notes files.
No changes to spec or code. Triggered by "close out", `/thinkthrough close`, or at halt.

**Apply** — separate session after `/clear`. Read notes with `spec:recommended` flags, push
changes to the spec and/or code, then update the flag to `spec:applied`.

The two steps are intentionally separate so that a session can be captured without committing to
a spec edit in the same context window.

### Spec Tag Calibration
`2026-06-14` · `spec:na` · `impl:implemented`

Set `spec:recommended` only when a decision changes or confirms a behavioral contract: inputs,
outputs, state transitions, exit behavior. Implementation details, file locations (unless
contractual), internal naming, and bug fixes default to `spec:na`. When uncertain, lean toward
`na` — the user reviews `recommended` items and promotes them; false positives create noise.

## Acceptance Criteria

- -

## Guardrails

- -

## Open Questions

- -

## Not in scope yet

- -

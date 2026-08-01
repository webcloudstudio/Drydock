# DONE: plan

Date: 2026-07-31

### Build-Time Context (Downstream — Noted Here, Not Owned Here)
`2026-07-31` · `spec:na` · `impl:implemented`

These are implemented by `build`; the graph supports them:

- **No long-term memory.** Each build iteration assembles a complete, clean instruction set from
  scratch: full builder view of the stack + compacted user/contract view. No reliance on what the
  model remembers.
- **Verification.** After each build, tool calls check success. AC expressed as executable Python
  runnables where possible; some non-executable AC is unavoidable.
- **Drift oracle.** Graph node state tracks what is built and verified; green propagates along
  `depends-on` edges. Propagation model not yet fully elaborated.

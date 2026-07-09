# notes_refit.md — Design Notes for `drydock refit`

## Merge Process

The current prototype uses a separate merge process to integrate refit outputs into the working
tree. The approach is under review: git diff is being evaluated as a cleaner mechanism — each
output file would be diffed against its prior state, dirty files flagged, and only changed files
reapplied. If the git-diff approach proves out, the spec's merge step description will be updated
to reflect the new behavior.

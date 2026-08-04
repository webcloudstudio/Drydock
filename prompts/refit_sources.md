---
name: refit_sources
description: Author an exact build specification for a source-driven change.
version: 1.0.0
intent: Produce one precise refit ticket body for the affected Blueprint.
command: refit --sources
output: blueprint/<Blueprint-name>_refit_<number>.md
---

Write the exact specification of the source-driven change for the named Blueprint.
The output is the implementation contract consumed by `drydock build`. Describe only
what must change, including observable behavior, affected interfaces, acceptance criteria,
and guardrails. Do not rewrite the Blueprint, author Manifest syntax, choose dependencies,
or include commentary about this task.

Emit the result in one artifact block named exactly as requested:

```text
=== blueprint/<Blueprint-name>_refit_<number>.md ===
<ticket body>
=== END blueprint/<Blueprint-name>_refit_<number>.md ===
```

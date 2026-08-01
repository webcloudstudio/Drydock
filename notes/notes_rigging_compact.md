# NOTES: Rigging Compact

| Field | Value |
|-------|-------|
| Version | 2026-06-22 V1 |
| Route | rigging compact |
| Status | Working notes — not canonical specification |
| Description | Design decisions for drydock rigging compact — usage-surface extraction via MCP-inspired compact derivatives. |
| Pending spec | 0 approved items |
| Pending impl | 0 unimplemented sections |

## Goal

Build `drydock rigging compact` the correct way: extract the caller-facing usage surface of a
specification file and emit an MCP-inspired compact derivative for injection into consumer story
prompts. Builder stories receive the full file; consumer stories receive the compact.

## Acceptance Criteria

- Compact output contains only callable units in MCP block format; no implementation detail
- Branding/tone/narrative files produce `no-surface` status and no output file
- `--include-file` / `--exclude-file` / `--include-dir` work independently and in combination
- `no-surface` does not increment the failure count or set exit code 1
- Freshness gate and `--force` behavior unchanged

## Guardrails

- The previous `_GENERAL_OBJECTIVE` preserved constraints verbatim. The new objective explicitly
  instructs the agent to drop implementation detail and rationale.
- The `COMPACT_ERROR` token must appear literally in the response; the module does not attempt to
  infer "no surface" from empty or low-quality output — that remains a `failed` status.

## Open Questions

-

## Not in scope yet

- Rigging configuration to declare which files are always compacted (mentioned in spec as a TODO;
  deferred — auto-discovery + explicit flags cover current needs)
- Per-file `--objective` override via CLI
- Batch LLM execution (one call per file is correct for now; revisit if latency becomes a problem)

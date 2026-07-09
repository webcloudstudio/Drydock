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

## Decisions

### Compact audience is user, not builder
`2026-06-22` · `spec:approved` · `impl:implemented`

The compact derivative is written for a **consumer** of the service described in the source file —
an agent that calls the API, not one that builds it. Builders receive the full source file.
The previous implementation produced a "behaviorally faithful miniaturization" preserving every
constraint and code block. That was the wrong lens; it produced a smaller builder document, not a
caller document. The new prompt extracts only callable units.

### Output format: MCP-inspired markdown
`2026-06-22` · `spec:approved` · `impl:implemented`

Each callable unit (HTTP route, class method, function, required config entry) is one block:

```
### METHOD /path   or   ### ClassName.method_name
One-line description.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|

Returns: TypeName — brief description
```

This mirrors the MCP tool schema (name, description, inputSchema, returnType) in a form any LLM
trained on tool-use patterns can read immediately. Tables may be used for structured return schemas.
Rationale, implementation detail, constraints, and code blocks showing internals are excluded.

### No-surface classification and COMPACT_ERROR
`2026-06-22` · `spec:approved` · `impl:implemented`

Files with no callable technical surface (branding guides, tone documents, process narratives)
cannot produce a useful compact derivative. The LLM classifies these inside the prompt and emits:

```
COMPACT_ERROR: no technical surface — builder use only
```

The module detects this token, marks the item `no-surface` (not `failed`), and writes no compact
file. Exit code remains 0 — this is expected behavior, not an error. The distinction from `failed`
(which is an LLM error) is critical: `no-surface` is the correct outcome for builder-only files.

### File selection: --include-file, --exclude-file, --include-dir
`2026-06-22` · `spec:approved` · `impl:implemented`

The existing auto-discovery (required pairs + existing `_compact.md` siblings) remains the
default. Three new flags extend it:

- `--include-file <file.md>` — add a specific file (repeatable)
- `--exclude-file <file.md>` — remove a file from the auto-discovered set (repeatable)
- `--include-dir <dir>` — add all `.md` files under a directory (repeatable)

All inputs must resolve to `.md` files. `_compact.md` files are never sources.
Files are processed one at a time; no batch LLM calls.

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

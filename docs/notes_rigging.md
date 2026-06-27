# NOTES: Rigging Update and Verify

| Field | Value |
|-------|-------|
| Version | 2026-06-26 V2 |
| Route | rigging update / rigging verify |
| Status | Working notes — not canonical specification |
| Description | Design decisions for drydock rigging update and rigging verify — injecting compact Rigging into built target projects and verifying compliance. |
| Pending spec | 0 approved items |
| Pending impl | 0 unimplemented sections |

## Goal

Build `drydock rigging update` and `drydock rigging verify` the correct way: propagate
current `BUSINESS_RULES_compact.md` into a built target project's `AGENTS.md` via injection
markers, stamp provenance metadata, and report whether the target is current.

## Decisions

### rigging update: inject compact rules into AGENTS.md
`2026-06-26` · `spec:na` · `impl:implemented`

Source: `BUSINESS_RULES_compact.md` from Rigging (resolved via `paths.py`).
Target: `AGENTS.md` in `$DRYDOCK_BUILD_DIRECTORY/<Target>`.

Mechanism:
1. Strip existing `# DRYDOCK_RIGGING_START` … `# DRYDOCK_RIGGING_END` block from `AGENTS.md`.
2. Append the current compact content wrapped in those markers.

`AGENTS.md` is a contract on the built target — always present.

### rigging update: stamp METADATA.md
`2026-06-26` · `spec:na` · `impl:implemented`

Mechanical stamp — no user input. Fields written to `METADATA.md` in
`$DRYDOCK_BUILD_DIRECTORY/<Target>`:

| Field | Source |
|---|---|
| `drydock_target` | Target name argument |
| `drydock_build_directory` | Resolved `$DRYDOCK_BUILD_DIRECTORY/<Target>` path |
| `drydock_project_state` | Lifecycle state read from built target's `METADATA.md` |
| `drydock_rigging_updated` | ISO timestamp of this run |

`name` and `short_description` are required fields but are human-authored (collected during
`drydock analyze` — see [[analyze-name-questionnaire]]). `rigging update` does not fill them;
`rigging verify` flags their absence.

### Injection markers
`2026-06-26` · `spec:na` · `impl:implemented`

Drydock-native markers: `# DRYDOCK_RIGGING_START` and `# DRYDOCK_RIGGING_END`.
V1 used `# CLAUDE_RULES_START / # CLAUDE_RULES_END`; Drydock uses its own namespace.

### rigging verify: staleness and compliance checks
`2026-06-26` · `spec:na` · `impl:implemented`

Checks (per-check pass/fail output):
1. `AGENTS.md` injected block exists and its content hash matches the current compact — stale or
   missing = fail.
2. `METADATA.md` has `name` field.
3. `METADATA.md` has `short_description` field.
4. METADATA.md stamp fields (`drydock_target`, `drydock_build_directory`,
   `drydock_project_state`, `drydock_rigging_updated`) exist.

Overall PASS/FAIL. Exit 0 all pass, 1 any fail.

### --dry-run flag on rigging update
`2026-06-26` · `spec:na` · `impl:implemented`

`--dry-run` previews what would change without writing any files. Mirrors V1 behavior.

### Branding/voice injection: deferred
`2026-06-26` · `spec:na` · `impl:unimplemented`

Injecting branding/voice content (e.g. `BRANDING_EDSVOICE.md` equivalent) into the target
`AGENTS.md` is explicitly deferred. Current scope: business rules compact only.

### name and short_description collection: belongs in analyze
`2026-06-26` · `spec:na` · `impl:unimplemented`

`name` and `short_description` must be collected during `drydock analyze` as a questionnaire
step and written to the Target's `METADATA.md`. They are not seeded by `rigging update`.
This is a required addition to `drydock analyze` but is out of scope for this rigging session.

## Acceptance Criteria

- `rigging update` injects current compact into `AGENTS.md` via `DRYDOCK_RIGGING_START/END` markers ✓
- `rigging update` stamps all four provenance fields in the built target's `METADATA.md` ✓
- `rigging update --dry-run` shows what would change without writing ✓
- `rigging verify` reports per-check pass/fail and exits 0/1 correctly ✓
- Stale injected block (compact changed since last update) is detected by verify ✓
- Missing `name` or `short_description` is flagged by verify ✓

## Guardrails

- `AGENTS.md` in the built target is always present — commands may assume it exists.
- Rigging source is resolved via `paths.py`; never hardcode a path.
- Do not inject branding/voice in this scope.
- `rigging update` does not prompt for user input.

## Open Questions

-

## Not in scope yet

- Branding/voice injection into `AGENTS.md`
- `name` / `short_description` collection in `drydock analyze` (tracked as a separate requirement)
- Template file copying (V1 copied `common.sh`, `common.py`, `index.html`, Console/ — not needed in Drydock V2)

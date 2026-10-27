# MEMORY: drydock rigging

| Field | Value |
|---|---|
| Version | 2026-10-15 V1 |
| Description | Manage the governed rules every build reads. |
| Route | rigging |
| Modules | `rigging_compact.py`, `rigging_update.py`, `rigging_verify.py`, `rigging_manifest.py`, `rigging_contract.py`, `paths.py` |
| Prompts | `rigging_compact_architecture.md`, `rigging_compact_contracts.md`, `rigging_compact_database.md` |
| Tests | `tests/test_rigging*.py` |
| Topics | [foundations](../topics/foundations.md) |
| Pending spec | 0 |
| Pending impl | 1 |

## Intent

Manage the governed rules every build reads. `compact` derives the caller-facing usage surface
of a specification into a `*_compact.md` sibling so consumer stories carry the contract, not the
whole file. `update` and `verify` propagate and check business rules in a built Target. `--add`
catalogs new Rigging files for Analyze.

## Guardrails

- None.

## Details

### Current contract

The full and compact shipped persistence/SQLite/PostgreSQL/Python references publish the Python
initializer consistently. Their provenance hashes match the updated full sources without a
provider call. Generated schema and shipped engines remain DATABASE-owned. The initializer is
an explicit creation API, not startup migration or canonical test cleanup.


### Syntax

```text
drydock rigging --add [--file <path>]... [--dir <path>]...
drydock rigging compact [<Target>] [--all] [--force] [--include-file <f.md>]...
                        [--exclude-file <f.md>]... [--include-dir <dir>]...
drydock rigging update <Target> [--dry-run]
drydock rigging verify <Target>
```

### Rules

`2026-10-19` · Each Target compaction role receives the selected language in its job context. Shipped Rigging compaction and source freshness rules remain unchanged. Breaking this rule emits interfaces for the wrong language.

`2026-10-24` · **Every CLI compaction refreshes shipped Rigging.** A bare `compact` scans
Drydock's shipped `Rigging/` tree; a `<Target>` adds that Target's `blueprint/` scope.
`--all` remains accepted and is redundant. Explicit include paths add sources; exclusions remove
sources from either scope. With no Target, cwd anchors paths but is never scanned. Internal
build-time `ensure_compact_files` remains restricted to its explicit sources. Cost when broken:
stale shipped contracts such as SQLite guidance survive an ordinary maintenance run.

`2026-09-19` · **Discovery is refresh-biased.** Blueprint scope takes `DATABASE.md`,
`BUSINESS_RULES.md`, and any `*.md` that already has a `_compact.md` or `_compact.skip.md` sibling.
Rigging scope only refreshes existing siblings and never compacts a file for the first time.
Compass files and derivatives are never sources. Cost when broken: `--all` compacts Drydock's whole
prose tree on every run.

`2026-09-19` · **Freshness is by mtime or content hash.** A source is skipped when its sibling is at
least as new, or when the sibling's provenance line records the source's current sha256; a hash
match refreshes the sibling's mtime. `--force` bypasses the gate. Cost when broken: a byte-identical
rewrite triggers a paid call.

`2026-09-19` · **The model emits; the module writes.** Each file is routed by name to a role
(`ARCHITECTURE.md` → architecture, `DATABASE.md` → database API, else contracts) and compacted in
one call. A file with no callable surface yields `*_compact.skip.md` only when the response carries
the literal `COMPACT_ERROR` token; empty or low-quality output is `failed`, never inferred as
no-surface. Builders receive the full file; consumers receive the compact. Cost when broken: a
summary of prose injected as if it were a contract.

`2026-06-26` · **`rigging update` owns one marked block in the built Target's `AGENTS.md`.** It
replaces the `# DRYDOCK_RIGGING_START` … `# DRYDOCK_RIGGING_END` block with the current
`BUSINESS_RULES_compact.md` (resolved through `paths.py`) and stamps `drydock_target`,
`drydock_build_directory`, `drydock_project_state`, and `drydock_rigging_updated` in its
`METADATA.md`. It never prompts and never fills `name` or `short_description`, which Analyze
collects. `--dry-run` writes nothing. Cost when broken: hand edits outside the markers lost, or
human-authored identity overwritten.

`2026-06-26` · **`rigging verify` is a per-check compliance report.** The injected block exists and
matches the current compact by hash; `METADATA.md` carries `name`, `short_description`, and the
four stamp fields. Cost when broken: a stale business-rules block builds against superseded rules
unnoticed.

`2026-07-18` · **`rigging --add` only catalogs.** It appends files inside `Rigging/` to the
`Rigging/MANIFEST.md` catalog table with placeholder category, purpose, and prerequisites for the
Commander to complete; existing entries are reported, not duplicated. Paths outside `Rigging/`,
missing files, and the manifest itself are usage errors. Cost when broken: Analyze is offered a
Rigging file whose purpose was invented.

### Mechanism

1. **compact** — discover sources, apply the freshness gate, route each to its role prompt,
   assemble deterministically, one `run_prompt` per file, write the derivative with a provenance
   line. Statuses: `compacted`, `skipped-fresh`, `skipped-unchanged`, `no-surface`, `failed`.
2. **update** — strip and re-append the marked block in `AGENTS.md`, stamp `METADATA.md`.
3. **verify** — evaluate each check, print ✓/✗ per check and `RESULT: PASS|FAIL`.
4. **--add** — validate paths under `Rigging/`, append catalog rows.

`2026-10-26` · **Freshness gate.** A derivative whose provenance records a source sha256 is fresh
only when that sha matches the current source bytes; mtime cannot override it (checkout, copy or
same-second edits leave changed bytes older than the derivative). A derivative without provenance
keeps the mtime test. `compact` and `status` share `_is_stale`. Stabilization F23.

### Exit codes

| Code | Condition |
|---|---|
| `0` | `compact`: no `failed` file (`no-surface` is success). `update`: done. `verify`: all checks pass. `--add`: always. |
| `1` | `compact`: any file `failed`. `update`: failed. `verify`: any check fails. |
| `2` | Usage error, including invalid `--add` paths. |

### Spec divergence

- The specification shows `drydock rigging compact <Target>` with a required `<Target>`; the
  CLI permits no Target and always refreshes shipped Rigging alongside any requested sources.
- The specification says `--add` takes `--file`/`--dir`; it does not say the paths must lie under
  `Rigging/` or that it only edits `Rigging/MANIFEST.md`.

## Decisions

### Branding/voice injection: deferred
`2026-06-26` · `spec:na` · `impl:unimplemented`

Injecting branding/voice content (e.g. `BRANDING_VOICE.md` equivalent) into the target
`AGENTS.md` is explicitly deferred. Current scope: business rules compact only.

## Questions

-

## Actions

-

## Working Notes

-

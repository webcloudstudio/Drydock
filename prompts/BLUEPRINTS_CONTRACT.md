# Blueprints Contract

Contract governing the layout, file types, header format, and dependency conventions for Drydock
Blueprint directories. Used by `drydock analyze`, `drydock plan create`, `drydock refit`, and all
prompt assembly workflows.

---

## Overview

A **Blueprint** is the complete Typed Specification for one project. It lives at
`$DRYDOCK_WORKSPACE/targets/<Target>/blueprint/` and contains all human-authored and
process-created specification files. The Blueprint is the single source of truth for what the
project is, what it must do, and how it is built.

---

## Specification File Types

| File | Purpose | Required |
|------|---------|----------|
| `METADATA.md` | Project identity: name, display_name, short_description, status, stack, code_root | Yes |
| `COMPASS.md` | Product intent, constraints, success criteria, guardrails, open questions | Yes |
| `ARCHITECTURE.md` | Modules, routes, boundaries, interfaces, technical decisions | Yes |
| `README.md` | One-line description and `## Intent` section | Yes |
| `AGENTS.md` | Callable surface: `## Endpoints`, `## Capabilities` (JSON), `## Links` | If exposes services |
| `DATABASE.md` | Persistence contract: all stores, typed access classes, schemas, migrations | If has persistent state |
| `UI-GENERAL.md` | Shared UI patterns across screens | If has UI |
| `SCREEN-{Name}.md` | Per-screen: route, layout, interactions, acceptance criteria | If has UI |
| `FEATURE-{Name}.md` | Per-feature: purpose, status, trigger, sequence, routes, reads, writes, AC, guardrails | As needed |
| `BUILD_PLAN_COMPASS.md` | Internal inventory of Blueprint inputs and planning groups | Process-created |
| `ARCHITECTURE_FUNC_compact.md` | Compact architecture for Functionality phases — module summaries, config, no routes | Optional |
| `ARCHITECTURE_UI_compact.md` | Compact architecture for UI phases — routes table, directory layout | Optional |
| `HOMEPAGE.md` | Portfolio homepage: branding, contact, bio | If publishes a portfolio |
| `HOMEPAGE-PUBLISHER.md` | Template-based homepage publishing configuration | If publishes a portfolio |
| `IDEAS.md` | Feature ideas and backlog — no typed header required | No |
| `*-AC.md` / `AC-*.md` / `*-AC-*.md` | Acceptance criteria — any file where `AC` is a whole word in the filename | As needed |
| `changes/TICKET-NNN-{Name}.md` | Post-baseline change, defect, or spike request | As needed |

Every authored Specification file ends with `## Acceptance Criteria`, `## Guardrails`, and
`## Open Questions`. Use `- None.` when no entries apply.

`ARCHITECTURE_FUNC_compact.md` and `ARCHITECTURE_UI_compact.md` are compact derivatives of
`ARCHITECTURE.md` authored by the spec author. When present, `drydock plan create` automatically
selects the appropriate variant based on phase content (FEATURE-* files → FUNC compact; SCREEN-*
files → UI compact). Both fall back to `ARCHITECTURE.md` if absent.

---

## Specification File Header Format

Every authored Specification file except `METADATA.md` and `README.md` must begin with a typed
header. Operational and generated files (`IDEAS.md`, build plans, analysis outputs, and AC files)
are not authored Specification files.

```markdown
# {FileType}: {ObjectName}

| Field       | Value |
|-------------|-------|
| Version     | YYYYMMDD V1 |
| Description | One sentence summary. |
| Depends On  | FEATURE-SERVICE-CATALOG.md, UI-GENERAL.md |
| Provides    | GET /welcome, GET /welcome/summary |
| Phase       | 2 |
```

**FileType values:** `COMPASS`, `SCREEN`, `FEATURE`, `DATABASE`, `UI-GENERAL`, `ARCHITECTURE`,
`HOMEPAGE`

**ObjectName:** Human-readable name matching the file subject (e.g., `Welcome Summary`,
`Service Catalog`).

**Fields:**

| Field | Set By | Required | Description |
|-------|--------|----------|-------------|
| `Version` | Author | Yes | Date + increment: `YYYYMMDD V1`. Every agent write must set this to the current date with the next increment. If the existing version is already today's date, increment the number. Never carry forward a stale date. |
| `Description` | Author | Yes | One sentence |
| `Depends On` | `drydock plan create` | No | Filenames this file requires to exist before build |
| `Provides` | `drydock plan create` | No | HTTP routes or interfaces this file exposes |
| `Phase` | `drydock plan create` | No | Build phase hint (integer); tooling may override |

**Additional optional fields for SCREEN files:**

| Field | Required | Description |
|-------|----------|-------------|
| `Route` | No | The URL this screen is served at |
| `Parent` | No | Parent menu item or `—` |
| `Main Menu` | No | Menu label and position |
| `Sub Menu` | No | Submenu label and position |
| `Tab Order` | No | Tab index within parent, or `—` |

`Depends On` and `Provides` are written by `drydock plan create` — do not edit manually.
`Phase` is written by `drydock plan create` — do not edit manually unless overriding.

---

## Common Authored Specification Sections

Every authored Specification file ends with these sections, using `- None.` when no entries apply:

```markdown
## Acceptance Criteria

- None.

## Guardrails

- None.

## Open Questions

- None.
```

`COMPASS.md` uses `## Compass`, `## Constraints`, and `## Success Criteria` as its body sections.
Do not use `## Goals`; measurable product outcomes belong in `## Success Criteria`.

---

## AGENTS.md Format

Three optional sections; include only what applies. JSON only — no YAML.

### ## Endpoints

Documents the project's HTTP API. Parsed by GAME's scanner into the Service Catalog.

```markdown
## Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET    | /health          | Health check |
| POST   | /api/items       | Create item  |
| GET    | /api/items/{id}  | Get item     |
```

### ## Capabilities

Typed, transport-agnostic callable functions. Parsed by GAME's scanner into the Capability
Catalog.

```json
{
  "capabilities": [
    {
      "name": "download_prices",
      "description": "Download historical market prices",
      "tags": ["finance", "data-source", "etl"],

      "invoke": {
        "cli": "bin/download_prices",
        "rest": { "method": "POST", "path": "/download/prices" },
        "mcp": "download_prices"
      },

      "input": {
        "symbol":     { "type": "string", "required": true },
        "start_date": { "type": "date",   "required": true },
        "end_date":   { "type": "date",   "required": true }
      },

      "output": {
        "dataset_id":      { "type": "string" },
        "rows_downloaded": { "type": "integer" }
      },

      "permissions": {
        "owners": ["ed"],
        "access": "readwrite"
      },

      "lifecycle": "on-demand"
    }
  ]
}
```

**Capability fields:**

| Field | Required | Notes |
|-------|----------|-------|
| `name` | Yes | Globally unique slug across the network |
| `description` | Yes | One sentence |
| `tags` | No | Arbitrary strings for filtering |
| `invoke.cli` | If CLI enabled | Path to bin/ script |
| `invoke.rest` | If REST enabled | `method` + `path` |
| `invoke.mcp` | If MCP enabled | MCP tool name |
| `input` | Yes | Named fields: `type`, `required` |
| `output` | Yes | Named fields: `type` |
| `permissions.owners` | No | Identities with write access |
| `permissions.access` | No | `readonly` \| `readwrite` |
| `lifecycle` | Yes | `on-demand` \| `always-on` \| `scheduled` |

**Rules:**
1. Capability names are globally unique within the network.
2. Contracts are transport-independent — same input/output schema regardless of transport.
3. Input and output must be JSON-serializable.
4. Permissions are declared in the publishing project and enforced by the platform.

### ## Links

External links shown in the Service Catalog UI.

```markdown
## Links

| Label | URL |
|-------|-----|
| GitHub | https://github.com/... |
| Docs   | https://...           |
```

---

## Acceptance Criteria Files

**Naming rule:** any file where `AC` is a whole word in the filename is an acceptance criteria
file. `AC` must be delimited by `-`, `_`, or file boundaries — not embedded in another word.
Examples: `AC-001-login.md`, `FEATURE-LOGIN-AC.md`, `AC-NAVIGATION.md`.
`ACCEPTANCE_CRITERIA.md` does NOT follow this standard (AC is not a standalone word).

AC files enable test-driven design and a way to enforce specific behaviors without polluting the
parent specification.

**Two types of AC statements:**

| Type | Example | Rule |
|------|---------|------|
| Positive assertion | "The status badge color is red" | Reconcile into parent spec, then archive this entry |
| Negative/guardrail | "Field X must not appear on this screen" | Keep permanently in AC — these guard against model hallucination, not spec omission |

**Reconciliation:** When a positive AC fact has been implemented and verified, move it to the
parent spec body and delete the AC entry. Negative guardrails are permanent — never move them to
the spec.

**AC file format:**

```markdown
# AC: {ObjectName}

| Field       | Value |
|-------------|-------|
| Version     | YYYYMMDD V1 |
| Description | Acceptance criteria for {ObjectName}. |
| Parent      | FEATURE-{Name}.md |

## Guardrails

- Field X must not appear on this screen.
- The delete button must not be shown to read-only users.

## Assertions

- The status badge is rendered in red when severity is HIGH.
```

**Standard AC filename forms:**
- `AC-NNN-{Name}.md` — numbered sequential acceptance-criteria ticket (authored)
- `{Parent}-AC.md` — paired directly with a spec file (e.g. `FEATURE-LOGIN-AC.md`)
- `AC-{Topic}.md` — topic-scoped AC file (e.g. `AC-NAVIGATION.md`)

**All fix and change tickets use AC naming** — `AC` as a whole word in the filename. A targeted
bug fix is expressed as a testable acceptance criterion.

---

## Dependency Declarations

`drydock plan create` scans spec file headers to populate `Depends On` and `Provides`. The
following conventions apply automatically without explicit header declaration:

| Convention | Rule |
|------------|------|
| `SCREEN-*.md` → `UI-GENERAL.md` | All screens depend on shared UI patterns |
| `DATABASE.md` → Phase 1 | Always first phase; always base context |
| `ARCHITECTURE.md` → base context | Included in every phase prompt |
| `FEATURE-*.md` providing routes → listed in `Provides` | Extracted from route tables in file |
| `SCREEN-*.md` using a route → depends on providing `FEATURE` | Matched from route references in body |

The `Depends On` and `Provides` fields form a simple directed dependency graph. `drydock plan
create` traverses this graph to assign phases, assign build order, and compute context sizes.
A file can only be built in a phase after all its `Depends On` files are built.

---

## Persistence Encapsulation (DATABASE.md scope)

`DATABASE.md` is the project's persistence contract — not SQL schema alone. It documents every
persistent store and the typed class that encapsulates it:

- **Relational tables** — schema plus the row dataclass / CRUD class / composing `Database` class.
- **Config / `.env`** — required keys and the typed `Config` class.
- **File stores** — directories and the `FileStore` class.
- **External services** — the service contract and its wrapper.

Application code reaches each store only through its class. A storage change that leaves the
interface unchanged does not invalidate downstream features.

---

## METADATA.md — Service Identity Fields

In addition to standard project fields, service repositories should declare:

```
service_name:      Platform        # top-level service grouping (e.g. Platform, Analytics, Tools)
service_component: GAME            # component name within the service (matches directory name)
```

These fields are used by capability declarations in `AGENTS.md` and by GAME's service registry
scanner to group related repositories under a named service.

---

## Authoring Conventions

**Authoring phase:** all unresolved questions go in `## Open Questions` sections. Do not create
`BUILD_PLAN_COMPASS.md` or numbered ticket files while authoring.

**Build phase:** run `drydock plan create` once the specification is ready. Use `drydock status`
to check for spec errors and staleness before building. After a build, fold changes back by editing
the specification and re-applying with `drydock refit`.

**Spikes:** a spike is a runnable investigation. Results feed future iterations. When run, the
finding is written into the named file, resolving the matching `## Open Question` in place.

**Feature specifications:** all feature purpose, status, triggers, sequences, routes, reads,
writes, acceptance criteria, and guardrails belong in individual `FEATURE-*.md` files. README,
METADATA, AGENTS.md, and generated files do not contain feature specifications.

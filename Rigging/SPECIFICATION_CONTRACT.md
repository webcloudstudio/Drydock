# SPECIFICATION_CONTRACT.md

Contract governing layout and file conventions for specification directories.
Specification directories live in the Specifications repository (path configured via `specification_directory:` in METADATA.md).

Used by: `bin/setup.sh`, `bin/validate.sh`, `bin/oneshot.sh`, `bin/oneshot_phased.sh`, and all prompt generators.

---

## Specification File Types

| File | Purpose | Required |
|------|---------|----------|
| `METADATA.md` | Project identity (name, display_name, short_description, status) | Yes |
| `AGENTS.md` | Callable surface area: `## Endpoints`, `## Capabilities` (JSON), `## Links` | If exposes services |
| `README.md` | One-line description + `## Intent` section | Yes |
| `INTENT.md` | Product intent, constraints, and success criteria | Yes |
| `ARCHITECTURE.md` | Modules, routes, directory layout | Yes |
| `ARCHITECTURE_FUNC_compact.md` | Compact architecture for Functionality phases — module summaries, config, no routes table | No |
| `ARCHITECTURE_UI_compact.md` | Compact architecture for UI phases — routes table, directory layout, Flask basics only | No |
| `DATABASE.md` | Persistence contract: all persistent stores (SQLite schema, config/env keys, file stores, external-service contracts) and the typed access class that encapsulates each | If has persistent state |
| `UI-GENERAL.md` | Shared UI patterns across screens | If has UI |
| `SCREEN-{Name}.md` | Per-screen: route, layout, interactions | If has UI |
| `FEATURE-{Name}.md` | Per-feature: purpose, status, trigger, sequence, routes, reads, writes, acceptance criteria, and guardrails | As needed |
| `HOMEPAGE.md` | Portfolio homepage: branding, contact, bio | If publishes a portfolio |
| `HOMEPAGE-PUBLISHER.md` | Template-based homepage publishing configuration | If publishes a portfolio |
| `IDEAS.md` | Feature ideas and backlog | No |
| `*-AC.md` / `AC-*.md` / `*-AC-*.md` | Acceptance criteria — any file where `AC` is a whole word in the filename. Guardrails (negative assertions) stay permanent; positive facts reconcile into parent spec. | As needed |
| `BUILD_PLAN.md` | Phase plan for phased builds — consumed by oneshot_phased.sh | If phased build |
| `BUILD_PLAN_INTENT.md` | Ordered semantic bundles for priority-driven phasing — user-edited, consumed by build_plan_auto.py | If phased build |
| `REFERENCE_GAPS.md` | Specification completeness gaps (written by spec_iterate.sh) | No |
| `SPEC_SCORECARD.md` | 7-dimension quality rating (written by spec_iterate.sh) | No |

Every authored Specification file, including `INTENT.md`, ends with `## Acceptance Criteria`, `## Guardrails`, and `## Open Questions`.

`ARCHITECTURE_FUNC_compact.md` and `ARCHITECTURE_UI_compact.md` are compact derivatives of `ARCHITECTURE.md` authored by the spec author. When present, `build_plan_auto.py` automatically selects the appropriate variant based on phase content (FEATURE-* files → FUNC compact; SCREEN-* files → UI compact). Both fall back to `ARCHITECTURE.md` if absent.

### Persistence Encapsulation (DATABASE.md scope)

`DATABASE.md` is the project's persistence contract — not SQL schema alone. It documents every
persistent store and the typed class that encapsulates it:

- **Relational tables** — schema plus the row dataclass / CRUD class / composing `Database` class.
- **Config / `.env`** — required keys and the typed `Config` class.
- **File stores** — directories and the `FileStore` class.
- **External services** — the service contract and its wrapper (`marina`, a `MessageBus`, etc.).

Application code reaches each store only through its class. The class interface is the
dependency boundary: a storage change that leaves the interface unchanged does not invalidate
downstream features. See `stack/persistence.md` for the mandatory patterns.

**Feature specifications:** All feature purpose, status, triggers, sequences, routes, reads, writes, acceptance criteria, and guardrails belong in individual `FEATURE-*.md` files. `build_spec_relationships.py` and `build_plan_auto.py` target individual FEATURE files to assign phases, compute context sizes, and resolve SCREEN dependencies. README, METADATA, AGENTS.md, and generated files do not contain feature specifications.

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

Typed, transport-agnostic callable functions. Parsed by GAME's scanner into the Capability Catalog.

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

## Numbered Ticket Files

Post-build artifacts — do not create during authoring. Authored manually as targeted fix tickets.

| Pattern | Purpose |
|---------|---------|
| `AC-NNN-{Name}.md` | Acceptance criteria and targeted fix tickets — use AC naming for all post-build corrections |

**All fix and change tickets use AC naming** — `AC` as a whole word in the filename. There is no separate PATCH type; a targeted bug fix is expressed as a testable acceptance criterion.

**Standard AC filename forms:**
- `AC-NNN-{Name}.md` — numbered sequential acceptance-criteria ticket (authored)
- `{Parent}-AC.md` — paired directly with a spec file (e.g. `FEATURE-LOGIN-AC.md`)
- `AC-{Topic}.md` — topic-scoped AC file (e.g. `AC-NAVIGATION.md`)

---

## Acceptance Criteria Files

**Naming rule:** any file where `AC` is a whole word in the filename is an acceptance criteria file. `AC` must be delimited by `-`, `_`, or file boundaries — not embedded in another word. Examples: `AC-001-login.md`, `FEATURE-LOGIN-AC.md`, `AC-NAVIGATION.md`. `ACCEPTANCE_CRITERIA.md` does NOT follow this standard (AC is not a standalone word).

AC files enable test-driven design and a simple way to force specific behaviors without polluting the parent specification.

**Two types of AC statements:**

| Type | Example | Rule |
|------|---------|------|
| Positive assertion | "The status badge color is red" | Reconcile into parent spec, then archive this entry |
| Negative/guardrail | "Field X must not appear on this screen" | Keep permanently in AC — these guard against model hallucination, not spec omission |

**Why keep negative assertions in AC:** Negative statements in a specification read as contradictions — "the fields are a, b, c… and specifically not d" is confusing because d is not mentioned elsewhere. A separate AC file frames the same statement as a test guardrail, which is its true purpose.

**Reconciliation:** When a positive AC fact has been implemented and verified, move it to the parent spec body and delete the AC entry. Negative guardrails are permanent — never move them to the spec.

**Header format:** AC files use `FileType: AC` and do not require `## Open Questions`.

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

---

## Authoring vs. Build Phase

Do not mix phases:

**Authoring** — all unresolved questions go in `## Open Questions` sections. Do not create `REFERENCE_GAPS.md`, `SPEC_SCORECARD.md`, `SPEC_ITERATION.md`, or numbered ticket files while authoring.

**Build** — run `oneshot.sh` or `oneshot_phased.sh` once the operator signals the specification is ready to build. Use `validate.sh` to check for spec errors and staleness before building. After a build, fold changes back by editing the specification and re-applying with `iterate.sh` (or re-running `oneshot_phased.sh`, which rebuilds only stale phases).

**Spikes** — a spike is a runnable investigation authored in `IDEAS.md` and seeded into the relevant `## Open Questions`. Each spike names the spec or stack file its findings belong to. When run, the decision is written into that named file, resolving the matching `## Open Question` in place — never injected wholesale into build prompts. Topic-scoping follows from placing each decision in the file the build already includes for that phase.

---

## Specification File Header Format

Every authored Specification file except `METADATA.md` and `README.md` must begin with a typed header. Operational and generated files (`IDEAS.md`, build plans, analysis outputs, and acceptance-criteria files) are not authored Specification files. The `Version` field is updated on every write — agents must not skip this step.

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

**FileType values:** `INTENT`, `SCREEN`, `FEATURE`, `DATABASE`, `UI-GENERAL`, `ARCHITECTURE`, `HOMEPAGE`

**ObjectName:** Human-readable name matching the file subject (e.g., `Welcome Summary`, `Service Catalog`).

**Fields:**

| Field | Set By | Required | Description |
|-------|--------|----------|-------------|
| `Version` | Author | Yes | Date + increment: `YYYYMMDD V1`. **Update rule:** every agent write must set this to the current date with the next increment (`V1`, `V2`, …). If the existing version is already today's date, increment the number. Never carry forward a stale date. |
| `Description` | Author | Yes | One sentence |
| `Depends On` | `build_spec_relationships.py` | No | Filenames this file requires to exist before build |
| `Provides` | `build_spec_relationships.py` | No | HTTP routes or interfaces this file exposes |
| `Phase` | `build_plan_auto.py` | No | Build phase hint (integer); tooling may override |

**Additional optional fields for SCREEN files** (set by author):

| Field | Required | Description |
|-------|----------|-------------|
| `Route` | No | The URL this screen is served at |
| `Parent` | No | Parent menu item or `—` |
| `Main Menu` | No | Menu label and position |
| `Sub Menu` | No | Submenu label and position |
| `Tab Order` | No | Tab index within parent, or `—` |

`Depends On` and `Provides` are written by `bin/build_spec_relationships.py` — do not edit manually.
`Phase` is written by `bin/build_plan_auto.py` — do not edit manually unless overriding.

## Common Authored Specification Format

The body between the typed header and terminal sections is specific to the file type. Every authored
Specification file ends with these sections, using `- None.` when no entries apply:

```markdown
## Acceptance Criteria

- None.

## Guardrails

- None.

## Open Questions

- None.
```

`INTENT.md` uses `## Intent`, `## Constraints`, and `## Success Criteria` as its file-specific body
sections. Do not use `## Goals`; measurable product outcomes belong in `## Success Criteria`.

---

## Dependency Declarations

`bin/build_spec_relationships.py` scans spec files to populate `Depends On` and `Provides` headers.
Tooling applies the following conventions automatically (no header declaration needed):

| Convention | Rule |
|------------|------|
| `SCREEN-*.md` → `UI-GENERAL.md` | All screens depend on shared UI patterns |
| `DATABASE.md` → Phase 1 | Always first phase; always base context |
| `ARCHITECTURE.md` → base context | Included in every phase prompt |
| `FEATURE-*.md` providing routes → listed in `Provides` | Extracted from route tables in file |
| `SCREEN-*.md` using a route → depends on providing `FEATURE` | Matched from route references in body |

Run order for large projects:

```bash
python3 bin/build_spec_relationships.py <ProjectName>   # populate Depends On / Provides
python3 bin/build_plan_auto.py <ProjectName>            # generate BUILD_PLAN.md from headers
bash bin/validate.sh <ProjectName>                      # verify headers are consistent
bash bin/oneshot.sh <ProjectName> <TargetDir>           # build (delegates to phased if > 80KB)
```

---

## METADATA.md — Service Identity Fields

In addition to standard project fields, service repositories should declare:

```
service_name:      Platform        # top-level service grouping (e.g. Platform, Analytics, Tools)
service_component: GAME            # component name within the service (matches directory name)
```

These fields are used by capability declarations in `AGENTS.md` and by GAME's service registry scanner to group related repositories under a named service.

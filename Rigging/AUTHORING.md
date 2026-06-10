# Specification Authoring & Build Operations

**Version:** 20260604 V1
**Description:** Author/operator-facing rules for specification naming and the spec-to-build pipeline. Not loaded into AI build prompts — see `prompts/oneshot_build_rules.md` for what the building agent reads.

This document is the home for content that previously lived in `prompts/oneshot_build_rules.md` but is concerned with *how humans organize specifications and runs*, not with *how the building agent expands a concise spec into code*. Moving it here drops ~2KB from every per-phase build prompt.

Related: `RulesEngine/SPECIFICATION_CONTRACT.md` defines spec file types and headers; this file covers naming patterns, ticket lifecycle, and the build pipeline scripts.

---

## Naming Conventions

| Prefix | Contains | Example |
|--------|----------|---------|
| `METADATA.md` | Project identity fields | Always present |
| `README.md` | One-line description + intent section | Always present |
| `DATABASE.md` | Tables and columns | If project has a database |
| `UI.md` | Shared visual patterns | If project has a UI |
| `ARCHITECTURE.md` | Code organization | Always present |
| `SCREEN-{Name}.md` | Per-screen specification | One per screen |
| `FEATURE-{Name}.md` | Cross-cutting behavior | One per major feature |

**Screen names** match the nav bar label: `SCREEN-Dashboard.md`, `SCREEN-Configuration.md`.

**Feature names** describe the capability: `FEATURE-Scan.md`, `FEATURE-Operations.md`.

### CHANGE Tickets (iteration only)

Mutations to existing specifications are expressed as CHANGE tickets, not edits fed raw to the build. Tickets live in `changes/CHANGE-NNN-description.md` within the specification directory.

| Prefix | Contains | Location |
|--------|----------|----------|
| `changes/CHANGE-NNN-description.md` | Targeted mutation to existing specification | `changes/` subdirectory |

**Ticket format:**

```markdown
# Change: NNN — Short description
**Status:** pending
**Type:** mutation
**Scope:** list of target files or areas

## Intent
Why this change is needed. One paragraph.

## Changes Required
- Specific, unambiguous instruction
- Another instruction

## Open Questions
None.
```

**Status values:** `pending` → `applied` (by LLM after apply) or `rejected` (by LLM if underspecified).
Rejected tickets gain a `## Rejection Reason` section. Applied tickets are kept for history.

---

## Pipeline

```
setup.sh  →  (author edits)  →  validate.sh  →  convert.sh  →  build.sh
   CREATE             DRAFT            VALIDATED       CONVERTED       BUILT
```

| Step | Script | Output |
|------|--------|--------|
| CREATE | `bin/setup.sh <name> ["desc"]` | Specification directory with template files |
| DRAFT | (author edits files) | Concise specifications |
| VALIDATED | `bin/validate.sh <name>` | Exit 0 = ready, exit 1 = fix issues |
| CONVERTED | `bin/convert.sh <name> > convert-prompt.md` | Detailed specifications (optional — build handles inline) |
| BUILT | `bin/build.sh <name> > build-prompt.md` | Tagged commit + complete build prompt |
| PROMOTED | (copy specification dir to own repo) | Independent project |

One-shot path: skip CONVERTED, go straight from VALIDATED to BUILT. `bin/build.sh` includes ONESHOT_BUILD_RULES.md so the AI agent handles expansion and building in a single pass.

---
name: import_source
description: Reverse-engineer project source code into Drydock Blueprint specification files.
version: "1"
intent: Read source code and produce structured Typed Specification files for a Drydock Blueprint.
command: drydock import --format source
output: Blueprint specification files in <file path="...">...</file> XML blocks
---

# Reverse-Engineer Project Into Blueprint

## Task

Read the source code of the **{{PROJECT_NAME}}** project provided below and produce a complete set
of Drydock Blueprint specification files. Each file should be concise — tables, bullets, and short
descriptions. Do NOT write implementation code; write specifications that describe what the project
does.

**Detected stack:** {{STACK_HINTS}}

## Output Format

Produce each file inside an XML block tagged with the destination filename. Use this exact format:

```
<file path="FILENAME.md">
file content here
</file>
```

Every file must be a complete, stand-alone specification file. Do not reference other files by
line number or assume the reader has the source code.

## Required Output Files

Produce all applicable files below. Use the exact filenames.

1. **METADATA.md** — key: value format. Required fields:
   `name`, `display_name`, `short_description`, `version`, `status`, `stack`, `description`

2. **README.md** — one-line description plus `## Intent` section (why it exists, who it's for)

3. **COMPASS.md** — typed heading `# COMPASS: {Name}`, followed by: `## Intent`, `## Constraints`,
   `## Success Criteria`, `## Guardrails`, `## Open Questions`

4. **ARCHITECTURE.md** — typed heading `# ARCHITECTURE: {Name}`, covering: modules or packages with
   brief purpose, route table (Method | Path | Handler | Purpose), directory layout tree, and
   technical decisions

5. **DATABASE.md** — typed heading `# DATABASE: {Name}`. One section per entity with column table
   (Name | Type | Constraints | Description). Include migrations and access class signatures if
   present in the source.

6. **FEATURE-{Name}.md** — one file per non-trivial feature. Typed heading `# FEATURE: {Name}`.
   Sections: `## Purpose`, `## Status`, `## Behavior` (trigger, sequence, routes, reads, writes),
   `## Acceptance Criteria`, `## Guardrails`, `## Open Questions`. Use the naming pattern
   `FEATURE-AREA.md` for area-based grouping.

7. **SCREEN-{Name}.md** — one file per distinct UI screen or page when the project has a UI.
   Typed heading `# SCREEN: {Name}`. Sections: `## Route`, `## Layout`, `## Interactions`,
   `## Data Displayed`, `## Acceptance Criteria`, `## Guardrails`, `## Open Questions`.

8. **UI-GENERAL.md** — typed heading `# UI-GENERAL: {Name}`. Include only when the project has a
   UI. Covers shared layout, navigation, color usage, and component patterns.

## Rules

- Every authored file except METADATA.md and README.md must end with these three sections, using
  `- None.` when no entries apply:
  ```
  ## Acceptance Criteria
  ## Guardrails
  ## Open Questions
  ```
- Be concise: tables and bullets, not paragraphs
- Screens and features must be separate files, not combined
- Route tables in ARCHITECTURE.md must list every route
- DATABASE.md must show every table and column — do not summarize
- Status must be `PROTOTYPE` unless the project is clearly production-ready
- Do not invent behavior; only describe what is present in the source
- Preserve ambiguous or conflicting statements in `## Open Questions`

---

## Project Source

{{SOURCE_CONTENT}}

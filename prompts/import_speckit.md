---
name: import_speckit
description: Translate a Spec Kit project into Drydock Blueprint specification files.
version: "1"
intent: Map Spec Kit constitution and feature artifacts into owning Drydock typed specification files.
command: drydock import --format speckit
output: Blueprint files in <file path="...">...</file> blocks plus a conversion report
---

# Translate Spec Kit Project Into Blueprint

## Task

Translate the **{{PROJECT_NAME}}** Spec Kit project provided below into a complete set of Drydock
Blueprint specification files. Apply the concept mapping defined here. Preserve all content — do
not discard, summarize, or omit any statement from the Spec Kit inputs.

## Concept Mapping

Apply this mapping from Spec Kit artifacts to Drydock files:

| Spec Kit input | Drydock destination |
|---|---|
| `.specify/memory/constitution.md` — project intent and constraints | Project-specific intent, constraints, and success criteria in `COMPASS.md`; reusable engineering rules stay in Drydock governance, not in `COMPASS.md` |
| `specs/<feature>/spec.md` — feature behavior and acceptance | One `FEATURE-{Name}.md`; clearly identified UI behavior also contributes to `SCREEN-{Name}.md` |
| `spec.md` user stories and acceptance scenarios | Feature behavior and acceptance criteria in the owning `FEATURE-{Name}.md` |
| `spec.md` success criteria and assumptions | `COMPASS.md` when project-wide; otherwise the owning `FEATURE-{Name}.md` |
| `plan.md` technical context and structure | `ARCHITECTURE.md`, `METADATA.md`, and `DATABASE.md` where applicable |
| `research.md` accepted decisions | The owning `FEATURE-{Name}.md`, `ARCHITECTURE.md`, or `DATABASE.md` |
| `research.md` unresolved decisions | `## Open Questions` in the owning Drydock file |
| `data-model.md` — persistence schema | `DATABASE.md` |
| `contracts/` — API contracts | Routes and interfaces in `FEATURE-{Name}.md` and `ARCHITECTURE.md` |
| `quickstart.md` — setup and validation | Useful operating instructions in `README.md`; otherwise note in Open Questions |
| `tasks.md` — ordered task breakdown | Ignored — Drydock generates its own plan from the Blueprint |

## Output Format

Produce each Blueprint file inside an XML block:

```
<file path="FILENAME.md">
file content here
</file>
```

After all `<file ...>` blocks, produce a conversion report between `<conversion-report>` tags:

```
<conversion-report>
# Spec Kit Conversion Report

## Mapped
- list of successfully mapped statements or files

## Duplicated
- statements that appeared in multiple Spec Kit files and were merged

## Ambiguous
- statements whose Drydock destination was unclear; placed in Open Questions

## Ignored
- Spec Kit content deliberately not mapped (explain why for each)
</conversion-report>
```

## Required Output Files

1. **METADATA.md** — key: value format: `name`, `display_name`, `short_description`, `version`,
   `status`, `stack`, `description`

2. **README.md** — one-line description plus `## Intent`

3. **COMPASS.md** — typed heading `# COMPASS: {Name}`. Sections: `## Intent`, `## Constraints`,
   `## Success Criteria`, `## Guardrails`, `## Open Questions`

4. **ARCHITECTURE.md** — typed heading `# ARCHITECTURE: {Name}`. Route table, module descriptions,
   technical decisions from `plan.md` and `research.md` accepted decisions

5. **DATABASE.md** — typed heading `# DATABASE: {Name}`. Column tables from `data-model.md`

6. **FEATURE-{Name}.md** — one file per Spec Kit feature. Typed heading `# FEATURE: {Name}`.
   Include behavior, acceptance criteria, and contract routes.

7. **SCREEN-{Name}.md** — one file per distinct screen when UI behavior is first-class in a
   feature's `spec.md`. Typed heading `# SCREEN: {Name}`.

## Rules

- Every authored file except METADATA.md and README.md must end with:
  ```
  ## Acceptance Criteria
  ## Guardrails
  ## Open Questions
  ```
  Use `- None.` when no entries apply.
- Do not discard ambiguous content; place it in `## Open Questions` with a note explaining
  the ambiguity.
- The conversion report must list every mapping decision, including ignored content with a reason.
- Do not invent behavior not present in the Spec Kit inputs.

---

## Spec Kit Project

**Blueprint:** {{PROJECT_NAME}}

{{SPECKIT_CONTENT}}

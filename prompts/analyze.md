---
name: analyze
description: Analyze Blueprint specification files — build dependency graph, detect project type, assess completeness, surface gaps and spike candidates, emit ANALYSIS.md and planning questionnaire.
version: 20260613 V1
intent: Evaluate a Blueprint's typed specification files and produce a structured ANALYSIS.md and optional planning.json questionnaire for Product Owner review before plan creation.
command: drydock analyze
model: opus
output: ANALYSIS.md, planning.json
---

# Blueprint Analysis Agent

You are analyzing a Drydock Blueprint — a directory of typed specification files. Your job is to
produce two outputs: an `ANALYSIS.md` for the Product Owner and a `planning.json` questionnaire
when unknowns exist that must be resolved before plan creation.

Emit **only** the two output blocks delimited below. No preamble, no explanation, no commentary.

---

## Inputs

The Blueprint files are injected below the job block. Each file is fenced with its filename.

---

## Tasks

Execute these in order:

**1. Parse the header graph.**  
For every authored spec file (all `.md` except `METADATA.md`, `README.md`, `BUILD_*.md`,
`IDEAS.md`, and `changes/`), extract from the typed header table:
`Version`, `Description`, `Depends On`, `Provides`, `Phase`.
Determine file type from the H1 prefix (`COMPASS`, `FEATURE`, `SCREEN`, `DATABASE`,
`ARCHITECTURE`, `AGENTS`, `UI-GENERAL`, `HOMEPAGE`).
Files lacking a typed header table are `non-conformant`.

**2. Build the dependency graph and sort.**  
Edge: A → B when A's `Depends On` lists B. Topological sort → build order.
Files with no outgoing `Depends On` edges are build roots. Mark terminal nodes (nothing depends
on them).

**3. Detect project type.**  
Classify using these signals:

| Type | Signals |
|---|---|
| `web` | `SCREEN-*.md` present; HTTP routes in `Provides`; HTTP verbs in ARCHITECTURE |
| `api` | `AGENTS.md` with `## Capabilities`; no `SCREEN-*.md`; commands/verbs in `Provides` |
| `cli` | Commands and sub-verbs in `Provides`; no routes or screens |
| `library` | Public API symbols in `Provides`; no routes, no screens |
| `pipeline` | Dataset or file names in `Provides`; no routes |
| `event-driven` | Topics, queues, or event types in `Provides` |

Mixed signals → type = `ambiguous`. Record both candidate types and add a
`project_type_clarification` questionnaire item.

**4. Check completeness against BLUEPRINTS_CONTRACT.**  
Required for all projects: `METADATA.md`, `COMPASS.md`, `ARCHITECTURE.md`, `README.md`
with `## Intent` section.  
Required for web: at least one `FEATURE-*.md` and one `SCREEN-*.md`.  
Required for api: `AGENTS.md` with `## Capabilities`.  
Required if persistence mentioned in COMPASS or ARCHITECTURE: `DATABASE.md`.  
Required sections inside each present file: `## Acceptance Criteria`, `## Guardrails`,
`## Open Questions` at end of every authored spec; COMPASS additionally needs `## Compass`,
`## Constraints`, `## Success Criteria`.  
Record each missing file or section as a `gap`.

**5. Check stack declaration.**  
Read `stack:` field from `METADATA.md`. If absent, empty, or literally `TBD`:
gate triggered → add `stack_declaration` questionnaire item.

**6. Collect spike candidates.**  
Gather every bullet under `## Open Questions` in every spec file that is not `- None.`
Tag each: `[filename] question text`.
If any question requires PO direction before build, add a `design_decisions` questionnaire item.

**7. Compute readiness verdict.**

| Verdict | Condition |
|---|---|
| `ready` | COMPASS present; stack declared; zero gaps in required files; no `design_decisions` gate |
| `ready_with_questions` | Required files present but questionnaire items exist |
| `blocked` | COMPASS.md missing; or structural errors that prevent plan creation |

---

## Output Format

Emit exactly these two blocks. Nothing outside them.

```
=== ANALYSIS.md ===
# Blueprint Analysis: {ProjectName}
generated: {ISO timestamp}
blueprint: {path}

## Project Summary
{Name, description, stack from METADATA.md. One short paragraph.}

## Project Type
type: {web | api | cli | library | pipeline | event-driven | ambiguous}
{One sentence citing the signals that determined the type.}

## Dependency Graph
| File | Type | Depends On | Provides | Phase |
|------|------|------------|----------|-------|
{One row per spec file, topological order, most-depended-on first.}

## Coverage Assessment
| Check | Status | Notes |
|-------|--------|-------|
{One row per required file and section. Status: pass | gap | warn.}

## Gaps
{Bullet list. "- None." if clean.}

## Spike Candidates
{Bullet list: `[{file}] {question text}`. "- None." if no open questions.}

## Stack Assessment
stack: {declared value | "not declared"}
{One sentence: declared and sufficient | declared but incomplete | not declared — gate triggered.}

## Readiness Verdict
verdict: {ready | ready_with_questions | blocked}
{One sentence reason.}

## Notes
{Non-conformant headers, ambiguous signals, any other observations. "None." if clean.}
=== END ANALYSIS.md ===

=== planning.json ===
{
  "id": "planning",
  "title": "Planning Session — Blueprint Questions",
  "purpose": "Resolve unknowns required before plan creation.",
  "questions": []
}
=== END planning.json ===
```

**Questionnaire item schema** (add to `questions` array only when a gate triggers):

```json
{
  "id": "{gate_id}",
  "label": "{Short Label}",
  "prompt": "{Full question text for the Product Owner?}",
  "input": "text | textarea | select | multiselect",
  "gate": "plan_create"
}
```

Gate ids and their triggers:

| id | Trigger | input type |
|---|---|---|
| `stack_declaration` | stack absent or empty | text |
| `project_type_clarification` | type is ambiguous | select |
| `design_decisions` | open questions requiring PO direction | textarea |

If no gates trigger, emit `planning.json` with an empty `questions` array.

---

## Hard Rules

- Emit only the two `=== ... ===` blocks. No text outside them.
- Do not modify or re-emit Blueprint spec file content.
- Do not invent gaps that do not exist in the files.
- Topological sort is required; do not list files in filesystem order.
- `planning.json` must be valid JSON.
- Verdict `blocked` requires COMPASS.md absent or a structural error; `ready` requires
  all required files present and stack declared.

---

The job metadata and Blueprint files follow below.

# drydock analyze — Process Specification

**Version:** 20260613 V1  
**Command:** `drydock analyze <Blueprint> [<Target>]`  
**Status:** Draft — candidate section for `docs/Drydock_Specification.md`

---

## Purpose

`drydock analyze` evaluates a Blueprint's specification files for completeness, header conformance,
dependency consistency, project type, and readiness for plan creation. It surfaces gaps,
spike candidates from open questions, and emits a structured questionnaire for Product Owner
review. It does not create or modify `MANIFEST.md`.

Run analyze before `drydock plan create`. Plan create reads the ANALYSIS.md and BUILD_CONFIGURATION.md
answers produced by analyze. If ANALYSIS.md is absent, plan create warns and proceeds with
deterministic defaults; questionnaire gates will have been skipped.

---

## Command Signature

```
drydock analyze <Blueprint> [<Target>]
```

- `<Blueprint>` — path to the Blueprint directory (must contain `METADATA.md`)
- `<Target>` — optional; when provided, enables drift analysis comparing spec to built code

Without `<Target>`: Blueprint-only analysis.  
With `<Target>`: Blueprint analysis + drift check (Provides routes vs. implemented code).

---

## Hard Gate

`METADATA.md` must exist in `<Blueprint>`. Abort with exit code 1 if absent.

Missing `COMPASS.md` does not abort analyze — it is noted in ANALYSIS.md as a plan-create
blocker with readiness verdict `blocked`.

---

## Algorithm

### Step 1 — Header Graph

Parse every `*.md` in the Blueprint directory. For each authored Specification file
(all except `METADATA.md`, `README.md`, operational files, and `BUILD_*` files), extract from
the typed header table:

| Field | Source |
|---|---|
| File type | H1 prefix: `COMPASS`, `SCREEN`, `FEATURE`, `DATABASE`, `ARCHITECTURE`, `AGENTS`, `UI-GENERAL`, `HOMEPAGE` |
| Object name | H1 suffix after the colon |
| `Version` | Header table |
| `Description` | Header table |
| `Depends On` | Header table — comma-separated filenames |
| `Provides` | Header table — comma-separated routes, commands, or symbols |
| `Phase` | Header table — integer hint |

**Graph construction:**  
Nodes = spec files. Directed edge from A → B when A's `Depends On` lists B (A requires B first).
Topological sort of this graph yields natural build order. Files with no outgoing edges
(depend on nothing) are build roots. Files with no incoming edges (nothing depends on them)
are terminal leaves.

Record header conformance: authored spec files missing the typed header table are flagged as
`non-conformant` in ANALYSIS.md.

### Step 2 — Project Type Detection

Classify from file inventory and COMPASS / ARCHITECTURE content:

| Type | Detection signals |
|---|---|
| `web` | `SCREEN-*.md` present; HTTP routes in any `Provides` field; HTTP verbs in ARCHITECTURE |
| `api` | `AGENTS.md` with `## Capabilities`; commands/verbs in `Provides`; no `SCREEN-*.md` |
| `cli` | Commands and sub-verbs in `Provides`; no routes or screens |
| `library` | Public API symbols in `Provides`; no routes, no screens |
| `pipeline` | Datasets, tables, or filenames in `Provides`; no routes |
| `event-driven` | Topics, queues, or event types in `Provides`; no routes |

Mixed signals: record both candidate types; set `project_type` to `ambiguous` and add a
`project_type_clarification` questionnaire item.

### Step 3 — Completeness Check

Check required files per BLUEPRINTS_CONTRACT:

| File | Required for |
|---|---|
| `METADATA.md` | All projects |
| `COMPASS.md` | All projects (plan-create gate) |
| `ARCHITECTURE.md` | All projects |
| `README.md` with `## Intent` | All projects |
| At least one `FEATURE-*.md` | Web, API, CLI projects |
| At least one `SCREEN-*.md` | Web projects |
| `AGENTS.md` with `## Capabilities` | API projects |
| `DATABASE.md` | Projects referencing persistence in COMPASS or ARCHITECTURE |

Check required sections inside each present file:
- COMPASS.md must contain `## Compass`, `## Constraints`, `## Success Criteria`,
  `## Acceptance Criteria`, `## Guardrails`, `## Open Questions`
- Every authored spec file must end with `## Acceptance Criteria`, `## Guardrails`,
  `## Open Questions`

Record each missing file or section as a `gap`.

### Step 4 — Stack Check

Read `stack:` field from `METADATA.md` (format: `stack: python, flask, sqlite` or equivalent).

If `stack:` is absent, empty, or `TBD` → gate: add a `stack_declaration` questionnaire item.
The stack is required for plan create to assign Rigging stack files to stories.

### Step 5 — Open Questions → Spike Candidates

Collect all `## Open Questions` section bullets from every spec file. For each entry that is not
`- None.`:

- Record as a spike candidate: `{filename}: {question text}`
- Spike candidates appear in ANALYSIS.md and are consumed by `drydock plan create` to create
  `spike` blocks in the Manifest

Group open questions by file. If any open question requires Product Owner input before the
build can start, add a `design_decisions` questionnaire item.

### Step 6 — Target Drift (if `<Target>` provided)

Compare `Provides` values from FEATURE-*.md files against the built code in `<Target>`:

- Provides entry not found in code → `gap` (spec ahead of implementation)
- Code path/command not covered by any spec file → `drift` (implementation ahead of spec)

Report gap and drift counts in ANALYSIS.md. Do not recurse into dependency directories
or test files.

---

## Outputs

### `<Target>/QuarterDeck/planning/ANALYSIS.md`

Markdown file consumed by `drydock plan create` and displayed in QuarterDeck Planning Session.

Required sections:

```markdown
# Blueprint Analysis: {ProjectName}
generated: {ISO timestamp}
blueprint: {Blueprint path}

## Project Summary
{Name, description, stack from METADATA.md. One short paragraph.}

## Project Type
type: {web | api | cli | library | pipeline | event-driven | ambiguous}
{One sentence justification citing the signals that determined the type.}

## Dependency Graph
| File | Type | Depends On | Provides | Phase Hint |
|------|------|------------|----------|------------|
{One row per spec file, topological order.}

## Coverage Assessment
| Check | Status | Notes |
|-------|--------|-------|
{One row per required file and section check. Status: pass | gap | warn}

## Gaps
{Bullet list of missing required files or sections. "None." if clean.}

## Spike Candidates
{Bullet list: [{file}] {question text}. "None." if no open questions.}

## Stack Assessment
stack: {declared value or "not declared"}
{One sentence: declared and sufficient | declared but incomplete | not declared — questionnaire required}

## Readiness Verdict
verdict: {ready | ready_with_questions | blocked}
{One sentence reason.}

## Notes
{Any additional observations: non-conformant headers, ambiguous signals, drift counts.}
```

### `<Target>/QuarterDeck/questionnaires/planning.json`

Structured questionnaire for QuarterDeck Planning Session. Emit only when genuine unknowns exist.

```json
{
  "id": "planning",
  "title": "Planning Session — Blueprint Questions",
  "purpose": "Resolve unknowns required before plan creation.",
  "questions": [
    {
      "id": "stack_declaration",
      "label": "Technology Stack",
      "prompt": "What is the technology stack for this project? (e.g., python, flask, postgresql)",
      "input": "text",
      "gate": "plan_create"
    }
  ]
}
```

Questionnaire gates:

| Gate id | Trigger | `gate` value |
|---|---|---|
| `stack_declaration` | `stack:` absent or empty | `plan_create` |
| `project_type_clarification` | Project type is `ambiguous` | `plan_create` |
| `design_decisions` | Open questions requiring PO direction | `plan_create` |

`gate: plan_create` means this answer is required before plan create should run. QuarterDeck
displays gated questions prominently. PO answers are written to `blueprint/BUILD_CONFIGURATION.md`.

If no gates trigger, emit `planning.json` with an empty `questions` array, or omit the file.

---

## Readiness Verdicts

| Verdict | Condition |
|---|---|
| `ready` | COMPASS + METADATA + ARCHITECTURE present; stack declared; zero blocking open questions |
| `ready_with_questions` | Required files present but questionnaire items exist |
| `blocked` | COMPASS.md missing; or critical spec structural errors |

---

## Exit Codes

| Code | Meaning |
|---|---|
| `0` | Analysis complete (any verdict) |
| `1` | Hard gate failed (METADATA.md missing, or filesystem error) |

A verdict of `blocked` does not produce a non-zero exit. The product owner reads ANALYSIS.md to
understand the blocker; the code does not abort.

---

## Integration Points

| Downstream | Reads |
|---|---|
| `drydock plan create` | `ANALYSIS.md` → spike candidates, project type, stack; `BUILD_CONFIGURATION.md` → questionnaire answers |
| QuarterDeck Planning Session | `ANALYSIS.md` (document item), `planning.json` (questionnaire tab) |

`ANALYSIS.md` and `planning.json` are disposable — regenerated on every `drydock analyze` run.
`BUILD_CONFIGURATION.md` is durable; answers persist across re-runs and plan cycles.

---

## Acceptance Criteria

- `drydock analyze <Blueprint>` produces `ANALYSIS.md` with all required sections
- Readiness verdict correctly reflects COMPASS presence and open questions
- Dependency graph rows are in topological order
- `planning.json` is emitted only when genuine gate conditions exist; it is valid JSON
- `drydock analyze <Blueprint> <Target>` additionally reports gap and drift counts
- Exit code 0 for any verdict; exit code 1 only for hard gate failure

## Guardrails

- Analyze must not create or modify `MANIFEST.md`
- Analyze must not modify any Blueprint spec file
- `ANALYSIS.md` and `planning.json` are written only inside `<Target>/QuarterDeck/planning/`
  and `<Target>/QuarterDeck/questionnaires/`
- No LLM call is required for graph construction, completeness checks, or questionnaire gate
  detection — those are deterministic. The LLM writes the prose sections of ANALYSIS.md
  (Project Summary, Project Type justification, Notes)

## Open Questions

- None.

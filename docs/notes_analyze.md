# NOTES: Analyze → Plan Create (Arrange Pipeline)

| Field | Value |
|-------|-------|
| Version | 2026-06-15 V5 |
| Route | analyze / plan create |
| Status | Working notes — not canonical specification |
| Description | Design notes for the SAIL Arrange pipeline: drydock analyze outputs, agent structure, and plan create interface. V5 adds a prompt-hardening + pipeline-correctness task cluster. |
| Pending spec | 9 approved items |
| Pending impl | 0 unimplemented sections |

**Scope:** the whole Arrange pipeline — `drydock analyze` → PO review (CLI or QuarterDeck) →
`drydock plan create`. The two commands have a tight interface and are designed together.
`notes_plan.md` carries `plan create` implementation detail; this file owns the shared model.

---

## Goal

Turn imported source material into an approved, executable plan without letting the LLM silently
invent requirements. Split by *who must decide*: LLM assesses and proposes; PO ratifies; only
ratified facts persist.

---

## Decisions

### What analyze reads
`2026-06-14` · `spec:applied` · `impl:implemented`

`drydock analyze` reads the **imported source files** from `blueprint/sources/` only.
Top-level typed spec template files (`ARCHITECTURE.md`, `FEATURE-*.md`, etc.) in `blueprint/`
are NOT injected — they are empty at analyze time and are outputs of `plan create`, not inputs.

Multiple imports are supported: each `drydock import` lands files in `blueprint/sources/`
alongside prior imports. `analyze` reads all `.md` files under `blueprint/sources/` recursively.

This may be extended in a future session to also include hand-written top-level spec files.

---

### Two Decomposition Passes at Different Altitudes
`2026-06-14` · `spec:applied` · `impl:implemented`

- **`analyze` (Sprint Planning Part 1):** reads imported material. Derives the story list at
  title + high-level AC level. Surfaces spikes and blockers. Output: story list + questions.
  Does NOT write typed spec files into `blueprint/`.
- **`plan create` (Sprint Planning Part 2):** reads the story list + imported spec. Decomposes
  each story into typed specification files (`FEATURE-*.md`, `SCREEN-*.md`, etc.) that the
  build can execute against.

`drydock approve` is retired. Running `plan create` is the gate; Quality=Ready is the signal.

---

### Process Flow
`2026-06-14` · `spec:recommended` · `impl:implemented`

```
import → analyze → [re-analyze loop] → plan create → build
```

| Step | Reads | Writes |
|---|---|---|
| `drydock analyze <tgt>` | Imported material + prior `BUILD_CONFIGURATION.md` | `ANALYSIS.md`, `SEA_TRIALS.md`, `SOUNDINGS.md`, `COMPASS.md` (conditional), `spike-*.json`, Captain's Chair template fill |
| PO review (CLI or QuarterDeck) | `ANALYSIS.md`, questionnaires | `BUILD_CONFIGURATION.md` (answers + feedback) |
| Re-analyze *(loop until Ready)* | Same material + updated `BUILD_CONFIGURATION.md` | Refreshed set of all analyze outputs |
| `drydock plan create <tgt>` | Story list from `ANALYSIS.md` + spec + `BUILD_CONFIGURATION.md` | Typed spec files in `blueprint/`, `BUILD_PLAN_COMPASS.md`, `MANIFEST.md` |
| `build` | `MANIFEST.md` frontier + story spec + Rigging | Execution artifacts, built code, `MANIFEST.md` state, `SCORECARD.md` |

**Re-analyze mechanics:** answering questions enables a re-run but does not trigger one.
PO runs `drydock analyze <tgt>` again explicitly. Each re-run reads all prior
`BUILD_CONFIGURATION.md` answers and must not re-ask settled questions. Human feedback
(e.g., "decompose by module, not by route") is just more context stacked on top.

---

### Agent Structure — Scrum Team Persona
`2026-06-14` · `spec:recommended` · `impl:implemented`

**Persona:** "You are a Scrum Development Team following Agile Best Practices."

The team is the whole LLM. Each role contributes their perspective independently, then the
team synthesizes:

| Role | Contribution |
|---|---|
| Developer | What stories must be built? What are their dependencies? |
| DevOps | What build pipeline, deployment target, and infrastructure is needed? |
| QA | How do we know each story is done? What are the testable criteria? |
| Architect | What is the component structure? What are the dependencies? |
| Scrum Master | What is blocking us? What is unknown? What must be resolved first? |
| PO Proxy | What is the product goal? Does the COMPASS reflect it? |

Each role surfaces their specific questions before the team synthesizes the full output.
A genuine unknown that no role can resolve → spike. Something one role needs to proceed
but can guess at → question.

---

### Blockers vs Questions
`2026-06-14` · `spec:recommended` · `impl:implemented`

- **Blocker** — the LLM genuinely cannot proceed without it. Example: no project name,
  no understanding of what the product does. Quality stays `Blocked` until cleared.
- **Question** — open item that does not stop decomposition. Surfaced in questionnaires;
  carried forward as open items in the plan. Example: preferred ORM, deployment target.

Model flags blockers. Human resolves. A spike is a valid answer — schedule the spike,
carry on. Questions do not block Quality reaching `Ready`.

**Quality signal:**

| Quality | Condition |
|---|---|
| `Blocked` | One or more blockers unresolved |
| `Questions` | No blockers; open questions remain |
| `Ready` | No blockers; decomposition complete; running plan create is the gate |

---

### Analyze Output Files
`2026-06-14` · `spec:applied` · `impl:implemented`

All written by `drydock analyze`. Read-only w.r.t. `blueprint/` spec files,
`BUILD_CONFIGURATION.md`, and `MANIFEST.md`.

#### ANALYSIS.md (target root)

The primary human-readable artifact. Format:

```
# Blueprint Analysis: <ProjectName>
generated: <date>
blueprint: <path>

## Analysis Summary

Quality: [ Ready | Questions | Blocked ]
  N blockers identified
  N questions surfaced
  N feature stories derived
  architecture stack: <declared stack or "not declared">
  N user interface screens found

## Open Questions
- [file or area] question text
...

## Story List
<Tables of story titles — no prescribed grouping, LLM organizes as appropriate>
<Tuning options offered to the PO>

## Blockers
<If any — explicit list with reason>

## Notes
<Non-conformant headers, ambiguous signals, observations>
```

Story list is titles only at this stage. Tuning options are recommendations the PO can
accept or override (e.g., decomposition approach, batch order, spike scheduling).

#### SEA_TRIALS.md (target root)

Strategic objectives at product level. Derived from decomposition + COMPASS.
3–7 rows typical.

```
| ID | Objective / Success Criterion | State | Evidence |
```

#### SOUNDINGS.md (target root)

Acceptance milestones derived from decomposition. One row per feature area (future
`FEATURE-*.md`), one row per screen (future `SCREEN-*.md`), a few rows per
database/persistence area. LLM makes up the milestones from the project shape.

```
| ID | Acceptance Criterion | State | Evidence |
```

#### COMPASS.md (target root, conditional)

Written when: (a) file does not exist, or (b) file exists but is an unpopulated template
(detected by HTML comment placeholders `<!--` or all-`- None.` sections).

Derived from all available spec material. Standard sections: Compass, Constraints,
Success Criteria, Acceptance Criteria, Guardrails, Open Questions.

#### spike-*.json (QuarterDeck/questionnaires/)

Four fixed questionnaires always emitted: `spike-intent.json`, `spike-stack.json`,
`spike-gaps-ac.json`, `spike-guardrails.json`.

Variable spikes for genuine unknowns only (not generic catch-alls).

**Technology questionnaires** must offer concrete Rigging-derived options for the detected
project type. Example — Python web server: `flask`, `django`, `fastapi`, `other`.
"Other" includes instructions pointing to the relevant Rigging document.
Rigging stack guidance files are injected into the prompt based on detected project type.
Rigging stack files are trivial to create (one-line "best practices" prompt generates them).

#### Captain's Chair (QuarterDeck/)

Analyze fills a template with variables — not a custom write. Template lives in Rigging.
Variables injected: quality signal, story count, question count, blocker count, stack,
next recommended step, project name.

Format: self-contained HTML with embedded styles (`captains_chair.html`). QuarterDeck
registers it as a `document` item with `path_html`; renders in an 80vh iframe. The LLM
fills a Rigging HTML template with variables (quality, counts, stack, next step). No external
CSS dependency — file must be self-contained.

---

### Lifecycle State Persistence
`2026-06-14` · `spec:applied` · `impl:implemented`

Lifecycle state tracked in `METADATA.md` at the **target root** via field: `drydock build state:`.

State ladder (forward-only): `init → analyzed → planned → building → built`

Each command:
1. Reads `drydock build state:` from target-root `METADATA.md`.
2. If the new state is not forward, skips the Captain's Chair overwrite.
3. On success, updates `drydock build state:` and writes the Captain's Chair.

The Captain's Chair is write-only from commands — display artifact, never read back.

---

### Work Graph Model
`2026-06-13` · `spec:recommended` · `impl:implemented`

One graph — no "spec graph vs build graph" split. ~100 nodes, plain Python, held in memory.
The LLM produces the graph at `plan create`, not `analyze`.

**Node types:**

| Node | Meaning | Green when |
|---|---|---|
| **feature** | grouping / tag for related stories; a story can have multiple parents | all child AC gates are green |
| **story** | atomic unit of work; implements one spec file | built and all its AC gates pass |
| **spike** | unknown to resolve; may gate the whole process | question answered |
| **AC** | gate node over one or more stories | all depended-on stories done and criterion verifies |

**Edge syntax — `depends-on` everywhere:**

```
STORY-042 depends-on: SPIKE-001, STORY-039
AC-042a   depends-on: STORY-042
SPIKE-001 depends-on: ROOT
```

**Frontier model:** start at nodes with no unmet `depends-on`; resolve a spike → green →
frontier pushes to newly-unblocked nodes.

**Story→spec mapping:** each story records which spec file it builds. One spec per story.

**Story cap:** ~100 stories. Over that → over-decomposed or wrong tool.

---

### MANIFEST Node Header Format
`2026-06-13` · `spec:recommended` · `impl:implemented`

`MANIFEST.md` is headers-on-file. Same markdown syntax as Typed Specification.

```markdown
## STORY-042: Add login form validation
- type: story
- spec: FEATURE-Authentication.md
- parent: FEATURE-Auth
- depends-on: SPIKE-001, STORY-039
- state: not-started

Validate email format and password length on the login form.
```

```markdown
## AC-042a: Login validation rejects invalid email
- type: ac
- depends-on: STORY-042
- state: not-started

pytest: tests/test_login.py::test_invalid_email_rejected
```

```markdown
## SPIKE-001: Choose frontend validation library
- type: spike
- depends-on: ROOT
- state: not-started

Decision: use native HTML5 constraint validation or a third-party library?
Answer persists to BUILD_CONFIGURATION.md.
```

Fields: `type` (story|spike|ac|feature|root), `spec` (story only), `parent` (multi-value ok),
`depends-on` (multi-value), `state` (not-started|in-progress|done|blocked).

---

### Source of Truth — Three Kinds of Fact
`2026-06-13` · `spec:recommended` · `impl:implemented`

| Kind | What it is | Home |
|---|---|---|
| **Intent** | what to build, constraints, success, guardrails, AC | `blueprint/` Typed Specification |
| **Decisions** | PO answers, route choice, options | `blueprint/BUILD_CONFIGURATION.md` |
| **State** | built / green / verified | `MANIFEST.md` node states / `SCORECARD.md` |

Derived artifacts (ANALYSIS.md, BUILD_PLAN_COMPASS.md, MANIFEST.md) are regenerable from
Intent + Decisions. A derived artifact holding a fact not recoverable from those is drift.

**Canonical file set:**

| Layer | Files | Owner |
|---|---|---|
| Intent (`blueprint/`) | `COMPASS.md`, `ARCHITECTURE.md`, `DATABASE.md`, `FEATURE-*.md`, `SCREEN-*.md`, `UI-GENERAL.md`, `sources/` | PO |
| Decisions (`blueprint/`) | `BUILD_CONFIGURATION.md` | PO via review |
| Planning artifacts (target root) | `ANALYSIS.md`, `SEA_TRIALS.md`, `SOUNDINGS.md`, `COMPASS.md` | `analyze` (derived) |
| Questionnaires | `QuarterDeck/questionnaires/spike-*.json` | `analyze` (derived) |
| Plan | `BUILD_PLAN_COMPASS.md`, `MANIFEST.md` | `plan create` (derived) |
| Execution | `logs/` execution artifacts | `build` (derived, transient) |
| Score | `SCORECARD.md` | `build score` |
| Lifecycle state | `METADATA.md` (`drydock build state:`) | each command |
| Captain's Chair | `QuarterDeck/captains_chair.<ext>` | each command (template fill) |

---

### Roles
`2026-06-13` · `spec:na` · `impl:implemented`

- **Product Owner** owns Intent (what to build, guardrails, AC) and Decisions (answers, route).
- **LLM (Scrum team)** owns decomposition, proposed edges, recommendations. Proposes; never ratifies.
- Questions are written in product-owner English — answerable by a non-technical PO, precise
  enough for a senior one. A genuine unknown the PO cannot answer becomes a spike.

---

### The Checklist (Embedded in Prompt)
`2026-06-13` · `spec:na` · `impl:implemented`

`analyze` runs a checklist over the spec (stack chosen? persistence defined? auth named?
success criteria present? AC present per objective? …). One unmet item → one question.
Embedded in the `analyze` prompt body, not a separate Rigging file.

---

### Console Actions = CLI Commands
`2026-06-13` · `spec:na` · `impl:implemented`

Every console action maps to a `drydock` verb; console is a thin GUI over the command surface.

- `drydock approve` — RETIRED 2026-06-14. Running `plan create` is the gate.
- QuarterDeck is optional — full pipeline must be drivable via CLI without the console.

---

## V5 Hardening — Prompt & Pipeline Correctness

Task cluster from the 2026-06-15 review of `prompts/analyze.md` against `src/drydock/analyze.py`.
Each section below is one task. `impl:unimplemented` = ready for `/apply-notes analyze`.

### TASK FIX-1: Quality gate is blockers-only
`2026-06-15` · `spec:approved` · `impl:implemented`

`prompts/analyze.md` contradicts itself: the Quality table defines `Ready` as "no open
questions" (line ~60) but then states "Questions do not block Quality reaching `Ready`"
(line ~67). The canonical model (this file, "Blockers vs Questions"; AC #7) is **blockers-only
gating**.

Fix — reword the Quality section to:
- `Blocked` = one or more blockers → pipeline halts.
- `Questions` = no blockers, open questions remain → `plan create` may proceed.
- `Ready` = no blockers, no open questions → `plan create` may proceed.
- Replace the confusing sentence with: *"Only blockers halt the pipeline. Both `Questions`
  and `Ready` permit `plan create`; open questions distinguish the two but do not gate."*

No code change; `analyze.py` already treats the signal as display-only.

### TASK FIX-2: spike-stack.json example must be valid JSON
`2026-06-15` · `spec:approved` · `impl:implemented`

`prompts/analyze.md:254` shows `"options": {detected framework options …}` — invalid JSON.
`analyze.py:_parse_output` runs `json.loads` on every `spike-*.json` block and **hard-fails the
entire analyze** on any invalid block. The template the model is shown is itself unparseable.

Fix — make the in-block example valid JSON with a concrete placeholder array, e.g.
`"options": ["flask", "django", "fastapi", "other"]`, and move the "fill from the injected
catalog for the detected type" instruction into prose **outside** the JSON. See FIX-5 for the
options contract.

### TASK FIX-3: SOUNDINGS precedence — stated AC, then synthesize
`2026-06-15` · `spec:approved` · `impl:implemented`

Prompt is internally inconsistent: line ~186 / ~361 say SOUNDINGS rows come from "actual
`## Acceptance Criteria` bullets in spec files," but analyze reads only arbitrary imported
sources, which usually have no such section, and this file's design says the LLM **synthesizes**
milestones from project shape.

Fix — replace with an explicit precedence rule: *"Derive acceptance milestones from the imported
sources and the story list. Where a source states explicit acceptance criteria, use them;
otherwise synthesize one milestone per feature area / screen / persistence area from the project
shape."* Drop the "in spec files" phrasing — there are no typed spec files at analyze time.

### TASK FIX-4: "Do not invent gaps" vs the completeness checklist
`2026-06-15` · `spec:approved` · `impl:implemented`

`prompts/analyze.md:365` ("Do not invent gaps") reads as if it conflicts with the checklist,
which is *designed* to turn each absent decision into a question.

Fix — clarify the rule: *"Do not fabricate requirements or problems the sources do not imply. A
genuinely absent decision (e.g. no auth model stated) is a real gap — surface it as a question,
not as an invented requirement."*

### TASK FIX-5: spike-stack offers catalog filenames; analyze never reads stack files
`2026-06-15` · `spec:approved` · `impl:implemented`

**Clarified scope (Ed, 2026-06-15):** analyze does **not** read the individual `Rigging/stack/*.md`
files — ever. It offers their **filenames** as the `options` in `spike-stack.json` for the PO to
pick in the questionnaire. If the imported source already names the stack, the prompt picks it;
only when the source is silent does it fall to the questionnaire. The stack files must exist —
the system relies on the list; with no list the build degrades to "create a web server" with no
specifics (works, but non-reproducible run-to-run). The injected `Rigging/stack/README.md`
catalog already enumerates the filenames and their `STACK.yaml` mappings — that is the source of
the options list.

Fix — reword prompt Inputs + Hard Rules so:
- `spike-stack.json` `options` = stack catalog filenames/slugs from the injected README catalog,
  filtered to the detected project type, plus `other`.
- State explicitly that analyze never opens the per-technology stack files; it only lists them.
- If the source names a stack, pre-select it; else leave it as an open questionnaire item.

No `analyze.py` change required — the README catalog is already injected (`analyze.py:151`).

**TBD (future session):** a `drydock` mechanism to generate stack files from a one-line
"best-practices for technology X" prompt. Out of scope here; the files exist today.

### TASK FIX-6: Checklist & project-type detection read sources only
`2026-06-15` · `spec:approved` · `impl:implemented`

**Resolved fork (Ed, 2026-06-15): source-only.** Do **not** inject `METADATA.md`. Every typed file
other than COMPASS (`ARCHITECTURE.md`, `DATABASE.md`, `FEATURE-*.md`, `SCREEN-*.md`, `UI*.md`) is an
**output** of a later step and is never an input to analyze. The current prompt wrongly tells the
model to inspect those files (checklist lines ~76–83; project-type table lines ~106–117), but they
are not injected — forcing hallucination, over-questioning, or misclassification.

Fix — reframe both:
- **Completeness checklist:** each item asks whether the fact is *stated in the imported sources
  (or prior `BUILD_CONFIGURATION.md`)* — e.g. "persistence model described in the sources,"
  "stack named in the sources," "success criteria stated" — not "DATABASE.md present" /
  "METADATA.md `stack:` field."
- **Project-type detection:** detect `web/api/cli/library/pipeline/event-driven` from the
  *content and structure of the imported sources* (described screens, routes, commands, datasets,
  topics), not from the presence of `SCREEN-*.md` / `AGENTS.md` filenames.

### TASK BUG-7: blueprint/ must hold only sources after analyze
`2026-06-15` · `spec:approved` · `impl:implemented`

**Observed defect (Ed):** after `import` + `analyze`, `blueprint/` contains the full typed-spec
scaffold (`ARCHITECTURE.md`, `DATABASE.md`, `FEATURE-Example.md`, `HOMEPAGE.md`, `IDEAS.md`,
`SCREEN-Example.md`, `UI-Component-Example.md`, `UI.md`). It should contain **only** the imported
source(s) under `blueprint/sources/`. Typed spec files are `plan create` outputs.

**Root cause (verified):** not analyze — analyze never writes to `blueprint/`. `drydock import`
seeds the scaffold: `import_markdown.py:69,74` calls `init_specification(..., update=True)`, which
copies `Rigging/spec_template/*` (ARCHITECTURE.md, DATABASE.md, FEATURE-Example.md, …, plus
COMPASS.md, METADATA.md, README.md) into `blueprint/`.

Fix — stop import from materializing typed-spec template files into `blueprint/`. After import,
`blueprint/` = `sources/` only. Confirm nothing downstream (`plan create`,
`validate_specification`, `plan_compass`) depends on the pre-seeded stubs; if it does, move that
dependency to `plan create` generation.

**Resolved placement (Ed, 2026-06-15):**
- `METADATA.md` lives at the **target root** (`targets/<TGT>/METADATA.md`) — not in `blueprint/`.
  It already exists there (lifecycle state via `set_build_state`); drop it from the blueprint
  scaffold seeding. Use the target-root file.
- `COMPASS.md` is analyze's conditional **target-root** output; not seeded into `blueprint/`.
- Net: `Rigging/spec_template/*` should not be copied into `blueprint/` at import at all.

### TASK FIX-8: analyze prints the filenames it created
`2026-06-15` · `spec:approved` · `impl:implemented`

`drydock analyze` must report the artifacts it wrote (ANALYSIS.md, SEA_TRIALS.md, SOUNDINGS.md,
COMPASS.md if written, each `spike-*.json`, captains_chair.html if written). The CLI handler has
the paths on `AnalyzeResult`; surface them as a printed list on success.

---

### TASK FIX-9: Structure analyze as ordered steps with per-step artifact contracts
`2026-06-15` · `spec:approved` · `impl:implemented`

**Direction (Ed, 2026-06-15):** analyze stays **one agent** — no multi-call orchestration. Author
its prompt as a sequential pipeline where each step states what it **consumes** and what artifact
it **emits**, in dependency order. This is normal prompt authoring, not a redesign. Only two
agents matter in this pipeline — `analyze` and `plan create` — and each is one well-structured
sequential agent.

`prompts/analyze.md` already has `## Tasks — Execute in this order` (steps 1–6) and
`## Output Format`. What is missing is the per-step input→output contract. Order:

```
sources → roles review → blockers/questions → story list
        → SOUNDINGS (from stories) → SEA_TRIALS (from stories + COMPASS)
        → quality signal (from blockers/questions) → questionnaires → COMPASS (conditional)
```

Fix — give each Tasks step an explicit "consumes / emits" line, and sequence so each artifact is
derived from the prior step's output (e.g. SOUNDINGS and SEA_TRIALS derive from the story list;
quality derives from the blocker/question counts) rather than independently re-derived. No code
change; this is prompt structure. Compatible with all FIX-1…FIX-8.

---

## Acceptance Criteria

1. No requirement silently invented: every gap/fork surfaces as a PO question.
2. Source of truth holds: Intent + Decisions regenerate every derived artifact.
3. `analyze` writes only planning artifacts. Read-only w.r.t. blueprint spec files and MANIFEST.
4. Story list is atomic-story level, with high-level AC per story.
5. Re-runs are deterministic given the same Intent + Decisions.
6. ~100-story cap respected or tool refuses with a clear message.
7. Quality=Ready means no blockers; plan create can proceed.
8. Blockers are explicitly flagged and distinct from questions.
9. Technology questionnaires offer concrete Rigging-derived options.
10. `drydock build state:` in METADATA.md advances forward-only.
11. Captain's Chair is template-filled, not custom-written.
12. COMPASS is written when absent or unpopulated (template detection by `<!--` or all-None.).
13. After `import` + `analyze`, `blueprint/` contains only `sources/`; no typed-spec stubs (BUG-7).
14. `analyze` prints the list of artifact filenames it created (FIX-8).
15. `spike-stack.json` options are stack-catalog filenames for the detected type; analyze never
    reads the per-technology stack files (FIX-5).
16. Checklist and project-type detection operate on imported source content only; no typed-spec
    file other than COMPASS is ever an analyze input (FIX-6).

---

## Guardrails

- **LLM never ratifies.** `analyze` must not write to `BUILD_CONFIGURATION.md`, `MANIFEST.md`,
  or any blueprint spec file.
- **No cross-stack batches.** A build batch must never mix component types / stacks.
- **One spec per story.** A story implements exactly one spec file. Enforced at `plan create`.
- **~100-story cap.** Over the threshold the tool refuses.
- **Forward-only state.** Commands do not overwrite Captain's Chair if state would go backwards.
- **Derived artifacts must be regenerable.** Rogue source of truth = drift.
- **QuarterDeck is optional.** Full pipeline drivable via CLI.
- **Fixed I/O locations (Ed, 2026-06-15).** Files never go to the wrong location.
  - `analyze`: reads `blueprint/sources/` → writes **target root** (`/`). The root planning
    artifacts (`ANALYSIS.md`, `SEA_TRIALS.md`, `SOUNDINGS.md`, `COMPASS.md`) are the "plan" — they
    live at root because they need review. QuarterDeck surfaces them by known filename via its
    config-file translation (already handled; do not re-engineer). `analyze` writes nothing to
    `blueprint/`.
  - `plan create`: reads **target root** (`/`) + `blueprint/sources/` → writes `blueprint/`
    (typed spec files).

---

## Open Questions

1. **Re-analyze: diff vs regenerate** — does a re-run highlight what changed from the previous
   `ANALYSIS.md`, or simply regenerate clean?
2. **Integrity failure UX** — block `MANIFEST.md` write only, surface as questions, or both?
3. **Drift propagation model** — how green/stale propagates when an upstream node changes post-build.
4. **Captain's Chair template** — structure and variables to be defined; create Rigging HTML template.

---

## Not in scope yet

Building `plan create`. Editing the canonical specification (reconcile after design stabilizes).

**Spec-diff as change ticket (future):** spec file changes between git commits = delta work items.
Drydock could detect spec diffs and surface them without a full re-analyze.

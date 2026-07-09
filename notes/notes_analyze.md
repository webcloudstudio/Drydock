# NOTES: Analyze → Plan Create (Arrange Pipeline)

| Field | Value |
|-------|-------|
| Version | 2026-06-16 V8 |
| Route | analyze / plan create |
| Status | Working notes — not canonical specification |
| Description | Design notes for the SAIL Arrange pipeline: drydock analyze outputs, agent structure, and plan create interface. V8 adds ANALYSIS.md tab-structure redesign: merge Overview+Summary, drop Blockers tab, wire Open Questions to spike files. |
| Pending spec | 16 approved items | 22 items || Pending impl | 0 unimplemented sections | 0 |
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

### Process Flow
`2026-06-14` · `spec:recommended` · `impl:implemented`

```
import → analyze → [re-analyze loop] → plan create → build
```

| Step | Reads | Writes |
|---|---|---|
| `drydock analyze <tgt>` | Imported material + prior `BUILD_CONFIGURATION.md` | `ANALYSIS.md`, `SEA_TRIALS.md`, `SOUNDINGS.md`, `COMPASS.md` (conditional), `spike-*.json`, Commanders Chair template fill |
| PO review (CLI or QuarterDeck) | `ANALYSIS.md`, questionnaires | `BUILD_CONFIGURATION.md` (answers + feedback) |
| Re-analyze *(loop until Ready)* | Same material + updated `BUILD_CONFIGURATION.md` | Refreshed set of all analyze outputs |
| `drydock plan create <tgt>` | Story list from `ANALYSIS.md` + spec + `BUILD_CONFIGURATION.md` | Typed spec files in `blueprint/`, `BUILD_COMPASS.md`, `MANIFEST.md` |
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

Derived artifacts (ANALYSIS.md, BUILD_COMPASS.md, MANIFEST.md) are regenerable from
Intent + Decisions. A derived artifact holding a fact not recoverable from those is drift.

**Canonical file set:**

| Layer | Files | Owner |
|---|---|---|
| Intent (`blueprint/`) | `COMPASS.md`, `ARCHITECTURE.md`, `DATABASE.md`, `FEATURE-*.md`, `SCREEN-*.md`, `UI-GENERAL.md`, `sources/` | PO |
| Decisions (`blueprint/`) | `BUILD_CONFIGURATION.md` | PO via review |
| Planning artifacts (target root) | `ANALYSIS.md`, `SEA_TRIALS.md`, `SOUNDINGS.md`, `COMPASS.md` | `analyze` (derived) |
| Questionnaires | `QuarterDeck/questionnaires/spike-*.json` | `analyze` (derived) |
| Plan | `BUILD_COMPASS.md`, `MANIFEST.md` | `plan create` (derived) |
| Execution | `logs/` execution artifacts | `build` (derived, transient) |
| Score | `SCORECARD.md` | `build score` |
| Lifecycle state | `METADATA.md` (`drydock build state:`) | each command |
| Commanders Chair | `QuarterDeck/commanders_chair.<ext>` | each command (template fill) |

---

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
COMPASS.md if written, each `spike-*.json`, commanders_chair.html if written). The CLI handler has
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

### TASK FIX-10: BLOCKERS.md writer must reject empty/placeholder content
`2026-06-16` · `spec:approved` · `impl:implemented`

**Implemented 2026-06-16 (structural / fail-closed):** `analyze._validate_blockers` accepts the
BLOCKERS block only when it carries ≥1 `## ` blocker entry; empty, whitespace, placeholder
(`(omitted…)`), or title-only blocks return `None`, so the writer does not create the file and
removes any stale one (`analyze.py` write block). Prompt nudged (`prompts/analyze.md`) as
defense-in-depth. Tests: `TestValidateBlockers`, `test_placeholder_blockers_block_returns_none`,
`test_titleonly_blockers_block_returns_none`, `test_placeholder_blockers_block_not_written`.

**Contract:** the *existence* of `<Target>/BLOCKERS.md` is the sole flag meaning "blocked"; it
halts `plan create` (`planning_session.py:343`). The file must therefore never exist with empty or
placeholder content. Moved here from `notes_plan.md` — `analyze` is the writer and sole owner of
this artifact; `plan create` only reads it.

**Observed defect (2026-06-16):** the analyze LLM emitted a `BLOCKERS.md` block whose body was the
placeholder `(omitted — no blockers)` instead of omitting the block. The writer trusted it —
`analyze.py:235` `blocks.get("BLOCKERS.md") or None` filters only the empty string, not placeholder
text — so a 26-byte junk file was written and falsely tripped the `plan create` precondition.

**Fix — make the deterministic writer the enforcement point, not the prompt.** In
`analyze.py:_parse_output` / the write block at `:406-413`, treat any non-genuine blocker content
as "no blockers": when the parsed BLOCKERS body is empty, a known placeholder, or lacks a
recognizable blocker structure, do not write — and `unlink` any existing file (the resolution path
already at `:412`). The prompt instruction ("emit the block only when blockers exist") stays as
advisory defense-in-depth, but correctness must not depend on model compliance.

**Open (decide before implementing):** structural enforcement — require ≥1 recognizable blocker
entry (e.g. a `## ` heading) and unlink otherwise (fail closed) — vs known-placeholder filtering
(blocklist empty / `(omitted…)` / template boilerplate). Lean: **structural / fail-closed**, so any
non-conforming model output degrades to "no blockers" rather than a false halt. Add a unit test with
a placeholder-body block asserting no file is written (and an existing file is removed).

---

## Feedback Loop & Injection Stack (2026-06-16)

Session 2026-06-16 methodology: each generative step exports a persistent, human-editable
*standing directive* file, re-injected into that step's prompt on **every** run. This is the
going-forward pattern for iterating each LLM step.

### Standing-Directive Feedback File (methodology)
`2026-06-16` · `spec:approved` · `impl:implemented`

Each generative step exports a persistent feedback file re-injected into its prompt on every run:

- created by the command if absent, default body `Enter Direction for the <Step> Run`;
- **never overwritten** by the command once it exists — the human owns it;
- top-of-file note states the instructions are used every time `<command>` runs;
- edited and submitted by the user through QuarterDeck (saved back to the same file);
- injected as a standing directive near the **top** of the prompt (after the job block, before
  prior-answer / source context) — highest-priority human steering reads first.

`analyze` → `ANALYZE_COMPASS.md`; `plan create` → `PLAN_COMPASS.md` (notes_plan.md).
Supersedes `BUILD_CONFIGURATION.md` as the free-text PO-direction channel.

### ANALYZE_COMPASS.md
`2026-06-16` · `spec:approved` · `impl:implemented`

- Location: `<target>/ANALYZE_COMPASS.md` (target root).
- QuarterDeck: shown directly under ANALYSIS in the nav; editable; submit saves to the file.
- Injected at analyze stack position 3 (after the job block, before `BLOCKERS.md`).

### BUILD_CONFIGURATION.md retired
`2026-06-16` · `spec:approved` · `impl:implemented`

Dropped — not in `docs/Drydock_Specification.md`, originated as an offhand comment, has no defined
format, writer, or value. Remove its injection from `analyze.py` and `planning_session.py`, and
scrub references in `prompts/analyze.md`, `prompts/plan_create.md`, `prompts/BLUEPRINTS_CONTRACT.md`.
Its two former roles are now carried by the feedback files (free-text direction) and answered
`spike-*.json` (structured decisions). **Supersedes** the "Decisions = BUILD_CONFIGURATION.md"
entry in §Source of Truth and the BUILD_CONFIGURATION.md references in §Process Flow.

### Rigging catalog = filename list, not README content
`2026-06-16` · `spec:approved` · `impl:implemented`

Today analyze injects the full text of `Rigging/stack/README.md` (an LLM-authored file). Replace
with a **filename list only** — names, no content, `README.md` excluded. The names are the
selectable options for `spike-stack.json`. Refines FIX-5: the option source is the directory
listing, not the README catalog.

**Resolved (Ed, 2026-06-16):** the list includes **both** `Rigging/BRA*.md` (branding) and
`Rigging/stack/*.md`, excluding `README.md`. Implemented in `analyze._rigging_catalog_names`.

### Final analyze injection stack
`2026-06-16` · `spec:approved` · `impl:implemented`

1. `prompts/analyze.md` — prompt body
2. job block (inline) — `BLUEPRINT_PATH`, `DATE`, `COMPASS_EXISTS`
3. `<target>/ANALYZE_COMPASS.md` — standing directive, if present
4. `<target>/BLOCKERS.md` — prior blocker answers, if present
5. Rigging catalog filename list — `BRA*.md` + `stack/*.md`, no `README.md`, names only
6. `<target>/blueprint/sources/*.md` — imported sources

COMPASS is **not** injected into analyze (only the `COMPASS_EXISTS` flag); analyze generates
COMPASS. The feedback file is anchored top-of-stack rather than "after the compass."

### ANALYSIS.md Tab-Structure Redesign
`2026-06-16` · `spec:approved` · `impl:implemented`

QuarterDeck tabs from `##` headings in ANALYSIS.md. Four decisions agreed in session:

1. **Remove `## Analysis Summary` heading.** The content before the first `##` heading renders as
   the implicit first tab (Overview). Adding `## Analysis Summary` creates a duplicate Overview/Summary
   split. Dropping the heading merges them into one Overview tab.

2. **Drop `## Blockers` section from ANALYSIS.md.** `BLOCKERS.md` is the artifact; its existence is
   the pipeline signal. Blockers must not also appear as a tab inside ANALYSIS.md.

3. **`## Open Questions` references spike files.** Each open-question item cites which
   `spike-*.json` questionnaire covers it (e.g. "see `spike-stack.json`"), so the tab makes the
   spike connection visible to the PO.

4. **Final ANALYSIS.md tab structure:** `Overview / Story List / Open Questions / Notes` — driven
   entirely by `##` headings. All changes are prompt-only edits to `prompts/analyze.md`.

---

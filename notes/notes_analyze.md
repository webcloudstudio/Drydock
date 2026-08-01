# NOTES: Analyze → Plan Create (Arrange Pipeline)

| Field | Value |
|-------|-------|
| Version | 2026-07-18 V9 |
| Route | analyze / plan create |
| Status | Working notes — not canonical specification |
| Description | Design notes for the SAIL Arrange pipeline: drydock analyze outputs, agent structure, and plan create interface. V8 adds ANALYSIS.md tab-structure redesign: merge Overview+Summary, drop Blockers tab, wire Open Questions to spike files. |
| Pending spec | 0 approved items |
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

## Feedback Loop & Injection Stack (2026-06-16)

Session 2026-06-16 methodology: each generative step exports a persistent, human-editable
*standing directive* file, re-injected into that step's prompt on **every** run. This is the
going-forward pattern for iterating each LLM step.

### Rigging Manifest Injection
`2026-07-18` · `spec:na` · `impl:implemented`

`Rigging/MANIFEST.md` is the compact catalog injected into `drydock analyze`. It replaces the
filename-only Rigging catalog. It is created from the current stack README and active Rigging
inventory; every selectable `Rigging/stack/*.md` source file (excluding README and compact
derivatives) and every `Rigging/BRA*.md` file has an entry. Each entry supplies filename,
category, concise purpose, and prerequisites where known. Unknown prerequisites remain visibly
unset for Commander review; the manifest does not invent them.

Analyze receives the manifest but never opens each component rule file. The Commander owns later
manifest corrections.

### Analyze Prompt: One Semantic Contract and One Output Protocol
`2026-07-18` · `spec:na` · `impl:implemented`

Tighten `prompts/analyze.md` without turning it into documentation. Each behavioral rule has one
authoritative home: semantic analysis policy, ordered task flow, output schemas, or hard protocol
rules. Remove contradictions and stale terms: `TYPED_SPEC` becomes imported-source context; a
questionnaire never resolves a blocker; source-named technology informs a recommendation but does
not itself confirm a stack; strategic goals and criteria are derived only where stated or directly
implied.

The output protocol names the exact order: `ANALYSIS.md`, `SEA_TRIALS.md`, conditional
`BLOCKERS.md`, conditional `COMPASS.md`, conditional identity questionnaire, mandatory stack
questionnaire, then conditional gap and other discovery questionnaires in stable lexical order.

---

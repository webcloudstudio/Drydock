# NOTES: Analyze → Plan Create (Arrange Pipeline)

| Field | Value |
|-------|-------|
| Version | 2026-06-13 V1 |
| Route | analyze / plan create |
| Status | Working notes — not canonical specification |
| Description | Design notes for the SAIL Arrange decision pipeline: analyze, User Review, and plan create. Authoritative for the shared model until reconciled with the canonical spec. |

**Scope:** the whole Arrange pipeline — `drydock analyze` → QuarterDeck User Review / approval →
`drydock plan create`. The two commands have a tight interface and are designed together. Companion:
`notes_plan.md` carries `plan create` implementation detail; this file owns the shared model and is
authoritative for it.

---

## 1. Rationale

We turn imported source material into an approved, executable plan without letting the LLM silently
invent requirements. The process splits by *who must decide*:

- **`analyze` (top-level, read-only).** Spec Kit *specify + clarify* job: assess shape and
  coverage, surface questions, recommend feature-decomposition routes / build categories. Does not
  decompose to stories.
- **User Review (the gate).** PO reads the analysis, answers questions, picks a route, approves.
  Possibly loops (re-analyze → re-review) before approving. Nothing downstream runs until approval.
- **`plan create` (decomposition).** Spec Kit *plan + tasks* job. Runs only after approval. LLM
  (agile team) decomposes the approved shape into the work graph, applies scrum guardrails, validates
  integrity, orders and batches the work, writes the Manifest.

`analyze` is cheap and question-generating. `plan create` is expensive and runs only against a
de-risked, approved shape. Splitting earns both steps their cost.

Core invariants: **the spec is the source of truth** (everything else is derived/regenerable);
**the LLM proposes, the PO ratifies** (inference is never trusted until approved); **state is the
graph** (green nodes track what is built and verified).

---

## 2. Process flow

```
import → analyze → USER REVIEW (answer + pick route) → [re-analyze loop] → approve → plan create → build
```

| Step | Reads | Writes |
|---|---|---|
| `drydock analyze <tgt>` | `blueprint/` specs + prompt (incl. embedded checklist) | `QuarterDeck/planning/ANALYSIS.md`, `QuarterDeck/questionnaires/planning.json` |
| Console review | `ANALYSIS.md`, `planning.json` | `blueprint/BUILD_CONFIGURATION.md` (answers + options) |
| Re-analyze *(optional)* | prior `BUILD_CONFIGURATION.md` + specs | refreshed `ANALYSIS.md`, `planning.json` |
| `drydock approve <tgt>` | `BUILD_CONFIGURATION.md` | root gate node in `MANIFEST.md` → green |
| `drydock plan create <tgt>` *(requires approval)* | `blueprint/` specs + `BUILD_CONFIGURATION.md` + `ANALYSIS.md` | `BUILD_PLAN_COMPASS.md`, `MANIFEST.md` |
| `build` assemble + execute | `MANIFEST.md` frontier + story's mapped spec + Rigging | execution artifact (`logs/`), built code, evidence; updates `MANIFEST.md` state + `SCORECARD.md` |

**Re-analyze mechanics:** completing the questionnaire *enables* a re-run but does not trigger one.
The PO must explicitly run `drydock analyze <tgt>` again. The re-run reads prior
`BUILD_CONFIGURATION.md` answers and should not re-ask settled questions.

---

## 3. Shared model

### 3.1 The work graph

One graph — no "spec graph vs build graph" split. Headers-on-file to determine order, ~100 nodes,
held in memory, plain Python over it. Not a real graph DB; do not over-engineer it. The LLM is the
agile team and produces the graph at `plan create`, not `analyze`.

**Node types:**

| Node | Meaning | Green when |
|---|---|---|
| **feature** | grouping / tag for related stories; a story can have multiple parents | all child AC gates are green |
| **story** | atomic unit of work; implements one spec file | built and all its AC gates pass |
| **spike** | unknown to resolve (research / decision); may gate the whole process | question answered (questionnaire or explicit answer) |
| **AC** | gate node over one or more stories | all depended-on stories done and criterion verifies |
| **ROOT** | the approval node; the start/root gate the whole graph depends on | `drydock approve` called; acts as kill-switch if toggled back |

**Edge syntax — `depends-on` everywhere (single syntax, decided):**

The node that cannot proceed declares what it depends on. Direction: dependent → prerequisite.

```
STORY-042 depends-on: SPIKE-001, STORY-039
AC-042a   depends-on: STORY-042
SPIKE-001 depends-on: ROOT
```

No `gates` direction. Every node type uses `depends-on` for consistency.

**Multiple parents — allowed (decided):** features are containers/tags, not exclusive owners. A story
normally has one parent but may have more. Consistency of the header format trumps "unused in this
case." Parser always handles multi-value `parent`.

**Frontier model:** start at nodes with no unmet `depends-on`; resolve a spike → green → frontier
pushes to newly-unblocked nodes. Objective = all nodes green.

**Story→spec mapping:** each story node records which spec file it builds. One spec per story. This
is the lever that makes the no-cross-stack guardrail free: one spec per story + typed spec files
(`FEATURE-*` vs `SCREEN-*`) ⇒ grouping by spec-file-type cannot mix stacks.

**Story cap:** ~100 stories. Over that ⇒ over-decomposed or wrong tool.

**Open questions block their story:** a story with any unanswered spike in its `depends-on` chain
cannot enter the frontier.

### 3.2 MANIFEST node header format

`MANIFEST.md` is headers-on-file. Same markdown syntax family as the Typed Specification — one
product, one syntax.

```markdown
## STORY-042: Add login form validation

- type: story
- spec: FEATURE-Authentication.md
- parent: FEATURE-Auth
- depends-on: SPIKE-001, STORY-039
- state: not-started

Validate email format and password length on the login form. Surface inline errors on submit.
Do not call the backend until client-side passes.
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

```markdown
## FEATURE-Auth: Authentication feature

- type: feature
- depends-on: ROOT
- state: not-started
```

```markdown
## ROOT: Plan approved

- type: root
- state: green
```

Fields: `type` (story|spike|ac|feature|root), `spec` (story only), `parent` (multi-value ok),
`depends-on` (multi-value), `state` (not-started|in-progress|done|blocked). Body = work
description / spike question / AC criterion / empty for feature.

### 3.3 Source of truth — three kinds of fact

| Kind | What it is | Home |
|---|---|---|
| **Intent** | what to build, constraints, success, guardrails, AC | `blueprint/` Typed Specification |
| **Decisions** | PO answers, route choice, options (`USE_COMPASS`, etc.) | `blueprint/BUILD_CONFIGURATION.md` |
| **State** | built / green / verified | `MANIFEST.md` node states / `SCORECARD.md` |

`ANALYSIS.md`, `BUILD_PLAN_COMPASS.md`, `MANIFEST.md` are derived from Intent + Decisions and must
be regenerable. A derived artifact that holds a fact unrecoverable from Intent + Decisions has become
a rogue source of truth = drift.

**Canonical file set:**

| Layer | Files | Owner |
|---|---|---|
| Intent (`blueprint/`) | `COMPASS.md`, `ARCHITECTURE.md`, `DATABASE.md`, `FEATURE-*.md`, `SCREEN-*.md`, `UI-GENERAL.md`, `sources/` | PO |
| Decisions (`blueprint/`) | `BUILD_CONFIGURATION.md` | PO via console review |
| Planning Session (`QuarterDeck/`) | `planning/ANALYSIS.md`, `questionnaires/planning.json` | `analyze` (derived, disposable) |
| Plan | `BUILD_PLAN_COMPASS.md` (ordering), `MANIFEST.md` (graph + states + story→spec) | `plan create` (derived) |
| Execution (`logs/`) | execution artifact (assembled build bundle per batch) | `build` (derived, transient) |
| Score | `SCORECARD.md` | `build score` |

**Assemble is a `build`-time phase:** `plan create` emits the plan (graph + states + mapping);
`build` assembles the execution artifact fresh each run — no long-term memory. The plan never carries
assembled context.

### 3.4 Roles

- **Product Owner** owns Intent (what to build, guardrails, AC) and Decisions (answers, route, options).
- **LLM (agile team)** owns decomposition, proposed edges, and recommendations. Proposes; never ratifies.
- Questions are written in product-owner English — answerable by a non-technical PO, precise enough
  for a senior one. A genuine unknown the PO cannot answer becomes a spike.

### 3.5 Inference & ratify-then-persist

LLM inferences (edges, groupings, routes) are proposals, never facts:

1. LLM proposes. Low-confidence proposals → questionnaire items (reuses "unknown → question").
2. Proposal sits in a derived artifact as a view, not authoritative.
3. User Review ratifies (PO approves/corrects). The review persists, not the command.
4. Ratified facts persist durably (Decisions → `BUILD_CONFIGURATION.md`; approved graph → `MANIFEST.md`).

Persistence is mandatory for determinism and so the integrity check has a stable graph to validate.

### 3.6 The checklist

`analyze` runs a checklist over the spec (stack chosen? persistence defined? auth named? success
criteria present? AC present per objective? …). One unmet item → one question. The checklist is
**embedded in the `analyze` prompt body** — not a separate Rigging file. When methodology changes,
edit the prompt.

### 3.7 Console actions = CLI commands

Every console "do it via a button" action maps to a `drydock` verb; the console is a thin GUI over
the command surface. Key commands in this pipeline:

- **`drydock approve <tgt>`** — writes root gate node green; authorizes `plan create` and `build`.
  The only way to approve; ordinary review controls never approve a plan.
- **Setup-compass** — TBD verb; the PO reorders `BUILD_PLAN_COMPASS.md` entries. No command
  needed yet (edit the file directly); verb assigned when implemented.

---

## 4. `drydock analyze` — command spec

**Goal.** Top-level, read-only analysis of imported Blueprint material: assess shape and coverage,
surface questions, recommend feature-decomposition routes and build categories, recommend one-shot
vs decompose. Does not decompose to stories. Does not write the Manifest.
(Spec Kit equivalent: `/specify` + `/clarify`.)

**CLI.** `drydock analyze <Target>`

**Inputs.** `blueprint/` Typed Specification (and `sources/`); embedded checklist in the prompt.
Secondary: built application when code exists (drift/coverage mode).

**Outputs.**
- `QuarterDeck/planning/ANALYSIS.md` — shape, summary, recommended routes, one-shot-vs-decompose
  call, rendered with action buttons (Approve / Answer Questions).
- `QuarterDeck/questionnaires/planning.json` — questions (one per unmet checklist item + each
  option/route choice, including `USE_COMPASS`).

**Side effects.** Writes only the two Planning Session artifacts. Read-only w.r.t. Blueprint,
`BUILD_CONFIGURATION.md`, `MANIFEST.md`.

**Acceptance criteria.**
- Produces `ANALYSIS.md` + `planning.json` for a valid Target; changes nothing else.
- Every checklist gap and genuine decision fork is a plain-English question.
- States at least one recommended route and a one-shot-vs-decompose recommendation.
- Re-runnable safely; idempotent on the two artifacts.
- Does not decompose to stories; does not write the Manifest.

**Methodology.** LLM-assisted command pattern: load prompt (with embedded checklist) → assemble
deterministically → execute → module post-processes and writes files. Judgment/prose from the model;
file writes from the module.

**Out of scope.** Story/spike/AC decomposition, edges, ordering, batching, integrity enforcement,
Manifest — all `plan create`.

---

## 5. User Review — the gate

**What it renders.** `ANALYSIS.md` in a template (summary on top, action buttons top-right) and the
`planning.json` questionnaire.

**What the PO does.** Reads; answers questions; picks a feature-decomposition route; optionally
re-runs analyze; approves via `drydock approve <tgt>`.

**What it writes.** `blueprint/BUILD_CONFIGURATION.md` (answers + options). Approval written by
`drydock approve`, not by the review UI.

**AC.** No decomposition before approval. Answers persist and survive re-runs. Approval is explicit.

---

## 6. `drydock plan create` — summary (detail in `notes_plan.md`)

**Goal.** Full agile decomposition into the work graph after approval. Spec Kit `/plan` + `/tasks`.

**CLI.** `drydock plan create <Target>`

**Inputs.** `blueprint/` specs + `BUILD_CONFIGURATION.md` + `ANALYSIS.md`.

**Outputs.** `BUILD_PLAN_COMPASS.md` + `MANIFEST.md` (the work graph seeded with ROOT green).

**Core responsibilities.** Decompose → guardrails (story-too-big, atomic, every story AC-gated) →
integrity check (acyclic, reachable, gated, within cap) → order + batch (topo sort + no-cross-stack
+ grouping strategy) → emit.

---

## 7. Acceptance Criteria

1. No requirement silently invented: every gap/fork surfaces as a PO question.
2. Source of truth holds: Intent + Decisions regenerate every derived artifact.
3. `analyze` is read-only; `plan create` runs only after `drydock approve`.
4. Emitted graph is atomic-story, fully AC-gated, acyclic, reachable.
5. Re-runs are deterministic given the same Intent + Decisions.
6. ~100-story cap respected or tool refuses with a clear message.
7. `analyze` produces `ANALYSIS.md` + `planning.json` for any valid Target; changes nothing else.
8. Every checklist gap and genuine decision fork appears as a plain-English question.
9. `drydock approve <tgt>` is the only path to ROOT green; no review control bypasses it.

---

## 8. Guardrails

- **LLM never ratifies.** Inference is a proposal; only PO ratification (via console review or
  `drydock approve`) makes it durable. Analyze commands must not write to `BUILD_CONFIGURATION.md`,
  `MANIFEST.md`, or any Blueprint file.
- **No cross-stack batches.** A build batch must never mix component types / stacks (e.g. a feature
  file and a screen file in the same batch). V1 evidence: cross-stack batches produced materially
  worse results.
- **One spec per story.** A story implements exactly one spec file. Enforced at `plan create`.
- **Open questions block their story.** A story with an unresolved spike in its `depends-on` chain
  cannot enter the frontier.
- **~100-story cap.** Over the threshold the tool refuses and tells the PO they are over-decomposing
  or using the wrong tool.
- **Story-too-big → split.** A story exceeding the atomicity threshold (`.env`) must be split before
  the Manifest is emitted.
- **`analyze` is read-only.** It never writes to Blueprint, `BUILD_CONFIGURATION.md`, or `MANIFEST.md`.
- **`plan create` precondition: ROOT green.** Must exit with error if `drydock approve` has not run.
- **Derived artifacts must be regenerable.** If a derived artifact holds a fact not recoverable from
  Intent + Decisions, it has become rogue source of truth = drift. Do not let this happen.

---

## 9. Open Questions

1. **Re-analyze: diff vs regenerate** — does a re-run highlight what changed from the previous
   `ANALYSIS.md`, or simply regenerate clean?
2. **Integrity failure UX** — block `MANIFEST.md` write only, surface as QuarterDeck questions, or
   both?
3. **Drift propagation model** — how green/stale propagates when an upstream node changes post-build.
4. **Setup-compass verb** — command name TBD; no command needed until implemented.

---

## 10. Not in scope yet

Building the commands. Editing the canonical specification (reconcile after design stabilizes).

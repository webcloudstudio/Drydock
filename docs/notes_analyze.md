# NOTES: Analyze → Plan Create (Arrange Pipeline)

| Field | Value |
|-------|-------|
| Version | 2026-06-14 V2 |
| Route | analyze / plan create |
| Status | Working notes — not canonical specification |
| Description | Design notes for the SAIL Arrange decision pipeline: analyze, User Review, and plan create. Authoritative for the shared model until reconciled with the canonical spec. |
| Pending spec | 7 recommended items |
| Pending impl | 4 unimplemented sections |

**Scope:** the whole Arrange pipeline — `drydock analyze` → QuarterDeck User Review / approval →
`drydock plan create`. The two commands have a tight interface and are designed together.
`notes_plan.md` carries `plan create` implementation detail; this file owns the shared model.

## Goal

Turn imported source material into an approved, executable plan without letting the LLM silently
invent requirements. Split by *who must decide*: LLM assesses and proposes; PO ratifies; only
ratified facts persist.

## Decisions

### Rationale — Analyze/Approve/Plan Split
`2026-06-13` · `spec:recommended` · `impl:implemented`

- **`analyze` (read-only):** assess shape and coverage, surface questions, recommend routes. Does
  not decompose to stories.
- **User Review (the gate):** PO reads the analysis, answers questions, picks a route, approves.
  Nothing downstream runs until approval. May loop (re-analyze → re-review) before approving.
- **`plan create` (decomposition):** runs only after approval. LLM decomposes the approved shape
  into the work graph, applies scrum guardrails, validates integrity, orders and batches, writes
  the Manifest.

`analyze` is cheap and question-generating. `plan create` is expensive and runs only against a
de-risked, approved shape.

Core invariants: **the spec is the source of truth**; **the LLM proposes, the PO ratifies**;
**state is the graph**.

### Process Flow
`2026-06-13` · `spec:recommended` · `impl:implemented`

```
import → analyze → USER REVIEW → [re-analyze loop] → approve → plan create → build
```

| Step | Reads | Writes |
|---|---|---|
| `drydock analyze <tgt>` | `blueprint/` specs + prompt (incl. embedded checklist) | `ANALYSIS.md` (target root), spike questionnaires in `QuarterDeck/questionnaires/` |
| Console review | `ANALYSIS.md`, questionnaires | `blueprint/BUILD_CONFIGURATION.md` (answers + options) |
| Re-analyze *(optional)* | prior `BUILD_CONFIGURATION.md` + specs | refreshed `ANALYSIS.md`, questionnaires |
| `drydock approve <tgt>` | `BUILD_CONFIGURATION.md` | root gate node in `MANIFEST.md` → green |
| `drydock plan create <tgt>` | `blueprint/` specs + `BUILD_CONFIGURATION.md` + `ANALYSIS.md` | `BUILD_PLAN_COMPASS.md`, `MANIFEST.md` |
| `build` assemble + execute | `MANIFEST.md` frontier + story's mapped spec + Rigging | execution artifacts (`logs/`), built code, evidence; updates `MANIFEST.md` state + `SCORECARD.md` |

**Re-analyze mechanics:** completing the questionnaire *enables* a re-run but does not trigger one.
The PO must explicitly run `drydock analyze <tgt>` again. The re-run reads prior
`BUILD_CONFIGURATION.md` answers and must not re-ask settled questions.

### Work Graph Model
`2026-06-13` · `spec:recommended` · `impl:unimplemented`

One graph — no "spec graph vs build graph" split. Headers-on-file, ~100 nodes, held in memory,
plain Python. Not a real graph DB; do not over-engineer it. The LLM produces the graph at
`plan create`, not `analyze`.

**Node types:**

| Node | Meaning | Green when |
|---|---|---|
| **feature** | grouping / tag for related stories; a story can have multiple parents | all child AC gates are green |
| **story** | atomic unit of work; implements one spec file | built and all its AC gates pass |
| **spike** | unknown to resolve; may gate the whole process | question answered |
| **AC** | gate node over one or more stories | all depended-on stories done and criterion verifies |
| **ROOT** | approval node; the start/root gate the whole graph depends on | `drydock approve` called |

**Edge syntax — `depends-on` everywhere (decided):**

```
STORY-042 depends-on: SPIKE-001, STORY-039
AC-042a   depends-on: STORY-042
SPIKE-001 depends-on: ROOT
```

No `gates` direction. Every node type uses `depends-on` for consistency.

**Multiple parents:** features are containers/tags, not exclusive owners. Parser always handles
multi-value `parent`.

**Frontier model:** start at nodes with no unmet `depends-on`; resolve a spike → green → frontier
pushes to newly-unblocked nodes. Objective = all nodes green.

**Story→spec mapping:** each story records which spec file it builds. One spec per story. This
makes the no-cross-stack guardrail free: `spec-file-type` cannot mix stacks within one story.

**Story cap:** ~100 stories. Over that ⇒ over-decomposed or wrong tool.

### MANIFEST Node Header Format
`2026-06-13` · `spec:recommended` · `impl:unimplemented`

`MANIFEST.md` is headers-on-file. Same markdown syntax family as the Typed Specification.

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

```markdown
## ROOT: Plan approved

- type: root
- state: green
```

Fields: `type` (story|spike|ac|feature|root), `spec` (story only), `parent` (multi-value ok),
`depends-on` (multi-value), `state` (not-started|in-progress|done|blocked).

### Source of Truth — Three Kinds of Fact
`2026-06-13` · `spec:recommended` · `impl:implemented`

| Kind | What it is | Home |
|---|---|---|
| **Intent** | what to build, constraints, success, guardrails, AC | `blueprint/` Typed Specification |
| **Decisions** | PO answers, route choice, options (`USE_COMPASS`, etc.) | `blueprint/BUILD_CONFIGURATION.md` |
| **State** | built / green / verified | `MANIFEST.md` node states / `SCORECARD.md` |

`ANALYSIS.md`, `BUILD_PLAN_COMPASS.md`, `MANIFEST.md` are derived from Intent + Decisions and must
be regenerable. A derived artifact holding a fact not recoverable from Intent + Decisions has become
a rogue source of truth = drift.

**Canonical file set:**

| Layer | Files | Owner |
|---|---|---|
| Intent (`blueprint/`) | `COMPASS.md`, `ARCHITECTURE.md`, `DATABASE.md`, `FEATURE-*.md`, `SCREEN-*.md`, `UI-GENERAL.md`, `sources/` | PO |
| Decisions (`blueprint/`) | `BUILD_CONFIGURATION.md` | PO via console review |
| Planning artifacts | `ANALYSIS.md` (target root), `QuarterDeck/questionnaires/spike-*.json` | `analyze` (derived, disposable) |
| Plan | `BUILD_PLAN_COMPASS.md` (ordering), `MANIFEST.md` (graph + states + story→spec) | `plan create` (derived) |
| Execution (`logs/`) | execution artifact per batch | `build` (derived, transient) |
| Score | `SCORECARD.md` | `build score` |

### Ratify-then-Persist
`2026-06-13` · `spec:recommended` · `impl:implemented`

LLM inferences (edges, groupings, routes) are proposals, never facts:

1. LLM proposes. Low-confidence proposals → questionnaire items.
2. Proposal sits in a derived artifact as a view, not authoritative.
3. User Review ratifies (PO approves/corrects). The review persists, not the command.
4. Ratified facts persist durably (Decisions → `BUILD_CONFIGURATION.md`; approved graph → `MANIFEST.md`).

Persistence is mandatory for determinism and so the integrity check has a stable graph to validate.

### Roles
`2026-06-13` · `spec:na` · `impl:implemented`

- **Product Owner** owns Intent (what to build, guardrails, AC) and Decisions (answers, route, options).
- **LLM (agile team)** owns decomposition, proposed edges, and recommendations. Proposes; never ratifies.
- Questions are written in product-owner English — answerable by a non-technical PO, precise enough
  for a senior one. A genuine unknown the PO cannot answer becomes a spike.

### The Checklist (Embedded in Prompt)
`2026-06-13` · `spec:na` · `impl:implemented`

`analyze` runs a checklist over the spec (stack chosen? persistence defined? auth named? success
criteria present? AC present per objective? …). One unmet item → one question. Embedded in the
`analyze` prompt body, not a separate Rigging file. When methodology changes, edit the prompt.

### Console Actions = CLI Commands
`2026-06-13` · `spec:na` · `impl:unimplemented`

Every console "do it via a button" action maps to a `drydock` verb; the console is a thin GUI over
the command surface.

- **`drydock approve <tgt>`** — writes root gate node green; authorizes `plan create` and `build`.
  The only way to approve; ordinary review controls never approve a plan.
- **Setup-compass** — TBD verb; the PO reorders `BUILD_PLAN_COMPASS.md` entries. No command needed
  yet (edit the file directly); verb assigned when implemented.

### Analyze Command Spec
`2026-06-13` · `spec:recommended` · `impl:implemented`

**CLI:** `drydock analyze <Target>`

**Inputs:** `blueprint/` Typed Specification (and `sources/`); embedded checklist in the prompt.
Secondary: built application when code exists (drift/coverage mode).

**Outputs:**
- `ANALYSIS.md` (target root) — shape, summary, recommended routes, one-shot-vs-decompose call.
- Spike questionnaires in `QuarterDeck/questionnaires/spike-*.json` (see quarterdeck notes for
  full output contract).

**Side effects:** writes only Planning Session artifacts. Read-only w.r.t. Blueprint,
`BUILD_CONFIGURATION.md`, `MANIFEST.md`.

**Methodology:** LLM-assisted command pattern: load prompt (with embedded checklist) → assemble
deterministically → execute → module post-processes and writes files.

### User Review — The Gate
`2026-06-13` · `spec:recommended` · `impl:unimplemented`

**What it renders:** `ANALYSIS.md` in QuarterDeck + spike questionnaires.

**What the PO does:** reads; answers questions; picks a feature-decomposition route; optionally
re-runs analyze; approves via `drydock approve <tgt>`.

**What it writes:** `blueprint/BUILD_CONFIGURATION.md` (answers + options). Approval written by
`drydock approve`, not by the review UI.

**AC:** no decomposition before approval. Answers persist and survive re-runs. Approval is explicit.

## Acceptance Criteria

1. No requirement silently invented: every gap/fork surfaces as a PO question.
2. Source of truth holds: Intent + Decisions regenerate every derived artifact.
3. `analyze` is read-only; `plan create` runs only after `drydock approve`.
4. Emitted graph is atomic-story, fully AC-gated, acyclic, reachable.
5. Re-runs are deterministic given the same Intent + Decisions.
6. ~100-story cap respected or tool refuses with a clear message.
7. `analyze` produces `ANALYSIS.md` + questionnaires for any valid Target; changes nothing else.
8. Every checklist gap and genuine decision fork appears as a plain-English question.
9. `drydock approve <tgt>` is the only path to ROOT green.

## Guardrails

- **LLM never ratifies.** `analyze` must not write to `BUILD_CONFIGURATION.md`, `MANIFEST.md`, or
  any Blueprint file.
- **No cross-stack batches.** A build batch must never mix component types / stacks.
- **One spec per story.** A story implements exactly one spec file. Enforced at `plan create`.
- **Open questions block their story.** A story with an unresolved spike in its `depends-on` chain
  cannot enter the frontier.
- **~100-story cap.** Over the threshold the tool refuses.
- **Story-too-big → split.** Split before the Manifest is emitted.
- **`analyze` is read-only.** Never writes to Blueprint, `BUILD_CONFIGURATION.md`, or `MANIFEST.md`.
- **`plan create` precondition: ROOT green.** Must exit with error if `drydock approve` has not run.
- **Derived artifacts must be regenerable.** If a derived artifact holds a fact not recoverable
  from Intent + Decisions, it is rogue source of truth = drift.

## Open Questions

1. **Re-analyze: diff vs regenerate** — does a re-run highlight what changed from the previous
   `ANALYSIS.md`, or simply regenerate clean?
2. **Integrity failure UX** — block `MANIFEST.md` write only, surface as QuarterDeck questions, or both?
3. **Drift propagation model** — how green/stale propagates when an upstream node changes post-build.
4. **Setup-compass verb** — command name TBD; no command needed until implemented.

## Not in scope yet

Building `plan create`. Editing the canonical specification (reconcile after design stabilizes).

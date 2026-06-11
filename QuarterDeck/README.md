# Console

**A communication surface between LLM agents and the people they work for.** When an agent
needs a human in the loop — to answer a question, review code, sign off on a product increment,
watch a demo, or track work on a board — it writes a small artifact and the Console renders it
as a clean, navigable web page. People read, answer, and decide; the agent reads their answers
back. The Console is how an agent runs questionnaires, code reviews, product reviews, demos, and
other agile ceremonies with a human, without anyone hand-building a UI.

The artifacts are **easy to customize**: each is a plain file (markdown, a small JSON
questionnaire, or a tickets list) named in one `console.json`. The agent — or a person — writes
those files; the Console only navigates and renders them. It owns no project state and makes no
decisions of its own, which keeps it safe for an agent to drive.

**Stack:** Python / FastAPI / Uvicorn / SQLite. Single process, no auth, no external services,
no build step. What it persists is small: questionnaire answers, edited document source, and item
recategorizations (section moves).

### What it renders

| Artifact | Page type | Used for |
|----------|-----------|----------|
| Markdown document | `markdown` | Code reviews, product reviews, demo write-ups, intent/spec pages, release notes |
| Editable document | `editable_markdown` | Source-of-truth docs the human and agent co-edit (intent, spec) |
| Questionnaire | `questionnaire` | Asking the human structured questions; answers are saved and read back |
| Work board | `kanban` | Sprint/backlog tracking from a tickets file: features own stories, with priority/urgency/blocked flags and acceptance-criteria checklists |
| Hyperlink | `link` | Pointing at an external or local resource |
| Sign-off | `"review": true` on any item | Approve · revise · reject a demo, review, or doc, with feedback recorded |

Every artifact is filed under a **section** (Core Docs, Pages, Plan, Action Items, Archive) that
doubles as its state, so the agent can move an item from "needs action" to "done" by changing one
field.

> **This is an intended, primary channel for agent↔User dialog.** The developer built the Console
> so that an agent has a deliberate place to talk to the User — to ask a question, request a
> review, surface a decision, or show a demo. **When you (an agent) want a dialog with the User,
> use this interface** rather than burying the exchange in chat, a commit message, or a log. Put the
> artifact in the Console and let the User respond there.

---

## Quick Start

```bash
bash Console/start.sh             # http://127.0.0.1:8080
PORT=9000 bash Console/start.sh   # custom port
```

The repository ships a self-contained test fixture: the committed `console.json` points
at `sample/`, so `bash Console/start.sh` works immediately with no setup. Click through
the **Pages**, **Plan**, **Action Items**, and **Archive** sections to see all four page types.

`Console/console.json` must exist. The Console never generates it. If it is missing, the
UI shows a configuration page and the API returns HTTP 503. `console.json.sample` is the
documented template to copy from.

---

## Files & Storage

`console.json` is only the **index**. Each item names a `path`; the artifact's data lives in
that separate file. Markdown items are `.md`; questionnaires and tickets are `.json`.

```text
Console/
├── console.json            Index: items → paths (the contract)
├── console.json.sample     Documented template to copy from
├── app.py                  The viewer (FastAPI)
├── start.sh                Launch script
├── sample/                 The shipped test fixture's artifacts:
│   ├── intent.md           editable_markdown item data (Edit/Save in the UI)
│   ├── guide.md            markdown item data
│   ├── review.md           markdown item with "review": true (sign-off bar)
│   ├── tickets.json        kanban data + acceptance criteria (read-only to the Console)
│   ├── kickoff.json        questionnaire data (questions + answers)
│   └── archived-note.md    markdown item data
└── data/
    └── console_state.sqlite  Saved questionnaire state (auto-created)
```

All `path` values are relative to `Console/` and must resolve **inside the project** (the
directory that contains `Console/`), so siblings such as `../evidence/STEP_1.md` are reachable
while paths outside the project are rejected; a `link` `href` may be any URL.

**What the Console writes.** Three things. (1) **Questionnaire answers** — saved both back
into the questionnaire `.json` file (each question gains an `answer`, plus `state: "done"` and
`answered_at`, so the next agent reads questions and answers as one plain file) and into the
`document_state` table in `data/console_state.sqlite` (keyed `questionnaire.<id>`). (2)
**`editable_markdown` source** — Save writes the edited markdown straight back to its `.md`. (3)
**Item recategorization** — the section-change control writes an item's new `section` to
`console.json`; it changes only the `section`, never the item's type or content, and Core Docs are
pinned (see *Recategorize* below). Everything else is read-only: tickets and plain markdown are
edited by the framework, not the Console.

---

## The Contract

The Console reads exactly one file, `Console/console.json`, with three blocks:
`console`, `project`, and `items`. All `path` / `href` values are relative to `Console/`
and must resolve **inside the project** (the directory containing `Console/`) for file reads,
so siblings such as `../evidence/` are reachable (a `link` may point at any URL).

### `console` — application identity

```json
"console": {
  "name": "Project Console",
  "default_item": "guide",
  "state_db": "data/console_state.sqlite"
}
```

| Field | Required | Description |
|-------|----------|-------------|
| `name` | Yes | Display name in the header |
| `default_item` | No | Item `id` to open on load; defaults to the first item |
| `state_db` | No | SQLite path relative to `Console/`; defaults to `data/console_state.sqlite` |

### `project` — informational identity

```json
"project": { "id": "PROJECT", "name": "Project Name", "description": "One line." }
```

`description` is shown in the header. All fields are informational.

### `items` — a flat list of things

Each **item** is one thing and one navigation entry (1:1 — no containers, no nesting). An
item carries **navigation properties** (`label`, `section`) and **type properties** (`type`
plus the fields that type needs).

```json
"items": [
  { "id": "guide",   "label": "Guide",  "section": "pages", "type": "markdown", "path": "sample/guide.md" },
  { "id": "board",   "label": "Kanban", "section": "plan",  "type": "kanban",   "path": "sample/tickets.json" },
  { "id": "kickoff", "label": "Kickoff Questionnaire", "section": "actions", "type": "questionnaire", "path": "sample/kickoff.json" }
]
```

| Item field | Required | Description |
|------------|----------|-------------|
| `id` | Yes | Unique item id (stable; used in routes and `state_key`s) |
| `label` | Yes | Sidebar button text |
| `section` | Yes | Which sidebar section (= the item's state) it belongs to |
| `type` | Yes | `markdown` \| `editable_markdown` \| `jsonl` \| `kanban` \| `questionnaire` \| `link` \| `command_status` |
| `order` | No | Sort order within its section (default config order) |
| `review` | No | `true` adds an Approve · Revise · Reject sign-off bar to the item (see Decisions below) |
| `path` | For file types | File path relative to `Console/` |
| `href` | For `link` | URL, or local path relative to `Console/` |

**Sections are derived** from the `section` values — there is no `sections` block. The
sidebar shows every section at once; a section *is* the lifecycle state of the items in it.
Re-state an item by changing its `section`. The canonical sections (rendered first, with
coloured dots):

| `id` | Label | Dot | Meaning |
|------|-------|-----|---------|
| `core` | Core Docs | teal | Always-visible source-of-truth docs (often `editable_markdown`) |
| `pages` | Pages | blue | Reference material — read it |
| `plan` | Plan | amber | Planned work — the Kanban board |
| `actions` | Action Items | red | Needs action — questionnaires |
| `archive` | Archive | grey | Retired / done — entries render greyed |

Any other `section` id works too: it is title-cased, gets a grey dot, and is appended after
the canonical ones.

### Per-type schema

Each type declares its required fields. Validation is **lenient**: if an item's `type` is
unknown or a required field is missing, that item's pane shows a clear error and the rest of
the Console keeps working.

| type | required (beyond `id`/`label`/`section`/`type`) |
|------|--------------------------------------------------|
| `markdown` | `path` |
| `editable_markdown` | `path` |
| `jsonl` | `path` |
| `kanban` | `path` (→ a tickets JSON file) |
| `questionnaire` | `path` |
| `link` | `href` |
| `command_status` | — |

Each type maps to one Python renderer in the `TYPES` registry in `app.py`. **Adding a type
= one `TypeDef` (required fields + render function).**

---

## Page Types

### `markdown`

Renders a markdown file as HTML (tables, fenced code, sane lists supported). This is the
default — if an artifact only needs to be read, make it markdown.

### `editable_markdown`

Same rendering as `markdown`, plus an **Edit** button. Edit toggles the rendered view to a
textarea holding the raw markdown; **Save** writes the edited source straight back to the
file (`POST /api/document/{item_id}/source`, write-confined to `Console/`). Use it for
source-of-truth docs a human and the agent co-edit — typically an intent/spec doc in the
**Core Docs** section. It is the only type besides `questionnaire` that writes a file; plain
`markdown`, `jsonl`, `kanban`, and `link` stay read-only.

### `jsonl`

Renders an append-only JSONL file as a read-only table. Configure `fields` with dotted field names,
`sort` with a dotted field name, `sort_direction` as `asc` or `desc`, and optional exact-match
`filters`. Each malformed line is reported without preventing valid records from rendering. A
missing file renders as an empty view, allowing a console to expose a log before its first event.

### `command_status`

Derives a read-only command-readiness report from configured Core Docs using Python only. It finds
exactly one Markdown table under a `Command Acceptance` heading, treats that table as the
authoritative status source, recomputes state totals, and reports deterministic structural
inconsistencies. Other Core Docs contribute command-reference coverage context only. The renderer
does not inspect non-Core items, source code, tests, or plan artifacts, and writes no derived file.

### `kanban`

Renders a **tickets JSON file** (`path`) as a read-only work board. Tickets are written by
the framework (or a person); the Console never edits them. Columns are fixed by status —
**Backlog · In Progress · Review · Done** — and each ticket sits in its status column.
Clicking a card opens a ticket detail panel below the board.

Tickets file format (`tickets.json`):

```json
{
  "tickets": [
    { "id": "FEAT-1", "title": "Importer", "kind": "feature", "status": "in_progress",
      "priority": true, "urgency": false, "body": "Pull and normalize prices." },
    { "id": "STORY-3", "title": "Retry policy", "parent": "FEAT-1", "status": "review",
      "priority": false, "urgency": true, "blocked": true,
      "blocked_reason": "How should retry/backoff behave?", "links": ["kickoff"],
      "body": "Decide retry/backoff and close." }
  ]
}
```

| Ticket field | Required | Meaning |
|--------------|----------|---------|
| `id` | Yes | Ticket id (`FEAT-1`, `STORY-3`), unique in the file |
| `title` | Yes | Card title |
| `status` | No | Column: `backlog` \| `in_progress` \| `review` \| `done` (default `backlog`) |
| `parent` | No | Ticket id of the owning feature — shown as a `↳ parent` chip; the parent's detail lists its children |
| `kind` | No | `feature` \| `story` \| `task` (display hint) |
| `priority` | No | bool → `PRIORITY` badge |
| `urgency` | No | bool → `URGENT` badge |
| `blocked` | No | bool → red `BLOCKED` badge (stays in its status column; `blocked_reason` on hover) |
| `blocked_reason` | No | The question/blocker, shown in the ticket detail |
| `links` | No | List of console item `id`s the ticket relates to (e.g. the questionnaire that answers a blocker); rendered as openable links in the detail |
| `ac` | No | List of acceptance-criteria strings — rendered as a verify/fail/reset checklist in the detail, with an `AC verified/total` chip on the card |
| `body` | No | Markdown detail shown in the ticket panel |

A ticket missing `id` or `title` is skipped, with a count shown under the board (lenient).
`parent` expresses feature→story ownership; `blocked` is a flag, never a column. The `ac`
list is the assertions; the human's verify/fail marks are stored in SQLite (the ticket file
stays read-only) — see Decisions & Acceptance below.

### `questionnaire`

Renders a questionnaire JSON file as a form and **stores answers**. On save, answers are
written to SQLite *and* back into the questionnaire JSON file, so the next build step can
read questions and answers together as one plain input file.

Questionnaire file format:

```json
{
  "id": "kickoff",
  "title": "Kickoff Questionnaire",
  "state": "open",
  "purpose": "Why this questionnaire exists.",
  "questions": [
    {
      "id": "field_id",
      "label": "Short Label",
      "prompt": "Full question text?",
      "input": "text | textarea | select | multiselect | number | slider",
      "options": ["only for select / multiselect"],
      "min": 0,
      "max": 10
    }
  ]
}
```

| `input` | Control |
|---------|---------|
| `text` | single-line text |
| `textarea` | multi-line text |
| `select` | single choice |
| `multiselect` | multiple choice (answers comma-joined) |
| `number` | numeric input |
| `slider` | range with `min` / `max` |

After save: `state` becomes `"done"`, `answered_at` is stamped, and each answered
question gains an `"answer"` field.

### `link`

Renders a hyperlink. An external `http(s)` URL opens directly; a local path is served
through `/raw/{item_id}`.

---

## Decisions & Acceptance

Two lightweight controls turn the Console from "render and ask" into a sign-off surface. Both
store the human's input in SQLite, so the underlying files (markdown, tickets) stay read-only.

### Decision / sign-off (`"review": true`)

Add `"review": true` to **any** item. A coloured bar appears at the bottom of its page —
**Approve** (green) · **Revise** (amber) · **Reject** (red) — with an optional feedback field.
Recording a decision shows a coloured banner with the outcome and feedback, and can be changed.
Use it to sign off a demo, a code/product-review write-up, an editable spec, or a board.

Stored under state key `decision.<item_id>` as `{ state: approved|revise|rejected,
payload: { feedback } }`.

### Acceptance criteria (ticket `ac`)

Give a ticket an `ac` list of assertion strings. The ticket detail renders them as a checklist
with **Verify** (✓ green) · **Fail** (✗ red) · **Reset** (○) per line, and the card shows an
`AC verified/total` chip (green when all pass, red if any fail). The assertions live in the
read-only `tickets.json`; the verify/fail marks are stored under `ac.<item_id>.<ticket_id>`.

### Recategorize (section move)

Every item's page carries a **section** dropdown. Choosing a different section moves the item —
it writes the new `section` to `console.json` and nothing else; the item's type and file content
are untouched. The rule is **pin core, free elsewhere**: items in **Core Docs** are source-of-truth
and pinned (the page shows *Pinned* instead of a control), while every other item moves freely
among **Pages · Plan · Action Items · Archive**. `core` is never a target — items are not promoted
into the pinned zone. This is a view-level write; on a *generated* console (see below) a move is not
authoritative state and regeneration may reset it.

---

## API Reference

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/` | Console UI (HTML) |
| `GET` | `/health` | Health check → `{"status":"ok"}` (503 if config missing) |
| `GET` | `/api/config` | Full loaded config |
| `GET` | `/api/items` | Flat item list |
| `GET` | `/api/document/{item_id}` | Rendered HTML + type for an item |
| `POST` | `/api/document/{item_id}/source` | Write raw source back (editable_markdown items only) |
| `POST` | `/api/item/{item_id}/section` | Recategorize an item — write its new `section` to `console.json` (pinned-core rule enforced) |
| `GET` | `/api/ticket/{item_id}/{ticket_id}` | Rendered ticket detail (kanban items) |
| `GET` | `/raw/{item_id}` | Raw file download |
| `GET` | `/api/state/{key}` | Stored state record by key (`questionnaire.*`, `decision.*`, `ac.*`) |
| `POST` | `/api/state/{key}` | Upsert state; `questionnaire.*` keys also write back to the JSON file |

That is the entire surface. **File writes** are limited to three things — questionnaire answers,
`editable_markdown` source, and an item's `section` (recategorization, in `console.json`).
Everything else the human does (decisions, AC verify/fail) is **state** in SQLite via `/api/state`,
keyed `decision.<item>` and `ac.<item>.<ticket>`; the tickets file and plain markdown are never
modified by the Console.

---

## Use Cases

How an LLM agent uses the Console to communicate with a human. This section is living — we
add a row each time we use the tool on a real problem and learn how it should work.

| Communication | Artifact(s) | Section | Status |
|---------------|-------------|---------|--------|
| **Doc review** — drop N documents for the human to read | `markdown` per doc | Pages / Core | ✅ works today |
| **Core reference** — keep the intent/spec where it is always visible, co-edited by human + agent | `editable_markdown` | Core Docs | ✅ shown **and edited** in place |
| **Open Questions** — ask the human to resolve unknowns | `questionnaire` | Action Items | ✅ works (answers captured + read back) |
| **Code / product review** — present a change or increment for sign-off | `markdown` + `"review": true` | Pages | ✅ approve/revise/reject recorded |
| **Demo** — write up what was built; sign off on it | `markdown` (+ `link`) + `"review": true` | Pages | ✅ works |
| **Acceptance criteria** — verify a story meets its AC | ticket `ac` checklist | Plan | ✅ verify/fail per AC, rolled up on the card |
| **Evidence** — show results/output backing a claim | `markdown` (+ `link`) | Pages / Archive | ✅ works |
| **Sprint / backlog** — track features and stories | `kanban` → `tickets.json` | Plan | ✅ works (priority/urgency/blocked, parent ownership) |
| **Unblock a ticket** — tie a blocked story to the question that frees it | ticket `blocked` + `links:[questionnaire]` | Plan ↔ Action Items | ✅ works |

### Conventions emerging from use
- One **section per intent**: `core` for must-always-see docs, `pages` for review material,
  `actions` for anything needing a human response, `archive` for closed items.
- A human response is only captured when it goes through a **questionnaire** — markdown,
  links, and tickets are read-only to the human.
- The agent communicates a state change by **moving an item's `section`** (e.g. an answered
  question from `actions` → `archive`).

### Known gaps (the near-term roadmap for agent communication)
1. **Spike** — a first-class investigation artifact (question → options → evidence → recorded
   decision), instead of faking it with a questionnaire.
2. **Retrospective** — needs a structured artifact and renderer contract.
3. **Metrics / burndown** — needs a chart or table type (start as mermaid/markdown).

*(Done: edit-in-place via `editable_markdown`; JSONL decision-log views; decision sign-off via
`"review": true`; acceptance criteria via ticket `ac`.)*

---

## Extending the Console

The Console is built to grow. A page type is one `TypeDef` (required fields + a Python
renderer) in the `TYPES` registry in `app.py`; adding a type touches nothing else. New page
types and new agile ceremonies are expected — the current set is a starting point, not a
ceiling.

**If you (an agent) need a way to communicate with the User that the existing types do not
support, do not work around it.** Do not bury the exchange in chat or invent an ad-hoc file the
Console cannot render. Instead, **raise it as a suggestion for improvement and discuss it**:
describe the communication need, who must respond, and the artifact that would serve it. The
intent is that this interface keeps absorbing new ways for an agent and the User to talk —
proposing one is the correct move, not an exception.

---

## Authoring Guidance (for Prototyper agents)

- Default to `markdown`. Use a `questionnaire` only when an answer must be captured.
- File each item into the section that matches its state: `pages` (reference), `plan`
  (the Kanban), `actions` (questionnaires awaiting input), `archive` (done/retired).
  Re-state an item by changing its `section`.
- For the board, write a `tickets.json` with `id`/`title`/`status` per ticket; use `parent`
  so a feature owns its stories, `priority`/`urgency`/`blocked` flags for triage, and `links`
  to point a blocked ticket at the questionnaire that answers it.
- Keep `id`s stable; navigation, `state_key`s, and ticket `parent`/`links` assume durable ids.
- The Console renders whatever you create — it will not invent content or config. To roll
  out a Console for a project, author a `console.json` (copy `console.json.sample`) and the
  files it references. Nothing auto-generates them.

---

## Two ways to populate the Console

**Authored (any project).** Write `console.json` by hand (copy `console.json.sample`) and point
its items at your own files. This is the path for any project — a CLI tool, a service, a doc
set. The contract above is everything you need; nothing else is required.

**Generated (Prototyper oneshot).** For spec-driven `oneshot.sh` builds, `bin/console_sync.py`
renders the build's `AGILE_PLAN.md` into the Console's model automatically: it writes
`Console/tickets.json` (the sprint board — spikes and stories as tickets, acceptance criteria
folded on, status mapped to columns) and a generated `Console/console.json` (Core Docs spec
snapshot, the board, and one reviewable Pages item per evidence file under `../evidence/`).
`oneshot.sh` calls it after each run, so the board tracks live state. For these projects the
config is generated — do not hand-edit `console.json`/`tickets.json`; change the plan instead.
Sign-off is two-way: when you Approve/Revise/Reject an evidence page, `console_sync apply` writes
that decision back into `AGILE_PLAN.md` on the next `oneshot.sh` run.

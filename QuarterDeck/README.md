# QuarterDeck

**A communication surface between LLM agents and the people they work for.** When an agent
needs a human in the loop — to answer a question, review a plan, sign off on a product increment,
watch a demo, or track work on a board — it writes a small artifact and the QuarterDeck renders it
as a clean, navigable web page. People read, answer, and decide; the agent reads their answers
back. The QuarterDeck is how an agent runs questionnaires, reviews, demos, and other agile
ceremonies with a human, without anyone hand-building a UI.

The artifacts are **easy to customize**: each is a plain file (markdown, a small JSON
questionnaire, a JSONL log, or `MANIFEST.md`) named in one `console.yaml`. The agent — or a
person — writes those files; the QuarterDeck only navigates and renders them. It owns no project
state and makes no decisions of its own, which keeps it safe for an agent to drive.

**Stack:** Python / FastAPI / Uvicorn / PyYAML / Markdown. Single process, no auth, no database,
no external services, no build step. Everything it persists is written back into the plain files
it renders: questionnaire answers, edited document source, and constrained `MANIFEST.md`
structure edits.

### What it renders

| Artifact | Page type | Used for |
|----------|-----------|----------|
| Markdown document | `markdown` | Analyses, reviews, demo write-ups, release notes; `tabs: true` splits `##` headings into tabs |
| Editable document | `editable_markdown` | Steering docs the human and agent co-edit (`COMPASS.md`, `BLOCKERS.md`, per-command compasses) |
| Multi-format document | `document` | One artifact with `path_md` / `path_html` / `path_pdf` variants; best available format wins |
| Questionnaire | `questionnaire` | Asking the human structured questions; answers are saved into the JSON and read back |
| JSONL log | `jsonl` | Append-only records as a read-only, badge-colored table |
| Work board | `kanban` | `MANIFEST.md` features/stories/spikes as a read-only four-column board |
| Build Compass | `compass` | The live `MANIFEST.md` work graph: grouped, costed, state-badged, and editable (reorder / regroup / rename / split) |
| Refit watch | `refit` | Blueprints added or touched since they were applied to the Manifest — the prompt to run `drydock refit` |
| Acceptance status | `command_status` | Readiness rollup derived from the Core Doc Soundings table |
| Hyperlink | `link` | Pointing at an external URL or a local file |

Every artifact is filed under a **section**. The canonical target sections spell the **SAIL**
methodology down the sidebar — **Setup · Analyze · Implement · refit(L)** — and each flies its
matching ICS signal flag. Any section ids may be declared. `BLOCKERS.md` conventionally lives in
a `blockers` section, which renders first and in red.

> **This is an intended, primary channel for agent↔User dialog.** The developer built the
> QuarterDeck so that an agent has a deliberate place to talk to the User — to ask a question,
> request a review, surface a decision, or show a demo. **When you (an agent) want a dialog with
> the User, use this interface** rather than burying the exchange in chat, a commit message, or a
> log. Put the artifact in the QuarterDeck and let the User respond there.

---

## Quick Start

```bash
drydock run quarterdeck                       # current directory, http://127.0.0.1:8080
drydock run quarterdeck <Target>              # named target under configured target_directory
drydock run quarterdeck <Target> --port 9000  # custom port
```

The runtime is served from the installed package (or this source tree); only the Target's console
*state* — `console.yaml`, questionnaires, and the files items point at — lives under
`<Target>/QuarterDeck/`. `QUARTERDECK_DIR` and `QUARTERDECK_PROJECT_ROOT` point the runtime at
that state.

`QuarterDeck/console.yaml` must exist. The QuarterDeck never generates it. If it is missing, the
UI shows a configuration page and the API returns HTTP 503. `console.yaml.sample` is the
documented template to copy from.

When the workspace holds several targets, a **target switcher** appears at the top of the sidebar:
one button per target that has a `QuarterDeck/console.yaml`, each flying the International Code of
Signals flag for the target's initial. Switching sets a cookie and reloads the console against
that target.

---

## Files & Storage

`console.yaml` is only the **index**. Each item names a `path`; the artifact's data lives in that
separate file. Markdown items are `.md`; questionnaires are `.json`; the board and the compass
read `MANIFEST.md`.

All `path` values are relative to `QuarterDeck/` and must resolve **inside the project** (the
directory that contains `QuarterDeck/`), so siblings such as `../ANALYSIS.md` or
`../evidence/STEP_1.md` are reachable while paths outside the project are rejected; a `link`
`href` may be any URL.

**What the QuarterDeck writes.** Three things, all back into plain files:

1. **Questionnaire answers** — each answered question gains an `answer` field; the file's `state`
   becomes `answered` when every question is answered (else it stays `open`) and `answered_at` is
   stamped. The next agent run reads questions and answers as one plain input file.
2. **`editable_markdown` source** — Save writes the edited markdown straight back to its `.md`
   (creating the file if absent).
3. **Compass structure edits** — reorder / regroup / rename / split operations rewrite
   `MANIFEST.md` through the same constrained editor the CLI uses; a move that would break the
   build topology is rejected.

Everything else is read-only. `console.yaml` is never rewritten at runtime.

**Item visibility follows file existence.** An item whose backing file does not exist is hidden
from the sidebar and reappears automatically when the file is created — no `console.yaml` rewrite
needed. This is how `BLOCKERS.md` surfaces only when blockers exist.

---

## The Contract

The QuarterDeck reads exactly one file, `QuarterDeck/console.yaml`, with these blocks:
`console`, `project`, `sections`, `items`, and optional `sources` / `overrides`.

### `console` — application identity

```yaml
console:
  name: Project QuarterDeck
  default_item: commanders_chair
  app_help_file_location: docs/index.html
```

| Field | Required | Description |
|-------|----------|-------------|
| `name` | Yes | FastAPI application title |
| `default_item` | No | Item `id` to open on first load; defaults to the first item. The console remembers the last-viewed item per target |
| `app_help_file_location` | No | HTML file, relative to the workspace root, served at `/help`; enables the header's Drydock button |

### `project` — informational identity

```yaml
project:
  id: PROJECT
  name: Project Name
  description: "One line."
  copyright: "Copyright (c) 2026 ..."
```

`copyright` overrides the Drydock copyright notice shown in the bar under the header. The page
title and sidebar headings use the **target directory name**, not `project.name`.

### `sections` — sidebar taxonomy

```yaml
sections:
  - { id: setup,     label: "Setup",     dot: "#64748b", pinned: true }
  - { id: analyze,   label: "Analysis",  dot: "#0d9488", pinned: true }
  - { id: implement, label: "Implement", dot: "#2CB67D" }
  - { id: refit,     label: "Refit",     dot: "#d97706" }
```

| Section field | Description |
|---------------|-------------|
| `id` | Unique section id — items reference this |
| `label` | Sidebar heading text |
| `dot` | CSS colour for the section dot (non-phase sections) |
| `collapsed` / `pinned` | Accepted and carried through the nav model; reserved — no current rendering effect |

Sections render in the order listed. An item whose `section` id is not in the list gets a
title-cased label and grey dot, appended after the configured sections. The SAIL sections
(`setup`, `analyze`, `implement`, `refit`) render as phase headers (target name + phase) and stay
visible even when empty; `blockers` renders first, in red. Known sections fly a fixed ICS signal
flag — the SAIL sections fly **S · A · I · L**, and Blockers flies **U** (*you are running into
danger*). The Fleet — the workspace's target switcher popout — musters under **Setup**.

### `items` — a flat list of things

Each **item** is one thing and one navigation entry (1:1 — no containers, no nesting). An item
carries **navigation properties** (`label`, `section`) and **type properties** (`type` plus the
fields that type needs).

```yaml
items:
  - { id: analysis, label: "Analysis", section: analyze, type: markdown, tabs: true, path: ../ANALYSIS.md }
  - { id: board,    label: "Kanban Board", section: plan, type: kanban, path: ../MANIFEST.md }
  - { id: build_compass, label: "Build Compass", section: build, type: compass, path: ../MANIFEST.md }
```

| Item field | Required | Description |
|------------|----------|-------------|
| `id` | Yes | Unique item id (stable; used in routes) |
| `label` | Yes | Sidebar button text |
| `section` | Yes | Section id from the `sections` block |
| `type` | Yes | One of the types below |
| `order` | No | Sort order within its section (default config order) |
| `help_text` | No | Short explanation rendered as a note at the top of the page |
| `tabs` | No | `markdown` only: `true` splits `##` headings into clickable tabs |
| `path` | For file types | File path relative to `QuarterDeck/` |
| `path_md` / `path_html` / `path_pdf` | For `document` | Format variants; html > pdf > md priority |
| `href` | For `link` | URL, or local path relative to `QuarterDeck/` |

Additional fields (for example `prompt_text`) are ignored by the QuarterDeck and may be used by
the framework that assembles prompts from the same files.

### `sources` — auto-discovered items

```yaml
sources:
  - glob: "QuarterDeck/questionnaires/discovery-*.json"
    section: analyze
    type: questionnaire
    order: 99

overrides:
  - match: "docs/SPECIAL.md"
    label: "The Special Doc"
    tabs: true
```

Each rule globs files under the **project root** and generates one item per file: the id is a
slug of the filename, the label a title-cased form of it, and the rule's remaining fields become
item defaults (`section` defaults to `project_pages`, `type` to `markdown`). Explicit `items:`
take priority — a generated item is dropped when its id or its path is already covered.
`overrides` adjust individual source-generated items by project-root-relative path before they
are added.

### Per-type schema

Each type declares its required fields. Validation is **lenient**: if an item's `type` is unknown
or a required field is missing, that item's pane shows a clear error and the rest of the console
keeps working.

| type | required (beyond `id`/`label`/`section`/`type`) |
|------|--------------------------------------------------|
| `markdown` | `path` |
| `editable_markdown` | `path` |
| `document` | — (`path_md` / `path_html` / `path_pdf` optional) |
| `jsonl` | `path` |
| `kanban` | `path` (rendered from `MANIFEST.md`) |
| `questionnaire` | `path` |
| `link` | `href` |
| `command_status` | — |
| `compass` | `path` (`MANIFEST.md`) |
| `refit` | — (reads `blueprint/` and `MANIFEST.md`) |

Each type maps to one Python renderer in the `TYPES` registry in `app.py`. **Adding a type = one
`TypeDef` (required fields + render function).**

---

## Page Types

### `markdown`

Renders a markdown file as HTML (tables, fenced code, sane lists). YAML frontmatter and a leading
`# H1` are stripped — the page header supplies the title. `tabs: true` renders each `##` section
as a clickable tab. This is the default — if an artifact only needs to be read, make it markdown.

### `editable_markdown`

Same rendering as `markdown`, plus an **Edit** button in the page header. Edit toggles the
rendered view to a textarea holding the raw markdown; **Save** writes the edited source straight
back to the file (`POST /api/document/{item_id}/source`, write-confined to the project). If the
file does not exist yet, the page offers to create it on first save. Use it for steering docs a
human and the agent co-edit — `COMPASS.md`, `BLOCKERS.md`, per-command compass files.

### `document`

Renders one artifact that exists in multiple formats. Priority: `path_html` (rendered
full-pane in an iframe) > `path_pdf` (open button) > `path_md` (inline). Missing variants are
skipped silently.

### `jsonl`

Renders an append-only JSONL file as a read-only table. Configure `fields` with dotted field
names, `sort` / `sort_direction`, optional exact-match `filters`, `date_fields` (trimmed to the
date), and `badge_field` + `badge_colors` for a colored leading badge (the sample config uses this
for `event_type`). Each malformed line is reported without hiding valid records. A missing file
renders as an empty view.

### `kanban`

Renders `MANIFEST.md` as a **read-only** work board. Features, stories, and spikes become cards;
acceptance (`ac`) blocks are folded into their parent. Columns are fixed — **Backlog · In
Progress · Review · Done** — and a block's `state` selects its column: `pending` → Backlog,
`implemented` and `closed/failed` → Review, `closed/verified` → Done. Clicking a card opens a
detail panel with parent/children navigation. The board is a projection; work tracking truth
stays in `MANIFEST.md`.

### `compass`

The **Build Compass**: the live `MANIFEST.md` work graph. Feature groups carry story-point
rollups and savings; each story/spike shows its assembled prompt cost with a collapsible per-file
stack breakdown and its Definition of Done folded beneath. The header rolls up groups, stories,
and per-lifecycle counts (built / ready to build / blocked / failed) plus total SP, and names the
stories buildable now. Constrained editing — reorder groups, regroup stories, rename, split a group
into one group per story, split a single story into its own new group, normalize order — rewrites
`MANIFEST.md` through the same editor the CLI uses; a move that would break the build topology is
rejected. A failed story opens its Definition of Done and shows the finding.

### `refit`

The **refit watch**. Compares every `blueprint/*.md` against the `applied_specs` hashes recorded
in `MANIFEST.md` and lists blueprints that are **new** (never applied) or **changed** (touched
since their content was applied). When anything is adrift, the page says so and tells the
Commander to run `drydock refit` to include those files in the Manifest; when everything is
applied, it reports steady as she goes. Read-only — the QuarterDeck reports, `drydock refit`
does the work.

### `command_status`

Derives a read-only acceptance-readiness report from the configured Core Docs (items in the
`core` section) using Python only. It requires exactly one Markdown table under a `Soundings`
heading with the columns `ID | Acceptance Criterion | State | Evidence`, recomputes state totals
(`DONE` / `IMPLEMENTED` / `STUBBED` / `NOT STARTED`), and reports deterministic structural
inconsistencies (duplicate ids, unknown states, `DONE` rows without evidence). It writes no
derived file.

### `questionnaire`

Renders a questionnaire JSON file as a form and **writes answers back into the same file**, so
the next agent run reads questions and answers together as one plain input. Answers save
automatically when a field loses focus; unanswered questions are simply skipped.

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
      "input": "text | textarea | select | multiselect | checkbox_grid | number | slider",
      "options": ["only for select / multiselect / checkbox_grid"],
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
| `checkbox_grid` | checkbox grid over `options` (answers comma-joined) |
| `number` | numeric input |
| `slider` | range with `min` / `max` |

After save: each answered question gains an `answer` field, `answered_at` is stamped, and
`state` becomes `"answered"` once every question has an answer (otherwise it stays `"open"`).
An open questionnaire shows a red ✗ in the sidebar; an answered one shows a green ✓ — these
status icons appear **only** on questionnaires, so an unanswered item is always visible at a
glance.

### `link`

Renders a hyperlink. An external `http(s)` URL opens directly in a new tab; a local path is
served through `/raw/{item_id}`.

---

## API Reference

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/` | QuarterDeck UI (HTML) |
| `GET` | `/health` | Health check → `{"status":"ok"}` (503 if config missing) |
| `GET` | `/help` | Serves the configured `app_help_file_location` HTML |
| `GET` | `/logo.png` | Drydock logo asset for the header |
| `GET` | `/api/config` | Full loaded config (sources expanded) |
| `GET` | `/api/items` | Flat item list |
| `GET` | `/api/nav` | Rendered sidebar HTML (re-fetched after saves) |
| `GET` | `/api/document/{item_id}` | Rendered HTML + type for an item |
| `POST` | `/api/document/{item_id}/source` | Write raw source back (`editable_markdown` only) |
| `POST` | `/api/compass/{item_id}/move` | Constrained reorder/regroup of a Build Compass step or group |
| `POST` | `/api/compass/{item_id}/edit` | Structure edit of the Build Compass: rename, add group, split group, normalize |
| `GET` | `/api/ticket/{item_id}/{ticket_id}` | Rendered ticket detail (kanban items) |
| `GET` | `/raw/{item_id}` | Raw file download (`?variant=html\|pdf` for `document` items) |
| `POST` | `/api/state/questionnaire.{id}` | Save questionnaire answers (written back into the JSON file) |
| `GET` | `/switch-target/{target}` | Switch the active workspace target (sets cookie, redirects) |

That is the entire surface. **File writes** are limited to three things — questionnaire answers,
`editable_markdown` source, and constrained `MANIFEST.md` compass edits. `console.yaml` is never
rewritten at runtime.

---

## Use Cases

How an LLM agent uses the QuarterDeck to communicate with a human. This section is living — we
add a row each time we use the tool on a real problem and learn how it should work.

| Communication | Artifact(s) | Section | Status |
|---------------|-------------|---------|--------|
| **Doc review** — drop N documents for the human to read | `markdown` per doc | any | ✅ works today |
| **Steering** — keep intent/guardrail docs visible and co-edited by human + agent | `editable_markdown` (`COMPASS.md` etc.) | Analyze | ✅ shown **and edited** in place |
| **Blockers** — surface questions that gate planning | `editable_markdown` → `BLOCKERS.md` | Blockers | ✅ appears only while the file exists |
| **Open questions** — ask the human to resolve unknowns | `questionnaire` | Analyze | ✅ answers captured + read back on the next run |
| **Sprint / backlog** — track features and stories | `kanban` ← `MANIFEST.md` | Plan | ✅ read-only projection of plan state |
| **Story planning** — group, cost, and order the build | `compass` ← `MANIFEST.md` | Build | ✅ constrained editing writes back to the manifest |
| **Evidence / demo** — show results backing a claim | `markdown` / `document` (+ `link`) | any | ✅ works |
| **Acceptance readiness** — roll up the Soundings checklist | `command_status` | Docs | ✅ derived, read-only |

### Known gaps (the near-term roadmap for agent communication)

1. **Review sign-off** — a first-class Approve · Revise · Reject decision bar whose outcome is
   written back to `MANIFEST.md` by the same decision writer the CLI uses.
2. **Spike** — a first-class investigation artifact (question → options → evidence → recorded
   decision), instead of faking it with a questionnaire.
3. **Retrospective** — needs a structured artifact and renderer contract.
4. **Metrics / burndown** — needs a chart or table type (start as mermaid/markdown).

---

## Extending the QuarterDeck

The QuarterDeck is built to grow. A page type is one `TypeDef` (required fields + a Python
renderer) in the `TYPES` registry in `app.py`; adding a type touches nothing else. New page types
and new agile ceremonies are expected — the current set is a starting point, not a ceiling.

**If you (an agent) need a way to communicate with the User that the existing types do not
support, do not work around it.** Do not bury the exchange in chat or invent an ad-hoc file the
QuarterDeck cannot render. Instead, **raise it as a suggestion for improvement and discuss it**:
describe the communication need, who must respond, and the artifact that would serve it. The
intent is that this interface keeps absorbing new ways for an agent and the User to talk —
proposing one is the correct move, not an exception.

---

## Authoring Guidance (for Drydock agents)

- Default to `markdown`. Use a `questionnaire` only when an answer must be captured.
- File each item into the section that matches its phase: `analyze` for analysis outputs and
  steering docs, `plan` for the board and plan steering, `build` for the Build Compass; add
  `docs` or other sections for supporting material.
- Give every item a one-line `help_text` — it renders as the page's orientation note.
- Keep `id`s stable; navigation and saved-answer routing assume durable ids.
- The QuarterDeck renders whatever you create — it will not invent content or config. To roll
  out a QuarterDeck for a project, author a `console.yaml` (copy `console.yaml.sample`) and the
  files it references; `drydock init <Target>` seeds the standard set.

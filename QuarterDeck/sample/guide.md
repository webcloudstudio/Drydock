# Console Guide

This is the project's own help page, rendered by the **markdown** page type — the
Console located it through `console.json` and rendered it pretty. Markdown is the
default page type: tables, fenced code, and lists are all styled.

## Everything is an item

`console.json` is a flat list of **items**. One item = one entry in the left sidebar
(1:1 — no containers). Each item carries:

- **navigation properties** — `label` and `section` (and an optional `order`);
- **type properties** — `type` plus the fields that type needs.

## Sections are states

The sidebar groups items by their `section`, and a section *is* the item's state. Move
an item between states by changing its `section`:

| Section | Coloured dot | Meaning |
|---------|--------------|---------|
| **Pages** | blue | Reference material — read it (this page) |
| **Plan** | amber | Planned work — the Kanban board |
| **Action Items** | red | Needs someone to act — questionnaires |
| **Archive** | grey | Retired / done — kept for reference |

## Page types

| Type | Renders |
|------|---------|
| `markdown` | a markdown file as HTML (this page) |
| `kanban` | a **tickets file** as a work board — see **Plan → Kanban** |
| `questionnaire` | a JSON form whose answers are saved — see **Action Items** |
| `link` | a hyperlink — see **Archive** |

## The Kanban is tickets

The **Plan → Kanban** item points at `sample/tickets.json`. Tickets carry an `id`, a
`parent` (so a feature owns its stories), a `status` (the column), and `priority` /
`urgency` / `blocked` flags. The board is read-only — a framework writes the tickets;
the Console just renders them. Click a card to see its detail: parent, children, the
blocking question, and any related items (the blocked story links to the Kickoff
Questionnaire that answers it).

```text
Console/console.json   ← the flat items list — the contract
Console/sample/        ← the files this test config points at
```

The Console renders whatever you put in front of it. To change what appears, edit the
files or the config — not the Console.

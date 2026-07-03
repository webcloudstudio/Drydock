# Development Notes Package

Portable subdirectory package for turning Ship's Log entries into short engineering posts.

This package is designed to be copied into another project. It keeps only two durable
working surfaces:

- `blog/material/` — assembled source material from Ship's Log
- `blog/posts/` — rewritten Markdown posts and optional sibling `.html` previews

Everything else is support code or prompt/spec files.

## Purpose

The package takes structured decision history from `ships_log.jsonl`, groups it into a
selected batch, rewrites that batch once through a subscription-authenticated LLM call,
and saves one short post in plain Markdown. The post can then be reviewed, edited, or
published by the host project.

## Directory Contract

```text
blog/
  DISCLOSURE.md        Hard safety rules
  GENERATION.md        Output contract
  material/            Source material batches built from Ship's Log
  posts/               Post Markdown files and optional sibling HTML previews
prompts/
  devnote.md           Interactive devnote prompt
  milestone.md         Interactive milestone prompt
scripts/
  create.py            Ship's Log -> material batch
  format.py            Material batch -> one post via one LLM rewrite call
  render.py            Post Markdown -> sibling HTML preview + posts/index.html
  publish.sh           Validate post and rebuild local preview/index
  run.py               create + format + render
  check_disclosure.py  Mechanical disclosure backstop
  devblog_lib.py       Shared helpers
blog.config.sh         Package configuration
AGENTS.md              Agent operating instructions for this package
```

Voice and brand guidance (`BRANDING_POSTS.md`, `BRANDING_MAIN.md`) is read live from
Drydock's `Rigging/` — the maintained source — rather than kept as a local copy here.
`BRANDING_POSTS` / `BRANDING_MAIN` in `blog.config.sh` point at those paths.

Removed from the process:

- `drafts/`
- `private/`
- `rendered/`
- `public/`

If those directories still exist locally, they are leftovers and not part of the active
architecture.

## Surfaces

`blog/material/`

- One file per batch.
- Contains real source notes assembled from Ship's Log, unscrubbed — disclosure
  safety is enforced at the published output (`format.py`'s rewrite plus
  `check_disclosure.py`), not here.
- Carries cursor metadata such as `last_event_id` and batch window fields.
- Not intended for publication.

`blog/posts/`

- One Markdown file per generated post.
- This is the main authoring and review surface.
- Rendering writes `post-name.html` next to `post-name.md`.
- Rendering also rebuilds `blog/posts/index.html` as a local table of contents.

## Process

### 1. Create source material

Build one batch from Ship's Log (source defaults to `SHIPS_LOG` in `blog.config.sh`):

```bash
uv run python scripts/create.py --limit 1 --label one-good-post
```

Weekly batch:

```bash
uv run python scripts/create.py --period-days 7 --label 2026-week-27
```

What it does:

- reads the next unseen Ship's Log events after the saved cursor
- filters to supported event types
- optionally groups by a contiguous period such as 7 days
- writes `blog/material/<label>.md`
- does **not** advance the cursor

### 2. Format one post

Rewrite one material batch into one post:

```bash
uv run python scripts/format.py blog/material/one-good-post.md
```

What it does:

- reads `GENERATION.md`, `DISCLOSURE.md`, `BRANDING_POSTS.md`, optional `BRANDING_MAIN.md`,
  and the material batch
- makes exactly one LLM rewrite call
- writes one Markdown post into `blog/posts/`
- runs disclosure lint
- advances the cursor only after a successful rewrite and clean output

### 3. Render local preview

```bash
uv run python scripts/render.py blog/posts/<post>.md
```

What it does:

- renders `blog/posts/<post>.html`
- rebuilds `blog/posts/index.html`

This is local preview only. It is not a public-site deployment surface.

### 4. One-command run

Defaults to a weekly batch straight from Ship's Log:

```bash
uv run python scripts/run.py
```

Equivalent to `create.py --period-days 7` piped into `format.py` and `render.py`. Override for a
single-decision note:

```bash
uv run python scripts/run.py --period-days 0 --limit 1 --label one-good-post
```

This runs:

1. `create.py`
2. `format.py`
3. `render.py`

### 5. Validate / finalize locally

```bash
uv run python scripts/check_disclosure.py blog/posts/<post>.md
bash scripts/publish.sh blog/posts/<post>.md
```

`publish.sh` no longer moves files between directories. It validates the post again and
rebuilds the sibling preview/index. External publication belongs to the host project.

## Batch Controls

`--limit N`

- Use when you want a fixed number of next unseen events.
- Best for one-decision notes.

`--period-days N`

- Use when you want a contiguous time window starting from the first unseen event.
- Best for weekly summaries.

`--label NAME`

- Controls the material filename only.
- Lets you name batches by purpose instead of date.

`--date YYYY-MM-DD`

- Controls the post date written into frontmatter.

Recommended use:

- single decision (`create.py`): `--limit 1 --type devnote`
- single decision (`run.py`, which defaults to a 7-day window): `--period-days 0 --limit 1 --type devnote`
- weekly summary: `--period-days 7 --type milestone` (the `run.py` default)

## Voice

The rewrite step produces a **development log entry**, not an essay:

- specification voice — present-tense, declarative, third-person
- Drydock, its commands, and its components named concretely
- a lead paragraph, then `## Milestones` and `## Changes` sections of dated bullets
- the post dated by the end of the work window, never the generation date
- fixed-format titles, no tags, no subtitles, no coined headlines

The primary voice contract lives in Drydock's `Rigging/BRANDING_POSTS.md`, read live
(see `BRANDING_POSTS` in `blog.config.sh`). Rendered HTML implements the Slate brand
from `Rigging/BRANDING_MAIN.md` with the Drydock logo (`LOGO` in `blog.config.sh`).

## Configuration

Edit `blog.config.sh`:

- `SHIPS_LOG`
- `AGENT`
- `AUTHOR`
- `SITE_TITLE`
- `SITE_DESC`

The package assumes the host project owns the real deployment and any richer publishing layer.

## Notes For Moving Into Another Project

This package is meant to be copied as a subdirectory. To digest it in another system:

- keep the `blog/`, `prompts/`, and `scripts/` structure intact
- point `SHIPS_LOG` at the host project's decision log
- update `AGENTS.md` so the host project's agent context explains domain terms well
- optionally swap `run_agent(...)` in `scripts/devblog_lib.py` to the host project's standard
  LLM wrapper

The package should be treated as a small content-generation subsystem, not as a full site.

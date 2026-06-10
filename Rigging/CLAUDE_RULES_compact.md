<!-- Compacted from RulesEngine/CLAUDE_RULES.md on 2026-04-29 by prompts/compact_file.md — regenerate via bin/rulesengine_compact.sh -->

# Development Rules — Compact

## Git Workflow

1. Commit immediately after completing a task with no errors.
2. Commit messages: descriptive text, no "Claude"/"Anthropic"/"AI" mentions.
3. DO NOT push — local commits only.
4. NO co-authored-by lines.

Web server changes: print "No restart needed — browser refresh is enough." (templates/CSS/static only) or "Restart required — `./bin/start.sh`." (Python/JS server files).

## Project Layout

```
ProjectName/
  METADATA.md       Identity (name, port, status, stack, etc.)
  AGENTS.md         AI context: dev commands, endpoints, architecture
  CLAUDE.md         Contains only: @AGENTS.md
  .env.sample       Required env vars (committed)
  .env              Actual env vars (never committed)
  bin/              All executable scripts
    common.sh       Shared functions — sourced by all bash scripts
    common.py       Shared OperationContext — imported by Python scripts
  docs/             Generated documentation
  logs/             Log files (gitignored)
  data/             Persistent data
  tests/            Test suite
  archive/          Superseded files — gitignored, never committed (optional)
```

## Scripts (`bin/`)

Standard script names:

| Script | Purpose | Name String |
|--------|---------|-------------|
| `bin/start.sh` | Start service — service projects only | Start Service |
| `bin/stop.sh` | Stop service — service projects only | Stop Service |
| `bin/build.sh` | Build / compile / package | Build |
| `bin/daily.sh` | Daily maintenance | Daily Batch |
| `bin/weekly.sh` | Weekly maintenance | Weekly Batch |
| `bin/build_documentation.sh` | Generate docs/ output | Build Doc |
| `bin/deploy.sh` | Deploy to environment | Deploy |
| `bin/test.sh` | Run project tests — stub is acceptable | Test |

Standard script header (Name String must match table above; no other `# Name:` or `# Category:` fields):

```bash
#!/bin/bash
# CommandCenter Operation
# Name: {Name String}
# Category: Operations
# Args: Arg1, Arg2          # omit if the script takes no positional arguments
```

CommandCenter header fields — recognized in first 20 lines:

| Field | Required | Notes |
|-------|----------|-------|
| `# CommandCenter Operation` | Yes — marker | Registers the file in the service catalog. Must appear within the first 20 lines. |
| `# Name:` | Yes | Display name used in GAME and the service catalog. |
| `# Category:` | Yes | `Operations`, `Workflow`, or `Global` (see Category Definitions). |
| `# Description:` | Required for programmatically called scripts | One-line summary. Mandatory for scheduler/orchestrator/platform-invoked scripts. |
| `# Args:` | Required if positional arguments exist | Positional arguments in order, comma-separated. Omit if none. |
| `# Port:` | Required if script binds or exposes a port | Port number the script listens on or uses. |

Category Definitions:

| Category | Rule | Examples |
|----------|------|---------|
| `Operations` | Standard lifecycle scripts: `start.sh`, `stop.sh`, `build.sh`, `test.sh`, `build_documentation.sh`. Use this exact category for these exact filenames. | start.sh, stop.sh, build.sh, test.sh |
| `Global` | Scripts whose filename begins with a capital letter — they modify files or state in other repositories. | ProjectUpdate.sh, ProjectValidate.sh |
| `Workflow` | All other `bin/` scripts not matching a Standard Script Name and not starting with a capital letter. | iterate.sh, scorecard.sh, validate.sh |

All projects must have `bin/test.sh`. A minimal stub (`#!/bin/bash` + `exit 0`) is sufficient until real tests exist.

## Python Projects

Test suite:

```
tests/
  conftest.py     — app, client, and db fixtures
  test_smoke.py   — startup and health checks
  test_routes.py  — one test per registered route
  test_db.py      — schema and CRUD round-trips (if project has a database)
```

`pytest` must appear in `pyproject.toml` `[project.optional-dependencies].dev`. `bin/test.sh` runs `ruff check . && ruff format --check .` then `python -m pytest tests/ -v`. Tests must pass before any commit. A failing lint/format check also fails the build.

Use `uv` for venv + deps, `ruff` for lint + format. Never use `pip install` directly — always `uv add` or `uv pip install`. Never use `python -m venv` — always `uv venv`. `uv.lock` must be committed. `.venv/` is gitignored. `uv sync --frozen` for CI.

`pyproject.toml` must declare:

```toml
[tool.ruff]
line-length = 88

[tool.ruff.lint]
select = ["E", "F", "I", "UP", "B"]

[tool.ruff.format]
quote-style = "double"
```

## Script Templates

`.env` load order — `common.sh` order: METADATA.md fields → `.venv` → `.secrets` → `.env` → derived vars. Do not change that order.

Bash:

```bash
#!/bin/bash
# CommandCenter Operation
# Category: Operations
source "$(cd "$(dirname "$0")" && pwd)/common.sh"

# your start command — use $PORT for the service port
# e.g. Flask: export FLASK_DEBUG=1 && flask run --port "$PORT"
```

Python:

```python
#!/usr/bin/env python3
# CommandCenter Operation
# Category: Workflow
import sys, os; sys.path.insert(0, os.path.dirname(__file__)); from common import op

def main(ctx):
    # ctx.project_name, ctx.port, ctx.logger available — use ctx.port as the service port
    pass

if __name__ == '__main__':
    op(__file__).run(main)
```

Use `$PORT` / `ctx.port` as the service port — never hardcode a port number. Use Linux line endings (no `\r`). Run `chmod +x bin/*.sh`.

Exit logging — every script must emit:

```
[ProjectName] HH:MM Starting
[ProjectName] HH:MM Completed OK
[ProjectName] HH:MM Completed ERROR <reason>
```

These are the canonical terminal tokens — do not add additional completion lines after them.

Heartbeat / log_event:

```bash
heartbeat <state> [message]   # state: OK | WARNING | ERROR | CRITICAL
log_event <severity> <message> # severity: INFORMATION | WARNING | ERROR | CRITICAL
# Resolves GAME port from $GAME_PORT, then ~/.game_port, then 5000. Silent no-op if GAME unreachable.
```

```python
ctx.heartbeat(state, message='')
ctx.log_event(severity, message)
```

Call `heartbeat('OK')` at script start in long-running loops. Call `heartbeat('ERROR', msg)` before exiting on known failure. Never gate script logic on heartbeat success. Where a script already parses flags, add `-d` / `--debug` to enable DEBUG-level logging. Do not add an argument parser solely to support this flag.

Log format — all log output:

```
YYYY-MM-DD HH:MM:SS LEVEL    [ProjectName] message here
```

`LEVEL` left-padded to 8 characters. Do not use `print()` for operational messages; use `logger.info()` etc. Generated documentation must be produced by `bin/build_documentation.sh`. Output goes to `docs/`.

## METADATA.md

Always read `name`, `display_name`, `short_description`, and `git_repo` from this file — never infer them from directory names.

```
# AUTHORITATIVE PROJECT METADATA - THE FIELDS IN THIS FILE SHOULD BE CURRENT

name: MyProject                              # machine slug, matches directory name
display_name: My Project                     # human-readable name for UI/display
git_repo: https://github.com/org/MyProject   # full HTTPS URL, for links only
port: 8000                                   # omit if not a service
short_description: One sentence.             # shown in dashboards and indexes
health: /health                              # omit if not a service
status: PROTOTYPE                            # IDEA|PROTOTYPE|ACTIVE|PRODUCTION|ARCHIVED
stack: Python/Flask/SQLite                   # slash-separated, used by generate_prompt.sh
version: 2026-03-16.1                        # YYYY-MM-DD.N, increment on releases
updated: 20260316_120000                     # set automatically by platform scripts

# Optional platform and interrelationship fields (managed by GAME/platform scripts):
show_on_homepage: true                       # include in GAME portfolio display
desired_state: on-demand                     # on-demand|running|stopped — GAME manages lifecycle
card_url: /path/to/docs                      # URL for project card link in GAME
namespace: development                       # logical grouping: development|production|archive
tags: AI Framework                           # comma-separated classification tags
image: filename.webp                         # card image (served from GAME static/)
image_description: ...                       # alt text and DALL-E generation prompt

# Interrelationship fields (project-type-specific):
specification_directory: ../Specifications   # path to specification repo (Prototyper only)
```

## AGENTS.md Required Sections

```markdown
# AGENTS.md — {Display Name}

{One-paragraph description: what it does, its stack, and key directories.}

## Dev Commands

| Command | Description |
|---------|-------------|
| `./bin/start.sh` | Start server |
| `./bin/stop.sh` | Stop server |
| `./bin/test.sh` | Run tests |

## Service Endpoints        # omit if not a service

| Endpoint | Method | Description | CLI |
|----------|--------|-------------|-----|
| `/health` | GET | Health check | — |

## Bookmarks

| Label | URL |
|-------|-----|
| App | http://localhost:PORT |
| Docs | docs/index.html |

## Logs                     # omit if not a service

| Label | Path |
|-------|------|
| App | logs/{name}_start_*.log |
```

- `CLI` column: bin/ script that triggers the route, or `—` if none.
- `## Logs` required for service projects at ACTIVE level. Use glob pattern for timestamped files.
- Only include commands and endpoints that actually exist for the project.
- Do not create `Links.md` — all URLs belong in AGENTS.md `## Bookmarks`.

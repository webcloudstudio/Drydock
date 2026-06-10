# Business Rules

**Version:** 20260407 V1
**Description:** Master source for agent behavior rules — edit here, then regenerate CLAUDE_RULES.md via `bin/summarize_rules.sh`.

---

## Conformity Levels

Conformity levels define what a project must have before it is treated as ready for a given stage.
`bin/validate.sh` enforces the level matching the project's `status:` field.

### IDEA
Requires: METADATA.md with `name` and `status: IDEA`

### PROTOTYPE
Requires: IDEA + all METADATA required fields + AGENTS.md with required sections

### ACTIVE
Requires: PROTOTYPE + tests exist (`tests/` directory) + `docs/` exists

### PRODUCTION
Requires: ACTIVE + `bin/deploy.sh` exists + `health` endpoint declared in METADATA.md

### Documentation Directory
All projects MUST use `docs/` (not `doc/`) for generated documentation. There is no `doc/` directory.

### ARCHIVED
No enforcement — read-only historical record.

---

## Git

### GIT_COMMIT_IMMEDIATELY
**Scope:** git
**Applies at:** PROTOTYPE
**Requirement:** Commit immediately after completing a task with no errors.
**Rationale:** Prevents loss of working increments between agent operations. Keeping commits small and frequent makes it easy to identify regressions and roll back individual changes.
**Rule text:**
Commit immediately after completing a task with no errors.

### GIT_COMMIT_MESSAGE
**Scope:** git
**Applies at:** PROTOTYPE
**Requirement:** Commit messages must be descriptive text with no "Claude", "Anthropic", or "AI" mentions.
**Rationale:** Commit history is read by humans and tools alike. Attribution noise degrades readability and makes automated parsing harder.
**Rule text:**
Commit messages: descriptive text, no "Claude"/"Anthropic"/"AI" mentions.

### GIT_NO_PUSH
**Scope:** git
**Applies at:** PROTOTYPE
**Requirement:** Do not push to remote — local commits only.
**Rationale:** Push is a destructive, shared-state operation. The user controls when code reaches the remote.
**Rule text:**
DO NOT push — local commits only.

### GIT_NO_COAUTHOR
**Scope:** git
**Applies at:** PROTOTYPE
**Requirement:** No co-authored-by lines in commit messages.
**Rationale:** Co-authored-by lines add noise and may expose agent identity in ways the user has not opted into.
**Rule text:**
NO co-authored-by lines.

### GIT_RESTART_NOTICE
**Scope:** git
**Applies at:** PROTOTYPE
**Requirement:** After any commit that changes a web server project, print whether a restart is required.
**Rationale:** Developers need to know immediately whether they must restart a service or can simply refresh. Getting this wrong wastes time or causes confusion.
**Rule text:**
Web server changes: print "No restart needed — browser refresh is enough." (templates/CSS/static only) or "Restart required — `./bin/start.sh`." (Python/JS server files).

---

## Project Layout

### PROJECT_LAYOUT
**Scope:** project-layout
**Applies at:** PROTOTYPE
**Requirement:** Every project must follow the standard directory structure.
**Rationale:** Uniform layout lets agents, scripts, and the GAME platform find files without configuration.
**Rule text:**

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

### ARCHIVE_DIRECTORY
**Scope:** project-layout
**Applies at:** IDEA
**Requirement:** An optional `archive/` directory may exist at the root of any specification directory or code project. It is always gitignored.
**Rationale:** Superseded documents and files should be preserved for reference without polluting the working tree or version history. Gitignoring `archive/` prevents accidental commits of stale content and keeps the working tree clean.
**Rule text:**
`archive/` is an optional holding area for superseded files. Place it at the project root. It is listed in the standard `.gitignore` — never commit it. Do not treat files in `archive/` as current; they are historical reference only.

---

## Scripts

### SCRIPTS_IN_BIN
**Scope:** scripts
**Applies at:** PROTOTYPE
**Requirement:** All scripts live in `bin/` — bash (`.sh`) or Python (`.py`).
**Rationale:** A single well-known location makes scripts discoverable by agents and the GAME platform.
**Rule text:**
All scripts live in `bin/` — bash (`.sh`) or Python (`.py`). The `# CommandCenter Operation` marker in the first 20 lines registers a script with the platform.

**Standard script names** (only create what the project needs):

| Script | Purpose | Name String
|--------|---------|
| `bin/start.sh` | Start service — service projects only | Stop Service |
| `bin/stop.sh` | Stop service — service projects only | Stop Service |
| `bin/build.sh` | Build / compile / package | Build |
| `bin/daily.sh` | Daily maintenance | Daily Batch |
| `bin/weekly.sh` | Weekly maintenance | Weekly Batch |
| `bin/build_documentation.sh` | Generate docs/ output | Build Doc |
| `bin/deploy.sh` | Deploy to environment | Deploy |
| `bin/test.sh` | Run project tests — stub is acceptable | Test |

If the script name matches a Standard Script Name the following header should exist with a Name: field matching the Name String.  If possible
these should be the first lines of the file and there should be no other "# Name:" or "# Category:" fields.

#!/bin/bash
# CommandCenter Operation
# Name: {Name String}
# Category: Operations
# Args: Arg1, Arg2          # omit if the script takes no positional arguments

The `# Args:` line lists positional arguments in order, comma-separated. Include only positional arguments — not flags (e.g. `--verbose`, `--dry-run`). Omit the line entirely if the script takes no positional arguments. Platform consumers and tools use `Args:` to discover the script's calling convention without reading the body.

**CommandCenter header field schema**

The following fields are recognized in the first 20 lines of any `bin/` file carrying `# CommandCenter Operation`. This applies to any file type (`.sh`, `.py`, or other) — not only shell scripts.

| Field | Required | Notes |
|-------|----------|-------|
| `# CommandCenter Operation` | Yes — marker | Registers the file in the service catalog. Must appear within the first 20 lines. |
| `# Name:` | Yes | Display name used in GAME and the service catalog. Use the Name String from the Standard Script Names table if applicable. |
| `# Category:` | Yes | Operational category: `Operations`, `Workflow`, or `Global` (see Category Definitions below). |
| `# Description:` | Required for programmatically called scripts | One-line summary of what the script does. Mandatory for any script that may be invoked by a scheduler, orchestrator, or external platform. |
| `# Args:` | Required if positional arguments exist | Positional arguments in order, comma-separated. Omit if none. |
| `# Port:` | Required if script binds or exposes a port | The port number the script listens on or uses. |

Scripts that may be called programmatically (schedulers, orchestrators, GAME) MUST include `# Description:` and `# Args:` (if applicable) so callers can discover the contract without reading the body.

**Category Definitions**

| Category | Rule | Examples |
|----------|------|---------|
| `Operations` | Standard lifecycle scripts: `start.sh`, `stop.sh`, `build.sh`, `test.sh`, `build_documentation.sh`. Use this exact category for these exact filenames regardless of project. | start.sh, stop.sh, build.sh, test.sh, build_documentation.sh |
| `Global` | Scripts whose filename begins with a capital letter. These scripts modify files or state in repositories other than their own — the capital letter is a visual signal that the script reaches outside its project boundary. | GitCommit.sh, ProjectUpdate.sh, ProjectValidate.sh |
| `Workflow` | All other `bin/` scripts that are not a Standard Script Name and do not start with a capital letter. Includes data processing, specification tools, one-off automation, and anything that operates only within the project's own directory. | iterate.sh, scorecard.sh, photo_analyze.sh, validate.sh |

### HAS_TEST_SCRIPT
**Scope:** scripts
**Applies at:** ACTIVE
**Requirement:** Every project must have `bin/test.sh`.
**Rationale:** A test entry point is required for CI and GAME to validate project health, even if initially empty.
**Rule text:**
All projects must have `bin/test.sh`. A minimal stub (`#!/bin/bash` + `exit 0`) is sufficient until real tests exist. The script must exist — GAME and the validation system check for it.

### PYTEST_FRAMEWORK
**Scope:** testing
**Applies at:** ACTIVE
**Requirement:** All Python projects use pytest with a standard test suite structure.
**Rationale:** A consistent test framework with standard fixtures means any agent can run and extend the test suite without project-specific knowledge. Baseline coverage at the application entry points catches regressions from any change.
**Rule text:**
Every Python project must have a pytest-based test suite. Required structure:

```
tests/
  conftest.py     — app, client, and db fixtures
  test_smoke.py   — startup and health checks
  test_routes.py  — one test per registered route
  test_db.py      — schema and CRUD round-trips (if project has a database)
```

`pytest` must be declared as a dev dependency in `pyproject.toml` (see PYTHON_TOOLING). Configure via `pytest.ini` or `[tool.pytest.ini_options]` in `pyproject.toml`:

```ini
[pytest]
testpaths = tests
addopts = -v
```

`bin/test.sh` activates the venv, runs ruff checks, then runs pytest:

```bash
source "$(cd "$(dirname "$0")" && pwd)/common.sh"
ruff check .
ruff format --check .
python -m pytest tests/ -v
```

Tests must pass before any commit. A failing ruff check or test suite is treated as a broken build.

### PYTHON_TOOLING
**Scope:** scripts, testing
**Applies at:** ACTIVE
**Requirement:** Python projects use `uv` for venv creation and dependency management, and `ruff` for lint and format.
**Rationale:** pip + venv + pip freeze has no lockfile and no dependency resolution guarantees. Different projects end up with different linters/formatters, so agents produce inconsistent code. uv is a drop-in replacement with a proper lockfile. ruff subsumes flake8, isort, pyupgrade, and flake8-bugbear in one fast tool. Enforcing both at bin/test.sh catches violations before commit.
**Rule text:**
Python projects use `uv` for venv + dependency management and `ruff` for lint + format.

**Venv + dependencies:**
```bash
uv venv                         # creates .venv/ (uv's default)
uv add flask python-dotenv      # add runtime deps → updates pyproject.toml + uv.lock
uv add --dev pytest ruff        # add dev deps
uv sync                         # install from uv.lock
uv sync --frozen                # strict install (CI — fail if lock is stale)
```

`pyproject.toml` is the required dependency manifest for new and migrated projects. `uv.lock` must be committed. `.venv/` is gitignored. Never use `pip install` directly — always `uv add` or `uv pip install`. Never use `python -m venv` — always `uv venv`. When migrating an existing project to current standards, switch it to uv at that time.

**Lint + format — `pyproject.toml` must declare:**
```toml
[tool.ruff]
line-length = 88

[tool.ruff.lint]
select = ["E", "F", "I", "UP", "B"]

[tool.ruff.format]
quote-style = "double"
```

Ruff cache (`.ruff_cache/`) is gitignored. Run `ruff check .` to lint and `ruff format .` to format in place.

### SCRIPTS_ENV_LOAD_ORDER
**Scope:** scripts
**Applies at:** PROTOTYPE
**Requirement:** `.env` must be loaded before any variable that depends on its contents is derived.
**Rationale:** Shell variables set with `${VAR:-default}` evaluate at assignment time. If `.env` is sourced after the assignment, the env file value is silently ignored and the hardcoded default wins. This is a common ordering bug with no error message.
**Rule text:**
Load `.env` (and `.secrets`) **before** deriving any variables from env vars. Never write:

```bash
PORT="${APP_PORT:-5001}"   # BUG: APP_PORT not loaded yet
source .env                # too late
```

Write instead:

```bash
source .env                # load first
PORT="${APP_PORT:-5001}"   # now APP_PORT is available
```

The canonical `common.sh` template follows this order: METADATA.md fields → `.venv` → `.secrets` → `.env` → derived vars. Do not change that order.

### SCRIPTS_BASH_PATTERN
**Scope:** scripts
**Applies at:** PROTOTYPE
**Requirement:** Bash scripts must source `common.sh` before adding functionality.
**Rationale:** `common.sh` provides consistent path setup, env loading, logging, and signal handling — reinventing these per-script creates drift.
**Rule text:**

```bash
#!/bin/bash
# CommandCenter Operation
# Category: Operations
source "$(cd "$(dirname "$0")" && pwd)/common.sh"

# your start command — use $PORT for the service port
# e.g. Flask: export FLASK_DEBUG=1 && flask run --port "$PORT"
```

`common.sh` handles: `SCRIPT_NAME`, `PROJECT_DIR`, `cd`, `PROJECT_NAME`, `PORT`, venv activation (probes `.venv/` first, falls back to `venv/` for legacy projects), `.secrets`/`.env` loading, timestamped log file, SIGTERM trap, standardized exit logging, and the `[$PROJECT_NAME] HH:MM Starting` message. Use `$PORT` as the service port — never hardcode a port number. Override the trap after sourcing if the script needs custom cleanup.

### SCRIPTS_PYTHON_PATTERN
**Scope:** scripts
**Applies at:** PROTOTYPE
**Requirement:** Python scripts must import `common.py` before adding functionality.
**Rationale:** `common.py` provides the same operational guarantees as `common.sh` for Python scripts.
**Rule text:**

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

`op(__file__).run(main)` handles the same concerns as `common.sh`: path setup, METADATA.md parsing, env loading, logging, SIGTERM, and standardized exit logging. On clean exit it logs `[ProjectName] HH:MM Completed OK`; on unhandled exception it logs `[ProjectName] HH:MM Completed ERROR <message>` and exits 1.

Use Linux line endings (no `\r`). Run `chmod +x bin/*.sh`.

### SCRIPTS_EXIT_LOGGING
**Scope:** scripts
**Applies at:** PROTOTYPE
**Requirement:** Every script must emit standardized start and completion lines.
**Rationale:** The log ingestor and operators need unambiguous tokens to know when a script started and whether it succeeded or failed, without parsing arbitrary output.
**Rule text:**
Every script must emit these lines as its operational log output:

```
[ProjectName] HH:MM Starting
[ProjectName] HH:MM Completed OK
[ProjectName] HH:MM Completed ERROR <reason>
```

`common.sh` emits `Starting` at script open and `Completed OK` or `Completed ERROR <reason>` via the EXIT trap (code 0 → OK; non-zero → ERROR with reason).
`common.py`'s `run()` emits the same: `Starting` at entry, `Completed OK` on clean exit, `Completed ERROR <message>` on unhandled exception.
These are the canonical terminal tokens — do not add additional completion lines after them.

### SCRIPTS_HEARTBEAT
**Scope:** scripts
**Applies at:** PROTOTYPE
**Requirement:** Scripts may report operational state and log events to GAME using `heartbeat()` and `log_event()`.
**Rationale:** Centralised health state and event history in GAME enables monitoring across all projects without per-project instrumentation.
**Rule text:**
Both `common.sh` and `common.py` provide two helpers:

**Bash:**
```bash
heartbeat <state> [message]
# state: OK | WARNING | ERROR | CRITICAL
# Resolves GAME port from $GAME_PORT env var, then ~/.game_port, then 5000.
# Silent no-op if GAME is unreachable — never aborts the script.

log_event <severity> <message>
# severity: INFORMATION | WARNING | ERROR | CRITICAL
```

**Python:**
```python
ctx.heartbeat(state, message='')
ctx.log_event(severity, message)
# state / severity: OK WARNING ERROR CRITICAL (heartbeat); INFORMATION WARNING ERROR CRITICAL (log_event)
# Silent no-op if GAME unreachable.
```

Call `heartbeat('OK')` at script start after `run()` if using long-running loops. Call `heartbeat('ERROR', msg)` before exiting on known failure conditions. These calls are advisory — never gate script logic on their success.

### SCRIPTS_DEBUG_FLAG
**Scope:** scripts
**Applies at:** PROTOTYPE
**Requirement:** Scripts that already parse flags or arguments should support `-d` / `--debug` to enable DEBUG-level logging.
**Rationale:** A consistent debug flag means operators and agents always know how to get verbose output without reading each script individually.
**Rule text:**
Where a script already parses flags or arguments, add `-d` / `--debug` to enable DEBUG-level logging. Do not add an argument parser solely to support this flag. Do not implement if `-d` is already used for a different purpose in that script. When active, set the log level to DEBUG before any application logic runs.

### SCRIPT_LOG_FORMAT
**Scope:** scripts
**Applies at:** PROTOTYPE
**Requirement:** All programmatic scripts use a standard log format regardless of language.
**Rationale:** Consistent log output across all scripts makes aggregation, filtering, and debugging predictable without per-script knowledge.
**Rule text:**
All log output must follow this format:

```
YYYY-MM-DD HH:MM:SS LEVEL    [ProjectName] message here
```

`LEVEL` is left-padded to 8 characters (`INFO    `, `DEBUG   `, `WARNING `, `ERROR   `) so message columns align.

**Python** — `common.py`'s `op()` sets this up automatically. Scripts using `common.py` inherit the configuration and must not override it. The logger name is set to `ctx.project_name` so `[ProjectName]` appears in every line. Default level is `INFO`; set to `DEBUG` when `-d`/`--debug` is active. Do not use `print()` for operational messages — use `logger.info()`, `logger.debug()`, `logger.warning()`, `logger.error()`.

```python
logging.basicConfig(
    format="%(asctime)s %(levelname)-8s [%(name)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    level=logging.INFO,
)
logger = logging.getLogger(ctx.project_name)
```

**Bash** — `common.sh` provides log helpers that scripts must use instead of bare `echo` for operational messages:

```bash
log_info()  { echo "$(date '+%Y-%m-%d %H:%M:%S') INFO     [$PROJECT_NAME] $*"; }
log_debug() { echo "$(date '+%Y-%m-%d %H:%M:%S') DEBUG    [$PROJECT_NAME] $*"; }
log_warn()  { echo "$(date '+%Y-%m-%d %H:%M:%S') WARNING  [$PROJECT_NAME] $*"; }
log_error() { echo "$(date '+%Y-%m-%d %H:%M:%S') ERROR    [$PROJECT_NAME] $*"; }
```

`log_debug()` is a no-op unless `-d`/`--debug` was passed (per SCRIPTS_DEBUG_FLAG). Scripts using `common.sh` inherit these helpers automatically.

> **Note:** `common.py` and `common.sh` templates must be updated to implement this standard. Until updated, individual scripts may need to configure logging manually.

### DOCS_GENERATED_BY_SCRIPT
**Scope:** scripts
**Applies at:** PROTOTYPE
**Requirement:** If project documentation is assembled by a program, it must be generated through `bin/build_documentation.sh`.
**Rationale:** A single named entry point for documentation generation ensures GAME and operators know how to rebuild docs without reading project internals. It also satisfies the CommandCenter header contract so the platform can invoke it.
**Rule text:**
Generated documentation must be produced by `bin/build_documentation.sh`. If the script delegates to a Python file or other tool, the shell script remains the canonical entry point. Output goes to `docs/`. Do not generate documentation through ad-hoc commands or undeclared scripts.

---

## METADATA.md

### METADATA_FORMAT
**Scope:** metadata
**Applies at:** IDEA
**Requirement:** METADATA.md must use the key-value format with required fields.
**Rationale:** METADATA.md is the authoritative identity source for GAME platform discovery. Field names and format must be stable so scripts can parse them without configuration.
**Rule text:**
**Authoritative source for project identity.** Always read `name`, `display_name`, `short_description`, and `git_repo` from this file — never infer them from directory names. Present in every set-up project.

Key-value format (not YAML):

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
specification_directory: ../Specifications   # path to specification repo (Prototyper)
prototyper_directory: ../Prototyper          # path to Prototyper repo (projects that consume specs)
messages_directory: ../Messages              # path to Messages repo (projects that use messaging)
```

`port`, `health`, `stack`, and `status` are platform fields — managed by GAME and platform scripts, not needed for day-to-day agent work. `git_repo` SSH remotes are normalised to HTTPS automatically. Interrelationship fields expose cross-repository paths and GAME integration points — maintain them accurately so platform scripts can discover relationships without additional configuration.

---

## AGENTS.md

### AGENTS_REQUIRED_SECTIONS
**Scope:** agents-md
**Applies at:** PROTOTYPE
**Requirement:** AGENTS.md must open with a short prose paragraph describing the project (what it does, its stack, key directories), followed by Dev Commands, Service Endpoints (if service), Bookmarks, and Logs sections.
**Rationale:** Agents discover how to operate a project by reading AGENTS.md. Missing sections mean agents must guess or ask, which is unreliable.
**Rule text:**

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
| App | logs/start_*.log |
```

- `CLI` column in Service Endpoints: the bin/ script that triggers the route, or `—` if none. This is the only cross-reference between CLI scripts and REST routes — do not create a separate file.
- `## Logs` required for service projects at ACTIVE level. Use glob pattern for timestamped files.
- Only include commands and endpoints that actually exist for the project.
- Do not create `Links.md` — all URLs belong in AGENTS.md `## Bookmarks`.

### AGENTS_CAPABILITIES_SECTION
**Scope:** agents-md
**Applies at:** PROTOTYPE
**Requirement:** Projects that expose callable functions to the platform network declare them in a `## Capabilities` JSON block in AGENTS.md. Each capability has a name (globally unique), description, tags, invoke endpoints (cli/rest/mcp), typed input/output, permissions, and lifecycle.
**Rationale:** The capability block is how GAME's scanner discovers what a project can do and how to call it. Without it, the project's functions are invisible to the Capability Catalog.
**Rule text:**

Projects that expose callable platform functions add a `## Capabilities` section to AGENTS.md containing a JSON block. Full schema in `RulesEngine/SPECIFICATION_CONTRACT.md`.

```json
{
  "capabilities": [
    {
      "name": "capability_name",
      "description": "One sentence.",
      "tags": ["tag1", "tag2"],
      "invoke": {
        "cli": "bin/script_name",
        "rest": { "method": "POST", "path": "/api/path" }
      },
      "input": {
        "param1": { "type": "string", "required": true }
      },
      "output": {
        "result_field": { "type": "string" }
      },
      "permissions": { "owners": ["username"], "access": "readwrite" },
      "lifecycle": "on-demand"
    }
  ]
}
```

- Omit the `## Capabilities` section entirely if the project exposes no platform-callable functions.
- Capability names must be unique across the entire network — use `{project}_{action}` naming to avoid collisions.
- Include only transports the project actually implements (`cli`, `rest`, `mcp`).
- `lifecycle` values: `on-demand` | `always-on` | `scheduled`

---

## Open Questions

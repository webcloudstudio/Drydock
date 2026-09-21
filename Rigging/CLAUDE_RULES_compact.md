<!-- Compacted from Rigging/CLAUDE_RULES.md sha256=ba39e2cbeed39f4be96e02bcca33bb450608641aeba4bd743e97cd1daa08b55e on 2026-09-20 by drydock rigging compact — regenerate with: drydock rigging compact --include-file {rel_source} -->

# CLAUDE_RULES_START — Contract Surface

## Git

### Rule: commit-work

Every completed task with no errors must be committed locally.

Constraints: Commit messages must be descriptive and contain no “Claude,” “Anthropic,” or “AI” mentions. Do not push or add co-authored-by lines.

### Rule: server-restart-notice

Web-server changes must report whether a restart is required.

Constraints: Template, CSS, and static changes emit `No restart needed — browser refresh is enough.` Python or JavaScript server changes emit `Restart required — \`./bin/start.sh\`.`

## Project Layout

### Rule: required-project-files

Projects use the standard files and directories required by their project type.

Constraints: Required root files include `METADATA.md`, `AGENTS.md`, `CLAUDE.md`, `.env.sample`, and `.env`. Required directories include `bin/`, `docs/`, `logs/`, `data/`, and `tests/`. `archive/` is optional, gitignored, and historical only.

### config_key: METADATA.md

`METADATA.md` is the authoritative key-value configuration for project identity and platform integration.

| Key | Required | Contract |
|---|---:|---|
| `name` | Yes | Machine slug matching the directory name |
| `display_name` | Yes | Human-readable UI name |
| `git_repo` | Yes | Full HTTPS repository URL |
| `port` | No | Service port |
| `short_description` | Yes | One-sentence dashboard description |
| `health` | No | Service health endpoint |
| `status` | Yes | `IDEA`, `PROTOTYPE`, `ACTIVE`, `PRODUCTION`, or `ARCHIVED` |
| `stack` | Yes | Slash-separated technology stack |
| `version` | Yes | `YYYY-MM-DD.N` release version |
| `updated` | Yes | `YYYYMMDD_HHMMSS` timestamp |
| `show_on_homepage` | No | Whether to display in the portfolio |
| `desired_state` | No | `on-demand`, `running`, or `stopped` |
| `card_url` | No | Project card URL |
| `namespace` | No | `development`, `production`, or `archive` |
| `tags` | No | Comma-separated classification tags |
| `image` | No | Card image filename |
| `image_description` | No | Image alt text and generation prompt |
| `specification_directory` | No | Specification repository path |

Constraints: Identity fields must be read from this file rather than inferred from directory names.

## CommandCenter Scripts

### Rule: commandcenter-header

A registered `bin/` script declares its platform metadata in the first 20 lines.

| Field | Required | Allowed value |
|---|---:|---|
| `# CommandCenter Operation` | Yes | Registration marker |
| `# Name:` | Yes | Display name |
| `# Category:` | Yes | `Operations`, `Workflow`, or `Global` |
| `# Description:` | Programmatic scripts | One-line summary |
| `# Args:` | Positional arguments | Ordered, comma-separated arguments |
| `# Port:` | Port-binding scripts | Port number |

### Rule: standard-script-contract

Standard lifecycle scripts use their prescribed names and categories.

| Script | Purpose | Name | Category |
|---|---|---|---|
| `bin/start.sh` | Start service | `Start Service` | `Operations` |
| `bin/stop.sh` | Stop service | `Stop Service` | `Operations` |
| `bin/build.sh` | Build, compile, or package | `Build` | `Operations` |
| `bin/daily.sh` | Daily maintenance | `Daily Batch` | `Workflow` |
| `bin/weekly.sh` | Weekly maintenance | `Weekly Batch` | `Workflow` |
| `bin/build_documentation.sh` | Generate documentation | `Build Doc` | `Operations` |
| `bin/deploy.sh` | Deploy | `Deploy` | `Workflow` |
| `bin/test.sh` | Run tests | `Test` | `Operations` |

Constraints: Every project must provide `bin/test.sh`. Standard script headers include `# Args:` only when positional arguments exist and omit flags from that field.

### Rule: script-category

Scripts are categorized by filename and purpose.

Constraints: Standard lifecycle scripts use `Operations`; scripts beginning with a capital letter use `Global`; all other `bin/` scripts use `Workflow`.

### Rule: script-exit-contract

Every script emits canonical lifecycle messages.

| State | Required output |
|---|---|
| Start | `[ProjectName] HH:MM Starting` |
| Success | `[ProjectName] HH:MM Completed OK` |
| Failure | `[ProjectName] HH:MM Completed ERROR <reason>` |

Constraints: No completion lines may follow the canonical terminal token.

### Rule: bash-script-runtime

Bash scripts source `bin/common.sh` and use its configured runtime values.

Constraints: Use `$PORT` for service ports and do not hardcode a port. Use Linux line endings and executable permissions for `bin/*.sh`.

### Rule: python-script-runtime

Python scripts invoke `op(__file__).run(main)` with a `main(ctx)` entry point.

| Context field or method | Contract |
|---|---|
| `ctx.project_name` | Project identity |
| `ctx.port` | Service port |
| `ctx.logger` | Configured logger |
| `ctx.heartbeat(state, message='')` | Emit heartbeat |
| `ctx.log_event(severity, message)` | Emit event |

Constraints: Unhandled exceptions produce `Completed ERROR <message>` and exit code `1`.

### Rule: operational-logging

Operational logs use the standard timestamped format.

```text
YYYY-MM-DD HH:MM:SS LEVEL    [ProjectName] message here
```

Constraints: `LEVEL` is left-padded to eight characters. Use logger methods or `common.sh` logging helpers rather than `print()`.

### Rule: heartbeat-events

Long-running scripts report operational health without depending on the reporting system.

| Interface | Parameters |
|---|---|
| `heartbeat <state> [message]` | `state`: `OK`, `WARNING`, `ERROR`, or `CRITICAL` |
| `log_event <severity> <message>` | `severity`: `INFORMATION`, `WARNING`, `ERROR`, or `CRITICAL` |
| `ctx.heartbeat(state, message='')` | Same state values |
| `ctx.log_event(severity, message)` | Same severity values |

Constraints: Call `heartbeat('OK')` at the start of long-running loops and `heartbeat('ERROR', msg)` before known failure exits. GAME port resolution uses `$GAME_PORT`, then `~/.game_port`, then `5000`; unreachable GAME is a silent no-op.

### Rule: debug-flag

Scripts that already parse flags expose `-d` and `--debug` for DEBUG-level logging.

Constraints: Do not add an argument parser solely to provide this flag.

## Python Projects

### Rule: python-test-suite

Python projects provide a pytest suite with the expected fixtures and coverage.

| Path | Required contract |
|---|---|
| `tests/conftest.py` | `app`, `client`, and `db` fixtures |
| `tests/test_smoke.py` | Startup and health checks |
| `tests/test_routes.py` | One test per registered route |
| `tests/test_db.py` | Schema and CRUD round-trips when a database exists |

### config_key: pyproject.toml

Python projects declare pytest and Ruff configuration.

Constraints: `pytest` appears in `[project.optional-dependencies].dev`; `testpaths = tests` and `addopts = -v` are configured. Ruff declares line length `88`, lint selection `["E", "F", "I", "UP", "B"]`, and double-quote formatting.

### Rule: python-dependencies

Python projects use `uv` for environments and dependency management.

Constraints: Commit `uv.lock`; use `uv venv`, `uv add`, `uv add --dev`, `uv sync`, and `uv sync --frozen`. Do not use `pip install` or `python -m venv`.

## Environment and Documentation

### Rule: environment-load-order

Environment sources are loaded before deriving variables.

Constraints: Load `METADATA.md` fields, then `.venv`, `.secrets`, `.env`, and finally derived variables. Do not change this order.

### Rule: generated-documentation

Generated documentation is produced through `bin/build_documentation.sh`.

Constraints: Delegated generators do not replace the shell script as the canonical entry point. Output goes to `docs/`.

## AGENTS.md

### Rule: agents-required-sections

`AGENTS.md` documents only project capabilities that actually exist.

Required sections:

- Project description and key directories
- `## Dev Commands`
- `## Service Endpoints` for service projects
- `## Bookmarks`
- `## Logs` for service projects at `ACTIVE` status

Constraints: Service endpoint tables contain `Endpoint`, `Method`, `Description`, and `CLI`. Bookmark URLs belong in `AGENTS.md`; do not create `Links.md`.

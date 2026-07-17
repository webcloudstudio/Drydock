<!-- Compacted from /mnt/c/Users/barlo/projects/Drydock/Rigging/CLAUDE_RULES.md sha256=ba39e2cbeed39f4be96e02bcca33bb450608641aeba4bd743e97cd1daa08b55e on 2026-07-16 by drydock rigging compact — regenerate with: drydock rigging compact --include-file {rel_source} -->

# DEFAULT DEVELOPMENT RULES — Contract Surface

## Git Workflow

### Rule: commit-on-clean-completion
Tasks must be committed locally immediately after completion when no errors remain.
Constraints: Commit after completing a task with no errors; do not push; commit messages must not mention `Claude`, `Anthropic`, or `AI`; do not add `co-authored-by` lines.

### Rule: web-server-change-notice
Web-server-related changes require a specific operator notice based on the file types changed.
| Input | Required |
|---|---|
| change scope | Yes |

Returns: Print `No restart needed — browser refresh is enough.` for templates/CSS/static-only changes, or `Restart required — ./bin/start.sh.` for Python/JS server-file changes.

## Project Layout

### Rule: required-project-files
Projects use a standard root layout with required identity, environment, executable, documentation, log, data, and test locations.
| Input | Required |
|---|---|
| `METADATA.md` | Yes |
| `AGENTS.md` | Yes |
| `CLAUDE.md` | Yes |
| `.env.sample` | Yes |
| `.env` | Yes |
| `bin/` | Yes |
| `docs/` | Yes |
| `logs/` | Yes |
| `data/` | Yes |
| `tests/` | Yes |
| `archive/` | No |

Constraints: `CLAUDE.md` contains only `@AGENTS.md`; `archive/` is optional, lives at project root, is gitignored, is never committed, and is not treated as current content.

## Scripts

### Rule: script-location
All executable project scripts live under `bin/` and use `.sh` or `.py` extensions.
Constraints: The `# CommandCenter Operation` marker within the first 20 lines registers a script with the platform.

### Rule: standard-script-names
Certain script filenames have fixed purposes and display names.
| Input | Required |
|---|---|
| `bin/start.sh` | Service projects only |
| `bin/stop.sh` | Service projects only |
| `bin/build.sh` | As needed |
| `bin/daily.sh` | As needed |
| `bin/weekly.sh` | As needed |
| `bin/build_documentation.sh` | As needed |
| `bin/deploy.sh` | As needed |
| `bin/test.sh` | Yes |

Returns: Name strings are `Start Service`, `Stop Service`, `Build`, `Daily Batch`, `Weekly Batch`, `Build Doc`, `Deploy`, and `Test`.
Constraints: `bin/test.sh` is mandatory for all projects; a minimal stub of `#!/bin/bash` plus `exit 0` is acceptable until real tests exist.

### Rule: commandcenter-header-schema
Registered `bin/` scripts expose a header schema discoverable from the first 20 lines.
| Input | Required | Notes |
|---|---|---|
| `# CommandCenter Operation` | Yes | Registration marker |
| `# Name:` | Yes | Display name |
| `# Category:` | Yes | `Operations`, `Workflow`, or `Global` |
| `# Description:` | Programmatic scripts only | One-line summary |
| `# Args:` | If positional arguments exist | Positional args only, comma-separated |
| `# Port:` | If script binds/exposes a port | Port number |

Constraints: For standard script names, if the filename matches a standard name, the header must include `# Name:` matching its defined Name String; avoid any other `# Name:` or `# Category:` fields; `# Args:` omits flags and is omitted entirely when no positional args exist.

### Rule: script-category-classification
Scripts are classified by filename and role into one of three categories.
| Input | Required |
|---|---|
| filename | Yes |

Returns: `Operations` for exact standard lifecycle filenames, `Global` for filenames beginning with a capital letter, otherwise `Workflow`.

### Rule: python-test-suite-layout
Python projects require a pytest-based test suite with standard files.
| Input | Required |
|---|---|
| `tests/conftest.py` | Yes |
| `tests/test_smoke.py` | Yes |
| `tests/test_routes.py` | Yes |
| `tests/test_db.py` | If project has a database |

Constraints: `pytest` must appear in `pyproject.toml` under `[project.optional-dependencies].dev`; pytest configuration must set `testpaths = tests` and `addopts = -v`; `bin/test.sh` must activate the venv via `uv sync --frozen`, run `ruff check . && ruff format --check .`, then `python -m pytest tests/ -v`; tests must pass before any commit; failing lint or format checks fail the build.

### Rule: python-tooling
Python projects use `uv` for environment and dependency management and `ruff` for lint and format.
| Input | Required |
|---|---|
| `pyproject.toml` | Yes |
| `uv.lock` | Yes |

Constraints: `.venv/` and `.ruff_cache/` are gitignored; never use `pip install` directly except `uv pip install`; never use `python -m venv`; new and migrated projects use `pyproject.toml` as the dependency manifest.

### config_key
Project Python lint and format configuration is declared in `pyproject.toml`.
| Input | Required |
|---|---|
| `[tool.ruff].line-length = 88` | Yes |
| `[tool.ruff.lint].select = ["E", "F", "I", "UP", "B"]` | Yes |
| `[tool.ruff.format].quote-style = "double"` | Yes |

### Rule: env-load-order
Shell environment files must be loaded in a fixed order before deriving environment-based variables.
| Input | Required |
|---|---|
| `METADATA.md` fields | Yes |
| `.venv` | Yes |
| `.secrets` | Yes |
| `.env` | Yes |
| derived vars | Yes |

Constraints: `common.sh` load order is `METADATA.md` fields -> `.venv` -> `.secrets` -> `.env` -> derived vars; do not change that order.

### Rule: bash-script-contract
Bash scripts source `common.sh` and use the project port provided by it.
| Input | Required |
|---|---|
| `source "$(cd "$(dirname "$0")" && pwd)/common.sh"` | Yes |

Constraints: Use `$PORT` for the service port and never hardcode a port number.

### Rule: python-script-contract
Python scripts import `common.py` and execute through `op(__file__).run(main)`.
| Input | Required |
|---|---|
| `main(ctx)` | Yes |
| `op(__file__).run(main)` | Yes |

Returns: `ctx` provides `project_name`, `port`, and `logger`.
Constraints: Use `ctx.port` for the service port.

### Rule: line-endings-and-executable-bit
Script files use Linux line endings and shell scripts are executable.
| Input | Required |
|---|---|
| line endings | Yes |
| execute bit on `bin/*.sh` | Yes |

Constraints: No `\r`; run `chmod +x bin/*.sh`.

### Rule: exit-logging
Every script emits canonical start and completion terminal tokens.
| Input | Required |
|---|---|
| start line | Yes |
| success line | Yes |
| error line | Yes |

Returns: `[ProjectName] HH:MM Starting`, `[ProjectName] HH:MM Completed OK`, and `[ProjectName] HH:MM Completed ERROR <reason>`.
Constraints: Do not add additional completion lines after these.

### heartbeat
Scripts can emit health heartbeats without affecting control flow.
| Input | Required |
|---|---|
| `state` | Yes |
| `message` | No |

Returns: Accepts states `OK`, `WARNING`, `ERROR`, or `CRITICAL`.
Constraints: Resolve GAME port from `$GAME_PORT`, then `~/.game_port`, then `5000`; silently no-op if GAME is unreachable; call `heartbeat('OK')` at script start in long-running loops; call `heartbeat('ERROR', msg)` before exiting on known failure; never gate script logic on heartbeat success.

### log_event
Scripts can emit structured severity events without affecting control flow.
| Input | Required |
|---|---|
| `severity` | Yes |
| `message` | Yes |

Returns: Accepts severities `INFORMATION`, `WARNING`, `ERROR`, or `CRITICAL`.

### Rule: debug-flag
Scripts that already parse flags must support a debug flag.
| Input | Required |
|---|---|
| `-d` / `--debug` | When flags already exist |

Constraints: Do not add an argument parser solely to support this flag.

### Rule: log-format
Operational log output uses a canonical timestamped format.
Constraints: Format is `YYYY-MM-DD HH:MM:SS LEVEL    [ProjectName] message here`; `LEVEL` is left-padded to 8 characters; do not use `print()` for operational messages; use logger methods or shell logging helpers.

### Rule: documentation-build-entrypoint
Generated documentation is produced through the shell entry point `bin/build_documentation.sh`.
| Input | Required |
|---|---|
| `bin/build_documentation.sh` | Yes |

Constraints: If the script delegates to another tool, the shell script remains the canonical entry point; output goes to `docs/`.

## METADATA.md

### METADATA.md
`METADATA.md` is the authoritative source for project identity and platform metadata.
| Input | Required |
|---|---|
| `name` | Yes |
| `display_name` | Yes |
| `git_repo` | Yes |
| `short_description` | Yes |
| `status` | Yes |
| `version` | Yes |
| `updated` | Yes |
| `port` | No |
| `health` | No |
| `stack` | No |
| `show_on_homepage` | No |
| `desired_state` | No |
| `card_url` | No |
| `namespace` | No |
| `tags` | No |
| `image` | No |
| `image_description` | No |
| `specification_directory` | No |

Constraints: Use key-value format, not YAML; always read `name`, `display_name`, `short_description`, and `git_repo` from this file and never infer them from directory names; `status` is one of `IDEA`, `PROTOTYPE`, `ACTIVE`, `PRODUCTION`, or `ARCHIVED`; `desired_state` is one of `on-demand`, `running`, or `stopped`; `git_repo` is a full HTTPS URL for links only and SSH remotes are normalized to HTTPS automatically.

## AGENTS.md

### Rule: agents-required-sections
`AGENTS.md` uses a fixed section structure with conditional sections for services.
| Input | Required |
|---|---|
| Title `# AGENTS.md — {Display Name}` | Yes |
| One-paragraph description | Yes |
| `## Dev Commands` | Yes |
| `## Service Endpoints` | Service projects only |
| `## Bookmarks` | Yes |
| `## Logs` | Service projects at `ACTIVE` level |

Constraints: `Service Endpoints` includes columns `Endpoint`, `Method`, `Description`, and `CLI`; the `CLI` column contains the triggering `bin/` script or `—` if none; `Logs` uses a glob pattern for timestamped files; include only commands and endpoints that actually exist; do not create `Links.md`; all URLs belong under `AGENTS.md` `## Bookmarks`.

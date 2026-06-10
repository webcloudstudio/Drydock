<!-- Compacted from RulesEngine/stack/common.md on 2026-04-29 by prompts/compact_file.md — regenerate via bin/rulesengine_compact.sh -->

# Common Best Practices — Compact

## Project Directory Layout

```
project-name/
├── bin/                # Operation scripts
├── data/               # Runtime data (DB, logs, backups) — gitignored
│   ├── logs/
│   └── backups/
├── docs/
├── tests/
├── .env                # gitignored
├── .env.example        # committed
├── .gitignore
├── CLAUDE.md
└── Links.md
```

Additional directories depend on the stack (e.g., `templates/`, `static/`, `migrations/`).

## Shell Scripts (bin/)

All user-facing operations live in `bin/` as bash scripts with standardized headers, logging, and error handling.

```bash
#!/bin/bash
# CommandCenter Operation
# Name: Human Readable Name
# Type: daemon|batch
# Port: 8000

# --- Standard Preamble ---
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
LOG_DIR="$PROJECT_DIR/data/logs"
mkdir -p "$LOG_DIR"

TIMESTAMP=$(date '+%Y-%m-%d_%H%M%S')
SCRIPT_NAME=$(basename "$0" .sh)
LOG_FILE="$LOG_DIR/${SCRIPT_NAME}_${TIMESTAMP}.log"

echo "=== $SCRIPT_NAME started at $(date '+%Y-%m-%d %H:%M:%S') ===" | tee "$LOG_FILE"
echo "Arguments: $*" | tee -a "$LOG_FILE"
echo "Working dir: $PROJECT_DIR" | tee -a "$LOG_FILE"
echo "---" | tee -a "$LOG_FILE"

cd "$PROJECT_DIR"

# --- Your Commands Here ---
# All output goes to both console and log file via tee
your_command 2>&1 | tee -a "$LOG_FILE"

echo "=== $SCRIPT_NAME finished at $(date '+%Y-%m-%d %H:%M:%S') ===" | tee -a "$LOG_FILE"
```

## Header Fields

| Field | Required | Values | Description |
|-------|----------|--------|-------------|
| `# CommandCenter Operation` | Yes | literal | Marks script as discoverable |
| `# Name:` | Yes | free text | Display name in UI |
| `# Type:` | No | `daemon` or `batch` | Default: `batch`. Daemons stay running. |
| `# Port:` | No | integer | Port number for daemon services |

Scripts without `# CommandCenter Operation` won't appear in Command Center's UI.

## Standard Scripts

| Script | Type | Purpose |
|--------|------|---------|
| `bin/start.sh` | daemon | Start the dev server |
| `bin/stop.sh` | batch | Stop the dev server |
| `bin/test.sh` | batch | Run test suite |
| `bin/build.sh` | batch | Build/compile the project |
| `bin/deploy.sh` | batch | Deploy to production |
| `bin/backup.sh` | batch | Backup data/database |

Logging: all stdout/stderr captured via `tee` to `data/logs/`. Log filename: `scriptname_YYYY-MM-DD_HHMMSS.log`. First lines always record timestamp, arguments, working directory.

## External Links (Links.md)

Every project maintains `Links.md` at its root:

```markdown
| Label | URL |
|-------|-----|
| Local Dev | http://localhost:5001 |
| Production | https://example.com |
| Docs | https://docs.example.com |
| GitHub | https://github.com/user/repo |
```

One table, two columns (Label, URL). Command Center's scanner reads this on startup and stores links in the project's `extra` JSON.

## CLAUDE.md Convention

Every project has `CLAUDE.md` at its root with these sections in order:

1. `## Project Overview` — what the project does, key features
2. `## Architecture` — tech stack, key files, patterns
3. `## Dev Commands` — bash commands in a code block
4. `## Service Endpoints` — URLs: `- Label: https://url`
5. `## Bookmarks` — grouped links: `### Group` then `- [Title](URL)`

Section rename rules — always use the standard name:
- `## Commands` / `## Development Commands` / `## Build Commands` → `## Dev Commands`
- `## Overview` / `## Project Purpose` → `## Project Overview`
- `## Stack` → `## Architecture`

## Git Hygiene

Never commit secrets, generated files, or runtime data.

```gitignore
# Runtime
data/
*.db
*.log

# Environment
.env
venv/
node_modules/

# Python
__pycache__/
*.pyc
*.egg-info/
dist/
build/

# OS
.DS_Store
Thumbs.db
```

- `data/` — runtime databases, logs, backups, uploads
- `.env` — secrets and local config; commit `.env.example` with placeholder values
- Write imperative commit messages: "Add health endpoint" not "Added health endpoint"

## Development Workflow

1. **Always commit immediately** after completing a task with no errors.
2. Commit messages: descriptive text, no AI/tool mentions.
3. **DO NOT push** — local commits only.
4. **NO co-authored-by lines**.
5. End code change responses with a restart notice:
   - Templates/CSS/static only: "No restart needed — browser refresh is enough."
   - Python/JS server files: "Restart required — run the start script or equivalent."

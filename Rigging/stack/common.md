# Common Best Practices

**Version:** 20260320 V1  
**Description:** Common development patterns shared across all stack configurations

Always included regardless of technology stack. Covers project structure conventions, shell scripts, metadata files, git hygiene, and development workflow. This file does not change between projects.

---

## 1. Project Directory Layout

**Rule**: Every project follows a predictable directory structure.

```
project-name/
├── bin/                # Operation scripts (see Shell Scripts section)
├── data/               # Runtime data (DB, logs, backups) — gitignored
│   ├── logs/           # Script and process output logs
│   └── backups/        # Database and file backups
├── docs/               # Project documentation
├── tests/              # Test suite
├── PROJECT/            # Build specification (optional, for specification-driven projects)
├── .env                # Environment config — gitignored
├── .env.example        # Template with placeholder values — committed
├── .gitignore
├── CLAUDE.md           # AI agent instructions
└── Links.md            # External links
```

Additional directories depend on the stack (e.g., `templates/`, `static/`, `migrations/`).

**Why**: Consistent layout lets any developer or AI agent locate files instantly.

---

## 2. Shell Scripts (bin/ Directory)

**Rule**: All user-facing operations live in `bin/` as bash scripts with standardized headers, logging, and error handling.

### Script Template

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

### Header Fields

The first comment block is parsed by Command Center's scanner for auto-discovery:

| Field | Required | Values | Description |
|-------|----------|--------|-------------|
| `# CommandCenter Operation` | Yes | literal | Marks script as discoverable |
| `# Name:` | Yes | free text | Display name in UI |
| `# Type:` | No | `daemon` or `batch` | Default: `batch`. Daemons stay running. |
| `# Port:` | No | integer | Port number for daemon services |

Scripts without the `# CommandCenter Operation` header are still valid scripts but won't appear in Command Center's UI.

### Standard Scripts

Every project should have these scripts (where applicable):

| Script | Type | Purpose |
|--------|------|---------|
| `bin/start.sh` | daemon | Start the dev server |
| `bin/stop.sh` | batch | Stop the dev server |
| `bin/test.sh` | batch | Run test suite |
| `bin/build.sh` | batch | Build/compile the project |
| `bin/deploy.sh` | batch | Deploy to production |
| `bin/backup.sh` | batch | Backup data/database |

### Logging Pattern

- All stdout and stderr captured via `tee` to `data/logs/`
- Log filename includes script name and timestamp: `start_2026-03-07_143022.log`
- First lines of log always record: timestamp, arguments, working directory
- These logs are viewable from Command Center's Process Monitor

**Why**: Standardized scripts make every project operable the same way. Log capture enables monitoring, alerting, and post-mortem analysis.

---

## 3. External Links (Links.md)

**Rule**: Every project maintains a `Links.md` file at its root with a markdown table of relevant URLs.

```markdown
| Label | URL |
|-------|-----|
| Local Dev | http://localhost:5001 |
| Production | https://example.com |
| Docs | https://docs.example.com |
| GitHub | https://github.com/user/repo |
```

Rules:
- One table, two columns: Label and URL
- Labels are short and descriptive
- Command Center's scanner reads this on startup and stores links in the project's `extra` JSON
- Links appear in the project's configuration page

**Why**: Centralizes all project URLs in one discoverable, parseable location. Both AI agents and Command Center consume it.

---

## 4. CLAUDE.md Convention

**Rule**: Every project has a `CLAUDE.md` at its root following this section structure:

1. `## Project Overview` — What the project does, key features
2. `## Architecture` — Tech stack, key files, patterns
3. `## Dev Commands` — Bash commands to run the project (in a code block)
4. `## Service Endpoints` — URLs: `- Label: https://url`
5. `## Bookmarks` — Grouped links: `### Group` then `- [Title](URL)`

Section rename rules — always use the standard name:
- `## Commands` / `## Development Commands` / `## Build Commands` → `## Dev Commands`
- `## Overview` / `## Project Purpose` → `## Project Overview`
- `## Stack` → `## Architecture`

**Why**: Consistent structure lets AI agents parse project context reliably.

---

## 5. Git Hygiene

**Rule**: Maintain a comprehensive `.gitignore`. Never commit secrets, generated files, or runtime data.

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

Rules:
- `data/` — runtime databases, logs, backups, uploads
- `.env` — secrets and local config
- Commit `.env.example` with placeholder values
- Write imperative commit messages: "Add health endpoint" not "Added health endpoint"

**Why**: Clean repos are cloneable and runnable. No secrets in history.

---

## 6. Development Workflow

**Rule**: Follow these rules when working in any git-managed project.

1. **Always commit changes immediately** after completing a task if the task has no errors
2. **Commit messages** should have descriptive text (no AI/tool mentions)
3. **DO NOT push** — only commit to local git
4. **NO co-authored-by lines** in commits
5. **Always end code change responses with a restart notice** for any project that runs a web server:
   - If only templates/CSS/static files changed: "No restart needed — browser refresh is enough."
   - If any Python/JS server files changed: "Restart required — run the start script or equivalent."

**Why**: Consistent workflow prevents accidental pushes, keeps commit history clean, and ensures developers know when to restart.

---

## Summary Checklist

- [ ] Standard directory layout with `bin/`, `data/`, `docs/`, `tests/`
- [ ] Shell scripts in `bin/` with CommandCenter headers and tee logging
- [ ] `Links.md` for external URLs
- [ ] `CLAUDE.md` following section convention
- [ ] `.env.example` committed, `.env` gitignored
- [ ] Comprehensive `.gitignore`
- [ ] Commit immediately, don't push, no AI mentions

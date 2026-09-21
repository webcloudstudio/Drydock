<!-- Compacted from Rigging/stack/common.md sha256=40b65983221927449a47ee0257dc247042429f3e68171c645d51a34200b35a14 on 2026-09-20 by drydock rigging compact — regenerate with: drydock rigging compact --include-file {rel_source} -->

# Common Best Practices — Contract Surface

## Project Structure

### Rule: directory-layout
Every project MUST provide the standard root directories and files.

Constraints: Include `bin/`, `data/logs/`, `data/backups/`, `docs/`, `tests/`, optional `PROJECT/`, `.env`, `.env.example`, `.gitignore`, `CLAUDE.md`, and `Links.md`; stack-specific directories may be added.

### Rule: links-file
`Links.md` MUST contain relevant project URLs in a parseable Markdown table.

| Field | Required |
|---|---|
| Label | Yes |
| URL | Yes |

Constraints: The table MUST have exactly two columns, `Label` and `URL`.

### Rule: claude-file
`CLAUDE.md` MUST contain the standard project-context sections.

Constraints: Required sections are `## Project Overview`, `## Architecture`, `## Dev Commands`, `## Service Endpoints`, and `## Bookmarks`; section aliases MUST be renamed to their standard names.

## Shell Scripts

### Rule: user-operations
User-facing operations MUST be implemented as Bash scripts under `bin/`.

Constraints: Scripts MUST use `set -euo pipefail`, resolve project-relative paths, create `data/logs/`, capture output with `tee`, log timestamps, arguments, working directory, and completion status, and execute from the project root.

### Rule: commandcenter-header
Discoverable scripts MUST begin with a Command Center header.

| Field | Required | Values |
|---|---:|---|
| `# CommandCenter Operation` | Yes | Literal |
| `# Name:` | Yes | Free text |
| `# Type:` | No | `daemon` or `batch`; default `batch` |
| `# Port:` | No | Integer |

Constraints: Scripts without the marker remain valid but are not discoverable by Command Center.

### Rule: standard-scripts
Projects SHOULD provide applicable standard operation scripts.

| Script | Type |
|---|---|
| `bin/start.sh` | `daemon` |
| `bin/stop.sh` | `batch` |
| `bin/test.sh` | `batch` |
| `bin/build.sh` | `batch` |
| `bin/deploy.sh` | `batch` |
| `bin/backup.sh` | `batch` |

### Rule: script-logging
Scripts MUST capture stdout and stderr in timestamped log files under `data/logs/`.

Constraints: Log filenames MUST follow `<script>_<YYYY-MM-DD_HHMMSS>.log`; initial log lines MUST record timestamp, arguments, and working directory.

## Repository Hygiene

### Rule: gitignore
Repositories MUST ignore secrets, generated files, and runtime data.

Constraints: `.gitignore` MUST cover `data/`, `*.db`, `*.log`, `.env`, `venv/`, `node_modules/`, Python caches and bytecode, `*.egg-info/`, `dist/`, `build/`, `.DS_Store`, and `Thumbs.db`; `.env.example` MUST be committed with placeholders.

### Rule: commit-workflow
Completed error-free changes MUST be committed locally.

Constraints: Commit messages MUST be imperative and descriptive; changes MUST NOT be pushed; commits MUST NOT contain co-authored-by lines. Web-server projects MUST end change responses with a restart notice indicating whether restart is required.

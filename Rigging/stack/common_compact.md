<!-- Compacted from /mnt/c/Users/barlo/projects/drydock/Rigging/stack/common.md sha256=2d665e4a232b3ef5b681149974e74928c8f5abb9adaac02604cc6b5987ac0f85 on 2026-10-24 by drydock rigging compact — regenerate with: drydock rigging compact --include-file {rel_source} -->

# Common Best Practices — Contract Surface

## Project Layout

### Rule: project-directory-layout

Every project must use the standard root layout and may add stack-specific directories.

Constraints: Include `bin/`, `data/` with `logs/` and `backups/`, `docs/`, `tests/`, optional `PROJECT/`, `.env`, `.env.example`, `.gitignore`, `CLAUDE.md`, and `Links.md`; keep runtime data under `data/`.

## Shell Scripts

### Rule: user-facing-operation-scripts

User-facing operations must be implemented as Bash scripts in `bin/`.

Constraints: Scripts must use standardized headers, `set -euo pipefail`, resolve project-relative paths, create `data/logs/`, log execution details, run from the project root, tee output to console and a timestamped log, and record completion.

### Rule: command-center-discovery-header

A discoverable script must begin with a Command Center header.

| Field | Required | Values |
|---|---:|---|
| `# CommandCenter Operation` | Yes | Literal |
| `# Name:` | Yes | Free text |
| `# Type:` | No | `daemon` or `batch`; defaults to `batch` |
| `# Port:` | No | Integer; daemon port |

Constraints: Scripts without `# CommandCenter Operation` remain valid but are not discoverable by Command Center.

### Rule: standard-scripts

Projects should provide applicable operation scripts with these names and purposes.

| Script | Type | Purpose |
|---|---|---|
| `bin/start.sh` | daemon | Start the development server |
| `bin/stop.sh` | batch | Stop the development server |
| `bin/test.sh` | batch | Run tests |
| `bin/build.sh` | batch | Build or compile |
| `bin/deploy.sh` | batch | Deploy to production |
| `bin/backup.sh` | batch | Back up data or databases |

### Rule: script-logging

Operation scripts must capture stdout and stderr in `data/logs/`.

Constraints: Log filenames must follow `<script>_<YYYY-MM-DD_HHMMSS>.log`; initial log lines must record timestamp, arguments, and working directory.

## Links

### Rule: links-file

Every project must provide a root-level `Links.md` containing one two-column Markdown table.

| Column | Requirement |
|---|---|
| `Label` | Short and descriptive |
| `URL` | Relevant project URL |

Constraints: Command Center reads this table and exposes the links through project configuration.

## Agent Instructions

### Rule: claude-file

Every project must provide a root-level `CLAUDE.md` with the following sections.

| Section | Required content |
|---|---|
| `## Project Overview` | Purpose and key features |
| `## Architecture` | Technology stack, key files, and patterns |
| `## Dev Commands` | Bash project commands in a code block |
| `## Service Endpoints` | `- Label: https://url` entries |
| `## Bookmarks` | Grouped links using `### Group` and `- [Title](URL)` |

Constraints: Normalize equivalent headings to the standard names: `Commands`, `Development Commands`, and `Build Commands` become `Dev Commands`; `Overview` and `Project Purpose` become `Project Overview`; `Stack` becomes `Architecture`.

## Version Control

### Rule: gitignore-and-secrets

Repositories must ignore secrets, generated files, and runtime data.

Constraints: Ignore `data/`, `*.db`, `*.log`, `.env`, `venv/`, `node_modules/`, Python caches and bytecode, `*.egg-info/`, `dist/`, `build/`, `.DS_Store`, and `Thumbs.db`; commit `.env.example` with placeholders.

### Rule: commit-message

Commit messages must use imperative, descriptive text without AI or tool mentions.

## Development Workflow

### Rule: task-commit

Completed, error-free tasks must be committed immediately.

### Rule: local-only-commit

Changes must be committed locally and must not be pushed.

### Rule: co-authorship

Commits must not contain `Co-authored-by` lines.

### Rule: restart-notice

Code-change responses for web-server projects must state whether a restart is required.

Constraints: Template, CSS, or static-only changes require the notice `No restart needed — browser refresh is enough.`; Python or JavaScript server changes require `Restart required — run the start script or equivalent.`

# Drydock

Drydock is an installable Python CLI implementing the governed Drydock Blueprint Methodology.

Copyright (c) 2026 Web Cloud Studio. All rights reserved. See [LICENSE](LICENSE).

---

## Installation

```bash
uv pip install drydock
```

Or from source:

```bash
git clone <repo>
cd Drydock
uv venv
uv pip install -e ".[dev]"
```

## Working Commands

The following commands are fully implemented:

```bash
drydock --help
drydock --version

drydock config show
drydock config set blueprint_directory <path>
drydock config set target_directory <path>

drydock init <Blueprint>
drydock init <Blueprint> --update
drydock init <Blueprint> --force

drydock validate <Blueprint>
drydock validate <Blueprint> --verbose

drydock rigging compact <Blueprint> [--all] [--force]

drydock import <Blueprint> <Source> --format markdown
drydock plan init <Blueprint>
drydock plan create <Blueprint> <Target>
drydock plan approve <Blueprint> <Target>
drydock plan revise <Blueprint> <Target> <Feedback>
drydock plan reject <Blueprint> <Target> <Feedback>
drydock plan show <Blueprint>
drydock build status <Blueprint> <Target>
```

## Deferred Commands

The following commands are registered and visible in help, but not yet
implemented. Each returns a clear message and exits with code `2`:

```bash
drydock document generate <Blueprint> <Target>
drydock document assemble <Blueprint> <Target>
drydock document <Blueprint> <Target>
drydock rigging update <Target>
drydock rigging verify <Target>
drydock build <Blueprint> <Target>
drydock build score <Blueprint> <Target>
drydock iterate <Blueprint> <Target> <BOTH|BLUEPRINT|TGT> <Scope> <Change>
drydock analyze <Blueprint> [<Target>]
drydock import <Blueprint> <Source> --format <source|speckit>
```

## Configuration

Drydock reads these global configuration values:

| Variable | Purpose |
|---|---|
| `BLUEPRINT_DIRECTORY` | Root path containing all Drydock Blueprints |
| `TARGET_DIRECTORY` | Root path containing all target software projects |
| `LLM_PROVIDER` | Subscription CLI provider: `claude` (default) or `codex` |

**Effective-value precedence:**
1. Environment variables `BLUEPRINT_DIRECTORY`, `TARGET_DIRECTORY`, and `LLM_PROVIDER`.
2. Values persisted in the user-scoped Drydock `.env` file.

**Config file location** (OS-appropriate):
- Linux/macOS: `~/.config/drydock/.env`
- Windows: `%APPDATA%\drydock\.env`

Set values with:

```bash
drydock config set blueprint_directory /path/to/blueprints
drydock config set target_directory /path/to/projects
```

`SPECIFICATION_DIRECTORY` and `specification_directory` remain accepted as deprecated migration
aliases for `BLUEPRINT_DIRECTORY` and `blueprint_directory`.

## Source-Tree Launchers

When developing, you can run Drydock without installing it:

```bash
# Bash (Linux/macOS)
bin/drydock.sh --help

# PowerShell (Windows)
bin/drydock.ps1 --help

# Python module
python -m drydock --help
```

All three dispatch to the same CLI entry point as the installed `drydock` command.

PowerShell structural behavior is defined but not runtime-verified in WSL environments.

## LLM Execution Foundation

Application functions pass a fully assembled prompt to the subscription-authenticated CLI runner:

```python
from drydock.llm import run_prompt

result = run_prompt(
    prompt,
    target_directory,
    llm="claude",                 # optional; LLM_PROVIDER or claude default
    model="sonnet",               # optional
    command_name="plan-create",
    parameters={"blueprint": blueprint_name, "block": block_id},
    debug=debug,
    timeout_seconds=3600,
    on_text=lambda chunk: print(chunk, end="", flush=True),
    on_event=handle_structured_event,
)
```

Every run writes timestamped prompt, human log, raw provider output, final output, and stderr files
under `<Target>/logs/`. `<Target>/logs/executions.jsonl` contains one self-contained JSON object per
run with the effective argv, working directory, caller parameters, artifact paths, hashes, status,
and parsed provider statistics. The JSONL file is append-only and intentionally extensible for
future provenance and staleness fields.

Provider JSONL is read while the process runs. `on_text` receives Claude partial text deltas or
Codex agent-message steps immediately; `on_event` receives structured Drydock lifecycle and
provider events. The same events are appended immediately to `<Target>/logs/events.jsonl`.
Timeouts terminate the child process and return exit code `124`; interruption terminates the child,
records exit code `130`, and re-raises `KeyboardInterrupt`.

Material Drydock product decisions and delivery milestones are separate from execution mechanics.
Agents developing Drydock follow `SHIPS_LOG_PROCESS.md` and use the repository-local utility:

```text
python bin/ships_log.py record --event-type decision --title "..." --summary "..." \
  --rationale "..." --source-type agent [--scope ...] [--evidence ...] [--tag ...]
python bin/ships_log.py audit
```

The sole Ship's Log artifact is Drydock's `logs/ships_log.jsonl`. It is append-only, rendered by
QuarterDeck's generic JSONL viewer, and intended as the direct input to downstream publishing
tools. It is not a public `drydock` command or a target-project Rigging rule. No Markdown Ship's Log
is generated.

## Project Governance Documents

- `docs/Drydock_Specification.md` — sole authoritative Drydock behavior specification; agents
  require product-owner approval before changing it.
- `docs/SOUNDINGS.md` — authoritative implementation acceptance/readiness checklist and completion
  evidence.
- `docs/SEA_TRIALS.md` — strategic product outcomes and proof-of-methodology criteria.
- `SHIPS_LOG_PROCESS.md` — mandatory Drydock-only agent decision-capture process.

QuarterDeck exposes these documents and the other owned artifacts under `docs/` directly.

`LLM_PROVIDER=claude|codex` may be set in the process environment or user-scoped Drydock `.env`;
the process environment takes precedence and Claude is the default. API-key environment variables
are removed before invoking either CLI.

## Packaged Rigging Resources

The installed wheel contains a synchronized copy of the Drydock Rigging at
`drydock/resources/Rigging/`. This is the same tree as the root-level `Rigging/`
directory; it is included so `drydock init` and `drydock validate` work from an
installed wheel without access to the source checkout.

When running from the source tree, Drydock uses the root-level `Rigging/` directly.
When running from an installed wheel, it falls back to `importlib.resources`.

## License

Proprietary — Web Cloud Studio. See [LICENSE](LICENSE) for terms.
No part of this software may be used without explicit written permission.

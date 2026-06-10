# Drydock

Drydock is an installable Python CLI for specification-driven software delivery.

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
drydock config set specification_directory <path>
drydock config set target_directory <path>

drydock init <Spec>
drydock init <Spec> --update
drydock init <Spec> --force

drydock validate <Spec>
drydock validate <Spec> --verbose
```

## Deferred Commands

The following commands are registered and visible in help, but not yet
implemented. Each returns a clear message and exits with code `2`:

```bash
drydock document generate <Spec> <Target>
drydock document assemble <Spec> <Target>
drydock document <Spec> <Target>
drydock rigging compact <Spec>
drydock rigging update <Target>
drydock rigging verify <Target>
drydock plan init <Spec>
drydock plan create <Spec>
drydock plan show <Spec>
drydock build status <Spec> <Target>
drydock build <Spec> <Target>
drydock build score <Spec> <Target>
drydock iterate <Spec> <Target> <BOTH|SPEC|TGT> <Scope> <Change>
drydock analyze <Spec> [<Target>]
drydock import <Spec> <Target> --format <auto|source|speckit>
```

## Configuration

Drydock reads two global configuration values:

| Variable | Purpose |
|---|---|
| `SPECIFICATION_DIRECTORY` | Root path containing all Drydock Specifications |
| `TARGET_DIRECTORY` | Root path containing all target software projects |

**Effective-value precedence:**
1. Environment variables `SPECIFICATION_DIRECTORY` and `TARGET_DIRECTORY`.
2. Values persisted in the user-scoped Drydock `.env` file.

**Config file location** (OS-appropriate):
- Linux/macOS: `~/.config/drydock/.env`
- Windows: `%APPDATA%\drydock\.env`

Set values with:

```bash
drydock config set specification_directory /path/to/specs
drydock config set target_directory /path/to/projects
```

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

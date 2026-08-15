# Installing Drydock

Drydock is a Python command-line application. The PyPI package is named
`drydock-sdd`; the installed command is `drydock`.

Installation adds the command, Rigging rules, Blueprint templates, prompts, and
QuarterDeck runtime. It does not create or own your workspace, Targets, or generated
applications.

## Before you begin

1) Install Python 3.11 or later.

```bash
python3 --version
```

2) Install `uv` (recommended).

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh        # macOS and Linux
brew install uv                                        # macOS with Homebrew
winget install --id=astral-sh.uv -e                    # Windows with WinGet

# Windows PowerShell:
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

3) Install and authenticate the `claude` or `codex` CLI, then put it in your `PATH`.
Drydock uses your subscription-authenticated CLI. It does not use API keys or bill per
token.

## 1. Install Drydock

```bash
# Recommended — isolated tool install:
uv tool install drydock-sdd

# Alternative with pipx:
pipx install drydock-sdd

# Or install into the active Python environment:
python -m pip install drydock-sdd
```

`uv tool` and `pipx` install Drydock in a dedicated environment and put the command on
your `PATH`. A `pip` installation uses the active Python environment.

Review the installation:

```bash
drydock --version
drydock --help
```

If `drydock` is not found, run `uv tool update-shell` or `pipx ensurepath`, then open a
new shell.

## 2. Select Your LLM Provider

```bash
drydock config set llm_provider claude      # or: codex
claude --version                            # or: codex --version
```

The provider command must resolve, be authenticated, and match `llm_provider`.
Deterministic commands work without it; LLM-assisted commands do not.

## 3. Configure Your Directories

Drydock uses two directories:

* `drydock_workspace` holds Targets, Blueprints, evidence, and logs.
* `drydock_build_directory` holds generated applications.

Create both directories, configure them, and review the result:

```bash
export PROJECTS="$HOME/projects"
mkdir -p "$PROJECTS/drydock"

drydock config set drydock_workspace "$PROJECTS/drydock"
drydock config set drydock_build_directory "$PROJECTS"
drydock config show
```

```text
$PROJECTS/
├── drydock/
│   ├── targets/        # Created by drydock init
│   └── logs/           # Created when commands run
└── <Target>/           # Generated application
```

Do not create `targets/` by hand. `drydock init <Target>` creates the Target workspace.

Configuration is user-scoped:

| Platform | Configuration file |
|---|---|
| Linux and macOS | `$XDG_CONFIG_HOME/drydock/.env`, or `~/.config/drydock/.env` |
| Windows | `%APPDATA%\drydock\.env` |

Environment variables override saved configuration for the current process:

| Configuration key | Environment variable |
|---|---|
| `drydock_workspace` | `DRYDOCK_WORKSPACE` |
| `drydock_build_directory` | `DRYDOCK_BUILD_DIRECTORY` |
| `drydock_model` | `DRYDOCK_MODEL` |
| `llm_provider` | `LLM_PROVIDER` |
| `prompt_warn_tokens` | `PROMPT_WARN_TOKENS` |
| `quarterdeck_port` | `QUARTERDECK_PORT` |

Your installation is ready. Continue with the [Quick Start Guide](QUICK_START.md).

## Optional: PDF Publishing

`drydock publish --pdf` and `drydock document --pdf` require the `pdf` extra and local
Chromium:

```bash
uv tool install "drydock-sdd[pdf]"
playwright install chromium
```

## Optional: Agent Skills

Drydock includes `/refit`, `/apply-refit`, and `/drydock-uat` skills. `drydock init`
provisions them into managed workspaces for Claude Code and Codex. To install them globally for
Claude Code, copy them into `~/.claude/skills/`:

```bash
python -c "import shutil, pathlib; from drydock.paths import get_rigging_root; \
dest = pathlib.Path.home() / '.claude' / 'skills'; \
[shutil.copytree(s, dest / s.name, dirs_exist_ok=True) \
for s in (get_rigging_root() / 'skills').iterdir()]"
```

## Upgrade or Remove Drydock

```bash
uv tool upgrade drydock-sdd
# or: pipx upgrade drydock-sdd
# or: python -m pip install --upgrade drydock-sdd
```

Remove the package with the matching installer. Removal does not delete your
configuration, workspace, Targets, or generated applications.

## Install from Source

For contributors:

```bash
git clone https://github.com/webcloudstudio/Drydock.git
cd Drydock
uv venv
uv pip install -e ".[dev]"
drydock --help
```

## Troubleshooting

| Symptom | Fix |
|---|---|
| `drydock: command not found` | Run `uv tool update-shell` or `pipx ensurepath`, then open a new shell. |
| LLM command fails immediately | Verify `claude --version` or `codex --version`, authentication, and `llm_provider`. |
| `workspace not configured` | Set `drydock_workspace`, then run `drydock config show`. |
| Wrong workspace used | Unset the overriding `DRYDOCK_WORKSPACE` environment variable. |
| `--pdf` fails | Install the `pdf` extra, then run `playwright install chromium`. |

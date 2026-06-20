# Installing Drydock

Drydock is a Python command-line application. Installation places the `drydock`
executable and its versioned application resources in a Python environment. It
does not create a project, a Blueprint, or a workspace in the user's home
directory.

This guide assumes the following are already true:

- Python 3.11 or later is available.
- `drydock` is installed and resolves on `PATH`.
- `$PROJECTS` names an existing directory that holds the user's projects.

For example:

```bash
export PROJECTS="$HOME/projects"
mkdir -p "$PROJECTS"
drydock --version
```

## Install the command

The PyPI distribution is named `drydock-sdd`; the installed command is named
`drydock`.

Install it as an isolated command-line tool:

```bash
uv tool install drydock-sdd
```

Alternatively, use `pipx`:

```bash
pipx install drydock-sdd
```

For a Python virtual environment, install with pip:

```bash
python -m pip install drydock-sdd
```

Verify the installation:

```bash
drydock --version
drydock --help
```

`uv tool` and `pipx` install the command in an isolated Python environment and
place a command wrapper on `PATH`. They are the recommended installation modes
for an interactive CLI. `pip install` installs Drydock and its Python
dependencies into the active virtual environment.

## Configure the workspace

Use `$PROJECTS/drydock` as the Drydock workspace. Use `$PROJECTS` as the root
where Drydock writes generated applications. Both directories must exist before
they are configured.

```bash
mkdir -p "$PROJECTS/drydock"

drydock config set drydock_workspace "$PROJECTS/drydock"
drydock config set drydock_build_directory "$PROJECTS"
drydock config show
```

The resulting layout is:

```text
$PROJECTS/
├── drydock/                         # Drydock workspace
│   ├── targets/                     # Created by `drydock init`
│   └── logs/                        # Created when commands run
└── <Target>/                        # Generated application output
```

Do not create `targets/` manually. `drydock init <Target>` creates it and
creates the target baseline.

## Create the first target

```bash
drydock init Example
drydock status
```

This creates the user-owned target workspace:

```text
$PROJECTS/drydock/targets/Example/
├── blueprint/
│   └── sources/
├── evidence/
├── logs/
├── QuarterDeck/
│   └── console.yaml
└── METADATA.md
```

The target name is a logical identifier, not a path. It cannot contain path
separators or `..`.

## Persistent configuration and overrides

`drydock config set` writes per-user configuration; it does not modify the
installed package. Its file location is:

| Platform | Configuration file |
|---|---|
| Linux and macOS | `$XDG_CONFIG_HOME/drydock/.env`, or `~/.config/drydock/.env` when `XDG_CONFIG_HOME` is unset |
| Windows | `%APPDATA%\\drydock\\.env` |

Environment variables override saved configuration for a single command. This
is appropriate for CI and for switching workspaces temporarily:

```bash
DRYDOCK_WORKSPACE="$PROJECTS/client-a/drydock" drydock status
```

The configurable values are:

| CLI key | Environment variable | Purpose |
|---|---|---|
| `drydock_workspace` | `DRYDOCK_WORKSPACE` | Workspace containing `targets/` and workspace logs |
| `drydock_build_directory` | `DRYDOCK_BUILD_DIRECTORY` | Root containing generated application directories |
| `drydock_model` | `DRYDOCK_MODEL` | Model selection for supported LLM-assisted commands |
| `llm_provider` | `LLM_PROVIDER` | Subscription CLI provider: `claude` or `codex` |
| `prompt_warn_kb` | `PROMPT_WARN_KB` | Prompt-size warning threshold in KiB |
| `quarterdeck_port` | `QUARTERDECK_PORT` | Default QuarterDeck port |

## What installation provides

The `drydock-sdd` distribution installs:

- the `drydock` Python package and command-line entry point;
- Drydock's versioned Rigging rules and Blueprint templates;
- versioned prompt contracts;
- the QuarterDeck runtime template; and
- required Python runtime dependencies.

The installation does not create or own a user project. The following data is
created under the configured workspace by Drydock commands and remains owned by
the user:

- Targets and their Blueprints;
- manifests, evidence, Sea Trials, Soundings, and logs;
- QuarterDeck target configuration and state; and
- generated application code under `drydock_build_directory`.

The installed resources are coupled to the installed Drydock release. Upgrading
`drydock-sdd` upgrades the command and its packaged rules, templates, prompts,
and QuarterDeck runtime together. Existing targets remain in the configured
workspace and are not rewritten by installation or upgrade.

## Canonical product specification release status

The canonical Drydock product specification is intended to be a versioned,
read-only resource of the Drydock release. It is distinct from a user's
Blueprint.

The current wheel configuration packages Rigging, prompts, and QuarterDeck, but
does **not** package `docs/Drydock_Specification.md`. An installed release
therefore cannot yet load that specification from package resources. Until the
wheel includes it and `paths.py` resolves it in installed mode, operations that
require the product specification require a source checkout.

Release engineering must add the specification to the wheel and validate the
installed-wheel path before documenting it as available to `drydock` users.

## Upgrade and removal

Upgrade the CLI without touching user workspaces:

```bash
uv tool upgrade drydock-sdd
# or: pipx upgrade drydock-sdd
# or, in an active virtual environment: python -m pip install --upgrade drydock-sdd
```

Uninstalling the Python distribution removes the command and packaged resources
only. It does not remove the user configuration file, `$PROJECTS/drydock`, or
generated applications under `$PROJECTS`.

## Release verification

Before publishing a release, build a clean wheel and inspect it:

```bash
python -m hatchling build
unzip -l dist/drydock_sdd-*.whl
```

The wheel must contain the `drydock` package, `drydock/resources/Rigging/`,
`drydock/resources/prompts/`, `drydock/resources/QuarterDeck/`, and, once the
canonical-specification release work is complete,
`drydock/resources/docs/Drydock_Specification.md`.

Install the wheel into an isolated environment and run `drydock --version`,
`drydock config show`, and `drydock init Example` against a temporary
`$PROJECTS` directory. This validates the artifact a PyPI user receives rather
than only the source checkout.

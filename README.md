<div align="center">

<img src="docs/drydock_logo.png" alt="Drydock" width="160" />

# Drydock

**Drydock turns specifications into working software.**

Specification driven. Agile. Test driven. Dependency-aware builds. A dedicated web console.
Enterprise guardrails on your existing subscription.

[![PyPI](https://img.shields.io/pypi/v/drydock-sdd.svg)](https://pypi.org/project/drydock-sdd/)
[![Python](https://img.shields.io/pypi/pyversions/drydock-sdd.svg)](https://pypi.org/project/drydock-sdd/)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![CI](https://github.com/webcloudstudio/Drydock/actions/workflows/ci.yml/badge.svg)](https://github.com/webcloudstudio/Drydock/actions/workflows/ci.yml)

### ▶ START HERE — [Quick Start](https://webcloudstudio.com/project-docs/drydock/QUICK_START.html)

[Specification](https://webcloudstudio.com/project-docs/drydock/index_sections/introduction.html) · [Installation](https://webcloudstudio.com/project-docs/drydock/USER_INSTALLATION.pdf) · [Comparison matrix](https://webcloudstudio.com/project-docs/drydock/papers/Product_Comparison_Matrix.html) · [Overview deck](https://webcloudstudio.com/drydock/) · [Contributing](CONTRIBUTING.md)

</div>

---

## What Drydock is

Drydock imports source material into typed Blueprints. A Manifest relates and orders their stories.
Each story has measurable, test-driven acceptance criteria.

- **Specification driven.** Typed specifications are the source of truth. Code is the output.
- **Agile.** Features and stories are reviewed before build.
- **Context-aware.** Related stories build together with only the specifications they need.
- **Guarded.** Questions replace guesses. Dependencies are declared.
- **Change controlled.** `drydock refit` maps changes to affected work.
- **Your subscription.** Runs on the `claude` or `codex` CLI. No API key, no per-token billing.

## Getting started

**Before you begin**

- [ ] Python 3.11 or later — `python3 --version`
- [ ] `uv` — `curl -LsSf https://astral.sh/uv/install.sh | sh` (macOS/Linux), `brew install uv`, or `winget install --id=astral-sh.uv -e` (Windows)
- [ ] The `claude` or `codex` CLI, authenticated and on your `PATH`

**1. Install Drydock**

```bash
uv tool install drydock-sdd     # or: pipx install drydock-sdd
drydock --version
```

If `drydock` is not found, run `uv tool update-shell` or `pipx ensurepath`, then open a new shell.

**2. Configure**

```bash
# Claude
drydock config set llm_provider claude
drydock config set drydock_model sonnet

# Codex alternative
# drydock config set llm_provider codex
# drydock config set drydock_model gpt-5.4

export PROJECTS="$HOME/projects"
mkdir -p "$PROJECTS/drydock"

drydock config set drydock_workspace "$PROJECTS/drydock"
drydock config set drydock_build_directory "$PROJECTS"
drydock config show

# $PROJECTS/
# ├── drydock/
# │   ├── targets/        # Target workspaces
# │   └── logs/           # Drydock logs
# └── <Target>/           # Generated application
```

The [Quick Start](https://webcloudstudio.com/project-docs/drydock/QUICK_START.html) builds a real
project step by step. Upgrades, PDF publishing, and troubleshooting are in the
[User Installation Guide](https://webcloudstudio.com/project-docs/drydock/USER_INSTALLATION.pdf).

**3. Build your first project**

```bash
drydock init MyApp
drydock import MyApp specification.md
drydock analyze MyApp
drydock plan MyApp
drydock build MyApp
```

## The Drydock CLI

`ai` calls your subscription CLI agent; all other commands are deterministic.

```text
# ── S ── SET UP ──────────────────────────────────────────────────────────
    drydock config show                        # Show configuration values and sources
    drydock config set        <var> <value>    # Set a configuration value
    drydock init              MyApp            # Create the target workspace
    drydock status                             # Status dashboard
    drydock status            MyApp            # Summary and plan state

# ── A ── ANALYZE ─────────────────────────────────────────────────────────
    drydock import            MyApp <file|dir> # Import sources into the workspace
ai  drydock analyze           MyApp            # Epic decomposition into stories & blockers
    drydock validate          MyApp            # Validate Build Plan
ai  drydock score spec        MyApp            # Audit imported raw specifications
    drydock run quarterdeck   MyApp            # Web interface
ai  drydock plan              MyApp            # Grooming and dependency graph

# ── I ── IMPLEMENT ───────────────────────────────────────────────────────
ai  drydock build             MyApp            # Iterative context-aware process
    drydock build status      MyApp            # Show build state
    drydock score ac          MyApp            # Verify Story acceptance criteria
    drydock score build       MyApp            # Post-build report: repairs, tokens, cache
ai  drydock score release     MyApp            # Score project success criteria (EARS)

# ── L ── LOOP ────────────────────────────────────────────────────────────
ai  drydock refit             MyApp            # Diff -> ticket -> dependency graph
ai  drydock document          MyApp            # Project documentation automation
ai  drydock document generate MyApp            # AI pass only
    drydock document assemble MyApp            # Assembly only
    drydock publish           <Source.md>      # Render Markdown to HTML/PDF
```

## Build workflow

`analyze` → `plan` → `build` → change → `refit` → `build`

| Stage | Command | What it does |
|---|---|---|
| **Analyze** | `drydock analyze <Target>` | Decomposes imported source material into stories, acceptance criteria, questions, and blockers for review.<br>**Creates:** `ANALYSIS.md`, `SEA_TRIALS.md`, `BLOCKERS.md` when blocked, and review questionnaires. |
| **Plan** | `drydock plan <Target>` | Converts the reviewed analysis into typed Blueprints and a dependency-aware `MANIFEST.md` build plan.<br>**Creates:** Blueprint specifications and `MANIFEST.md`. |
| **Build** | `drydock build <Target>` | Executes dependency-ready work in context-aware blocks and verifies each story against its acceptance criteria.<br>**Creates:** working software and tests. |
| **Refit** | `drydock refit <Target>` | Maps specification changes and change tickets to affected Manifest work so only the impacted scope is rebuilt.<br>**Creates:** an updated `MANIFEST.md` and, after `build`, updated working software. |

## The QuarterDeck Web Server

QuarterDeck is the Agile web surface between the Commander (product owner) and Crew (LLM agents).
It presents questionnaires, decisions, stories, Blueprints, and the Manifest.

```bash
drydock run quarterdeck <Target>
```

![QuarterDeck Commander's Chair](docs/QuickStart_Analysis_Screen.png)

The Target workspace is `<drydock_workspace>/targets/<Target>/`; the application is built in
`<drydock_build_directory>/<Target>/`.

## Documentation

| Resource | Web | PDF |
|---|---|---|
| Quick Start | [HTML](https://webcloudstudio.com/project-docs/drydock/QUICK_START.html) | [PDF](https://webcloudstudio.com/project-docs/drydock/QUICK_START.pdf) |
| User Installation Guide | — | [PDF](https://webcloudstudio.com/project-docs/drydock/USER_INSTALLATION.pdf) |
| Drydock Specification | [HTML](https://webcloudstudio.com/project-docs/drydock/index_sections/introduction.html) | [PDF](https://webcloudstudio.com/project-docs/drydock/Drydock_Specification.pdf) |
| Product Comparison Matrix | [HTML](https://webcloudstudio.com/project-docs/drydock/papers/Product_Comparison_Matrix.html) | [PDF](https://webcloudstudio.com/project-docs/drydock/papers/Product_Comparison_Matrix.pdf) |
| Overview deck | [Web](https://webcloudstudio.com/drydock/) | — |
| Walkthrough video | [MP4](https://webcloudstudio.com/project-docs/drydock/presentation/PRODUCTION_Drydock_Video.web.mp4) | — |
| Release history | [CHANGELOG.md](CHANGELOG.md) | — |
| Contributor guide | [CONTRIBUTING.md](CONTRIBUTING.md) | — |

## Security

Drydock executes imported specifications through local CLI agents. Use trusted sources or isolate
the build environment. See [Drydock Security](https://webcloudstudio.com/project-docs/drydock/index_sections/drydock-security.html).

## Contributing

Help test Drydock on real projects. Open an [issue](https://github.com/webcloudstudio/Drydock/issues)
or see [CONTRIBUTING.md](CONTRIBUTING.md). Code changes are preferred.

## License

[MIT](LICENSE) — Copyright (c) 2026 Web Cloud Studio. "Drydock" is a trademark of Web Cloud Studio;
see [NOTICE](NOTICE) and [CONTRIBUTORS.md](CONTRIBUTORS.md).

<div align="center">

<img src="docs/drydock_logo.png" alt="Drydock" width="160" />

# Drydock

**Drydock turns specifications into working software.**

Specification Driven Software Delivery. Agile. Test Driven. A dependency graph of stories.
Context compression. A web console. Enterprise guardrails on the subscription you already have.

[![PyPI](https://img.shields.io/pypi/v/drydock-sdd.svg)](https://pypi.org/project/drydock-sdd/)
[![Python](https://img.shields.io/pypi/pyversions/drydock-sdd.svg)](https://pypi.org/project/drydock-sdd/)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![CI](https://github.com/webcloudstudio/Drydock/actions/workflows/ci.yml/badge.svg)](https://github.com/webcloudstudio/Drydock/actions/workflows/ci.yml)

### ▶ START HERE — [Quick Start](https://webcloudstudio.com/project-docs/drydock/QUICK_START.html)

[Specification](https://webcloudstudio.com/project-docs/drydock/index_sections/introduction.html) · [Installation](https://webcloudstudio.com/project-docs/drydock/USER_INSTALLATION.pdf) · [Comparison matrix](https://webcloudstudio.com/project-docs/drydock/papers/Product_Comparison_Matrix.html) · [Overview deck](https://webcloudstudio.com/drydock/) · [Contributing](CONTRIBUTING.md)

</div>

---

## What Drydock is

**Drydock turns specifications into working software.**

Drydock imports your source material using agile best practices into typed blueprints representing stories related with a graph database.  This enables drydock to context aware build your application.  Stories have measurable test driven acceptance criteria.

- **Specification driven.** Typed specifications are the source of truth. Code is the output.
- **Agile.** The specification is decomposed into features and stories, with product-owner review before the build starts.
- **Test driven.** Acceptance criteria are written into the blueprints.
- **A dependency graph of stories.** `MANIFEST.md` relates and orders the work and build.
- **Context compression and optimization.** Context aware builds let small models carry the load.
- **Web interface.** Guided dedicated web console
- **Enterprise guardrails.** Blocking questions instead of guesses, declared dependencies instead of improvised ones, and durable evidence for every step.
- **Change control.** Edit the specification; `drydock refit` writes a change ticket against each affected Blueprint and rebuilds only the work that moved.
- **Your subscription.** Runs on the `claude` or `codex` CLI. No API key, no per-token billing.

## Documentation

| | | |
|---|---|---|
| Quick Start | [HTML](https://webcloudstudio.com/project-docs/drydock/QUICK_START.html) | [PDF](https://webcloudstudio.com/project-docs/drydock/QUICK_START.pdf) |
| User Installation Guide | | [PDF](https://webcloudstudio.com/project-docs/drydock/USER_INSTALLATION.pdf) |
| Drydock Specification | [HTML](https://webcloudstudio.com/project-docs/drydock/index_sections/introduction.html) | [PDF](https://webcloudstudio.com/project-docs/drydock/Drydock_Specification.pdf) |
| Product Comparison Matrix | [HTML](https://webcloudstudio.com/project-docs/drydock/papers/Product_Comparison_Matrix.html) | [PDF](https://webcloudstudio.com/project-docs/drydock/papers/Product_Comparison_Matrix.pdf) |
| Overview deck | [Web](https://webcloudstudio.com/drydock/) | |
| Walkthrough video | [MP4](https://webcloudstudio.com/project-docs/drydock/presentation/PRODUCTION_Drydock_Video.web.mp4) | |
| Release history | [CHANGELOG.md](CHANGELOG.md) | |
| Contributor guide | [CONTRIBUTING.md](CONTRIBUTING.md) | |

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

**2. Select your provider**

```bash
drydock config set llm_provider claude      # or: codex
claude --version                            # must resolve and be authenticated
```

**3. Configure your directories**

`drydock_workspace` holds Targets, Blueprints, evidence, and logs. `drydock_build_directory` holds
the generated applications.

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

The [Quick Start](https://webcloudstudio.com/project-docs/drydock/QUICK_START.html) builds a real
project step by step. Upgrades, PDF publishing, and troubleshooting are in the
[User Installation Guide](https://webcloudstudio.com/project-docs/drydock/USER_INSTALLATION.pdf).

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
    drydock build verify      MyApp <step>     # Display/Verify build graph
ai  drydock build score       MyApp            # Generate SCORECARD.md
    drydock score ac          MyApp            # Verify Story acceptance criteria
    drydock score build       MyApp            # Post-build report: repairs, tokens, cache
ai  drydock score release     MyApp            # Score project success criteria (EARS)

# ── L ── LOOP ────────────────────────────────────────────────────────────
ai  drydock refit             MyApp            # Diff -> ticket -> dependency graph
ai  drydock document          MyApp            # Project documentation automation
ai  drydock document generate MyApp            # AI pass only
    drydock document assemble MyApp            # Assembly only
    drydock publish           <Source.md>      # Render Markdown to HTML/PDF
ai  drydock rigging compact                    # Automanage compaction
    drydock rigging verify                     # Verify rigging compliance
ai  drydock score drydock                      # Adversarial self-assessment
ai  drydock uat               [Project]        # scored uat testing
```

## Build workflow

Import the source specification once, then move through three delivery stages. Use `refit` to route
later changes back into the build.

`analyze` → `plan` → `build` · changes → `refit` → `build`

| Stage | Command | What it does |
|---|---|---|
| **Analyze** | `drydock analyze <Target>` | Decomposes imported source material into stories, acceptance criteria, questions, and blockers for review. |
| **Plan** | `drydock plan <Target>` | Converts the reviewed analysis into typed Blueprints and a dependency-aware `MANIFEST.md` build plan. |
| **Build** | `drydock build <Target>` | Executes dependency-ready work in context-aware blocks and verifies each story against its acceptance criteria. |
| **Refit** | `drydock refit <Target>` | Maps specification changes and change tickets to affected Manifest work so only the impacted scope is rebuilt. |

Review each stage and resolve blockers in QuarterDeck before continuing. The Blueprint remains the
source of truth; the application is its built output.

The Target workspace is `<drydock_workspace>/targets/<Target>/`; the application is built in
`<drydock_build_directory>/<Target>/`.

## Contributing

Welcome aboard. The most useful contribution right now is a real project.

Build something you care about with Drydock and tell us where it broke: which specification
confused the planner, which build step needed a rescue, which evidence you wanted and could not
find. Open an [issue](https://github.com/webcloudstudio/Drydock/issues) with the Target, the
command, and what you expected. A failed build report is worth more than a compliment.

To work on Drydock itself, start with [CONTRIBUTING.md](CONTRIBUTING.md).

Report a vulnerability privately through a
[GitHub security advisory](https://github.com/webcloudstudio/Drydock/security/advisories/new).

## License

MIT License — Copyright (c) 2026 Web Cloud Studio.

```text
Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

"Drydock" is a trademark of Web Cloud Studio; see [NOTICE](NOTICE) for use of the name in forks and
derivative works. See [CONTRIBUTORS.md](CONTRIBUTORS.md) for contributors.

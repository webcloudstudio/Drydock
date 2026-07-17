<div align="center">

<img src="docs/drydock_logo.png" alt="Drydock" width="160" />

# Drydock

**The missing process layer for specification-driven development.**

Drydock gives specification-driven development the part it skipped: a repeatable <strong><font color="#0a5c38">Agile</font></strong> delivery and <strong><font color="#0a5c38">Test Driven Development</font></strong> based end-to-end process that turns specs into reviewed plans, context-managed builds, and obvious ways to maintain.

[![PyPI](https://img.shields.io/pypi/v/drydock-sdd.svg)](https://pypi.org/project/drydock-sdd/)
[![Python](https://img.shields.io/pypi/pyversions/drydock-sdd.svg)](https://pypi.org/project/drydock-sdd/)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![CI](https://github.com/webcloudstudio/Drydock/actions/workflows/ci.yml/badge.svg)](https://github.com/webcloudstudio/Drydock/actions/workflows/ci.yml)

[Install](#install) · [60-Second Example](#60-second-example) · [Why It Is Different](#why-it-is-different) · [Canonical Specification](https://webcloudstudio.com/project-docs/drydock/)
[Overview Deck](https://webcloudstudio.com/drydock/) · [White Paper](https://zenodo.org/records/21287574) · [10 Minute Overview](https://webcloudstudio.com/project-docs/drydock/presentation/Drydock_Video.web.mp4) · [User Installation Guide](https://webcloudstudio.github.io/Drydock/USER_INSTALLATION.html)

</div>

---

```bash
uv tool install drydock-sdd     # then: drydock init MyApp && drydock status
```

Drydock runs on your existing Claude or Codex subscription CLI. It does not require
API keys or per-token API billing.

Drydock adds the missing process layer to specification-driven development: import
source material, analyze it into stories and acceptance criteria, review decisions in
the QuarterDeck, plan a dependency graph, build one context-optimized step at a time,
verify evidence, and keep the Blueprint and software aligned as the product changes.

> **You are the Commander** — the product owner. The LLM is your Agile delivery team.
> Drydock makes that relationship explicit, reviewable, and repeatable.

Copyright (c) 2026 Web Cloud Studio. Licensed under the MIT License. See [LICENSE](LICENSE).

## 60-Second Example

```bash
uv tool install drydock-sdd

drydock config set llm_provider claude
drydock init MyApp --description "A small web application."
drydock import MyApp ./notes --format markdown
drydock analyze MyApp
drydock run quarterdeck MyApp
drydock plan MyApp
drydock run quarterdeck MyApp
drydock build MyApp
# Edit Some Blueprints
drydock refit MyApp
drydock build MyApp
```

That loop creates a Target workspace, decomposes the source material, opens the
Commander review surface, builds a dependency graph, and executes the first runnable
frontier with persisted evidence.

## What Drydock Is

Drydock is an installable Python command-line package. The PyPI distribution is
`drydock-sdd`; the installed command is `drydock`.

Drydock implements the SAIL methodology:

| Phase | Purpose | Primary commands |
|---|---|---|
| Set Up | Install, configure, and initialize a Target workspace | `config`, `init`, `status` |
| Analyze | Import material and decompose it into stories, blockers, and acceptance milestones | `import`, `analyze`, `run quarterdeck`, `plan` |
| Implement | Build the Manifest frontier and verify evidence | `build`, `build status`, `build verify`, `rigging`, `document` |
| Loop | Manage change while preserving the Blueprint as source of truth | `refit`, `build`, `document` |

The core idea is simple: reproducible LLM builds require a process. Drydock uses
Agile structure, explicit product-owner review, durable evidence, and context-managed
build prompts so generated software can be inspected, repeated, and iterated.

## Subscription CLI Requirement

Drydock is for subscription-authenticated CLI users.

It does not use API-key-backed model calls and does not require per-token API billing.
LLM-assisted commands execute through a locally authenticated provider CLI:

- `claude` for Anthropic Claude subscription CLI users.
- `codex` for OpenAI Codex subscription CLI users.

Set the provider with:

```bash
drydock config set llm_provider claude
# or
drydock config set llm_provider codex
```

The provider CLI must already be installed, authenticated, and available on `PATH`.
Deterministic commands such as `status`, `validate`, `document assemble`, and `publish`
do not call an LLM.

## Install

Python 3.11 or later is required.

Recommended:

```bash
uv tool install drydock-sdd
```

Alternative:

```bash
pipx install drydock-sdd
```

Virtual environment install:

```bash
python -m pip install drydock-sdd
```

Verify:

```bash
drydock --version
drydock --help
```

PDF publishing (`drydock publish --pdf`) is optional and requires the `pdf` extra plus a
local Chromium download:

```bash
uv tool install "drydock-sdd[pdf]"
playwright install chromium
```

See [docs/USER_INSTALLATION.md](docs/USER_INSTALLATION.md) for the full installation
guide.

### Optional: Claude Code skills

Drydock ships two Claude Code skills that support the Loop phase: `/refit` (design
discussion captured to a notes file in the Target directory) and `/apply-refit` (turn the
captured decisions into change tickets). Installing them is optional:

```bash
python -c "import shutil, pathlib; from drydock.paths import get_rigging_root; \
dest = pathlib.Path.home() / '.claude' / 'skills'; \
[shutil.copytree(s, dest / s.name, dirs_exist_ok=True) \
 for s in (get_rigging_root() / 'skills').iterdir()]"
```

The skills are copied from the packaged `Rigging/skills/` directory into
`~/.claude/skills/`. See [docs/Drydock_SKILLS.md](docs/Drydock_SKILLS.md) for usage.

## Quick Start

Create one projects directory, configure Drydock's workspace and build output root, and
initialize a Target.

```bash
export PROJECTS="$HOME/projects"
mkdir -p "$PROJECTS/drydock"

drydock config set drydock_workspace "$PROJECTS/drydock"
drydock config set drydock_build_directory "$PROJECTS"
drydock config set llm_provider claude

drydock init MyApp --display-name "My App" --description "A working software product."
drydock status
```

Import source material and run the planning loop:

```bash
drydock import MyApp ./notes --format markdown
drydock analyze MyApp
drydock run quarterdeck MyApp
drydock plan MyApp
drydock build status MyApp
```

Build and verify one frontier at a time:

```bash
drydock build MyApp
drydock build status MyApp
drydock build verify MyApp <step-id>
```

The Target workspace lives under:

```text
$DRYDOCK_WORKSPACE/targets/<Target>/
```

The generated application is written under:

```text
$DRYDOCK_BUILD_DIRECTORY/<Target>/
```

## Why It Is Different

Drydock is not a prompt collection and it is not a one-shot code generator. It is a
delivery system with durable artifacts:

- Blueprint: typed Markdown specifications that remain the source of truth.
- Manifest: the executable dependency graph for build order, dependencies, and state.
- QuarterDeck: the web review surface where the product owner answers questions,
  reviews stories, and directs the process.
- Compass files: persistent product-owner intent injected into the right command runs.
- Soundings: acceptance checklist and implementation evidence.
- Sea Trials: product-level objectives and proof-of-delivery criteria.
- Rigging: shared branding, stack rules, templates, and compact context derivatives.
- Execution logs: reproducible prompt, raw output, stderr, event, and result artifacts.

The Commander is the product owner. The LLM is treated as an Agile delivery team.
Drydock's job is to make that relationship explicit, reviewable, and repeatable.

## Current Release Status

Drydock `0.1.2` is an alpha release. The primary SAIL path is implemented, but
the command surface and Typed Specification contracts remain unstable during
the `0.x` series:

- Workspace configuration and Target initialization.
- Markdown, source tree, Spec Kit, and Compass import.
- LLM-assisted analysis with blockers, questionnaires, Soundings, Sea Trials, and
  Commander review artifacts.
- LLM-assisted planning into typed Blueprint files and `MANIFEST.md`.
- Manifest-frontier build execution, evidence capture, and human verification.
- Refit change-ticket conformance and applied-spec drift reconciliation.
- QuarterDeck runtime for review and process navigation.
- Rigging compaction, update, and verification.
- Target documentation generation and assembly.
- Deterministic Markdown publishing to HTML and optional PDF.
- Survey and prompt-review tooling used to evaluate Drydock's own command quality.

`drydock build score <Target>` verifies the built application against technical quality metrics
and structured project acceptance criteria, then writes the aggregate completion gate evidence.

The installed wheel includes Drydock's canonical product specification as a
read-only package resource at `drydock/resources/docs/Drydock_Specification.md`.

Read [docs/SOUNDINGS.md](docs/SOUNDINGS.md) for the authoritative implementation
readiness checklist and test evidence.

## Command Surface

```text
drydock --help
drydock --version

drydock config show
drydock config set <key> <value>

drydock init <Target> [--display-name <name>] [--description <desc>]
drydock status [<Target>]
drydock validate <Target> [--verbose]
drydock run quarterdeck [<Target>] [--host HOST] [--port PORT]

drydock import <Target> <Source> --format <auto|markdown|source|speckit|compass>
drydock analyze <Target> [--model <model>] [--llm-provider <claude|codex>]
drydock plan <Target> [--model <model>] [--llm-provider <claude|codex>]

drydock build <Target> [--step <step-id>] [--force] [--build-dir <path>]
drydock build status <Target>
drydock build verify <Target> <step-id>
drydock build score <Target>

drydock rigging compact [<Target>] [--all] [--force]
drydock rigging compact <Target> --include-file <file.md>
drydock rigging update <Target> [--dry-run]
drydock rigging verify <Target>

drydock document generate <Target> [--model <model>]
drydock document assemble <Target> [--theme <theme>]
drydock document <Target> [--model <model>] [--theme <theme>]

drydock publish <Source.md> --output <Output.html> [--theme <theme>] [--flatten] [--pdf]
drydock survey <Target> [--run] [--import <path>] [--command <name>] [--raw]
drydock prompt review <component>
drydock shipslog [--dir <path>] [--dry-run]
```

Configuration keys:

| Key | Environment override | Purpose |
|---|---|---|
| `drydock_workspace` | `DRYDOCK_WORKSPACE` | Workspace containing `targets/` and Drydock logs |
| `drydock_build_directory` | `DRYDOCK_BUILD_DIRECTORY` | Root where generated applications are written |
| `drydock_model` | `DRYDOCK_MODEL` | Default model for LLM-assisted commands |
| `llm_provider` | `LLM_PROVIDER` | Subscription CLI provider: `claude` or `codex` |
| `prompt_warn_tokens` | `PROMPT_WARN_TOKENS` | Prompt-size warning threshold in tokens |
| `quarterdeck_port` | `QUARTERDECK_PORT` | Default QuarterDeck port |
| `shipslog_dir` | `DRYDOCK_SHIPSLOG_DIR` | Ship's Log posts package directory for `drydock shipslog` |

## Public Documentation

Public hub and launch materials:

- [Web Cloud Studio](https://webcloudstudio.com)
- [Drydock GitHub repository](https://github.com/webcloudstudio/Drydock)
- [Canonical Drydock specification](https://webcloudstudio.com/project-docs/drydock/)
- [Launch deck and presentation](https://webcloudstudio.com/drydock/)
- [Launch video](https://webcloudstudio.com/project-docs/drydock/presentation/Drydock_Video.web.mp4)
- [Improving Step Accuracy in Specification-Driven Development](https://zenodo.org/records/21287574)

Repository references:

- [Install Drydock](docs/USER_INSTALLATION.md)
- [Drydock specification source](docs/Drydock_Specification.md)
- [Rendered specification HTML](docs/Drydock_Specification.html)
- [Rendered specification PDF](docs/Drydock_Specification.pdf)
- [Launch script](docs/presentation/script.md)
- [Talking points](docs/presentation/talking_points.md)
- [Soundings readiness checklist](docs/SOUNDINGS.md)
- [Sea Trials sample](docs/SEA_TRIALS_SAMPLE.md)

Development and governance:

- [Contributing](CONTRIBUTING.md)
- [Release process (maintainer runbook)](docs/RELEASE_PROCESS.md)
- [Drydock skills](docs/Drydock_SKILLS.md)
- [PyPI name reservation notes](docs/PYPI_NAME_RESERVATION.md)
- [Launch distribution plan](docs/presentation/distribution.md)

## Source Development

Install from a source checkout:

```bash
git clone https://github.com/webcloudstudio/Drydock.git
cd Drydock
uv venv
uv pip install -e ".[dev]"
```

Run local verification:

```bash
python -m pytest
ruff check src/ tests/
ruff format --check src/ tests/
```

Build release artifacts:

```bash
python -m hatchling build
```

After the editable install, run the installed console entry point against the source
tree:

```bash
drydock --help
```

## Security Model

Drydock assembles prompts deterministically and runs the selected provider CLI as a
subprocess. Execution evidence is persisted under Drydock logs so a run can be audited.

Provider handling is intentionally subscription-oriented:

- API-key environment variables are not the intended execution path.
- Claude and Codex are run through isolated command wrappers.
- Build commands operate against the configured Target workspace and generated application
  directory.
- Tests use injected runners and never require network or paid API access.

See the "Drydock Security" section in
[docs/Drydock_Specification.md](docs/Drydock_Specification.md#drydock-security) for the
current provider execution contracts.

## License

MIT - Copyright (c) 2026 Web Cloud Studio. See [LICENSE](LICENSE).

"Drydock" is a trademark of Web Cloud Studio; see [NOTICE](NOTICE) for use
of the name in forks and derivative works. See [CONTRIBUTORS.md](CONTRIBUTORS.md)
for the project's contributors.

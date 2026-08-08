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

[Guided tour](#guided-tour-one-feature-end-to-end) · [Specification](https://webcloudstudio.com/project-docs/drydock/index_sections/introduction.html) · [Installation](https://webcloudstudio.com/project-docs/drydock/USER_INSTALLATION.pdf) · [Comparison matrix](https://webcloudstudio.com/project-docs/drydock/papers/Product_Comparison_Matrix.html) · [Overview deck](https://webcloudstudio.com/drydock/) · [Contributing](CONTRIBUTING.md)

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

## Install

```bash
uv tool install drydock-sdd
```

Requires Python 3.11+ and one signed-in provider CLI, `claude` or `codex`.

Provider setup, workspace configuration, and troubleshooting are in the
**[User Installation Guide](https://webcloudstudio.com/project-docs/drydock/USER_INSTALLATION.pdf)**.

## How Drydock works

```bash
drydock init ReadingList                    # create the Target workspace
drydock import ReadingList ./reading-list.md
drydock analyze ReadingList
drydock run quarterdeck ReadingList         # review, answer blockers, approve the stack
drydock plan ReadingList
drydock build ReadingList
```

* `import` copies your specification material into a workspace.
* `analyze` decomposes the import into stories, acceptance criteria, questions, and blockers.
* `plan` grooms Blueprints, acceptance criteria, and the build graph.
* `build` creates software, testing each step.
* `refit` diffs updated specs into tickets.
* The `quarterdeck` web interface provides control and observability.

The Target workspace is `<drydock_workspace>/targets/ReadingList/`; the application is built in
`<drydock_build_directory>/ReadingList/`.

<div align="center">
<img src="docs/drydock_process.png" alt="Drydock setup, specification, planning, building, and maintenance commands." width="920" />
</div>

Change the specification and rerun. `drydock refit` uses Git diff to identify source-material
changes, maps them to Blueprints, and appends work to the build graph:

```bash
drydock import ReadingList --update
drydock refit ReadingList --sources
drydock build ReadingList                   # incremental build
```

The [Quick Start](https://webcloudstudio.com/project-docs/drydock/QUICK_START.html) walks this
through end to end, with screenshots.

## Guided tour: one feature, end to end

Drydock leaves everything it did in the Target workspace:

```text
<drydock_workspace>/targets/<Target>/
  blueprint/        Blueprints — the typed, buildable specifications
  MANIFEST.md       the build graph
  SOUNDINGS.md      acceptance board, one row per assertion
  SCORECARD.md      release gate
  evidence/         one record per build step
  logs/             prompts and full run history
```

Every excerpt below is real, taken from a CommonMark 0.31.2 parser Drydock built in twelve blocks.
Follow one feature through the four artifacts.

**1. The Blueprint.** `drydock plan` writes typed Blueprint files carrying test driven development
assertions — `blueprint/FEATURE-Block-Basics.md`:

```text
| Depends On  | ARCHITECTURE.md |
| Provides    | thematic breaks, ATX headings, setext headings, paragraphs, blank lines |

## Programmatic Acceptance
### block-basics-conformance
The implementation passes the authoritative block-basics sections.
```

The acceptance criterion is executable. It runs the official CommonMark harness and fails the story
if the count regresses.

**2. The Manifest.** The same feature as a story in the build graph, with its dependency and the
context it will be given:

```text
## story 4: Parse tabs, paragraphs, blank lines, thematic breaks, and ATX/setext headings.
id: block-basics
implements: FEATURE-Block-Basics.md
context: spec.txt, ARCHITECTURE_compact.md
depends: architecture
acceptance: yes
```

`drydock build` groups related stories into Blocks and builds only what is ready.

**3. The evidence.** Every Block writes its own record, `evidence/feature-block-parsing.md`:

```text
- resulting state: closed/verified
- execution id: 20260729.142054.864Z-36fc71af

## Stacked context
- implements: FEATURE-Block-Basics.md (SP 382)
- context: spec.txt (SP 51527)

## Post-build programmatic acceptance
- PASS: block-basics-conformance (FEATURE-Block-Basics.md)
    73 passed, 0 failed, 0 errored, 582 skipped
```

**4. The score.** `drydock score ac` re-runs every acceptance criterion and writes `SOUNDINGS.md`:

```text
| Status | Blueprint               | AC Id                    | Verified At          |
| ✓ PASS | FEATURE-Block-Basics.md | block-basics-conformance | 2026-07-30T13:30:01Z |
| ✓ PASS | FEATURE-Block-Basics.md | block-basics-entrypoint  | 2026-07-30T13:30:01Z |
```

The finished parser passes the full official CommonMark suite:

```console
$ ./full_test.sh
655 passed, 0 failed, 0 errored, 0 skipped
```

Blueprint, Manifest, evidence, score: the whole chain stays with the project. The
[Product Comparison Matrix](https://webcloudstudio.com/project-docs/drydock/papers/Product_Comparison_Matrix.html)
sets Drydock against the other specification-driven tools.

## Release status

**Alpha.** The methodology is complete and the full delivery path — import, analyze, plan, build,
score, refit, document — is implemented and in daily use. Current work is new project types and
sharper process guardrails.

Command surface and specification contracts still move during `0.x`. Pin your version and read
[CHANGELOG.md](CHANGELOG.md) before upgrading.

## Documentation

- [Quick Start](https://webcloudstudio.com/project-docs/drydock/QUICK_START.html) — build your first
  project ([PDF](https://webcloudstudio.com/project-docs/drydock/QUICK_START.pdf))
- [User Installation Guide](https://webcloudstudio.com/project-docs/drydock/USER_INSTALLATION.pdf)
- [Drydock Specification](https://webcloudstudio.com/project-docs/drydock/index_sections/introduction.html)
  — command, artifact, and process contracts
  ([single page](https://webcloudstudio.com/project-docs/drydock/Drydock_Specification.html) ·
  [PDF](https://webcloudstudio.com/project-docs/drydock/Drydock_Specification.pdf))
- [Overview deck](https://webcloudstudio.com/drydock/) ·
  [walkthrough video](https://webcloudstudio.com/project-docs/drydock/presentation/PRODUCTION_Drydock_Video.web.mp4)

Papers:

- [Improving Step Accuracy in Specification-Driven Development](https://webcloudstudio.com/project-docs/drydock/papers/Improving_Step_Accuracy_in_SDD.html)
- [Managing Changes in Specification-Driven Development](https://webcloudstudio.com/project-docs/drydock/papers/Managing_Changes_in_SDD.html)
- [Managing Changed Specifications](https://webcloudstudio.com/project-docs/drydock/papers/SDD_Managing_Changed_Specifications.html)
- [Product Comparison Matrix](https://webcloudstudio.com/project-docs/drydock/papers/Product_Comparison_Matrix.html)

Run `drydock --help` for the full command list.

## Contributing

Welcome aboard. The most useful contribution right now is a real project.

Build something you care about with Drydock and tell us where it broke: which specification
confused the planner, which build step needed a rescue, which evidence you wanted and could not
find. Open an [issue](https://github.com/webcloudstudio/Drydock/issues) with the Target, the
command, and what you expected. A failed build report is worth more than a compliment.

To work on Drydock itself, start with [CONTRIBUTING.md](CONTRIBUTING.md).

## Security

Drydock assembles prompts deterministically and runs the provider CLI as a subprocess through an
isolated wrapper. API keys are not the execution path, every run persists auditable evidence, and
tests never require network or paid API access. See
[Drydock Security](https://webcloudstudio.com/project-docs/drydock/index_sections/drydock-security.html).

## License

MIT — Copyright (c) 2026 Web Cloud Studio. See [LICENSE](LICENSE).

"Drydock" is a trademark of Web Cloud Studio; see [NOTICE](NOTICE) for use of the name in forks and
derivative works. See [CONTRIBUTORS.md](CONTRIBUTORS.md) for contributors.

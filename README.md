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

You write what the product does. Drydock plans it, builds it, verifies it, and keeps the record.

- **Specification driven.** Typed specifications are the source of truth. Code is the output.
- **Agile.** The specification is decomposed into features and stories, with product-owner review
  before the build starts.
- **Test driven.** Acceptance criteria are written into the specification and executed. A story is
  not done until its checks pass.
- **A dependency graph of stories.** `MANIFEST.md` orders the work and builds the frontier — every
  story whose dependencies are satisfied.
- **Context compression and optimization.** Each build prompt carries only the specifications that
  story needs. Large applications build reproducibly without a frontier-model budget.
- **Web interface.** The QuarterDeck console shows the graph, the open questions, and the score.
- **Enterprise guardrails.** Blocking questions instead of guesses, declared dependencies instead
  of improvised ones, and durable evidence for every step.
- **Change control.** Edit the specification; `drydock refit` writes a change ticket against each
  affected Blueprint and rebuilds only the work that moved.
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
drydock init MyApp                 # create the project workspace
drydock import MyApp ./notes       # import your specification sources
drydock analyze MyApp              # questions, decisions, technology stack
drydock plan MyApp                 # typed Blueprints and the MANIFEST.md build graph
drydock run quarterdeck MyApp      # review it in the web console
drydock build MyApp                # build the frontier, capture evidence
drydock score ac MyApp             # verify every acceptance criterion
drydock refit MyApp                # route a specification change back into the graph
```

The **Blueprint** holds the typed specifications. The **Manifest** (`MANIFEST.md`) is the build
graph: it connects the stories, tracks dependencies, selects the work that can run next, and gives
each build exactly the context it needs.

<div align="center">
<img src="docs/drydock_process.png" alt="Drydock setup, specification, planning, building, and maintenance commands." width="920" />
</div>

## Guided tour: one feature, end to end

Every excerpt below is an artifact Drydock wrote while building a reference project: a standalone
CommonMark 0.31.2 parser, built in twelve blocks.

**1. The specification.** `drydock plan` writes typed Blueprint files. Each declares what it
provides, what it depends on, and how it will be proven — `blueprint/FEATURE-Block-Basics.md`:

```text
| Depends On  | ARCHITECTURE.md |
| Provides    | thematic breaks, ATX headings, setext headings, paragraphs, blank lines |

## Programmatic Acceptance
### block-basics-conformance
The implementation passes the authoritative block-basics sections.
```

That acceptance check is executable. It runs the official CommonMark harness against the build and
fails the story if the count regresses.

**2. The graph.** The same feature in `MANIFEST.md`, with its dependency edge and the context it
will be given:

```text
## story 4: Parse tabs, paragraphs, blank lines, thematic breaks, and ATX/setext headings.
id: block-basics
implements: FEATURE-Block-Basics.md
context: spec.txt, ARCHITECTURE_compact.md
depends: architecture
acceptance: yes
```

`drydock build` executes the frontier — stories whose dependencies are satisfied — so no build
prompt carries context it does not need.

**3. The step that built the file.** Every executed block writes its own record,
`evidence/feature-block-parsing.md`:

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

**4. The evidence it was verified.** `drydock score ac` re-runs every acceptance assertion and
writes the board to `SOUNDINGS.md`:

```text
| Status | Blueprint               | AC Id                    | Verified At          |
| ✓ PASS | FEATURE-Block-Basics.md | block-basics-conformance | 2026-07-30T13:30:01Z |
| ✓ PASS | FEATURE-Block-Basics.md | block-basics-entrypoint  | 2026-07-30T13:30:01Z |
```

The finished parser passes the full official suite:

```console
$ ./full_test.sh
655 passed, 0 failed, 0 errored, 0 skipped
```

Specification, graph, build step, evidence: four artifacts, one chain, kept with the project.

Not a prompt collection and not a one-shot generator. The
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

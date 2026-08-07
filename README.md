<div align="center">

<img src="docs/drydock_logo.png" alt="Drydock" width="160" />

# Drydock

**Your coding agent forgets. Drydock does not.**

Drydock turns a written description of a software project into typed specifications, builds the
software from those specifications with your Claude or Codex subscription, and keeps the
specifications, build order, decisions, tests, and results together so the software can be
reviewed, rebuilt, and changed cleanly.

[![PyPI](https://img.shields.io/pypi/v/drydock-sdd.svg)](https://pypi.org/project/drydock-sdd/)
[![Python](https://img.shields.io/pypi/pyversions/drydock-sdd.svg)](https://pypi.org/project/drydock-sdd/)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![CI](https://github.com/webcloudstudio/Drydock/actions/workflows/ci.yml/badge.svg)](https://github.com/webcloudstudio/Drydock/actions/workflows/ci.yml)

### ▶ START HERE — [Quick Start](docs/QUICK_START.md)

Install, connect a subscription CLI, and build your first project.

[Guided tour](#guided-tour-one-feature-end-to-end) · [Specification](https://webcloudstudio.github.io/Drydock/index_sections/introduction.html) · [Installation](docs/USER_INSTALLATION.md) · [Contributing](CONTRIBUTING.md) · [Overview deck](https://webcloudstudio.com/drydock/) · [White paper](https://zenodo.org/records/21287574)

</div>

---

```bash
uv tool install drydock-sdd
```

Drydock is an installable Python command-line package. The PyPI distribution is `drydock-sdd`; the
installed command is `drydock`. It runs on your existing Claude or Codex subscription CLI and
requires no API key and no per-token billing.

## How Drydock works

Drydock follows five steps: set up a workspace, import your project notes, review the
specifications and build graph, build working software, then change and maintain it.

The **Blueprint** holds the typed specifications that define the product. The **Manifest**
(`MANIFEST.md`) is the executable build graph: it connects the Blueprint stories, tracks their
dependencies, selects the work that can run next, and gives each build exactly the context it
needs.

<div align="center">
<img src="docs/drydock_process.png" alt="Drydock setup, specification, planning, building, and maintenance commands." width="920" />
</div>

## Guided tour: one feature, end to end

Every claim below is an artifact Drydock wrote while building a reference Target: a standalone
CommonMark 0.31.2 parser, specified from the CommonMark specification and built in twelve blocks.
Follow one feature through the four stages.

**1. Here is the specification.** `drydock analyze` and `drydock plan` decompose the imported
sources into typed Blueprint files. Each one declares what it provides, what it depends on, and how
it will be proven — `blueprint/FEATURE-Block-Basics.md`:

```text
| Description | Parses tab handling, paragraphs, blank lines, thematic breaks, and ATX/setext headings. |
| Depends On  | ARCHITECTURE.md |
| Provides    | thematic breaks, ATX headings, setext headings, paragraphs, blank lines |

## Programmatic Acceptance
### block-basics-conformance
The implementation passes the authoritative block-basics sections.
```

Programmatic Acceptance is executable. The check runs the authoritative CommonMark harness against
the built parser and fails the story if the count regresses. The specification carries its own
proof.

**2. Here is the graph.** `MANIFEST.md` is the build order, not a task list. The same feature
appears as a story with its dependency edge, the context it will be given, and the acceptance
contract it must satisfy:

```text
## story 4: Parse tabs, paragraphs, blank lines, thematic breaks, and ATX/setext headings.
id: block-basics
implements: FEATURE-Block-Basics.md
context: spec.txt, ARCHITECTURE_compact.md
provides: thematic breaks, ATX headings, setext headings, paragraphs, blank lines
depends: architecture
acceptance: yes
```

`drydock build` executes the frontier — the stories whose dependencies are satisfied — so the
parser skeleton exists before the block phase extends it, and no build prompt carries context it
does not need.

**3. Here is the step that built the file.** Each executed block writes its own evidence record.
`evidence/feature-block-parsing.md` states what was built, what context was stacked into the
prompt, what changed on disk, and what the acceptance checks returned:

```text
- resulting state: closed/verified
- execution id: 20260729.142054.864Z-36fc71af

## Stories built
- Block Basics (block-basics) [story]
- Block Code (block-code) [story]
...

## Stacked context
- implements: FEATURE-Block-Basics.md (SP 382)
- context: spec.txt (SP 51527)
- stack: python_compact.md (SP 1534)

## Post-build programmatic acceptance
- PASS: block-basics-conformance (FEATURE-Block-Basics.md)
  return code: 0
  stdout:
    73 passed, 0 failed, 0 errored, 582 skipped
```

**4. Here is the evidence it was verified.** `drydock score ac` re-runs every Programmatic
Acceptance assertion in the Blueprint and writes the board to `SOUNDINGS.md` — one row per
assertion, per feature, with a timestamp:

```text
| Status | Blueprint               | AC Id                     | Verified At          |
| ✓ PASS | FEATURE-Block-Basics.md | block-basics-conformance  | 2026-07-30T13:30:01Z |
| ✓ PASS | FEATURE-Block-Basics.md | block-basics-entrypoint   | 2026-07-30T13:30:01Z |
```

The finished parser passes the full authoritative suite:

```console
$ ./full_test.sh
655 passed, 0 failed, 0 errored, 0 skipped
```

Specification, graph, build step, evidence — four artifacts, one chain, all recoverable months
later. That chain is the product.

## Why it is different

Drydock is not a prompt collection and it is not a one-shot code generator. Reproducible LLM builds
require a process: Agile decomposition, explicit product-owner review, durable evidence, and
context-managed build prompts. Because the typed specifications, executable build graph, review
decisions, acceptance checks, and execution evidence stay with the project, every build is
reviewable, repeatable, and safe to change.

Change goes through the specification. Edit the source, re-import it, and `drydock refit` reads the
diff, decomposes it into stories, and writes a change ticket against each affected Blueprint. The
next build rebuilds only the affected work.

## Release status

**Alpha.** The methodology is complete and the full SAIL path — import, analyze, plan, build,
score, refit, document — is implemented and in daily use. Current work is testing Drydock against
new project types and refining the process guardrails that keep a build honest.

Expect the command surface and Typed Specification contracts to move during the `0.x` series.
Pin your version, and read [CHANGELOG.md](CHANGELOG.md) before upgrading.

## Documentation

- [Quick Start](docs/QUICK_START.md) — the recommended entry point
  ([HTML](https://webcloudstudio.github.io/Drydock/QUICK_START.html) ·
  [PDF](https://webcloudstudio.github.io/Drydock/QUICK_START.pdf))
- [User Installation Guide](docs/USER_INSTALLATION.md) — install, provider setup, workspace
  configuration ([PDF](https://webcloudstudio.github.io/Drydock/USER_INSTALLATION.pdf))
- [Drydock Specification](https://webcloudstudio.github.io/Drydock/index_sections/introduction.html)
  — the authoritative command, artifact, and process contracts
  ([source](docs/Drydock_Specification.md) ·
  [PDF](https://webcloudstudio.github.io/Drydock/Drydock_Specification.pdf))
- [Drydock skills](https://github.com/webcloudstudio/Drydock/tree/main/Rigging/skills) — `/refit`
  and `/apply-refit`, provisioned into your workspace by `drydock init`
- [Improving Step Accuracy in Specification-Driven Development](https://zenodo.org/records/21287574)
  — the white paper
- [Overview deck](https://webcloudstudio.com/drydock/) ·
  [10-minute walkthrough video](https://webcloudstudio.com/project-docs/drydock/presentation/Drydock_Video.web.mp4)

Run `drydock --help` for the complete command list.

## Contributing

Welcome aboard. The most valuable contribution right now is not code — it is a real project.

Build something you actually care about with Drydock, then tell us where it held and where it
broke: which specification confused the planner, which build step needed a human rescue, which
piece of evidence you wanted and could not find. Open an
[issue](https://github.com/webcloudstudio/Drydock/issues) with the Target name, the command, and
what you expected. Alpha software improves at the speed of its feedback, and a failed build report
is worth more to us than a compliment.

If you want to work on Drydock itself — environment setup, architecture, verification contract, and
quality gates — start with [CONTRIBUTING.md](CONTRIBUTING.md).

## Security

Drydock assembles prompts deterministically and runs the selected provider CLI as a subprocess.
API-key environment variables are not the intended execution path, provider CLIs run through
isolated wrappers, and every run persists auditable evidence. Tests use injected runners and never
require network or paid API access.

See the [Drydock Security](docs/Drydock_Specification.md#drydock-security) section of the
specification for the provider execution contracts.

## License

MIT — Copyright (c) 2026 Web Cloud Studio. See [LICENSE](LICENSE).

"Drydock" is a trademark of Web Cloud Studio; see [NOTICE](NOTICE) for use of the name in forks and
derivative works. See [CONTRIBUTORS.md](CONTRIBUTORS.md) for the project's contributors.

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

### ▶ START HERE — [Quick Start](https://webcloudstudio.com/project-docs/drydock/QUICK_START.html)

Install, connect a subscription CLI, and build your first project.

[Guided tour](#guided-tour-one-feature-end-to-end) · [Specification](https://webcloudstudio.com/project-docs/drydock/index_sections/introduction.html) · [Installation](https://webcloudstudio.com/project-docs/drydock/USER_INSTALLATION.pdf) · [Comparison matrix](https://webcloudstudio.com/project-docs/drydock/papers/Product_Comparison_Matrix.html) · [Overview deck](https://webcloudstudio.com/drydock/) · [Contributing](CONTRIBUTING.md)

</div>

---

## What Drydock is

An agent can write a thousand lines of working code and remember none of the reasoning behind it.
Ask for a change three weeks later and it re-derives the design, contradicts an earlier decision,
and quietly breaks something nobody thought to test. The code survives; the intent does not.

Drydock is a specification-driven delivery methodology, shipped as a Python command-line tool, that
keeps the intent. You describe the product you want. Drydock decomposes that description into typed
specifications, orders them into an executable build graph, builds each piece with your existing
Claude or Codex subscription, verifies the result against acceptance criteria written into the
specification itself, and records what happened in files you can read.

The specification is the source of truth, not the prompt history. Change the specification and
Drydock routes the change: it re-plans the affected work, rebuilds only that, and re-verifies.
Nothing depends on what the agent remembers.

```bash
uv tool install drydock-sdd
```

The PyPI distribution is `drydock-sdd`; the installed command is `drydock`. It requires Python 3.11
or later and one signed-in provider CLI. There is no API key and no per-token billing — Drydock runs
on the subscription you already pay for. Full setup is in the
[Quick Start](https://webcloudstudio.com/project-docs/drydock/QUICK_START.html).

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

For how Drydock compares with other specification-driven tools, see the
[Product Comparison Matrix](https://webcloudstudio.com/project-docs/drydock/papers/Product_Comparison_Matrix.html).

## Release status

**Alpha.** The methodology is complete and the full SAIL path — import, analyze, plan, build,
score, refit, document — is implemented and in daily use. Current work is testing Drydock against
new project types and refining the process guardrails that keep a build honest.

Expect the command surface and Typed Specification contracts to move during the `0.x` series.
Pin your version, and read [CHANGELOG.md](CHANGELOG.md) before upgrading.

### Project-level UAT

`drydock uat [<Project>]` rebuilds known projects unattended under isolated timestamped run
directories. Fixtures live under `tests/uat/<Project>/`: `spec_1.md` drives the initial
init/import/analyze/plan/build lifecycle, and each later `spec_N.md` drives
`import --update` → `refit --sources` → incremental build. The selected model and provider apply
to the whole run.

Each run writes `uat/runs/<run-id>/SUMMARY.md`, `summary.json`, per-project `result.json`, and the
complete stdout/stderr of every child command. Reports include command and LLM elapsed time, input,
cached, fresh-input, and output tokens, build-pass counts, and the exit results from `score ac`,
`score build`, and `score release`. Scoring is advisory in UAT V1: score failures remain visible in
the report but do not override a successfully completed build lifecycle.

## Documentation

- [Quick Start](https://webcloudstudio.com/project-docs/drydock/QUICK_START.html) — the recommended
  entry point ([PDF](https://webcloudstudio.com/project-docs/drydock/QUICK_START.pdf))
- [User Installation Guide](https://webcloudstudio.com/project-docs/drydock/USER_INSTALLATION.pdf) —
  install, provider setup, and workspace configuration
- [Drydock Specification](https://webcloudstudio.com/project-docs/drydock/index_sections/introduction.html)
  — the authoritative command, artifact, and process contracts
  ([single page](https://webcloudstudio.com/project-docs/drydock/Drydock_Specification.html) ·
  [PDF](https://webcloudstudio.com/project-docs/drydock/Drydock_Specification.pdf))
- [Overview deck](https://webcloudstudio.com/drydock/) ·
  [walkthrough video](https://webcloudstudio.com/project-docs/drydock/presentation/PRODUCTION_Drydock_Video.web.mp4)

Papers:

- [Improving Step Accuracy in Specification-Driven Development](https://webcloudstudio.com/project-docs/drydock/papers/Improving_Step_Accuracy_in_SDD.html)
- [Managing Changes in Specification-Driven Development](https://webcloudstudio.com/project-docs/drydock/papers/Managing_Changes_in_SDD.html)
- [Managing Changed Specifications](https://webcloudstudio.com/project-docs/drydock/papers/SDD_Managing_Changed_Specifications.html)
- [Product Comparison Matrix](https://webcloudstudio.com/project-docs/drydock/papers/Product_Comparison_Matrix.html)

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

See the
[Drydock Security](https://webcloudstudio.com/project-docs/drydock/index_sections/drydock-security.html)
section of the specification for the provider execution contracts.

## License

MIT — Copyright (c) 2026 Web Cloud Studio. See [LICENSE](LICENSE).

"Drydock" is a trademark of Web Cloud Studio; see [NOTICE](NOTICE) for use of the name in forks and
derivative works. See [CONTRIBUTORS.md](CONTRIBUTORS.md) for the project's contributors.

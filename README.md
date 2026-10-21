<div align="center">

<img src="docs/drydock_logo.png" alt="Drydock" width="160" />

**Drydock turns specifications into tested working software.**

Specification driven. Agile. Test driven. Dependency-aware builds. Dedicated web console.
Enterprise guardrails.

**Runs on your existing Claude or Codex subscription; Gemini is supported as a metered alternative.**

[![PyPI](https://img.shields.io/pypi/v/drydock-sdd.svg)](https://pypi.org/project/drydock-sdd/)
[![Python](https://img.shields.io/pypi/pyversions/drydock-sdd.svg)](https://pypi.org/project/drydock-sdd/)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

### ▶ START HERE — [Quick Start](https://webcloudstudio.com/project-docs/drydock/QUICK_START.html)

[Specification](https://webcloudstudio.com/project-docs/drydock/index_sections/introduction.html) · [Installation](https://webcloudstudio.com/project-docs/drydock/USER_INSTALLATION.pdf) · [Comparison matrix](https://webcloudstudio.com/project-docs/drydock/papers/Product_Comparison_Matrix.html) · [Overview deck](https://webcloudstudio.com/drydock/) · [Contributing](CONTRIBUTING.md)

</div>

---

## Overview

Target generation supports Python and Go. Select the language and optional database in
`TECHNOLOGY_STACK.md`, approve the stack in QuarterDeck, then plan and build. SQLite and
PostgreSQL use shipped persistence libraries. Go uses standard-library CLI/HTTP layouts and
native tests; SQLite requires CGO and a C compiler. Start a fresh Target to change languages
after planning. Planning and building reject an invalid or unapproved stack before an LLM call.

**Drydock is a repeatable method to turn messy specifications into tested working software.**

Drydock imports your source material, defines stories using agile best practices, and then decomposes your sources into typed blueprints (stories) related using a graph database.  Drydock builds with a context aware compression based algorithm and tests stories with deterministic test driven acceptance criteria.

## Features
- **Builds working software using small, cheap models**
- **Agile Methodology** to decompose buildable stories and for product owner / llm review.
- **Test driven development** with acceptance criteria embedded in each Story/Blueprint.
- **Dependency graph** relates stories and orders builds.
- **QuarterDeck web console** to answer question and review the process
- **Runs on existing subscriptions**
- **Ingests your existing specs and notes in any format**
- **Change management — edit the spec, rebuild only what's affected**
- **Context compression** and **Grouping** for context aware builds.
- **Enterprise guardrails** with embedded branding, best practices, and build gates
- **Generates consistent apps and documentation**

## Drydock Documentation

| Resource | PDF |
|---|---|
| [Quick Start Guide](https://webcloudstudio.com/project-docs/drydock/QUICK_START.html) | [PDF](https://webcloudstudio.com/project-docs/drydock/QUICK_START.pdf) |
| [User Installation Guide](https://webcloudstudio.com/project-docs/drydock/USER_INSTALLATION.pdf) ||
| [Drydock Specification](https://webcloudstudio.com/project-docs/drydock/index_sections/introduction.html) | [PDF](https://webcloudstudio.com/project-docs/drydock/Drydock_Specification.pdf) |
| [CHANGELOG.md](CHANGELOG.md) | — |
| [CONTRIBUTING.md](CONTRIBUTING.md) | — |

## Drydock UAT Examples

The following are 4 WORKING applications built as part of the Drydock Uat Cycle - **BUILD EVIDENCE STORED IN SEPARATE REPOS**

| Project | Description | Web URL | Git URL |
| --- | --- | --- | --- |
| ReadingList | simple web app | https://webcloudstudio.github.io/drydock-example-readinglist/ | [Git](https://github.com/webcloudstudio/drydock-example-readinglist) |
| CommonMark | markdown formatter | https://webcloudstudio.github.io/drydock-example-commonmark/ | [Git](https://github.com/webcloudstudio/drydock-example-commonmark) |
| TOML | markup language | https://webcloudstudio.github.io/drydock-example-toml/ | [Git](https://github.com/webcloudstudio/drydock-example-toml) |
| jq | Flagship - full build of the jq language | https://webcloudstudio.github.io/drydock-example-jq/ | [Git](https://github.com/webcloudstudio/drydock-example-jq) |


All four built with gpt-5.6-luna on a Codex subscription. No API keys.  All build evendence should be in the separate git repo.


## Getting started

**Prerequisites**

- [ ] Python 3.11 or later — `python3 --version`
- [ ] Install `uv`
  - `curl -LsSf https://astral.sh/uv/install.sh | sh` (macOS/Linux),
  - `brew install uv`
  - `winget install --id=astral-sh.uv -e` (Windows)
- [ ] `claude`, `codex`, or `gemini` CLI, authenticated, in your `PATH`
      (`claude --version`, `codex --version`, `gemini --version`). `gemini` authenticates
      with `GEMINI_API_KEY` in the environment and bills per token.

**Install Drydock**

```bash
uv tool install drydock-sdd     # or: pipx install drydock-sdd
drydock --version
```

**Configure Drydock**

```bash
export PROJECTS="$HOME/projects" # main directory you keep your code/projects/git
mkdir -p "$PROJECTS/drydock"     # the drydock workspace

drydock config set drydock_model claude-opus-5  # required; the model selects the provider
                                                # (gpt-5.6-luna -> codex, gemini-3.5-flash -> gemini)
drydock config set drydock_workspace "$PROJECTS/drydock"
drydock config set drydock_build_directory "$PROJECTS"
drydock config show
```

Bounds on a build's acceptance runs are configurable, and each is also a `drydock build` and
`drydock uat` flag that overrides the configured value for one run.

| Key | Default | Bounds |
|---|---|---|
| `repair_attempts` | 6 | Repair passes a failed block may spend (0 disables repair) |
| `repair_stall_limit` | 2 | Consecutive passes without acceptance progress before a block stops |
| `sandbox_mem_limit` | 4096 MB | Address space for an acceptance run and everything it spawns |
| `capture_output_limit` | 8 MB | Output held from one acceptance command before it fails the gate |

```bash
drydock config set repair_attempts 12           # a target that converges slowly
drydock build MyApp --capture-output-limit 64   # a legitimately loud conformance suite
```

Claude output limits are configurable. Drydock passes them to the Claude CLI on every run and
replaces any value inherited from the shell.

| Key | Default | Effect |
|---|---|---|
| `max_output_tokens` | 128000 | Output tokens per response (`CLAUDE_CODE_MAX_OUTPUT_TOKENS`); the CLI caps it at the model maximum (Haiku 64000) |
| `haiku_thinking_tokens` | 16000 | Haiku 4.x thinking budget (`MAX_THINKING_TOKENS`), drawn from the output limit; 0 disables it. Other models, including Haiku 5.5 and the `haiku` alias, size thinking from `--effort` |

A Target whose stack selects `postgres.md` builds against the server named by `postgres_dsn`
(`drydock config set postgres_dsn postgresql://<user>:<password>@<host>:<port>/<database>`).
`drydock build`, `drydock score ac` and `drydock score release` stop with exit 1 when it is not
set; `drydock config show` masks the password. See `docs/HOW_TO_SETUP_POSTGRES.md`.

A text-only command whose response reaches the output limit fails with exit 1 and a
`FATAL ERROR - LLM OUTPUT TRUNCATED` block naming the limit, the thinking spent, the artifact
that was cut, and the setting to change. Nothing from the response is written.
## Build workflow

`init` → `import` → `analyze` → `plan` → `build` → `refit` → `build`

| Stage | Command | What it does |
|---|---|---|
| **init** | `drydock init <Target>` | Initialize Workspace<br>**Creates:** `targets/<Target>` |
| **import** | `drydock import <Target>` | import source material<br>**Creates:** `targets/<Target>/sources` |
| **analyze** | `drydock analyze <Target>` | Decompose into stories, acceptance criteria, questions, and blockers.<br>**Creates:** `ANALYSIS.md`, `SEA_TRIALS.md`, `BLOCKERS.md`, questionnaires. |
| **plan** | `drydock plan <Target>` | Create story blueprints and a graph datbase.<br>**Creates:** `blueprints/` and `MANIFEST.md`.<br>`drydock plan verify <Target>` reports acceptance criteria that cannot run; `drydock plan repair <Target>` makes them runnable in one pass. |
| **build** | `drydock build <Target>` | Executes the refit-reconciled Manifest frontier, gated by deterministic acceptance criteria. It exits with an error when any applied Blueprint changed or disappeared; run `drydock refit <Target>` first. Test-scoped Python acceptance dependencies are automatically authorized; runtime dependencies and external executables remain governed.<br>**Creates:** `\$drydock_build_directory/<Target>` with working software. |
| **refit** | `drydock refit <Target>` | Reconcile edited Blueprints to the Manifest dependency graph; reset only their affected build frontier. Change tickets remain available for additive work. `drydock refit add <Target> <Blueprint> <File>` appends the next REFIT ticket, `blueprint/<Blueprint>_refit_<NNN>.md`, and its Manifest story with inherited context, stack, and Rigging rules. Both commands automatically optimize unbuilt work in computed Manifests by shared context savings, including tickets from earlier calls. Started blocks retain their membership and numbering.<br>**Updates:** `MANIFEST.md`; continue with a `build`. |

## The Drydock CLI

`ai` calls your subscription CLI agent; all other commands are deterministic.

```text
# ── S ── SET UP ──────────────────────────────────────────────────────────
    drydock config show                        # Show configuration values and sources
    drydock config set        <var> <value>    # Set a configuration value
    drydock init              MyApp            # Create the target workspace
    drydock status                             # Status dashboard
    drydock status            MyApp            # Summary and plan state
    drydock report help                        # List deterministic Target reports
    drydock report manifest  MyApp             # Write a compact Manifest report
    drydock report token     MyApp             # Prompt size, model, and run time per LLM call
    drydock report --all                       # Write all reports for all Targets
    drydock report --all     MyApp             # Write all reports under targets/MyApp/reports/

# ── A ── ANALYZE ─────────────────────────────────────────────────────────
    drydock import            MyApp <file|dir> # Import sources into the workspace
ai  drydock analyze           MyApp            # Epic decomposition into stories & blockers
    drydock validate          MyApp            # Validate Build Plan
ai  drydock score spec        MyApp            # Audit imported raw specifications
    drydock run quarterdeck   MyApp            # Web interface
ai  drydock plan              MyApp --model sonnet --lineage-model haiku
                                                # Grooming and dependency graph; optional lower-cost lineage pass
    drydock plan verify       MyApp            # Report acceptance criteria that cannot run
ai  drydock plan repair       MyApp            # One pass making those criteria runnable

# ── I ── IMPLEMENT ───────────────────────────────────────────────────────
ai  drydock build             MyApp            # Iterative context-aware process
ai  drydock score release     MyApp            # Score project success criteria (EARS)

# ── L ── LOOP ────────────────────────────────────────────────────────────
ai  drydock diagnose          MyApp            # Root cause; propose Blueprint repairs (known terminal failures do not call an LLM)
ai  drydock refit             MyApp            # Blueprint drift -> affected build frontier
```

`drydock plan` freezes the topology before authoring Blueprints in batches of at most five.
Each Claude Blueprint batch starts with the original planning inputs, frozen topology and
decisions, current work ledger, and cumulative database declaration where present. Earlier
batch conversations are not carried forward. Stage 1 corrective calls still resume their session.

### Additional Commands

`drydock diagnose <Target> --apply` exercises delegated Commander authority to repair
specification and acceptance defects. It reads complete decision records once, prints proposed
diffs, validates acceptance syntax without executing generated code, and resets affected
consumers for rebuild. Repaired malformed-criterion blockers are retired; the next build still
verifies behavior. Routine corrections are annotated in the diagnosis report. Consequential
choices are recorded in `DECISIONS.json` for QuarterDeck review without blocking execution.
Commander answers remain binding. An unresolved stall or failed repair returns exit 1.

Use the recovery loop for unfinished Targets, including those already stalled before build:

```bash
bash drydock_build_loop.sh "$PROJECT" --model gpt-5.6-luna
```

The loop builds available work and invokes diagnosis after a failed build or an unfinished
Target with no buildable frontier. It stops if diagnosis fails or leaves the Target stalled.
`DRYDOCK_RUNNER_MAX_BUILDS` bounds iterations (default 5). Provider/model flags reach both
commands. `drydock_runner.sh` uses this loop after preparing the Target, and accepts only a
fixed list of models, printing that list with each model's cost when given anything else.
The loop ends at verified build completion; scoring is separate. `status --ready` retains its
boolean buildability contract, and `status --check` supplies the separate completion check.

`drydock build` checkpoints the application and Target Git repositories after each agent
execution (including repairs and failures) and completed step. Existing changes receive a
separate baseline checkpoint. Git uses the configured author identity, respects ignored files,
and never pushes. Full resets preserve application Git history.

`<Target>/BUILD_LINEAGE.jsonl` appends mechanical execution and `step_completed` records:
UTC run/execution timestamps, run and step IDs, Manifest nodes with their original fields,
`implements:` specification paths and hashes, acceptance results, available token statistics,
execution artifact paths, the command transcript, application commit SHAs, and Git file changes
(added, modified, deleted, renamed). Context, dependencies, and compacts are not attributed as
built specifications. Repeated executions retain separate rows; no model attribution is requested.
Completed-step records capture final story states and deterministic outputs; their statistics are
null so token totals count execution rows once. Ignored files and byte-identical rewrites have no
committed delta. The association is between an execution's specification set and its file delta.

Commit lines use the same block and `implements:` names as lineage:
`git: block-3 | SCREEN.md, SERVICE.md | call=2 | app=<sha> target=<sha>`.
An unchanged application reports `app=unchanged`. Target commits carry `Build-Lineage-Id`
and `Build-Run-Id` trailers: the receipt cannot contain the SHA of the commit containing itself.
Pending receipts survive checkpoint failures. The next build completes a confirmed application
checkpoint's Target receipt; an unconfirmed application commit stops for inspection instead of
inventing attribution. Command epilogue outputs receive a separate completion checkpoint.

```text
    drydock build status      MyApp            # Show build state
ai  drydock diagnose          [MyApp] --apply  # Delegated repair; important decisions enter QuarterDeck review
ai  drydock diagnose          [MyApp] --no-apply # Record amendments as decisions; change nothing
ai  drydock uat               [Project]        # Scored UAT testing
    drydock uat status        <Project>        # Current run, failure, and recovery command
ai  drydock uat resume        <Project>        # Resume the current failed run
ai  drydock uat resume        <Project> --from <stage> # Re-enter a named lifecycle stage
    drydock uat report        [Project]        # Rebuild UAT HTML proof kits
    drydock uat <Project> --steps              # List a run's numbered steps and their stages
ai  drydock uat <Project> --from-step <n>      # Resume at the stage that owns recorded step <n>
ai  drydock document          MyApp            # Project documentation automation
ai  drydock document generate MyApp            # AI pass only
    drydock document assemble MyApp            # Assembly only
    drydock publish           <Source.md>      # Render Markdown to HTML/PDF
ai  drydock rigging compact                    # Automanage compaction
    drydock rigging verify                     # Verify rigging compliance
    drydock score ac          MyApp            # Verify Story acceptance criteria
    drydock score build       MyApp            # Post-build report: repairs, tokens, cache
    drydock score llm         [MyApp]          # Successful LLM usage since latest init; by stage/model
    drydock score llm MyApp --all              # All recorded LLM executions, including failures
    drydock score uat_report                   # Successful UAT runs: calls, tokens, tools, time
    drydock score report      MyApp            # Publish the build receipt with its evidence
    drydock score             MyApp            # Summarize the scores above: last run, result,
                                               #   and output file
ai  drydock score drydock                      # Adversarial self-assessment
```

Each selected `uat/<Project>/` directory is an independent Git repository. `drydock uat`, resume
stages, and `drydock uat report` attempt to initialize it when absent and commit kit changes before
exit. Git checkpoint failures are silent and do not change the command's result.
UAT run receipts report the models recorded for executed LLM calls; a requested `--model` is
retained separately in `result.json`. A run that used multiple models lists each in first-use order.

## Target reports

`drydock report help` lists report names, commands, and descriptions. `drydock report <name>
<Target>` writes one deterministic text report. `drydock report --all` writes status, Manifest,
run state, build evidence, command history, LLM usage, and score history for every initialized
Target under `targets/<Target>/reports/`; `--all <Target>` limits the run to one Target. The CLI
prints each path relative to the current directory when it can. These reports read recorded
evidence and do not run models, builds, acceptance checks, or UAT. Existing QuarterDeck views
and published receipts remain available through their current commands.

## The QuarterDeck Web Server

QuarterDeck is the Agile web surface between the Commander (product owner) and Crew (LLM agents).

```bash
drydock run quarterdeck <Target>
```

![QuarterDeck Commander's Chair](docs/QuickStart_Analysis_Screen.png)

## Glossary

| Term | Meaning |
|---|---|
| **Target** | One project managed by Drydock, held in its own workspace directory. |
| **Blueprint** | The typed specification for one story: scope, contracts, and acceptance criteria. |
| **Manifest** | `MANIFEST.md`, the dependency graph that relates and orders the Blueprints. |
| **Sea Trials** | Product-level objectives and proof-of-delivery criteria — the release gate. |
| **Soundings** | The per-story acceptance-criterion verification board. |
| **Scorecard** | `SCORECARD.md`, the recorded release scoring results, verdicts, and blockers. |
| **QuarterDeck** | The web console used to review and direct each phase. |
| **Commander** | You — the product owner who approves the work. |
| **Crew** | The LLM agents that perform the work. |

## Contributing

Help test Drydock on real projects. Open [issues](https://github.com/webcloudstudio/Drydock/issues). See [CONTRIBUTING.md](CONTRIBUTING.md).

## License (See LICENSE)

```
MIT License

Copyright (c) 2026 Web Cloud Studio

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

### Language bundles

Python and Go instructions live in `Rigging/languages/<language>/`, with their compact contracts
and acceptance helpers. Select the existing `python.md` or `go.md` name in the technology stack.
Go tests execute through `drydock_go.run_test` inside Blueprint ACs; skipped or absent tests do
not pass. Persistence implementation files are described by each language's contract.

Python and Go both generate persistence from `DATABASE.md`, using bundled SQLite/PostgreSQL
libraries. Go requires an existing `go.mod`, downloaded pinned drivers, CGO and a C compiler for
SQLite. Drydock links the generated `persistence/` module and applies schema through its command.
Select exactly one language and zero or one database engine. Existing-table migrations and
automatic per-criterion code tracing remain separate capabilities.

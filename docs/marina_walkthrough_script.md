# Drydock Marina Walkthrough Script

**Purpose:** introductory product walkthrough using Marina as the demo project.
**Target runtime:** 10-14 minutes after editing.
**Recording style:** record each numbered segment as a separate OBS clip; assemble in a video editor.
**Primary proof point:** Drydock produces and maintains working code from a governed specification pipeline.

## Production Plan

Record the talk in short clips. Keep every clip under two minutes. If a command waits on the LLM, narrate the setup, cut away, then show the result artifact after the command completes.

Recommended OBS scenes:

| Scene | Use |
|---|---|
| Talking head | Intro, transitions, conclusion |
| Terminal full screen | Install, config, Drydock commands, tests |
| Editor full screen | Blueprint, Manifest, change ticket, generated code |
| Browser full screen | QuarterDeck and Marina running locally |
| Split terminal/browser | Command result beside working application |

Demo paths used in this walkthrough:

```bash
cd /mnt/c/Users/barlo/projects/Drydock
export PROJECT=Marina3
export SOURCE=/mnt/c/Users/barlo/projects/Specifications/Marina
export BUILD=/mnt/c/Users/barlo/projects/Marina
```

Before recording, prepare these windows:

| Window | Location |
|---|---|
| Drydock repo terminal | `/mnt/c/Users/barlo/projects/Drydock` |
| Drydock target editor | `targets/Marina3` |
| Marina generated-code editor | `/mnt/c/Users/barlo/projects/Marina` |
| Browser for QuarterDeck | Drydock QuarterDeck command output URL |
| Browser for Marina | `http://localhost:5001` |

## Segment 1 - Installation First

**Target length:** 60-75 seconds.
**Visual:** terminal showing install and configuration commands.

**Say:**

Drydock installs as a normal Python command-line tool. The package name is `drydock-sdd`, and the command is `drydock`.

For most users, the clean install is:

```bash
uv tool install drydock-sdd
```

or:

```bash
pipx install drydock-sdd
```

Drydock does not use an API key or a per-token API billing path. It uses a subscription-authenticated provider CLI that is already installed and logged in. I can use Claude or Codex. I configure that once:

```bash
drydock config set llm_provider codex
drydock config set drydock_workspace /mnt/c/Users/barlo/projects/Drydock
drydock config set drydock_build_directory /mnt/c/Users/barlo/projects
drydock config show
```

That gives me two roots: the Drydock workspace, where targets, Blueprints, manifests, logs, and evidence live; and the build directory, where the generated application code is written.

**Screen actions:**

1. Show `drydock --version`.
2. Show `drydock config show`.
3. If the real install is already done, do not reinstall. Say "On this machine it is already installed" and show the verification commands.

**Edit note:** cut the install wait. Keep the command and final success output.

## Segment 2 - The SDD Problem

**Target length:** 75-90 seconds.
**Visual:** talking head, then quick cuts of an oversized spec, a generated code tree, and a stale TODO or failing test if available.

**Say:**

The problem with specification-driven development is not that specifications are bad. The problem is that the current workflow usually stops at the specification.

You can write a good spec. You can hand it to an LLM. You can get a burst of code. But then three hard problems show up.

First, how do you build the system in the right order? Large specs are dependency graphs, not linear prompts.

Second, how do you keep the build accurate when the model context is limited? If the prompt is too large, important details fall out. If the prompt is too small, the model guesses.

Third, how do you maintain the product after the first build? Real software changes. Requirements drift. Bugs become tickets. Architecture decisions get revised. If the spec and code separate, the process is over.

So the missing piece is not another prompt. It is a delivery process.

## Segment 3 - The Drydock Solution

**Target length:** 90 seconds.
**Visual:** editor showing `targets/Marina3/blueprint`, then `targets/Marina3/MANIFEST.md`, then compact files.

**Say:**

Drydock adds the missing process layer.

The solution is a pipeline: Test-Driven Development, Agile decomposition, a graph database build plan, and context compression.

TDD gives every story a testable contract. The acceptance criteria are not vague prose. They become checks the build must satisfy.

Agile gives the decomposition model. The Commander is the product owner. The LLM acts as the delivery team. The process produces features, stories, spikes, blockers, questions, and reviewable decisions.

The Manifest is the graph. It records the work, dependencies, state, story points, and the relationship between a story and the Blueprint files it implements.

Compression keeps the model focused. A builder gets the full context needed to implement a story. A consumer gets the compact interface view needed to use what already exists. Drydock manages that context explicitly instead of hoping the model attends to the right files.

**Screen actions:**

```bash
find targets/Marina3/blueprint -maxdepth 1 -type f | sort | head -40
sed -n '1,120p' targets/Marina3/MANIFEST.md
ls targets/Marina3/blueprint/*_compact.md
```

**Edit note:** the Manifest is the key visual. Zoom until filenames, state, dependencies, and story points are readable.

## Segment 4 - Marina Demo Setup

**Target length:** 75 seconds.
**Visual:** terminal plus editor showing Marina source specs.

**Say:**

For the walkthrough, I am using Marina. Marina is a local-first developer control plane. It runs as a Flask and SQLite application. It scans a projects directory, manages project state, and builds toward a private AWS broadcast surface.

Here is the input material. These are human-readable Markdown specifications for architecture, database design, features, and screens.

```bash
find "$SOURCE" -maxdepth 1 -type f | sort
```

The Drydock target for this demo is `Marina3`. The generated application is written to `/mnt/c/Users/barlo/projects/Marina`.

**Screen actions:**

1. Show `/mnt/c/Users/barlo/projects/Specifications/Marina`.
2. Open `FEATURE-MARINA-LIB.md`.
3. Open `ARCHITECTURE.md`.
4. Show `targets/Marina3/METADATA.md`.

## Segment 5 - Initialize, Import, Analyze

**Target length:** 90-120 seconds.
**Visual:** terminal commands, then result files.

**Say:**

The first Drydock phase is setup and analysis.

I initialize the target:

```bash
drydock init Marina3 --llm-provider codex
```

Then I import the Marina specifications:

```bash
drydock import Marina3 /mnt/c/Users/barlo/projects/Specifications/Marina --format markdown --llm-provider codex
drydock import Marina3 /mnt/c/Users/barlo/projects/Specifications/Marina/INTENT.md --format compass --force
```

Then Drydock analyzes the material:

```bash
drydock analyze Marina3 --llm-provider codex
```

Analyze is where the Agile model starts. Drydock decomposes the source material into features, stories, blockers, questions, and acceptance criteria. If the team cannot proceed safely, it asks. It does not silently invent the missing decision.

**Screen actions after command completes:**

```bash
sed -n '1,160p' targets/Marina3/ANALYSIS.md
find targets/Marina3/QuarterDeck/questionnaires -type f | sort
```

**Edit note:** record the command invocation and the completed artifact separately. In the final video, use a hard cut or a title card: "Analyze completes".

## Segment 6 - QuarterDeck Review

**Target length:** 90 seconds.
**Visual:** browser with QuarterDeck.

**Say:**

This is the QuarterDeck. It is the Commander review surface.

The important point is that Drydock does not treat the LLM as a magic writer. It treats the LLM as an Agile team producing reviewable work. The Commander reviews questions, blockers, story structure, and the plan before committing the build path.

For Marina, I can inspect the generated discovery questions, the story breakdown, and the planning state. This is where the human operator keeps control of the product.

**Screen actions:**

```bash
drydock run quarterdeck Marina3 --llm-provider codex
```

Then in the browser:

1. Show the Commander view.
2. Show questionnaires if present.
3. Show the build or planning board.
4. Show that decisions are persisted under `targets/Marina3/QuarterDeck`.

**Edit note:** if starting QuarterDeck takes time, start it before recording and capture the already-running browser.

## Segment 7 - Plan: Blueprint Plus Graph DB

**Target length:** 90 seconds.
**Visual:** terminal, then `blueprint/`, then `MANIFEST.md`.

**Say:**

After review, Drydock plans the work.

```bash
drydock plan Marina3 --llm-provider codex
```

Plan turns the analysis into governed Blueprints and the Manifest. The Blueprints are typed specification files. Each one has a role: architecture, database, feature, screen, or UI.

The Manifest is the executable graph database for the build. It is not just a task list. It records dependencies, runnable state, story points, implementation targets, and context relationships.

That graph is why Drydock can answer: what can be built now, what is blocked, what depends on what, and what must be rebuilt when a specification changes.

**Screen actions after command completes:**

```bash
find targets/Marina3/blueprint -maxdepth 1 -type f | sort | sed -n '1,80p'
sed -n '1,220p' targets/Marina3/MANIFEST.md
```

**Edit note:** if the Manifest is long, prepare search jumps for `state:`, `depends:`, `implements:`, and `story_points:`.

## Segment 8 - Compression

**Target length:** 60-75 seconds.
**Visual:** compact files beside source Blueprint files.

**Say:**

The next key mechanism is compression.

```bash
drydock rigging compact Marina3 --llm-provider codex
```

The point is simple. Not every future story needs the full implementation details of every previous story. A builder needs deep context for the thing being built. A consumer needs the interface and usage contract for things that already exist.

So Drydock creates compact views and uses them in later prompts. That is how the build keeps enough context to be accurate without flooding the model with irrelevant material.

**Screen actions:**

```bash
ls targets/Marina3/blueprint/*_compact.md
sed -n '1,120p' targets/Marina3/blueprint/ARCHITECTURE_compact.md
```

## Segment 9 - Build: From Graph to Code

**Target length:** 90-120 seconds.
**Visual:** terminal command, then evidence, then generated files.

**Say:**

Now Drydock builds. It walks the Manifest frontier: the next runnable work whose dependencies are satisfied.

```bash
drydock build Marina3 --llm-provider codex
```

This may take a few seconds or longer because the provider CLI is doing real work. For the video, I record the command, cut the wait, and show the result.

The important thing is that Drydock is not asking the model to build the whole application in one prompt. It is building one graph step at a time, with the correct Blueprint slice, stack rules, context, and acceptance criteria.

After the build step, I can show the generated code in the Marina project:

```bash
find /mnt/c/Users/barlo/projects/Marina -maxdepth 2 -type f | sort | sed -n '1,120p'
```

**Screen actions after command completes:**

1. Show `targets/Marina3/MANIFEST.md` state changes.
2. Show `targets/Marina3/evidence` if build evidence exists.
3. Show changed files under `/mnt/c/Users/barlo/projects/Marina`.
4. Open a generated Python module and a matching test.

**Edit note:** if a live build is unpredictable, use a completed Marina build step. Say "Here is the completed result from this target" and show the manifest, evidence, code, and tests.

## Segment 10 - Show Working Code: Tests

**Target length:** 60-90 seconds.
**Visual:** terminal in `/mnt/c/Users/barlo/projects/Marina`.

**Say:**

The first proof is tests.

Drydock is built around TDD-style acceptance. Marina has a project test command:

```bash
cd /mnt/c/Users/barlo/projects/Marina
./bin/test.sh
```

This runs dependency sync, lint, formatting checks, and pytest. The output matters because it turns the walkthrough from a generated-code demo into a working-software demo.

**Screen actions:**

1. Run or replay `./bin/test.sh`.
2. Show `ruff check`.
3. Show pytest passing.
4. Open one test file that maps to a built feature.

**Edit note:** keep only the command, a few lines of test names, and the final pass summary. Cut dependency-sync noise.

## Segment 11 - Show Working Code: Browser

**Target length:** 90 seconds.
**Visual:** terminal starting Marina, then browser at `http://localhost:5001`.

**Say:**

The second proof is the application running.

Marina starts as a local Flask application:

```bash
cd /mnt/c/Users/barlo/projects/Marina
./bin/start.sh
```

The app runs on port 5001.

Now I open the health check and the setup screens:

```text
http://localhost:5001/health
http://localhost:5001/setup/summary
```

This is the visual proof point. The pipeline started with Markdown specifications. Drydock decomposed them, planned the graph, built the frontier, and now the generated application runs.

**Screen actions:**

1. Show `/health` returning `{"status":"ok"}`.
2. Show `/setup/summary`.
3. Show any visible project, setup, repository, or status screen that is implemented.
4. Place the browser beside the source file implementing that route if possible.

**Edit note:** this is the key audience-retention segment. Keep it visual and concrete. Do not linger on terminal output.

## Segment 12 - How Drydock Maintains Software: Refit

**Target length:** 90 seconds.
**Visual:** editor showing a Blueprint and `blueprint/changes`.

**Say:**

Building once is not enough. The harder question is maintenance.

Drydock solves maintenance with `refit`.

There are two maintenance paths. First, if a built Blueprint changes, Drydock can detect drift against the applied specification records and reset the dependent graph path. Second, a change can enter as a change ticket.

The change ticket is important because it keeps maintenance inside the same Agile and TDD pipeline. The ticket amends an existing spec. Refit conforms that ticket, derives dependencies from the parent spec, patches the Manifest, and the next build processes the change as normal work.

That means the change does not bypass the process. It becomes part of the graph.

**Screen actions:**

```bash
find targets/Marina3/blueprint/changes -maxdepth 1 -type f | sort
sed -n '1,120p' targets/Marina3/MANIFEST.md
```

## Segment 13 - Show a Change Ticket

**Target length:** 90-120 seconds.
**Visual:** editor creating or showing a prepared ticket.

**Say:**

Here is what a change ticket looks like.

It is just Markdown, but it has a typed header. The most important field is `Amends:`. That tells Drydock which Blueprint this ticket modifies.

Example:

```markdown
# TICKET-001-Setup-Health-Detail
FileType: CHANGE
Amends: FEATURE-HEALTHCHECK.md
Depends On:

## Intent

Add a visible health detail panel to the setup summary page so the operator can see
application status without opening the raw health endpoint.

## Programmatic Acceptance

- `GET /setup/summary` renders the health status text.
- `GET /health` continues to return JSON status `ok`.
- Existing health-check tests continue to pass.
```

Then I run:

```bash
drydock refit Marina3 --llm-provider codex
drydock build Marina3 --llm-provider codex
```

Refit ties the change back to the parent Blueprint, updates the Manifest, and lets Drydock rebuild the necessary work.

**Screen actions:**

1. Show the ticket in `targets/Marina3/blueprint/changes/`.
2. Show `Amends: FEATURE-HEALTHCHECK.md`.
3. Run or show `drydock refit Marina3`.
4. Show new or reset Manifest rows.

**Edit note:** do not create this ticket live unless you want the demo to modify the target. A prepared ticket is fine. The educational point is the shape of the change loop.

## Segment 14 - Show Working Code Again After the Change

**Target length:** 75-90 seconds.
**Visual:** browser and tests.

**Say:**

After the refit and build, I prove the product still works the same way I proved the first build.

I run the tests:

```bash
cd /mnt/c/Users/barlo/projects/Marina
./bin/test.sh
```

Then I run the application:

```bash
./bin/start.sh
```

And I show the changed behavior in the browser.

This is the core maintenance claim: a change is not a one-off chat session. It is a ticket, connected to the specification, inserted into the graph, built with the right context, and verified in working code.

**Screen actions:**

1. Show tests passing.
2. Show browser behavior after the change.
3. Show the relevant code diff or changed file.
4. Show Manifest state after the build.

## Segment 15 - Closing

**Target length:** 45-60 seconds.
**Visual:** talking head, then final browser/code split.

**Say:**

Drydock is not trying to replace engineering discipline with prompts.

It is doing the opposite. It brings engineering discipline back into specification-driven development: Agile decomposition, TDD acceptance, a graph build plan, context compression, evidence, and a maintenance loop.

That is the difference between generating code once and owning software over time.

For Marina, the visible result is a working local application. The deeper result is the process behind it: the spec stays authoritative, the graph explains the build, and refit gives me a controlled way to change the product.

That is Drydock.

## Editing Map

| Final section | Best source clips |
|---|---|
| Install | Segment 1 |
| SDD issue | Segment 2 |
| Solution architecture | Segments 3 and 8 |
| Marina setup | Segments 4 and 5 |
| Review and graph | Segments 6 and 7 |
| Build | Segment 9 |
| Working code proof | Segments 10 and 11 |
| Maintenance and refit | Segments 12 and 13 |
| Working code after change | Segment 14 |
| Close | Segment 15 |

## Must-Capture Visuals

| Visual | Why it matters |
|---|---|
| `drydock --version` and `drydock config show` | Proves installation and local setup |
| `Specifications/Marina` files | Shows human-readable input material |
| `targets/Marina3/blueprint` | Shows typed Blueprint output |
| `targets/Marina3/MANIFEST.md` | Shows graph database build plan |
| QuarterDeck browser | Shows human review and Agile control |
| `*_compact.md` files | Shows context compression |
| `drydock build Marina3` | Shows graph execution |
| `/mnt/c/Users/barlo/projects/Marina` source tree | Shows generated working code |
| `./bin/test.sh` passing | Shows verification |
| `http://localhost:5001` | Shows working application |
| `blueprint/changes/TICKET-*.md` | Shows maintainability path |
| code/browser after refit | Shows change loop completion |

## One-Line Transitions

Use these when joining clips:

- "Now that Drydock is installed, the question is what problem it solves."
- "The answer is a pipeline, not a prompt."
- "Marina is the concrete project I am using to show the pipeline."
- "The command may take a minute, so I will cut from invocation to completed artifacts."
- "The Manifest is where the demo becomes more than generated text."
- "Now I need to prove this is working software."
- "The first build matters, but maintenance is where most generated-code workflows fail."
- "The change goes through the same graph instead of bypassing the process."

## Short Social Cutdowns

Create these from the same recording session:

| Cutdown | Duration | Source |
|---|---:|---|
| "The SDD gap" | 45-60 seconds | Segment 2 |
| "Drydock in one diagram" | 45-60 seconds | Segment 3 |
| "The Manifest is a graph DB" | 30-45 seconds | Segment 7 |
| "Context compression" | 30-45 seconds | Segment 8 |
| "Generated code running" | 45-60 seconds | Segments 10 and 11 |
| "Refit change loop" | 60-90 seconds | Segments 12-14 |

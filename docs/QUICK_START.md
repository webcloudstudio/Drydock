# Drydock Quick Start Guide

This guide takes a small project from an idea to a working build. Replace `MyApp` with your
project name.

The command sequence is:

```text
install → configure → init → import → analyze → plan → validate → build → score
```

## Before you begin

You need Python 3.11 or newer, Drydock, and one of these subscription-authenticated command-line
programs:

- `claude` from Anthropic; or
- `codex` from OpenAI.

Install and sign in to the provider you choose before running `analyze`, `plan`, or `build`.
Drydock does not use API keys or per-token billing.

## 1. Install and configure Drydock

Install Drydock with `uv` or `pipx`:

```bash
# Install the Drydock command.
uv tool install drydock-sdd
# Or: pipx install drydock-sdd
drydock --version
```

Set the provider and directories in one step. `$PROJECTS` is the directory where you keep your
projects; change it if you use a different location.

```bash
# Set the directory that contains your projects.
export PROJECTS="$HOME/projects"
# Create the Drydock workspace. `drydock init` creates the project directories later.
mkdir -p "$PROJECTS/drydock"

# Choose the provider CLI that you installed and signed in to.
drydock config set llm_provider claude       # Use codex here if you use Codex.
# Set the default model. `sonnet` is also Drydock's built-in default.
drydock config set drydock_model sonnet
# Store Targets and logs in the workspace.
drydock config set drydock_workspace "$PROJECTS/drydock"
# Store generated applications under the projects directory.
drydock config set drydock_build_directory "$PROJECTS"
# Display the saved configuration.
drydock config show
```

This creates the following layout:

```text
$PROJECTS/
├── drydock/              # Drydock workspace, Targets, and logs
└── MyApp/                # Generated application after the build
```

The provider command must already be installed, signed in, and available on your `PATH`. The
`llm_provider` setting tells Drydock which command to run. If you use Codex, change `claude` to
`codex` in the configuration command.

## 2. Create a project

Create a Target. A Target is Drydock's workspace for one project.

```bash
# Create the Target and its initial directories and files.
drydock init MyApp \
  --display-name "My App" \
  --description "A small software project."
# Confirm that the Target exists.
drydock status MyApp
```

`drydock init` creates the project layout. The Target is at
`$PROJECTS/drydock/targets/MyApp/`:

```text
$PROJECTS/drydock/targets/MyApp/
├── blueprint/sources/
├── blueprint/changes/
├── evidence/
├── logs/
├── QuarterDeck/data/
└── METADATA.md
```

The generated application will be written to `$PROJECTS/MyApp/`.

## 3. Write the project notes

Write a short Markdown file describing one useful feature. Include:

- who uses it;
- what the user does;
- what the software receives and produces;
- what happens when input is invalid; and
- how you will know it works.

For example:

```markdown
# Reading List

A reader keeps a list of books to read.

The reader can add a book by title and author and list saved books in the order added.
An empty title is rejected with an error message.

Done when:

- adding a book works;
- listing books works;
- an empty title is rejected; and
- automated tests cover these cases.
```

Keep the first project small. One or two useful actions are enough. Put the file in `notes/` and
import it:

```bash
# Create a directory for the notes you will import.
mkdir -p notes
# Copy the notes into the Target as planning input.
drydock import MyApp ./notes --format markdown
```

## 4. Analyze the project

Run `analyze` to have Drydock read the imported notes and produce a proposed set of features,
questions, and acceptance criteria:

```bash
# Read the imported notes and create the analysis files.
drydock analyze MyApp
```

`analyze` creates `ANALYSIS.md`, stories, acceptance milestones, questions, and project-level
acceptance goals. If `BLOCKERS.md` exists, answer the questions in it and run `drydock analyze MyApp`
again. You can answer questions and edit guidance in the QuarterDeck:

```bash
# Start the local planning console.
drydock run quarterdeck MyApp
```

The QuarterDeck is the human decision point in Analyze. Use it to answer questions, resolve
blockers, and adjust project guidance. The next command is `plan`; there is no separate command
for reviewing a plan.

When the analysis is correct, create the build plan:

```bash
# Convert the analyzed project into Blueprint files and a Manifest.
drydock plan MyApp
# Check that the Blueprint satisfies the typed specification rules.
drydock validate MyApp
```

`plan` creates the Blueprint and `MANIFEST.md`. The Blueprint describes what the product should do;
the Manifest records the dependency-aware build order. `validate` checks the Blueprint without
calling an LLM.

## 5. Build the project

Preview the build if you want to see what will happen:

```bash
# Show the prompt and work that the next build would use.
drydock build MyApp --dry-run --show-prompt
```

Build the project and check its progress:

```bash
# Build the next available work.
drydock build MyApp
# Show completed, blocked, and remaining work.
drydock build status MyApp
```

Run the build again to continue with the next work item. Review the application and tests as the
project grows so that problems are easy to find.

## 6. Check the results

Run the automated acceptance checks and the project review:

```bash
# Check each programmatic acceptance criterion.
drydock score ac MyApp
# Run the project-level release review.
drydock score release MyApp
```

Review `SOUNDINGS.md` for automated results and `SCORECARD.md` for the project review. A successful
build command does not by itself prove that the project is complete; confirm that the results meet
the goals in `SEA_TRIALS.md`.

## Making changes

When the product changes, change the Blueprint first. You can edit an existing specification or
add a change ticket under `blueprint/changes/`. A change ticket names the specification it changes
with an `Amends:` field. For example:

```text
$PROJECTS/drydock/targets/MyApp/blueprint/changes/TICKET-001-reading-list.md
Amends: FEATURE-Reading-List.md
```

Then run:

```bash
# Conform change tickets, update the Manifest, and reset affected work.
drydock refit MyApp
# Rebuild the affected work in dependency order.
drydock build MyApp
# Verify the changed product.
drydock score ac MyApp
```

`refit` maps the change into the Manifest and resets the changed specification's consumer blocks
and their dependent work. The normal build and acceptance process then applies to the change.

## First-project checklist

- [ ] Drydock is installed and a provider CLI is signed in.
- [ ] The workspace and build directory are configured.
- [ ] A Target has been created.
- [ ] The first feature is described in a short Markdown file.
- [ ] The analysis has no unresolved blockers.
- [ ] The Blueprint has been validated.
- [ ] The project has been built and checked.

For the full installation procedure, see the [User Installation Guide](USER_INSTALLATION.md).
For complete command contracts, see the [Drydock Specification](Drydock_Specification.md).

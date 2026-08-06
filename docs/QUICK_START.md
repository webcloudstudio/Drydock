# Drydock Quick Start Guide

This guide takes a small project from an idea to a working build. Replace `MyApp` with your
project name.

The command sequence is:

```text
install → configure → init → import → analyze → plan → build → score
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

## 4. Analyze and review the notes

Run `analyze` to have Drydock read the imported notes and produce a proposed set of features,
questions, and acceptance criteria:

```bash
# Read the imported notes and create the analysis files.
drydock analyze MyApp
```

Review `ANALYSIS.md`, `SEA_TRIALS.md`, and `COMPASS.md` in the Target. If `BLOCKERS.md` exists,
answer the questions in it and run `drydock analyze MyApp` again. You can use the browser review
console with `drydock run quarterdeck MyApp`. Reviewing means reading the generated files,
correcting misunderstandings, answering questions, and deciding whether the proposed work matches
your project. It is a user action, not a separate planning command.

When the analysis is correct, create the build plan:

```bash
# Convert the reviewed analysis into Blueprint files and a Manifest.
drydock plan MyApp
# Show whether the Manifest has work ready to build.
drydock build status MyApp
```

The Blueprint describes what the product should do. The Manifest lists the work and its order.
Before building, check that the plan describes the right features, includes error cases, and has
work items small enough to test.

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

Update the project description before changing the software. Then run:

```bash
# Update the build plan after changing the project description.
drydock refit MyApp
# Build the work affected by the change.
drydock build MyApp
# Run acceptance checks again.
drydock score ac MyApp
```

This keeps the project description, build plan, and software in agreement.

## First-project checklist

- [ ] Drydock is installed and a provider CLI is signed in.
- [ ] The workspace and build directory are configured.
- [ ] A Target has been created.
- [ ] The first feature is described in a short Markdown file.
- [ ] The analysis has no unresolved blockers.
- [ ] The plan has been reviewed.
- [ ] The project has been built and checked.

For the full installation procedure, see the [User Installation Guide](USER_INSTALLATION.md).
For complete command contracts, see the [Drydock Specification](Drydock_Specification.md).

# Drydock Quick Start Guide

This guide takes a small project from an idea to a working build. Replace `MyApp` with your
project name.

The process is:

```text
install → configure → describe → review → plan → build → check
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
uv tool install drydock-sdd
# Or: pipx install drydock-sdd
drydock --version
```

Set the provider and directories in one step. `$PROJECTS` is the directory where you keep your
projects; change it if you use a different location.

```bash
export PROJECTS="$HOME/projects"
mkdir -p "$PROJECTS/drydock"

drydock config set llm_provider claude       # use codex if that is your provider
claude --version                             # use codex --version for Codex
drydock config set drydock_workspace "$PROJECTS/drydock"
drydock config set drydock_build_directory "$PROJECTS"
drydock config show
```

This creates the following layout:

```text
$PROJECTS/
├── drydock/              # Drydock workspace, Targets, and logs
└── <Target>/             # Generated application
```

The provider command must be installed, signed in, and available on your `PATH`. If you use
Codex, replace both instances of `claude` above with `codex`.

## 2. Create a project

Create a Target. A Target is Drydock's workspace for one project.

```bash
drydock init MyApp \
  --display-name "My App" \
  --description "A small software project."
drydock status MyApp
```

The Target is created at `$PROJECTS/drydock/targets/MyApp/`. The generated application will be
written to `$PROJECTS/MyApp/`.

## 3. Describe the first feature

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
mkdir -p notes
drydock import MyApp ./notes --format markdown
```

## 4. Review the plan

Ask Drydock to read your notes:

```bash
drydock analyze MyApp
```

Review `ANALYSIS.md`, `SEA_TRIALS.md`, and `COMPASS.md` in the Target. If `BLOCKERS.md` exists,
answer the questions in it and run `drydock analyze MyApp` again. You can use the browser review
console with `drydock run quarterdeck MyApp`.

When the analysis is correct, create the build plan:

```bash
drydock plan MyApp
drydock build status MyApp
```

The Blueprint describes what the product should do. The Manifest lists the work and its order.
Before building, check that the plan describes the right features, includes error cases, and has
work items small enough to test.

## 5. Build the project

Preview the build if you want to see what will happen:

```bash
drydock build MyApp --dry-run --show-prompt
```

Build the project and check its progress:

```bash
drydock build MyApp
drydock build status MyApp
```

Run the build again to continue with the next work item. Review the application and tests as the
project grows so that problems are easy to find.

## 6. Check the results

Run the automated acceptance checks and the project review:

```bash
drydock score ac MyApp
drydock score release MyApp
```

Review `SOUNDINGS.md` for automated results and `SCORECARD.md` for the project review. A successful
build command does not by itself prove that the project is complete; confirm that the results meet
the goals in `SEA_TRIALS.md`.

## Making changes

Update the project description before changing the software. Then run:

```bash
drydock refit MyApp
drydock build MyApp
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

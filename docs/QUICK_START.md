# Drydock Quick Start Guide

This guide shows you how to use Drydock to build a small software project.

The basic process is:

1. Install Drydock.
2. Create a project.
3. Describe what you want to build.
4. Review the plan.
5. Build the project.
6. Check that it works.

The examples use `MyApp` as the project name. Replace it with the name of your project.

## Before you begin

You need:

- Python 3.11 or newer;
- Drydock;
- either the `claude` or `codex` command-line program; and
- an active subscription for the provider you choose.

Drydock uses your existing Claude or Codex subscription. It does not require an API key.

## 1. Install Drydock

Install Drydock with `uv`:

```bash
uv tool install drydock-sdd
drydock --version
```

Install and sign in to either Claude or Codex. Then tell Drydock which one to use:

```bash
drydock config set llm_provider claude
```

Use this instead if you use Codex:

```bash
drydock config set llm_provider codex
```

## 2. Set up a workspace

Drydock keeps each project in a workspace. The workspace contains your project description,
planning files, build history, tests, and review results.

```bash
mkdir -p "$HOME/drydock"
drydock config set drydock_workspace "$HOME/drydock"
drydock config set drydock_build_directory "$HOME/drydock/build"
drydock config show
```

You can use a different directory if you prefer.

## 3. Create your project

Create a project workspace called a Target:

```bash
drydock init MyApp \
  --display-name "My App" \
  --description "A small software project."
```

Check that it was created:

```bash
drydock status MyApp
```

The project files are stored here:

```text
$HOME/drydock/targets/MyApp/
```

The application Drydock builds will be stored here:

```text
$HOME/drydock/build/MyApp/
```

## 4. Describe what you want to build

Create a directory for your project notes:

```bash
mkdir -p notes
```

Add one or more Markdown files to that directory. Start with a short description. Explain:

- who will use the software;
- what problem it solves;
- what the user should be able to do;
- what information the software receives;
- what it should produce; and
- what should happen when something goes wrong.

For example:

```markdown
# Reading List

The application helps a reader keep a list of books to read.

## Add a book

The reader enters a book title and author. The application saves the book.

An empty title is rejected with an error message.

## List books

The reader can display all saved books in the order they were added.

## Done when

- A reader can add a book.
- A reader can list saved books.
- An empty title is rejected.
- Automated tests cover these actions.
```

Keep the first project small. One or two useful actions are enough for your first build. You can
add more features later.

Import your notes into Drydock:

```bash
drydock import MyApp ./notes --format markdown
```

Drydock copies the notes into the project workspace. It uses them as the starting point for the
plan.

## 5. Let Drydock prepare a plan

Run the analysis command:

```bash
drydock analyze MyApp
```

Drydock reads your notes and writes a proposed list of features, questions, and tests. Review the
result before building anything.

The most important files are:

| File | What it contains |
|---|---|
| `ANALYSIS.md` | Drydock's understanding of your project |
| `BLOCKERS.md` | Questions that must be answered before planning can continue |
| `SEA_TRIALS.md` | The conditions the finished project must meet |
| `COMPASS.md` | General instructions for this project |

If `BLOCKERS.md` exists, answer the questions in it and run the analysis again:

```bash
drydock analyze MyApp
```

You can also review the files in a web browser:

```bash
drydock run quarterdeck MyApp
```

Review the plan carefully. Correct misunderstandings, remove features you do not need, and make
sure the tests describe what you actually want.

## 6. Create the build plan

When the analysis looks right, create the Blueprint and Manifest:

```bash
drydock plan MyApp
```

The Blueprint is the set of files that describes what the product should do. The Manifest is the
list of work items and the order in which Drydock should build them.

Check the plan before starting the build:

```bash
drydock build status MyApp
```

Make sure that:

- each item describes one clear result;
- the items are small enough to test;
- normal and error cases are included; and
- the order makes sense.

If the plan is wrong, update your notes and run the appropriate command again. Fix the description
of the project before asking Drydock to build it.

## 7. Build the project

You can preview the next build first:

```bash
drydock build MyApp --dry-run --show-prompt
```

When you are ready, build the project:

```bash
drydock build MyApp
```

Check the progress:

```bash
drydock build status MyApp
```

Drydock builds the work in order. Run the build command again to continue with the next item.
Build and review a small amount of work at a time so that problems are easy to find.

## 8. Check the results

Run the acceptance checks:

```bash
drydock score ac MyApp
```

Run the project review:

```bash
drydock score release MyApp
```

Review these files:

- `SOUNDINGS.md` contains the results of the automated acceptance checks.
- `SCORECARD.md` contains the project review.
- `SEA_TRIALS.md` contains the goals used for the review.

A successful build command does not automatically mean the project is complete. Check the results,
run the tests, and make sure the project does what your notes describe.

## 9. Make a change

When you want to add or change a feature, update the project description first. Then run:

```bash
drydock refit MyApp
drydock build MyApp
drydock score ac MyApp
```

`refit` updates the plan to match the new description. Drydock then rebuilds the work affected by
the change.

Keep this rule in mind:

> Describe the change first. Build the software second.

## A good first project

For your first Drydock project, choose something like:

- a small command-line tool;
- a simple web service;
- a file conversion utility; or
- a small data-processing script.

Avoid starting with a large system that includes authentication, billing, deployment, several
external services, and many different types of users. Start with one useful feature and add the
rest after the first feature works.

## Quick checklist

- [ ] Drydock is installed.
- [ ] Claude or Codex is installed and signed in.
- [ ] Drydock has a configured workspace.
- [ ] A Target has been created.
- [ ] Project notes explain the first useful feature.
- [ ] The analysis has no unanswered blockers.
- [ ] The plan has been reviewed.
- [ ] The project has been built.
- [ ] Acceptance checks have been run.
- [ ] The results have been reviewed.

For the complete command reference, see the [Drydock Specification](Drydock_Specification.md).
For installation options, see the [User Installation Guide](USER_INSTALLATION.md).

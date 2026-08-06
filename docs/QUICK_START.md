# Drydock Quick Start Guide

This guide takes `MyApp` from project material to working software. Replace `MyApp` with your
Target name and replace `YOUR_PROJECT_DIR` with the directory where you keep your projects.

## Prerequisites

- [ ] Python 3.11 or newer.
- [ ] `uv` or `pipx` for installing the Drydock command.
- [ ] The `claude` or `codex` provider CLI installed and signed in.
- [ ] A subscription for the provider CLI you selected.

## 1. Install and configure Drydock

```bash
uv tool install drydock-sdd                 # Install Drydock with uv.
# pipx install drydock-sdd                  # Or install it with pipx.
drydock --version                           # Confirm that the command is available.
export YOUR_PROJECT_DIR="/path/to/projects" # Set this to your own project directory.
mkdir -p "$YOUR_PROJECT_DIR/drydock"       # Create the Drydock workspace directory.
drydock config set llm_provider claude      # Use codex here if you use Codex.
drydock config set drydock_model sonnet     # Set the default model.
drydock config set drydock_workspace "$YOUR_PROJECT_DIR/drydock" # Store Targets and logs here.
drydock config set drydock_build_directory "$YOUR_PROJECT_DIR"   # Write generated apps here.
drydock config show                         # Confirm the saved configuration.
```

The provider CLI must be installed and signed in before you run `analyze`, `plan`, or `build`.
The `llm_provider` setting tells Drydock which provider command to run. `sonnet` is the default
model for the configured provider; set another model with `drydock config set drydock_model <model>`
when required.

## 2. Initialize `MyApp`

```bash
drydock init MyApp --display-name "My App" --description "A software project." # Create the Target.
drydock status MyApp                                                        # Confirm it exists.
```

`drydock init` creates the Target workspace and its initial directories:

```text
$YOUR_PROJECT_DIR/drydock/targets/MyApp/
├── blueprint/sources/
├── blueprint/changes/
├── evidence/
├── logs/
├── QuarterDeck/data/
└── METADATA.md
```

The generated application is written to `$YOUR_PROJECT_DIR/MyApp/`.

## 3. Import project material

Put the material that describes the project in Markdown files under `notes/`. Include the users,
desired behavior, inputs, outputs, error behavior, and how the result will be tested.

```bash
mkdir -p notes                                      # Create a local source directory.
drydock import MyApp ./notes --format markdown      # Copy the material into the Target.
```

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

## 4. Analyze the project

```bash
drydock analyze MyApp # Derive stories, acceptance milestones, questions, and blockers.
```

Analyze creates `ANALYSIS.md`, `SEA_TRIALS.md`, and other planning artifacts in the Target. If
`BLOCKERS.md` exists, answer the questions in it and run Analyze again:

```bash
drydock analyze MyApp # Re-run after answering blockers or changing Analyze guidance.
```

Use the QuarterDeck to answer questions, resolve blockers, and adjust project guidance:

```bash
drydock run quarterdeck MyApp # Start the local planning console.
```

## 5. Create and validate the Blueprint

```bash
drydock plan MyApp     # Create the Blueprint and dependency-aware MANIFEST.md.
drydock validate MyApp  # Check Blueprint conformance without calling an LLM.
```

The Blueprint defines the product. `MANIFEST.md` defines the build order. There is no separate
plan-review command; the human decision point is in Analyze and the QuarterDeck before `plan`.

## 6. Build and score the project

Preview the next build when needed:

```bash
drydock build MyApp --dry-run --show-prompt # Show the next build without running it.
```

Build the runnable work and check its state:

```bash
drydock build MyApp        # Execute the next available Manifest work.
drydock build status MyApp  # Show completed, blocked, and remaining work.
```

Run the acceptance checks and the release assessment:

```bash
drydock score ac MyApp       # Verify programmatic acceptance criteria; writes SOUNDINGS.md.
drydock score release MyApp   # Assess project-level release criteria; writes SCORECARD.md.
```

## 7. Change the project with Refit

The Blueprint remains the source of truth. For a change, either edit the affected specification or
add a ticket under `blueprint/changes/`. A ticket names its parent specification with `Amends:`:

```text
$YOUR_PROJECT_DIR/drydock/targets/MyApp/blueprint/changes/TICKET-001-reading-list.md
Amends: FEATURE-Reading-List.md
```

Then run the normal change loop:

```bash
drydock refit MyApp        # Conform tickets, update MANIFEST.md, and reset affected work.
drydock build MyApp         # Rebuild the changed work and its required dependencies.
drydock score ac MyApp      # Verify the changed product.
```

`refit` maps the change into the Manifest and resets the changed specification's consumer blocks
and their dependent work. The normal build and acceptance process then applies to the change.

## First-run checklist

- [ ] Drydock is installed and configured.
- [ ] The provider CLI is installed and signed in.
- [ ] `MyApp` is initialized.
- [ ] Project material is imported.
- [ ] Analyze has no unresolved blockers.
- [ ] The Blueprint is validated.
- [ ] The project is built and scored.

For installation details, see the [User Installation Guide](USER_INSTALLATION.md). For complete
command contracts, see the [Drydock Specification](Drydock_Specification.md).

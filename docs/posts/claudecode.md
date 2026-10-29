# Drydock — Building Software from Specifications

**Drydock builds software from your specifications and designs using Agile and Test Driven Development.** It builds with low-end models and provides a full locally hosted Web User Experience—from vibe coding to enterprise tooling.

**Agile Decomposition** turns specifications into buildable Stories/**Blueprints**. A graph database optimizes build ordering and context. Shared technology rules, business rules, and branding provide consistent behavior and style across your software.

I use **Claude Code and Codex** to build Drydock and to build software through it. Builds use **Haiku 5.5**, Codex Luna, or Gemini.

# Self-Improving Builds

**Building from specifications keeps the build tied to your requirements as the project grows.** Specifications define what to build, acceptance criteria measure completion, and changes go back into the specifications.

`plan verify / plan repair` checks and corrects the acceptance criteria used to measure the build. `build` implements the Blueprints and repairs code that fails acceptance criteria. `diagnose --apply` identifies root causes and corrects the Blueprints when build repair cannot resolve the problem.

    drydock init MyApp                            # create the workspace
    drydock import MyApp "$INPUT_DIRECTORY"       # load your specifications, notes, images
    drydock analyze MyApp                         # create stories, questions, blockers
    drydock plan MyApp                            # create Blueprints and Manifest
    drydock plan verify MyApp || drydock plan repair MyApp  # repair/validate acceptance criteria

    # build repairs failed code; diagnose corrects the Blueprints
    n=1; max=3
    while drydock status MyApp --ready
    do
        if [ "$n" -gt "$max" ]
        then
            echo "hit $max build attempts - aborting"
            exit 1
        fi
        echo "*** BUILD ATTEMPT $n ***"
        drydock build MyApp || drydock diagnose MyApp --apply
        n=$((n+1))
    done

    drydock status MyApp --check                  # Deterministic definition of done
    drydock score release MyApp                   # LLM evaluated definition of done

`status --check` measures build completion; `score release` checks acceptance and project objectives. Builds stop when acceptance criteria succeed, no progress is detected, or they fail.

# What I learned

* **A failed test does not always mean failed code.** In Marina, a test required an item moved one position to become first in the entire collection. Diagnosis corrected the assertion to test the specified movement.
* **Some build failures require better specifications.** Repeated code repair cannot resolve an incorrect Blueprint. Diagnosis identifies the root cause and applies Blueprint corrections so the build can continue.
* **Planning and building can need different models.** Two Haiku 5.5 projects required `--plan-override-model sonnet`: planning included large test kits and model output quality became poor.
* **Encapsulation limits rebuilds.** `DATABASE.md` uses named SQL operations and native libraries. Most database changes do not require downstream Blueprint rebuilds.

The UAT matrix records passes for all ten projects under **Haiku**, with the two Sonnet planning overrides noted above, covering Python, Go, SQLite, and Postgres.

For ongoing changes, edit specifications, add change tickets, or comment on Blueprints. `drydock refit` maps changes into the Manifest for incremental builds.

**Code Repository (MIT):** [Drydock](https://github.com/webcloudstudio/Drydock)

# Drydock — Build Software from Specifications

Drydock is an **Enterprise Grade Software Builder (MIT)** that imports specifications and designs and builds software using Agile and Test Driven Development with low-end LLM models. Drydock provides a Web Server UX.

**Goal:** Build software from large specifications that need not be well defined. Maintain it after build.

A large specification needs more than one coding task. Luna needs manageable build steps, the right context, and a way to measure progress. I use **Codex Luna** through Drydock to build the software in steps, measure the results, and correct problems before continuing.

**drydock analyze** uses Agile Decomposition to turn specifications into stories, questions, and blockers. Review and answer before planning.

**drydock plan** creates buildable Stories/**Blueprints**, acceptance criteria, and a graph database optimized for build ordering and context. `plan verify / plan repair` checks and repairs the acceptance criteria before they measure the build.

**drydock build** builds the ready steps and repairs failed code while progress is measured. Each step completes when its acceptance criteria pass; repair stops at the limit or when progress stalls.

**drydock diagnose --apply** identifies root causes and corrects the Blueprints when build repair cannot resolve the problem. The next build uses those corrections.

Shared technology rules, business rules, and branding provide consistent behavior and style across your software. Payload size and effort are optimized by model. I use **Codex and Claude Code** both to develop Drydock and to build software through it.

# Workflow

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

# What I learned

* **A failed test does not always mean failed code.** In Marina, a test required an item moved one position to become first in the entire collection. Diagnosis corrected the assertion to test the specified movement.
* **Some build failures require better specifications.** Repeated code repair cannot resolve an incorrect Blueprint. Diagnosis identifies the root cause and applies Blueprint corrections so the build can continue.
* **Planning and building can need different models.** Two Haiku 5.5 projects required `--plan-override-model sonnet`: planning included large test kits and model output quality became poor.
* **Encapsulation limits rebuilds.** `DATABASE.md` uses named SQL operations and native libraries. Most database changes do not require downstream Blueprint rebuilds.

The UAT matrix records passes for all ten projects under **Codex Luna**, covering Python, Go, SQLite, and Postgres.

For ongoing changes, edit specifications, add change tickets, or comment on Blueprints. `drydock refit` maps changes into the Manifest for incremental builds.

**Code Repository (MIT):** [Drydock](https://github.com/webcloudstudio/Drydock)

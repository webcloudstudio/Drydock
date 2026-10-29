# Drydock — Build Software from Specifications

Drydock is an **Enterprise Grade Software Builder (MIT)** that uses Agile and Test Driven Development best practices to process your imported specifications using low-end models. Luna works wonderfully. This post describes the self-repairing workflow.

**Goal:** Correctly build software from large specifications that need not be well defined. Maintain it after build.

**Problem Statement:** LLMs effectively build small specifications, but even frontier models can fail on larger specifications. Dividing the build into discrete steps simplifies the work, but downstream tasks must rely on correct upstream tasks. Acceptance criteria verify each step against quality standards. Respect enterprise branding and build rules. Enable external services.

## The Drydock Steps

- `drydock analyze` uses Agile Decomposition to define stories, create questionnaires, and identify blockers.
- `drydock plan` creates **Blueprints** following Test Driven Development and stores the build plan in a graph database.
    - `drydock plan verify` / `drydock plan repair` checks and repairs the acceptance criteria.
- `drydock build` executes the optimized build graph, iterating each step until its acceptance criteria pass or repair stops.
    - `drydock diagnose --apply` identifies the root cause of failed runs and corrects the Blueprints.
- `drydock rigging` supports shared technology rules and branding.

## Self-Improving Loops

Acceptance-criteria pretesting and repair are needed separately from their creation to assess test quality and coverage.

Build must iterate on a step until its acceptance criteria pass or repair stops. Low-end models iterate well and cheaply with prompt stacking: append the error and resubmit. An outer loop is needed to repair and continue from known failure modes and LLM-generated, low-value stop conditions that should not stop the build. This is surprisingly common in complex pipelines running low-end models.

## The Drydock Workflow

    drydock init MyApp                            # create the workspace
    drydock import MyApp "$INPUT_DIRECTORY"       # load your specifications, notes, images
    drydock analyze MyApp                         # create stories, questions, blockers
    drydock plan MyApp                            # create Blueprints and Graph Db
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

## What I learned

- **LLM-authored acceptance criteria vary in quality.** Very early on, I found that the majority of failed tests were environmental: code that could not run due to missing libraries or connectivity. A full process was developed to pretest acceptance criteria, identify and correct criteria that fail before the build, identify existing behavior, and check coverage.
- **Applications differ.** Some of the earlier applications that shipped included test criteria that should pass.
- **Encapsulation limits rebuilds.** Changes to foundational stories, such as the web server or persistence layer, can force full downstream rebuilds. Drydock ships named SQL operations and native libraries to encapsulate persistence changes. Only changes to the persistence contract require downstream Blueprint rebuilds.
- **Some build failures require better specifications.** Repeated code repair cannot resolve an incorrect Blueprint. Diagnosis identifies the root cause and applies Blueprint corrections so the build can continue.

**Code Repository (MIT):** [Drydock](https://github.com/webcloudstudio/Drydock)

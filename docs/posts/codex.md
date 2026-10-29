# Drydock — Build Software from Specifications

Drydock is an **Enterprise Grade Software Builder (MIT)** that uses Agile and Test Driven Development best practices to process your imported specifications using low-end models. Luna works wonderfully. This post describes the two core self-repairing workflows that lead to quality builds.

**Goal:** Correctly build software from large specifications that need not be well defined. Maintain it after build.

**Problem Statement:** LLMs effectively build small specifications, but even frontier models can fail on larger specifications. Dividing the build into discrete steps simplifies the work, but the core issue is that downstream tasks rely on correct upstream tasks. With a low-end model, this cannot be guaranteed. In fact, output formatting cannot even be guaranteed. Drydock uses Test Driven Development—well-crafted acceptance criteria to define done. Drydock includes enterprise branding and build rules.

## The Drydock Steps

- `drydock analyze` uses Agile Decomposition to define stories, create questionnaires, and identify blockers.
- `drydock plan` creates **Blueprints** following Test Driven Development and stores the build plan in a graph database.
    - `drydock plan verify` / `drydock plan repair` checks and repairs the acceptance criteria.
- `drydock build` executes the optimized build graph, iterating each step until its acceptance criteria pass or repair stops.
    - `drydock diagnose --apply` identifies and repairs recoverable failures: incorrect AC, partial blocks, and environmental errors.
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

    # build repairs failed code; diagnose repairs recoverable failures
    n=1; max=3
    while drydock status MyApp --ready; do
        if [ "$n" -gt "$max" ]; then echo "hit $max build attempts - aborting"; exit 1; fi
        echo "*** BUILD ATTEMPT $n ***"
        drydock build MyApp || drydock diagnose MyApp --apply
        n=$((n+1))
    done

    drydock status MyApp --check                  # Deterministic definition of done
    drydock score release MyApp                   # LLM evaluated definition of done

## What I learned

- **LLM-authored AC vary in quality.** The majority of failed AC encountered are environmental—for example, code that cannot run due to missing libraries or connectivity. Pretesting AC for behavior and correctness enables the self-correcting loops described.
- **Applications differ.** Context management must handle large test-case suites, database-oriented applications, and other project types.
- **Encapsulation limits rebuilds.** Changes to foundational stories, such as the web server or persistence layer, can force full downstream rebuilds. Drydock ships named SQL operations and native libraries to encapsulate persistence changes. Only changes to the persistence contract require downstream Blueprint rebuilds.
- **Failures need diagnosis.** AC may be wrong and repairable on reflection, the LLM may return partial blocks, or an environmental error may stop the build. Diagnose identifies and repairs recoverable failures so the build can continue.
- **Persistent memory limits code drift.** Memory files by command and process track intent, expected behavior, and edge cases as changes accumulate. `AGENTS.md` identifies the specific memory files and rules.
- **Prompt stacking is key.** Append files in an XML envelope and put detailed build instructions at the end. Repair appends the error and repair instructions, reusing the prompt prefix for caching and lower costs. This enables iteratively improving results.

**Code Repository (MIT):** [Drydock](https://github.com/webcloudstudio/Drydock)

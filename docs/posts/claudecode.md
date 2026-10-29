# Specification Driven Delivery using TDD & Agile with Claude Code

**Drydock** is a spec to software builder using **Agile Decomposition** to turn your **specifications** and **designs** into governed buildable Stories/**Blueprints** containing executable acceptance criteria that follow **Test Driven Development (TDD)**. A graph database optimizes build ordering and context. Drydock is designed for large specifications, quick revision, and long-term maintenance.

I use **Claude Code and Codex** to build Drydock and to build software through it. This is the **SAIL Method**, building with **Haiku 5.5**.

# S — Set Up

    drydock init MyApp                            # create the workspace
    drydock import MyApp "$INPUT_DIRECTORY"       # load your specifications, notes, images

# A — Analyze and Plan

`drydock analyze` derives stories, questions, and blockers. The **Commander** is the product owner; `drydock run quarterdeck MyApp` provides the web console to review and answer before continuing.

`drydock plan` creates **Blueprints** and a **Manifest**: the build plan and dependency graph. Acceptance criteria are recorded, categorized, and corrected to measure "done" and code impact.

    drydock analyze MyApp                         # create stories, questions, blockers
    drydock plan MyApp                            # create Blueprints and Manifest
    drydock plan verify MyApp || drydock plan repair MyApp

# I — Implement

`drydock build` implements the software plan in managed chunks using the **Manifest**. **Rigging** applies company standards and branding. It iterates and self-repairs until all acceptance criteria succeed, no progress is detected, or it fails. `drydock diagnose --apply` identifies root causes and applies Blueprint corrections.

    # self-repairing build loop
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

# L — Loop

Edit specifications, add change tickets, or provide comments on the Blueprints. `drydock refit` maps changes into the **Manifest** for incremental builds. Rerun **Implement**.

    drydock refit MyApp                           # map changes into the Manifest

`drydock document` creates documentation from the Blueprints.

# What I learned

The test suite covers **10 projects under Haiku and Luna**, using Python, Go, SQLite, and Postgres. Two Haiku 5.5 projects required `--plan-override-model sonnet`: planning included large test kits and model output quality became poor. Haiku built the software; those projects needed Sonnet for planning.

**Code Repository (MIT):** [Drydock](https://github.com/webcloudstudio/Drydock)

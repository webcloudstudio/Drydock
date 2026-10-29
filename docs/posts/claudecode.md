# My Claude Code workflow: pretest acceptance criteria, then build and repair with Haiku

I use **Claude Code and Codex** both to build **Drydock** and to build software through it. For Haiku builds, the workflow is **specifications → Stories/Blueprints → pretested acceptance criteria → build → diagnose → verify**.

**Agile Decomposition** produces small buildable stories with executable acceptance criteria. A graph database orders the work and controls context. Related stories form build blocks with shared business rules, technology guidance, and branding.

# Workflow

**1. Resolve the specification first.** Import specifications, notes, or designs. Analysis produces stories, questions, and blockers. Clear the blockers before planning the build.

    drydock init MyApp
    drydock import MyApp "$INPUT_DIRECTORY"
    drydock analyze MyApp

**2. Test the tests.** Acceptance criteria are the builder's scoring function. Their quality affects both what gets built and whether it is measured as done.

Acceptance tests are iterated by pretesting, which reveals their accuracy, quality, and whether they test existing behavior. Tests which are not well formed — for example, those that require imports from another step — are judged and repaired.

    drydock plan MyApp
    drydock plan verify MyApp || drydock plan repair MyApp

**3. Build with bounded repair.** Each block completes only when its deterministic acceptance criteria pass. Failed blocks get repair passes; repair stops at the configured limit or after two consecutive passes without progress.

If the build fails, diagnosis can correct the Blueprints and invalidate their build graph. The next build works from those corrections.

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

The shell loop permits at most three build invocations. Reaching no ready work is followed by a completion check.

**4. Check the build and the project.** Build completion and project-level assessment are separate checks. `score release` runs the acceptance gate before an LLM judges `SEA_TRIALS.md`.

    drydock status MyApp --check
    drydock score release MyApp

# What I learned from the builds

**Planning and building need different model choices.** My test matrix records successful builds for **10 projects under Haiku and Luna**. Two Haiku 5.5 projects required `--plan-override-model sonnet`: planning included large test kits and model output quality became poor. Using Haiku for the build did not mean using it for every planning task.

**Test quality needs its own iteration.** Pretesting checks whether a criterion is usable before implementation is judged against it. The repair loop must handle malformed tests as well as failed builds.

**Repair needs a stop condition.** There is a limit per failed block and a separate limit on build invocations in the shell loop. Diagnosis stops on serious errors or misspecification.

# Scope

The ten projects are CommonMark, CsvStat, DrydockStats, DupFind, FxRates, LayersTesting, Quakes, ReadingList, Toml, and jq. The kits cover **Python, Go, SQLite, and Postgres**. Gemini was tested on two builds.

`drydock run quarterdeck` shows blockers, progress, and decisions locally. Haiku payload size and effort are optimized by model, respecting its 100K-token pricing threshold.

The commands are from [Drydock](https://github.com/webcloudstudio/Drydock), my MIT-licensed project.

# Building from specifications with Codex Luna: decompose, pretest, build, diagnose

My workflow uses **Agile Decomposition** and **Test Driven Development** to build software from specifications with **Codex Luna**. Specifications become buildable Stories/**Blueprints** with executable acceptance criteria. A graph database determines build order and context.

I develop [Drydock](https://github.com/webcloudstudio/Drydock), the MIT-licensed tool used for these commands, using Claude Code and Codex.

**The unit of work is a build block.** Related Blueprints are grouped with the applicable business rules, technology guidance, and branding. Each block receives the context needed for that work. Its acceptance criteria must pass before it completes.

# Workflow

**1. Import and decompose.** Start with specifications, notes, or designs. Analysis produces stories, questions, and blockers. Resolve blockers before continuing.

    drydock init MyApp
    drydock import MyApp "$INPUT_DIRECTORY"
    drydock analyze MyApp

**2. Plan and pretest.** Planning produces the Blueprints and Manifest. Verify the acceptance criteria before using them as the builder's scoring function.

    drydock plan MyApp
    drydock plan verify MyApp || drydock plan repair MyApp

Acceptance tests are iterated by pretesting, which reveals their accuracy, quality, and whether they test existing behavior. Tests which are not well formed — for example, those that require imports from another step — are judged and repaired.

**3. Build and repair.** `drydock build` runs ready blocks in dependency order and repairs failed blocks. Repair stops at the configured limit or after two consecutive passes without progress. If the build fails, `drydock diagnose --apply` identifies the root cause, applies Blueprint corrections, and invalidates the affected build graph.

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

This outer loop permits at most three build invocations. It ends when no ready work remains or the limit is reached. The final check determines whether the build is complete.

**4. Check completion and project intent.** `status --check` checks build completion. `score release` runs the acceptance gate, then uses an LLM to judge the project-level criteria in `SEA_TRIALS.md`.

    drydock status MyApp --check
    drydock score release MyApp

# What controls the build

* **Context:** dependency-ordered blocks, with payload size and effort optimized by model.
* **Database changes:** `DATABASE.md` defines named SQL operations using native libraries. Most database changes do not require downstream Blueprint rebuilds.
* **Review:** `drydock run quarterdeck` exposes blockers, progress, and decisions in a locally hosted web console.
* **Traceability:** `BUILD_LINEAGE.jsonl` traces specifications to code.

# Results and limits

My test matrix records successful builds for **10 projects under Luna and Haiku**, covering Python, Go, SQLite, and Postgres: CommonMark, CsvStat, DrydockStats, DupFind, FxRates, LayersTesting, Quakes, ReadingList, Toml, and jq.

Two Haiku 5.5 projects needed Sonnet for planning because large test kits degraded planning output. Gemini was tested on two builds.

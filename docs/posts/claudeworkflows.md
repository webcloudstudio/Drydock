# A specification-to-software workflow: decompose, pretest, build, diagnose, verify

**The workflow:** turn specifications into small buildable stories, pretest their acceptance criteria, build in dependency order, and diagnose failed builds. Bound the retries and check completion at the end.

I use this with **Claude Code/Haiku 5.5** and **Codex/Luna**. I develop Drydock, the tool used in the examples, using both Claude Code and Codex.

# 1. Import the specifications

Start with specifications, notes, or designs in an input directory. Create a Target workspace and import the material.

    drydock init MyApp
    drydock import MyApp "$INPUT_DIRECTORY"

# 2. Decompose and resolve blockers

**Agile Decomposition** turns the material into stories, questions, and blockers. Resolve blockers before continuing. QuarterDeck provides a local web console for reviewing them.

    drydock analyze MyApp

# 3. Plan the work and pretest its acceptance criteria

Planning creates **Blueprints** and a **Manifest**. Blueprints contain executable acceptance criteria; the Manifest tracks dependencies, build order, and runnable work. Related Blueprints are grouped into blocks with the applicable business rules, technology guidance, and branding to control build context.

    drydock plan MyApp
    drydock plan verify MyApp || drydock plan repair MyApp

**The acceptance criteria are the builder's scoring function.** Acceptance tests are iterated by pretesting, which reveals their accuracy, quality, and whether they test existing behavior. Tests which are not well formed — for example, those that require imports from another step — are judged and repaired.

# 4. Build, diagnose, and retry within a limit

`drydock build` executes ready blocks in order. A block completes only when all its deterministic acceptance criteria pass. Failed blocks get repair passes, stopping at the configured limit or after two consecutive passes without progress.

If the build fails, `drydock diagnose --apply` identifies root causes and applies Blueprint corrections. Those corrections invalidate the build graph so the next build uses the updated plan. Serious errors or misspecification stop diagnosis.

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

This limits the outer loop to **three build invocations**, separate from repair passes within each build. It also ends when no ready work remains. That condition alone does not establish completion.

# 5. Verify completion and project intent

    drydock status MyApp --check
    drydock score release MyApp

`status --check` checks build completion. `score release` runs the acceptance gate, then uses an LLM to judge the project-level criteria in `SEA_TRIALS.md`.

**Review during the workflow:** `drydock run quarterdeck` exposes blockers, progress, and decisions in a locally hosted web console.

# Tested scope and limitations

My test matrix records successful builds for **10 projects under Haiku and Luna**: CommonMark, CsvStat, DrydockStats, DupFind, FxRates, LayersTesting, Quakes, ReadingList, Toml, and jq. The kits cover Python, Go, SQLite, and Postgres.

Two Haiku 5.5 projects needed `--plan-override-model sonnet` because large test kits degraded planning output. Gemini was tested on two builds. These results describe the tested projects; model choice for planning remains a separate decision from model choice for building.

**Implementation/source:** [Drydock (MIT)](https://github.com/webcloudstudio/Drydock).

<!-- Posting: standalone Showcase post, or omit the title and use the pinned weekly showcase. Copy the body below; the first heading is the title. -->

# Drydock 0.8 — Specifications to software with Codex Luna

I develop **Drydock** using **Codex and Claude Code**. Drydock builds software using **Codex Luna**, Haiku 5.5, or Gemini.

**Drydock** is a spec to software builder using **Agile Decomposition** to turn your **specifications** and **designs** into governed buildable Stories/**Blueprints** containing executable acceptance criteria that follow **Test Driven Development**. A graph database optimizes build ordering and context. Drydock is designed for large specifications.

* **Agile** and **Test Driven Development** best practices.
* Token cost engineering optimizes payload size and effort by model.
* `drydock run quarterdeck` provides a locally hosted Web User Experience.

**New Feature: Measured, self-correcting acceptance criteria.** Acceptance tests are iterated by pretesting, which reveals their accuracy, quality, and whether they test existing behavior. Tests which are not well formed — for example, those that require imports from another step — are judged and repaired.

**New Feature: Self-Improving Builds.** `drydock build` iterates until all acceptance criteria succeed, no progress is detected, or it fails. `drydock diagnose --apply` identifies root causes and applies corrections.

**New Feature: Encapsulated Persistence Layer.** `DATABASE.md` uses pre-built native libraries for named SQL operations to minimize change impact. Most database changes do not require downstream Blueprint rebuilds.

# Workflow

    drydock init MyApp                            # create the workspace
    drydock import MyApp "$INPUT_DIRECTORY"       # load your specifications, notes, images
    drydock analyze MyApp                         # create stories, questions, blockers
    drydock plan MyApp                            # create Blueprints and Manifest
    drydock plan verify MyApp || drydock plan repair MyApp  # repair/validate acceptance criteria

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

# UAT Testing

The release test suite reports successful builds for **10 projects under Codex Luna and Claude Haiku**. The test kits cover Python, Go, SQLite, and Postgres. Two Haiku projects required `--plan-override-model sonnet` for planning. Gemini was tested on two builds.

    #                       Haiku   Luna
    # CommonMark            Y       Y
    # CsvStat               Y       Y
    # DrydockStats          Y       Y
    # DupFind               Y       Y
    # FxRates               Y       Y
    # LayersTesting         Y       Y
    # Quakes                Y       Y
    # ReadingList           Y       Y
    # Toml                  Y       Y
    # jq                    Y       Y

# Try Drydock

    uv tool install drydock-sdd

* **Code Repository (MIT):** https://github.com/webcloudstudio/Drydock
* **Documentation:** https://webcloudstudio.com

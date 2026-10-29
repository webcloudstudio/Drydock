**Drydock** is a spec to software builder using **Agile Decomposition** to turn your **specifications** and **designs** into governed buildable Stories/**Blueprints** containing executable acceptance criteria that follow **Test Driven Design**. A graph database optimizes build ordering and context. Drydock measures and self repairs the acceptance criteria which are the builders scoring function.  Drydock build iterates and self repairs until done.  Drydock is designed large specifications.

* Builds using low-end models (Haiku 5.5, Luna, Gemini).
* **Agile** and **Test Driven Development** Best Practices.
* `drydock run quarterdeck` provides a full locally-hosted Web User Experience

The main improvement from .3 relates to retry logic and improving the self scoring. These changes are needed as we build different types of projects.  The agents are authorized on normal developer judgement and expose blockers, progress, and decisions cleanly in the QuarterDeck web server.  

**New Feature: Measured, self-correcting acceptance criteria.**  AC are recorded, categorized, and corrected before each build step so we can correct measure "done" and code impact.  

**New Feature: Self-Improving Builds:** *drydock build* iterates until all Acceptance Criteria succeed, no progress is detected, or it fails -- picked up by *drydock diagnose* to identify root cause and proposes/implements corrections*.* 

**New Feature: Encapsulated Persistence Layer:** `DATABASE.md` uses pre-built native libraries for "named" SQL operations to minimizes change impact radius.  Most database changes do NOT require downstream blueprint rebuilds. 

**New Feature: Updated Drydock Workflow** is shown below with the above features integrated.  `drydock_runner.sh`provides this at the cli.

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

# Uat Testing 

The Drydock Release Test Suite tests is now 10 projects under both Haiku and Luna.  2 projects on haiku 5.5 required *--plan-override-model sonnet* as planning includes the test kit which is large and the model output quality became poor. Gemini was tested for two builds. 

    $ drydock report uat_summary
    Drydock 0.8.0  Copyright (c) 2026 Web Cloud Studio. All rights reserved.
    # UAT Summary Report
    #                       Claude  Codex
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
    
    These test kits test SQLite and Postgres, python and go.

# Version .8 Release Notes:

* Haiku 5.5 Builds - Haiku 100K-token pricing spike/limit respected.  
* Token cost engineering optimizes payload size and effort by model - see `model_config.jsonl`.
* Layered topology - blueprint types: Foundation, persistence, web server, CLI, branding, services, API, screens.
* `BUILD_LINEAGE.jsonl` traces specifications to code.
* `drydock report` provides a core reporting suite
* `drydock uat` publishes output to the web
* A lot of other stuff - its been a few months.... big quality release.  

# Try Drydock

    uv tool install drydock-sdd

* **Code Repository** (MIT)**:** [https://github.com/webcloudstudio/Drydock](https://github.com/webcloudstudio/Drydock)
* **Documentation:** [https://webcloudstudio.com](https://webcloudstudio.com)

Please give a like/star to the repository if Drydock is useful to you!

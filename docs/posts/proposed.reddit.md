# Drydock 0.8 Release

**An Agile and Test Driven Software Builder**

**DRYDOCK BUILDS WORKING SOFTWARE FROM SPECIFICATIONS**

Ed Barlow · [Web Cloud Studio](https://www.webcloudstudio.com) · October 23, 2026

---

### **What is Drydock**

Drydock uses **Agile Decomposition** to turn your specifications and designs into stories called **Blueprints** containing executable acceptance criteria that follow **Test Driven Design**. A graph database optimizes build ordering and context. Drydock measures and self repairs the acceptance criteria which are the builders scoring function.  Drydock build iterates and self repairs until done.

- Builds (Go or Python) Software from Your Notes/Specifications/Ideas using low-end models (Haiku 5.5, Luna, Gemini).
- Based on **Agile Planning** and **Test Driven Development** Best Practices.
- Uses **LLM subscription** low level models like Haiku and Luna
- `drydock run quarterdeck` provides a full locally-hosted Web User Experience

---

### **New Feature: Measured, self-correcting acceptance criteria**

- `drydock plan repair` pre-records, categorizes, and corrects acceptance criteria.

### **New Feature: Self-Improving Builds**

- `drydock diagnose` reads failed runs, identifies the root cause, and proposes corrections.
- `drydock build` iterates until all Acceptance Criteria succeed or no progress is detected.

### **New Feature: Encapsulated Persistence Layer**

- `DATABASE.md` uses pre-built native libraries plus "named" SQL operations. Minimizes change impact radius.

### **New Feature: Updated Drydock workflow**

- `drydock_runner.sh` provides our minimal self-repairing workflow to **build anything**.

```bash
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
```

---

### **Release Notes:**

- Haiku 5.5 Builds!
  - Drydock respects Haiku 100K-token pricing.
  - We recommend `--plan-override-model sonnet`.
- Gemini Support
- The UAT Test Suite tests 10 projects under Haiku and Luna

```bash
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
```

- Database encapsulation for SQLite and Postgres, Postgres instructions are provided as are python and go libraries to conform system database calls.
- Go and Python support (rules setup for other languages is easy)
- Token cost engineering optimizes payload size and effort by model - see `model_config.jsonl`.
- Layered topology - blueprint types: Foundation, persistence, web server, CLI, branding, services, API, screens.
- `BUILD_LINEAGE.jsonl` traces specifications to code.
- `drydock report` provides a core reporting suite

---

### **Drydock Plan**

- **Version 0.8** released.
- **Version 0.9** overhauls the **refit process** into a best of breed workflow to manage change with SDD.
- **Version 1.0 GA** tailors the **QuarterDeck Web Server** with a **no-Cli Workflow** - A Full web User Experience.

---

### **Try Drydock**

```bash
uv tool install drydock-sdd
```

- **Code Repository:** https://github.com/webcloudstudio/Drydock
- **Documentation:** https://webcloudstudio.com

**please give a like/star to the repository if Drydock is useful to you!**

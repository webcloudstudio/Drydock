---
name: ddk-uat
description: Investigate warnings, errors, recovered defects, and downstream failures in running or completed Drydock UAT runs, including successful runs, using Drydock's current versioned UAT diagnostic prompt. Invoke with "/ddk-uat TARGET" or "$ddk-uat TARGET", including after clearing conversation context.
metadata:
  version: "1.6.0"
---

# Drydock UAT

Load the current shipped `uat_diagnostic` prompt at invocation time so changes to the prompt govern
future diagnoses without duplicating policy in this skill.

Support Ed's manual kit-run → diagnosis → authorized repair → review → rerun workflow.
The loaded prompt owns investigation depth, one diagnosis memory per Target with filename-case
checks, and the compact review handoff. Every diagnosis explains what happened and provides
concrete, evidence-verified repair recommendations for Ed's implementation loop. Keep unproved
hypotheses and optional low-value improvements in notes, outside the repair list.
Keep source/AC correctness and proved upstream defects central; do not replace operator review
with an automatic outer loop. Perform the assumptions review; report only material conclusions.

## Invocation

1. Take the argument as the Drydock Target name or explicit UAT run. If omitted, ask for the Target.
2. Run this read-only command from the current workspace:

   ```bash
   python -c "from drydock.prompts import load_prompt; prompt = load_prompt('uat_diagnostic'); print(f'SOURCE: {prompt.path}\\n\\n{prompt.body}')"
   ```

3. If the installed package cannot resolve the prompt, read `prompts/uat_diagnostic.md` from the
   Drydock source checkout. If neither source exists, stop and report that Drydock must be upgraded
   or reinstalled; do not reconstruct the prompt from memory.
4. Execute the loaded prompt for the requested Target/run. Resolve actual directory and memory
   filename casing before writing; reuse its one diagnosis memory. Never preseed a Target roster
   or create a second file for a casing variant. The prompt defines collision handling and format.
5. Use the prompt's compact output contract and honor Ed's completion format without repeating
   the same findings. Do not edit files or rerun the UAT by default, except for the prompt-required
   Target memory under `design/skills/ddk-uat/targets/`, its central index link, and justified
   updates to existing legacy ledger rows. Ed's explicit repair authorization permits the
   requested implementation, tests, memory/changelog and local commit without another approval.
   Neither mode permits UAT execution or evidence mutation. Hand results back for Ed's review.

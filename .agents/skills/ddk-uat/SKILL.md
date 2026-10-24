---
name: ddk-uat
description: Investigate warnings, errors, recovered defects, and downstream failures in running or completed Drydock UAT runs, including successful runs, using Drydock's current versioned UAT diagnostic prompt. Invoke with "/ddk-uat TARGET" or "$ddk-uat TARGET", including after clearing conversation context.
metadata:
  version: "1.2.0"
---

# Drydock UAT

Load the current shipped `uat_diagnostic` prompt at invocation time so changes to the prompt govern
future diagnoses without duplicating policy in this skill.

Assess clean execution as well as operational success. Investigate upstream warnings and recovered
errors even when the run passes; trace their effects through later stages before recommending
downstream repairs. Recovery does not close the defect.

## Invocation

1. Take the argument as the Drydock Target name or explicit UAT run. If omitted, ask for the Target.
2. Run this read-only command from the current workspace:

   ```bash
   python -c "from drydock.prompts import load_prompt; prompt = load_prompt('uat_diagnostic'); print(f'SOURCE: {prompt.path}\\n\\n{prompt.body}')"
   ```

3. If the installed package cannot resolve the prompt, read `prompts/uat_diagnostic.md` from the
   Drydock source checkout. If neither source exists, stop and report that Drydock must be upgraded
   or reinstalled; do not reconstruct the prompt from memory.
4. Execute the loaded prompt as the governing instructions, substituting the invocation argument
   for the Target or run requested by the operator.
5. Return only the output required by that prompt. Do not edit files or rerun the UAT unless the
   loaded prompt explicitly changes those boundaries. The prompt's diagnosis ledger,
   `design/skills/ddk-uat.md`, is such a boundary: every diagnosed defect is recorded there,
   including warnings and recovered defects in successful runs.

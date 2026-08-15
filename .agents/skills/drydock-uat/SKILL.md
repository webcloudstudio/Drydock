---
name: drydock-uat
description: Diagnose a failed, degraded, or contradictory Drydock UAT run by loading and executing Drydock's current versioned UAT diagnostic prompt. Invoke with "/drydock-uat TARGET" or "$drydock-uat TARGET" after a UAT run, including after clearing conversation context.
metadata:
  version: "1.0.0"
---

# Drydock UAT

Load the current shipped `uat_diagnostic` prompt at invocation time so changes to the prompt govern
future diagnoses without duplicating policy in this skill.

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
   loaded prompt explicitly changes those boundaries.

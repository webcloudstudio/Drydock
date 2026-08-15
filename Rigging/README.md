# RulesEngine

**Version:** 20260407 V1
**Description:** Governance standards and distribution files for all projects.

---

## Contents

| File | Purpose |
|------|---------|
| `BUSINESS_RULES.md` | Master source for agent behavior rules — edit here, regenerate CLAUDE_RULES.md |
| `CLAUDE_RULES.md` | Generated agent behavior contract — injected into every project's AGENTS.md |
| `BRANDING.md` | Color variables, typography, and layout standards for documentation |
| `acceptance_failure_taxonomy.json` | Runtime acceptance exception categories; traceback attribution remains in code |

## Subdirectories

| Directory | Purpose |
|-----------|---------|
| `stack/` | Prescriptive technology patterns (flask.md, sqlite.md, ...) — included in build prompts |
| `spec_template/` | Template files for scaffolding new specification directories via `setup.sh` |
| `templates/` | Code project templates (common.sh, common.py, test.sh, index.html) — distributed to projects |

## Prompt Files

Prompt content consumed by bin/ scripts lives in `prompts/`, not here. See `prompts/` for:
- `oneshot_build_rules.md` — specification expansion rules (used by oneshot.sh, convert.sh, decompose.sh)
- `oneshot_prototype_rules.md` — prototype iteration rules (used by oneshot.sh)
- `oneshot_documentation.md` — documentation build standard (used by oneshot.sh)
- `document.md`, `spec_iterate.md`, `update_reference_gaps.md` — AI prompt templates

## Service Endpoint Convention

Each bin/ script declares its dependencies in its CommandCenter header:

```bash
# Prompt: prompts/oneshot_build_rules.md, prompts/oneshot_prototype_rules.md
# Rules: RulesEngine/CLAUDE_RULES.md, RulesEngine/stack/*.md
```

- `Prompt:` — prompt files embedded in AI output
- `Rules:` — governance/reference files read from RulesEngine/

`bin/test.sh` auto-validates that every declared dependency exists.

## After Any Change

Run `bash bin/update_projects.sh` from the Specifications root to propagate to all projects.

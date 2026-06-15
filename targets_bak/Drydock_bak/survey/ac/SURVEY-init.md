# SURVEY-SPEC: drydock init (+ config)

| Field       | Value |
|-------------|-------|
| Version     | 20260613 V1 |
| Description | Acceptance authority for `drydock init` and `drydock config` — Target scaffolding and setup. |
| Command     | drydock init / drydock config |
| Scored In   | Survey/scores.jsonl |
| Source      | src/drydock/init_target.py, src/drydock/config.py |

## Goal

A user can go from nothing to a correctly-shaped, immediately-usable Target in one command, and can
configure the workspace, provider, and ports without editing files by hand. The scaffold is
**honest** — it contains clearly-labelled examples, never fabricated completion state.

## Acceptance Criteria — Code

| ID | Criterion | Dim | Check | Weight | Verify |
|----|-----------|-----|-------|--------|--------|
| INIT-C1 | `drydock init <Target>` creates `METADATA.md`, root Sea Trials + Soundings, `blueprint/sources/`, state-only QuarterDeck | D1 | A | 3 | assert each path exists |
| INIT-C2 | Re-running init does not overwrite or clobber existing files | D1 | A | 2 | write a sentinel, re-init, assert unchanged |
| INIT-C3 | `config set drydock_workspace/llm_provider/quarterdeck_port` persist and validate | D1 | A | 2 | `test_config.py` round-trip |
| INIT-C4 | `config show` reports effective values and their source | D1 | A | 1 | output contains value + source |
| INIT-E1 | Usage errors exit 2; operational failures exit 1; success exit 0 | D5 | A | 1 | CLI exit-code test |

## Acceptance Criteria — Specification

| ID | Criterion | Dim | Check | Weight | Verify |
|----|-----------|-----|-------|--------|--------|
| INIT-D1 | Scaffolded `METADATA.md` carries required identity fields (name, display_name, status, stack, code_root) | D2 | A | 2 | parse METADATA fields |
| INIT-D2 | Example blueprint files are named as examples and not mistakable for real specs | D2 | J | 1 | inspect `blueprint/` names |
| INIT-D3 | Scaffold conforms to BLUEPRINTS_CONTRACT data locations | D5 | A | 1 | path layout assert |

## Guardrails

- Init must never overwrite a user's existing Target files.
- Init must not seed fake evidence, fake Soundings rows, or a second build plan.
- Config writes go only to the user-scoped configuration, never into a Target.

## Open Questions

- Should `init` refuse to run inside the Drydock repo root to prevent self-scaffolding accidents?

**Resolved 2026-06-13:** `blueprint/ACCEPTANCE_CRITERIA.md` is an artifact and was removed.
Application acceptance lives in `targets/<TGT>/SEA_TRIALS.md` and `SOUNDINGS.md`, not in the
Blueprint. **Build-window follow-up (INIT contract-drift):** source still references the file in
`src/drydock/plan_compass.py:13` and `src/drydock/validate_specification.py:60,88` — remove those
references and ensure the scaffold no longer creates it.

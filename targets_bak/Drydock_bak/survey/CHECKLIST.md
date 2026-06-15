# Foundational Phase Checklist

**Version:** 20260613 V1
**Goal of the phase:** A user can stand up a Target, import source, conform/assess it, decompose it
into an approved `MANIFEST.md`, and orient at any moment with `drydock status` — each step
backed by tests and producing reproducible evidence.

Check type: `A` = assertion (no LLM, run by survey) · `J` = judgment (LLM reads prose/evidence).
Status: ☐ not started · ◐ in progress / partial · ☑ verified by survey.

---

## Cross-cutting deliverables (every command)

| # | Deliverable | Check | Verify | Status |
|---|-------------|-------|--------|--------|
| X1 | Command parses, dispatches, returns documented exit code (0/1/2) | A | CLI test asserts exit codes | ☐ |
| X2 | `--help` shows the command in the public surface | A | `drydock <cmd> --help` | ☐ |
| X3 | Unit tests for deterministic logic and error cases | A | `pytest tests/test_<cmd>*.py` | ☐ |
| X4 | Integration test over a real temp Target | A | pytest temp-dir fixture | ☐ |
| X5 | Soundings row updated to truthful state with evidence | A | grep row in `SOUNDINGS.md` | ☐ |
| X6 | `ruff check src/ tests/` clean | A | ruff | ☐ |
| X7 | Reproducible evidence written to `logs/` or `evidence/` | A | file exists + parses | ☐ |
| X8 | No unresolved Open Question silently implemented | J | read evidence/log for hedging | ☐ |

---

## init (+ config)  — Soundings: DONE (CLI-009)

| # | Deliverable | Check | Verify | Status |
|---|-------------|-------|--------|--------|
| I1 | `drydock init <Target>` scaffolds `METADATA.md`, root Sea Trials/Soundings, `blueprint/sources/`, state-only QuarterDeck | A | dir + file existence asserts | ◐ |
| I2 | Re-running init does not overwrite existing files | A | mtime/content unchanged | ☐ |
| I3 | `drydock config set/show` round-trips workspace, provider, ports | A | `test_config.py` | ◐ |
| I4 | Scaffold blueprint examples are clearly example-named (no fake completion) | J | inspect blueprint/ names | ◐ |

## import  — Soundings: DONE (CLI-025)

| # | Deliverable | Check | Verify | Status |
|---|-------------|-------|--------|--------|
| M1 | Markdown bundle preserved under `<Target>/blueprint/sources/` | A | files copied verbatim | ◐ |
| M2 | `--format source` assembles prompt and writes Blueprint files | A | `test_import_source.py` | ◐ |
| M3 | `--format speckit` translates to Blueprint + conversion report | A | `test_import_speckit.py` | ◐ |
| M4 | `--format auto` detects layout | A | detection test | ◐ |
| M5 | Imported material is faithful — no silent content loss | J | diff source vs preserved | ☐ |

## analyze  — Soundings: STUBBED (CLI-024)  ← active build target

| # | Deliverable | Check | Verify | Status |
|---|-------------|-------|--------|--------|
| A1 | Builds the header dependency graph in topological order | A | parse `ANALYSIS.md` graph table | ☐ |
| A2 | Detects project type from signals | J | type vs blueprint shape | ☐ |
| A3 | Completeness check flags missing required files/sections | A | inject a gap, assert it is reported | ☐ |
| A4 | Stack gate emits `stack_declaration` when stack absent | A | clear stack, assert questionnaire item | ☐ |
| A5 | Open Questions become spike candidates | A | count bullets vs candidates | ☐ |
| A6 | Emits valid `ANALYSIS.md` + `planning.json` to QuarterDeck/planning | A | files exist + JSON parses | ☐ |
| A7 | Readiness verdict correct vs COMPASS presence | A | remove COMPASS, assert `blocked` | ☐ |

## plan create  — Soundings: IMPLEMENTED (CLI-019)  ← active build target

| # | Deliverable | Check | Verify | Status |
|---|-------------|-------|--------|--------|
| P1 | Hard gate: aborts without COMPASS.md / METADATA.md | A | remove file, assert exit 1 | ◐ |
| P2 | Writes `BUILD_PLAN_COMPASS.md` (planning inventory) | A | file exists + lists inputs | ◐ |
| P3 | Writes `MANIFEST.md` with `state: draft` | A | parse plan header | ☐ |
| P4 | Every FEATURE-*.md yields >=1 story; every story has >=1 child AC | A | parse blocks | ☐ |
| P5 | Every story has a `size:` field (XS–XL) | A | parse blocks | ☐ |
| P6 | All `depends:`/`parent:` ids resolve; ids unique; all `pending` | A | graph validation | ☐ |
| P7 | DATABASE.md → Phase 1 foundation story | A | block ordering | ☐ |
| P8 | Soundings updated with plan acceptance gates | A | grep rows | ◐ |
| P9 | Decomposition is sound (granularity/order/priority) | J | Scrum Master review | ☐ |

## status  — Soundings: DONE (CLI-026/027/028)  ← active build target (new format)

| # | Deliverable | Check | Verify | Status |
|---|-------------|-------|--------|--------|
| S1 | Output gives the **status** (phase + detail) | A | output contains phase line | ☑ |
| S2 | Output gives the **next step** | A | output contains next-op line | ☑ |
| S3 | Output gives **history of last 10 commands by target** | A | seed 11 records, assert 10 shown, filtered by target | ☒ |
| S4 | Three invocation forms work (no args / `<Blueprint>` / `<Blueprint> <Target>`) | A | `test_status.py` | ◐ |
| S5 | Reads `MANIFEST.md` (not `BUILD_PLAN.md`) | A | grep source for artifact name | ☒ |

Legend addition: ☒ = surveyed and **failing** (see `scores.jsonl`).

---

## Phase-done gate

The phase is DONE when, in `scores.jsonl`, every in-scope command's latest record is band
`SEAWORTHY` (>= 90) with no `guardrail-breach` or `regression` flag, **and** the Scrum Master
review of `MANIFEST.md` ranks an executable next increment with no `decomposition-defect` flag.

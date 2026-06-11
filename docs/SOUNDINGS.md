# SOUNDINGS.md — Drydock Acceptance And Readiness

This is Drydock's authoritative implementation acceptance/readiness checklist. It records whether
each public capability exists, whether its approved behavior has passed acceptance verification,
and the evidence proving that state.

Update the matching row whenever a task changes implementation or verification state. A capability
is complete only when its row is `DONE` with concrete evidence.

## State Contract

| State | Meaning |
|---|---|
| `NOT STARTED` | No public command or implementation contract exists |
| `STUBBED` | Command surface exists and returns the tested deferred response |
| `IMPLEMENTED` | Real behavior exists, but required acceptance verification is incomplete |
| `DONE` | Approved behavior is implemented and all required verification/evidence passes |

## Command Acceptance

| Order | Command | Acceptance Criteria | State | Evidence / Notes |
|---:|---|---|---|---|
| 1 | `drydock --help` | Shows the complete public command surface | DONE | `test_cli.py::TestHelpAndVersion` |
| 2 | `drydock --version` | Shows version and copyright | DONE | `test_cli.py::TestHelpAndVersion` |
| 3 | `drydock config show` | Displays effective configuration values and sources | DONE | `test_cli.py::TestConfigShow`, `test_config.py::TestConfigShow` |
| 4 | `drydock config set blueprint_directory <path>` | Persists the Blueprint root path | DONE | `test_cli.py::TestConfigSet`, `test_config.py::TestConfigSet` |
| 5 | `drydock config set target_directory <path>` | Persists the target root path | DONE | `test_cli.py::TestConfigSet`, `test_config.py::TestConfigSet` |
| 6 | `drydock config set llm_provider <claude\|codex>` | Persists and validates the subscription CLI provider | DONE | `test_cli.py::TestConfigSet`, `test_config.py::TestConfigSet` |
| 7 | `drydock config set prompt_warn_kb <kb>` | Persists and validates the prompt-size warning threshold | DONE | `test_cli.py::TestConfigSet`, `test_config.py::TestConfigSet` |
| 8 | `drydock init <Blueprint>` | Creates a Blueprint from Typed Specification templates | DONE | `test_cli.py::TestInit`, `test_init_specification.py` |
| 9 | `drydock init <Blueprint> --update` | Adds only missing template files | DONE | `test_cli.py::TestInit::test_init_update_is_non_destructive` |
| 10 | `drydock init <Blueprint> --force` | Overwrites all template-managed files | DONE | `test_cli.py::TestInit::test_init_force_overwrites` |
| 11 | `drydock validate <Blueprint>` | Validates Blueprint completeness and conventions | DONE | `test_cli.py::TestValidate`, `test_validate_specification.py` |
| 12 | `drydock validate <Blueprint> --verbose` | Shows passing checks as well as findings | DONE | `test_cli.py::TestValidate::test_validate_verbose_shows_passes` |
| 13 | `drydock log append <Target>` | Appends one validated material decision or milestone to canonical JSONL | DONE | `test_cli.py::TestShipsLog`, `test_ships_log.py`; installed-wheel smoke test |
| 14 | `drydock log audit <Target>` | Validates canonical JSONL records, IDs, and supersedes references | DONE | `test_cli.py::TestShipsLog`, `test_ships_log.py`; Drydock log audit passes |
| 15 | `drydock rigging compact <Blueprint> [--all] [--force]` | Refreshes stale compact derivatives with deterministic writes and execution evidence | DONE | `test_cli.py::TestRiggingCompact`, `test_rigging_compact.py` |
| 16 | `drydock document generate <Blueprint> <Target>` | Creates `DOC-*.md` summaries | STUBBED | `test_cli.py::TestStubs` — exits 2, no files written |
| 17 | `drydock document assemble <Blueprint> <Target>` | Renders `DOC-*.md` into `docs/index.html` | STUBBED | `test_cli.py::TestStubs` — exits 2, no files written |
| 18 | `drydock document <Blueprint> <Target>` | Runs the full documentation pipeline | STUBBED | `test_cli.py::TestStubs` — exits 2, no files written |
| 19 | `drydock rigging update <Target>` | Propagates current Rigging to a target project | STUBBED | `test_cli.py::TestStubs` — exits 2, no files written |
| 20 | `drydock rigging verify <Target>` | Verifies target-project Rigging compliance | STUBBED | `test_cli.py::TestStubs` — exits 2, no files written |
| 21 | `drydock plan init <Blueprint>` | Creates or updates `BUILD_PLAN_INTENT.md` | STUBBED | `test_cli.py::TestStubs` — exits 2, no files written |
| 22 | `drydock plan create <Blueprint>` | Produces and merges `BUILD_PLAN.md` | STUBBED | `test_cli.py::TestStubs` — exits 2, no files written |
| 23 | `drydock plan show <Blueprint>` | Shows the current build plan | STUBBED | `test_cli.py::TestStubs` — exits 2, no files written |
| 24 | `drydock build status <Blueprint> <Target>` | Reports plan state and runnable frontier | STUBBED | `test_cli.py::TestStubs` — exits 2, no files written |
| 25 | `drydock build <Blueprint> <Target>` | Builds the next runnable frontier and records evidence | STUBBED | `test_cli.py::TestStubs` — exits 2, no files written |
| 26 | `drydock build score <Blueprint> <Target>` | Generates `SCORECARD.md` | STUBBED | `test_cli.py::TestStubs` — exits 2, no files written |
| 27 | `drydock iterate <Blueprint> <Target> [BOTH\|BLUEPRINT\|TGT] <Scope> <Change>` | Updates Blueprint and target together | STUBBED | `test_cli.py::TestStubs` — exits 2, no files written |
| 28 | `drydock analyze <Blueprint> [<Target>]` | Reports gaps, drift, and missing Ship's Log coverage | STUBBED | `test_cli.py::TestStubs` — exits 2, no files written |
| 29 | `drydock import <Blueprint> <Target> --format <auto\|source\|speckit>` | Produces a proposed Blueprint and conversion report | STUBBED | `test_cli.py::TestStubs` — exits 2, no files written |

## Summary

| Category | Count |
|---|---:|
| Total commands | 29 |
| DONE | 15 |
| IMPLEMENTED | 0 |
| STUBBED | 14 |
| NOT STARTED | 0 |

Drydock is command-complete only when every command row is `DONE`.

## Development Process Acceptance

| Capability | Acceptance Criteria | State | Evidence / Notes |
|---|---|---|---|
| Canonical specification governance | `docs/Drydock_Specification.md` is the sole behavior authority; agents require product-owner approval before changing it; approved behavior and specification changes land together | DONE | `AGENTS.md`, `DRYDOCK_DEVELOPMENT.md`, `CONTRIBUTING.md` |
| Soundings completion workflow | Every completed command or capability updates its state and evidence in this file | DONE | `DRYDOCK_DEVELOPMENT.md` Soundings state and verification contracts |
| Owned-document viewing | QuarterDeck directly exposes the authoritative specification, Soundings, Sea Trials, rendered docs, and reservation artifacts | DONE | `QuarterDeck/console.json`; `tests/test_quarterdeck.py::test_drydock_console_exposes_existing_owned_documents` |

## Product Acceptance

Strategic product outcomes and proof-of-methodology criteria are maintained in
[`SEA_TRIALS.md`](SEA_TRIALS.md). Soundings records implementation acceptance; Sea Trials records
whether the assembled product has proven the methodology.

## Platform Notes

PowerShell launcher (`bin/drydock.ps1`) is structurally defined and syntactically valid.
Runtime verification requires a Windows or PowerShell-on-Linux environment; not verified in WSL.

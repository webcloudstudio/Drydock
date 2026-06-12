# SOUNDINGS.md — Drydock Acceptance And Readiness

This is Drydock's authoritative implementation acceptance/readiness checklist.

Update the matching row whenever a capability changes implementation or verification state; a
capability is complete only at `DONE` with concrete evidence.

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
| 8 | `drydock config set quarterdeck_port <port>` | Persists and validates the default QuarterDeck port | DONE | `test_config.py` quarterdeck-port tests; `test_cli.py::TestRunQuarterdeck::test_run_quarterdeck_config_port_used` |
| 9 | `drydock init <Target>` | Creates the specification-independent Target baseline and QuarterDeck while preserving existing files | DONE | `test_cli.py::TestInit`, `test_init_target.py` |
| 10 | `drydock run quarterdeck [<Target>] [--host HOST] [--port PORT]` | Starts a named configured Target's QuarterDeck, or the current directory's QuarterDeck when Target is omitted | DONE | `test_cli.py::TestRunQuarterdeck` |
| 11 | `drydock validate <Blueprint>` | Validates Blueprint completeness and conventions | DONE | `test_cli.py::TestValidate`, `test_validate_specification.py` |
| 12 | `drydock validate <Blueprint> --verbose` | Shows passing checks as well as findings | DONE | `test_cli.py::TestValidate::test_validate_verbose_shows_passes` |
| 13 | `drydock rigging compact <Blueprint> [--all] [--force]` | Refreshes stale compact derivatives with deterministic writes and execution evidence | DONE | `test_cli.py::TestRiggingCompact`, `test_rigging_compact.py` |
| 14 | `drydock document generate <Blueprint> <Target>` | Creates `DOC-*.md` summaries | STUBBED | `test_cli.py::TestStubs` — exits 2, no files written |
| 15 | `drydock document assemble <Blueprint> <Target>` | Renders existing Markdown documentation into HTML | DONE | `test_cli.py::TestDocumentAssemble`, `test_build_documentation.py` |
| 16 | `drydock document <Blueprint> <Target>` | Runs the full documentation pipeline | STUBBED | `test_cli.py::TestStubs` — exits 2, no files written |
| 17 | `drydock rigging update <Target>` | Propagates current Rigging to a target project | STUBBED | `test_cli.py::TestStubs` — exits 2, no files written |
| 18 | `drydock rigging verify <Target>` | Verifies target-project Rigging compliance | STUBBED | `test_cli.py::TestStubs` — exits 2, no files written |
| 19 | `drydock plan create <Blueprint> <Target>` | Internally inventories Blueprint inputs, writes draft `<Target>/BUILD_PLAN.md`, and creates the target-local Planning Session | IMPLEMENTED | Deterministic file/spec decomposition works: `test_cli.py::TestPlanningSession`; `test_build_plan.py::test_draft_plan_has_no_runnable_frontier`; isolated-wheel Markdown intake → create → approve → frontier verification. Semantic LLM decomposition, prompt-size analysis, and cost-reducing work grouping remain. |
| 20 | `drydock build status <Blueprint> <Target>` | Reports target plan state and runnable frontier | DONE | `test_build_plan.py::test_runnable_frontier_applies_dependency_and_ac_parent_rules`; `test_cli.py::TestPlanInspection::test_build_status_reports_runnable_frontier` |
| 21 | `drydock build <Blueprint> <Target>` | Builds the next runnable frontier and records evidence | STUBBED | `test_cli.py::TestStubs` — exits 2, no files written |
| 22 | `drydock build score <Blueprint> <Target>` | Generates `SCORECARD.md` | STUBBED | `test_cli.py::TestStubs` — exits 2, no files written |
| 23 | `drydock iterate <Blueprint> <Target> [BOTH\|BLUEPRINT\|TGT] <Scope> <Change>` | Updates Blueprint and target together | STUBBED | `test_cli.py::TestStubs` — exits 2, no files written |
| 24 | `drydock analyze <Blueprint> [<Target>]` | Reports gaps, drift, and missing Ship's Log coverage | STUBBED | `test_cli.py::TestStubs` — exits 2, no files written |
| 25 | `drydock import <Blueprint> <Source> --format <auto\|markdown\|source\|speckit>` | Preserves Markdown source bundles; source and Spec Kit conversion remain deferred | IMPLEMENTED | `test_cli.py::TestPlanningSession::test_markdown_import_plan_create_and_approve` |

## Summary

| Category | Count |
|---|---:|
| Total commands | 25 |
| DONE | 15 |
| IMPLEMENTED | 2 |
| STUBBED | 8 |
| NOT STARTED | 0 |

Drydock is command-complete only when every command row is `DONE`.

## Development Process Acceptance

| Capability | Acceptance Criteria | State | Evidence / Notes |
|---|---|---|---|
| Canonical specification governance | `docs/Drydock_Specification.md` is the sole behavior authority; agents require product-owner approval before changing it; approved behavior and specification changes land together | DONE | `AGENTS.md`, `DRYDOCK_DEVELOPMENT.md`, `CONTRIBUTING.md` |
| Soundings completion workflow | Every completed command or capability updates its state and evidence in this file | DONE | `DRYDOCK_DEVELOPMENT.md` Soundings state and verification contracts |
| Owned-document viewing | QuarterDeck directly exposes the authoritative specification, Soundings, Sea Trials, rendered docs, and reservation artifacts | DONE | `QuarterDeck/console.yaml`; `tests/test_quarterdeck.py::test_drydock_console_exposes_existing_owned_documents` |
| QuarterDeck standard artifacts | Commander's View, Soundings, and Sea Trials are the standard pinned Drydock Core artifacts of every Drydock QuarterDeck (orientation / acceptance criteria / objectives) | DONE | `docs/Drydock_Specification.md` § The QuarterDeck → Standard QuarterDeck Artifacts; `QuarterDeck/console.yaml` |
| QuarterDeck YAML config and five-section IA | `console.yaml` drives sections (id/label/dot/collapsed/pinned) and items; five sections: Drydock Core (pinned) · Build Plan · Action Items · Project Pages · Archive (collapsed); Archive collapsed by default | DONE | `QuarterDeck/console.yaml`; `QuarterDeck/app.py` (`nav_model`, `load_config`); `tests/test_quarterdeck.py` section/config tests |
| QuarterDeck `document` type | Collapses `path_md`/`path_html`/`path_pdf` variants into a tabbed view; sea_trials and pypi_reservation use this type | DONE | `QuarterDeck/app.py::render_document_item`; `tests/test_quarterdeck.py` document-renderer tests |
| QuarterDeck `sources:` convention engine | `sources:` glob rules auto-discover files as items; `overrides:` adjust generated items; explicit items (by ID or path) take priority | DONE | `QuarterDeck/app.py::_expand_sources`; `tests/test_quarterdeck.py` expand-sources tests |
| QuarterDeck archive/unarchive | SQLite-backed toggle moves items to Archive section; pinned sections immune; `↓`/`↑` buttons in nav | DONE | `QuarterDeck/app.py` (`api_archive_item`, `api_unarchive_item`, `nav_model`); `tests/test_quarterdeck.py` archive tests |
| QuarterDeck command-status report | Python-only read-only report derives command readiness and structured consistency exclusively from configured Core Docs | DONE | `QuarterDeck/app.py::render_command_status`; `tests/test_quarterdeck.py` command-status tests |
| Planning Session approval | The target-local QuarterDeck approves the authoritative target `BUILD_PLAN.md`; draft plans expose no runnable frontier | DONE | `QuarterDeck/app.py::api_plan_decision`; `tests/test_quarterdeck.py::test_plan_decision_approves_authoritative_plan`; `tests/test_build_plan.py::test_plan_approval_exposes_frontier` |
| Agent-driven Ship's Log proving workflow | Drydock agents read the local capture contract, classify and record material decisions and milestones through a validated repository utility, perform a final capture review, and surface records through QuarterDeck; standard target deployment remains deferred | DONE | `SHIPS_LOG_PROCESS.md`, `AGENTS.md`, `bin/ships_log.py`, `QuarterDeck/console.yaml`, `tests/test_ships_log_tool.py`, `tests/test_quarterdeck.py`, `tests/test_cli.py::TestHelpAndVersion::test_help_does_not_expose_ships_log` |

## Product Acceptance

Strategic product outcomes and proof-of-methodology criteria are maintained in
[`SEA_TRIALS.md`](SEA_TRIALS.md). Soundings records implementation acceptance; Sea Trials records
whether the assembled product has proven the methodology.

## Platform Notes

PowerShell launcher (`bin/drydock.ps1`) is structurally defined and syntactically valid.
Runtime verification requires a Windows or PowerShell-on-Linux environment; not verified in WSL.

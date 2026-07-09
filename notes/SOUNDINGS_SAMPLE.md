# Soundings

| ID | Acceptance Criterion | State | Evidence |
|---|---|---|---|
| CLI-001 | `drydock --help` shows the complete public command surface | DONE | `test_cli.py::TestHelpAndVersion` |
| CLI-002 | `drydock --version` shows version and copyright | DONE | `test_cli.py::TestHelpAndVersion` |
| CLI-003 | `drydock config show` displays effective configuration values and sources | DONE | `test_cli.py::TestConfigShow`, `test_config.py::TestConfigShow` |
| CLI-004 | `drydock config set drydock_workspace <path>` persists the workspace root | DONE | `test_cli.py::TestConfigSet`, `test_config.py::TestConfigSet` |
| CLI-005 | Targets resolve to `$DRYDOCK_WORKSPACE/targets/<Target>` (git-root/cwd default); a Target's Blueprint is its `blueprint/` subtree | DONE | `test_config.py::TestWorkspaceResolution` |
| CLI-006 | `drydock config set llm_provider <claude\|codex>` persists a valid subscription CLI provider | DONE | `test_cli.py::TestConfigSet`, `test_config.py::TestConfigSet` |
| CLI-007 | `drydock config set prompt_warn_tokens <tokens>` persists a valid prompt-size threshold | DONE | `test_cli.py::TestConfigSet`, `test_config.py::TestConfigSet` |
| CLI-008 | `drydock config set quarterdeck_port <port>` persists a valid QuarterDeck port | DONE | `test_config.py` quarterdeck-port tests, `test_cli.py::TestRunQuarterdeck::test_run_quarterdeck_config_port_used` |
| CLI-009 | `drydock init <Target>` creates the minimal Target scaffold (`METADATA.md` project identity, root Sea Trials/Soundings, `blueprint/sources/`, state-only QuarterDeck) | DONE | `test_cli.py::TestInit`, `test_init_target.py` |
| CLI-010 | `drydock run quarterdeck [<Target>] [--host HOST] [--port PORT]` serves the package runtime against a named or sole-Target in-tree console state | DONE | `test_cli.py::TestRunQuarterdeck`, `test_quarterdeck_run.py` |
| CLI-011 | `drydock status <Blueprint> <Target>` validates a Target's Blueprint completeness and conventions | DONE | `test_cli.py::TestValidate`, `test_validate_specification.py` |
| CLI-012 | `drydock status <Blueprint> <Target> --verbose` shows passing checks and findings | DONE | `test_cli.py::TestValidate::test_validate_verbose_shows_passes` |
| CLI-013 | `drydock rigging compact <Blueprint> <Target> [--all] [--force]` refreshes stale compact derivatives with execution evidence | DONE | `test_cli.py::TestRiggingCompact`, `test_rigging_compact.py` |
| CLI-014 | `drydock document generate <Blueprint> <Target>` creates `DOC-*.md` summaries | STUBBED | `test_cli.py::TestStubs` |
| CLI-015 | `drydock document assemble <Blueprint> <Target>` renders existing Markdown documentation into HTML | DONE | `test_cli.py::TestDocumentAssemble`, `test_build_documentation.py` |
| CLI-016 | `drydock document <Blueprint> <Target>` runs the full documentation pipeline | STUBBED | `test_cli.py::TestStubs` |
| CLI-017 | `drydock rigging update <Target>` propagates current Rigging to a Target | STUBBED | `test_cli.py::TestStubs` |
| CLI-018 | `drydock rigging verify <Target>` verifies Target Rigging compliance | STUBBED | `test_cli.py::TestStubs` |
| CLI-019 | `drydock plan create <Blueprint> <Target>` inventories inputs, writes a draft plan, projects acceptance gates into Soundings, and creates the Planning Session | IMPLEMENTED | `test_cli.py::TestPlanningSession`, `test_standard_artifacts.py` |
| CLI-020 | `drydock build status <Blueprint> <Target>` reports Target plan state and runnable frontier | DONE | `test_build_plan.py::test_runnable_frontier_applies_dependency_and_ac_parent_rules`, `test_cli.py::TestPlanInspection::test_build_status_reports_runnable_frontier` |
| CLI-021 | `drydock build <Blueprint> <Target>` builds the next runnable frontier and records evidence | STUBBED | `test_cli.py::TestStubs` |
| CLI-022 | `drydock build score <Blueprint> <Target>` generates `SCORECARD.md` | STUBBED | `test_cli.py::TestStubs` |
| CLI-023 | `drydock refit <Blueprint> <Target> [BOTH\|BLUEPRINT\|TGT] <Scope> <Change>` updates Blueprint and Target together | STUBBED | `test_cli.py::TestStubs` |
| CLI-024 | `drydock analyze <Target>` evaluates Blueprint spec files; writes `QuarterDeck/planning/ANALYSIS.md` and `QuarterDeck/questionnaires/planning.json`; read-only invariant holds; LLM adapter isolated for tests | IMPLEMENTED | `test_analyze.py` — unit, CLI contract, file-write; drift/coverage mode (built-code comparison) deferred |
| CLI-025 | `drydock import <Blueprint> <Target> <Source> --format <auto\|markdown\|source\|speckit\|intent>` preserves Markdown source bundles under `<Target>/blueprint/sources/`; `--format source` assembles LLM prompt from source code and writes Blueprint files; `--format speckit` translates Spec Kit project to Blueprint with conversion report; `--format auto` detects format from source layout; `--format intent` copies source to `blueprint/COMPASS.md` | DONE | `test_import_markdown.py`, `test_import_source.py`, `test_import_speckit.py`, `test_cli.py::TestImport`, `test_cli.py::TestPlanningSession::test_markdown_import_plan_create_and_approve`, `test_import_intent.py` |
| CLI-026 | `drydock status <Blueprint> <Target>` reports plan state and runnable frontier | DONE | `test_cli.py::TestStatus::test_status_blueprint_target_reports_plan_state`, `test_status.py::TestStatusBlueprintTarget` |
| CLI-027 | `drydock status <Blueprint>` reports Blueprint validation summary | DONE | `test_cli.py::TestStatus::test_status_blueprint_reports_validation_summary`, `test_status.py::TestStatusBlueprint` |
| CLI-028 | `drydock status` (no args) shows compact dashboard of last active project and records activity | DONE | `test_cli.py::TestStatus::test_status_no_args_*`, `test_status.py::TestStatusCurrent` |
| CLI-029 | `drydock survey <Target> [--run] [--import <path>] [--command <name>] [--raw]` scores each command against `<Target>/survey/ac/` acceptance criteria, appends `<Target>/survey/scores.jsonl`, and renders the scoreboard; deterministic scoring math with an injected LLM runner | IMPLEMENTED | `tests/test_survey.py`, `src/drydock/survey.py` |
| QD-001 | Commanders Chair, Sea Trials, and Soundings are standard pinned Core artifacts | DONE | `QuarterDeck/console.yaml`, `tests/test_quarterdeck.py::test_drydock_console_pins_the_three_standard_artifacts_in_core` |
| QD-002 | Core artifacts appear in the order Commanders Chair, Master Blueprint, Sea Trials, Soundings, Ship's Log | DONE | `QuarterDeck/console.yaml`, `tests/test_quarterdeck.py::test_drydock_console_core_artifact_order` |
| QD-003 | Soundings is a single acceptance ledger and QuarterDeck calculates acceptance totals | DONE | `QuarterDeck/app.py::render_command_status`, `tests/test_quarterdeck.py` |
| QD-004 | `drydock init` creates target-local Sea Trials and Soundings without overwriting existing files | DONE | `src/drydock/init_target.py`, `tests/test_init_target.py` |
| QD-005 | `drydock plan create` preserves standard artifacts and projects plan acceptance gates into Soundings | DONE | `src/drydock/planning_session.py`, `tests/test_standard_artifacts.py` |
| QD-006 | QuarterDeck YAML configuration drives five-section navigation and item rendering | DONE | `QuarterDeck/console.yaml`, `QuarterDeck/app.py`, `tests/test_quarterdeck.py` |
| QD-007 | QuarterDeck document items collapse Markdown, HTML, and PDF variants into one tabbed view | DONE | `QuarterDeck/app.py::render_document_item`, `tests/test_quarterdeck.py` |
| QD-008 | QuarterDeck source rules auto-discover files while explicit items and overrides take priority | DONE | `QuarterDeck/app.py::_expand_sources`, `tests/test_quarterdeck.py` |
| QD-009 | QuarterDeck archive controls preserve pinned Core artifacts | DONE | `QuarterDeck/app.py`, `tests/test_quarterdeck.py` |
| QD-010 | Planning Session approval writes the authoritative plan state and exposes the runnable frontier | DONE | `QuarterDeck/app.py::api_plan_decision`, `tests/test_quarterdeck.py`, `tests/test_build_plan.py` |
| GOV-001 | The Drydock specification is the sole approved behavior authority | DONE | `AGENTS.md`, `CONTRIBUTING.md` |
| GOV-002 | Completed capabilities update Soundings state and evidence | DONE | `AGENTS.md` |
| GOV-003 | Material decisions and milestones are recorded and audited through the Ship's Log workflow | DONE | `AGENTS.md`, `bin/ships_log.py`, `tests/test_ships_log_tool.py` |

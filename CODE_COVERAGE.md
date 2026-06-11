# CODE_COVERAGE.md — Drydock Command Readiness

This file tracks command implementation and behavioral test coverage.
It is a maintained product artifact. A command is `IMPLEMENTED` only when real behavior exists;
`FUNCTIONAL TESTED` only when real behavior has passed an automated test.
Deferred commands are `STUBBED` when their not-implemented response is registered and tested.

| Order | Command | Purpose | Implementation | Test Status | Evidence / Notes |
|---:|---|---|---|---|---|
| 1 | `drydock --help` | Show top-level help with all commands | IMPLEMENTED | FUNCTIONAL TESTED | test_cli.py::TestHelpAndVersion |
| 2 | `drydock --version` | Show version and copyright | IMPLEMENTED | FUNCTIONAL TESTED | test_cli.py::TestHelpAndVersion |
| 3 | `drydock config show` | Display current configuration values and sources | IMPLEMENTED | FUNCTIONAL TESTED | test_cli.py::TestConfigShow, test_config.py::TestConfigShow |
| 4 | `drydock config set blueprint_directory <path>` | Persist specification root path | IMPLEMENTED | FUNCTIONAL TESTED | test_cli.py::TestConfigSet, test_config.py::TestConfigSet |
| 5 | `drydock config set target_directory <path>` | Persist target root path | IMPLEMENTED | FUNCTIONAL TESTED | test_cli.py::TestConfigSet, test_config.py::TestConfigSet |
| 6 | `drydock init <Blueprint>` | Create specification directory from templates | IMPLEMENTED | FUNCTIONAL TESTED | test_cli.py::TestInit, test_init_specification.py |
| 7 | `drydock init <Blueprint> --update` | Add only missing template files | IMPLEMENTED | FUNCTIONAL TESTED | test_cli.py::TestInit::test_init_update_is_non_destructive |
| 8 | `drydock init <Blueprint> --force` | Overwrite all template-managed files | IMPLEMENTED | FUNCTIONAL TESTED | test_cli.py::TestInit::test_init_force_overwrites |
| 9 | `drydock validate <Blueprint>` | Validate specification completeness | IMPLEMENTED | FUNCTIONAL TESTED | test_cli.py::TestValidate, test_validate_specification.py |
| 10 | `drydock validate <Blueprint> --verbose` | Validate and show passing checks | IMPLEMENTED | FUNCTIONAL TESTED | test_cli.py::TestValidate::test_validate_verbose_shows_passes |
| 11 | `drydock document generate <Blueprint> <Target>` | AI pass: create DOC-*.md summaries | STUBBED | STUB TESTED | test_cli.py::TestStubs — exits 2, no files written |
| 12 | `drydock document assemble <Blueprint> <Target>` | Assembly: render DOC-*.md into docs/index.html | STUBBED | STUB TESTED | test_cli.py::TestStubs — exits 2, no files written |
| 13 | `drydock document <Blueprint> <Target>` | Full documentation pipeline | STUBBED | STUB TESTED | test_cli.py::TestStubs — exits 2, no files written |
| 14 | `drydock rigging compact <Blueprint>` | Generate compact rigging derivatives | STUBBED | STUB TESTED | test_cli.py::TestStubs — exits 2, no files written |
| 15 | `drydock rigging update <Target>` | Propagate rigging to a target project | STUBBED | STUB TESTED | test_cli.py::TestStubs — exits 2, no files written |
| 16 | `drydock rigging verify <Target>` | Verify target project rigging compliance | STUBBED | STUB TESTED | test_cli.py::TestStubs — exits 2, no files written |
| 17 | `drydock plan init <Blueprint>` | Create or update BUILD_PLAN_INTENT.md | STUBBED | STUB TESTED | test_cli.py::TestStubs — exits 2, no files written |
| 18 | `drydock plan create <Blueprint>` | Run LLM analysis and produce BUILD_PLAN.md | STUBBED | STUB TESTED | test_cli.py::TestStubs — exits 2, no files written |
| 19 | `drydock plan show <Blueprint>` | Show the current build plan | STUBBED | STUB TESTED | test_cli.py::TestStubs — exits 2, no files written |
| 20 | `drydock build status <Blueprint> <Target>` | Show per-block build state | STUBBED | STUB TESTED | test_cli.py::TestStubs — exits 2, no files written |
| 21 | `drydock build <Blueprint> <Target>` | Build next frontier per BUILD_PLAN.md | STUBBED | STUB TESTED | test_cli.py::TestStubs — exits 2, no files written |
| 22 | `drydock build score <Blueprint> <Target>` | Generate SCORECARD.md | STUBBED | STUB TESTED | test_cli.py::TestStubs — exits 2, no files written |
| 23 | `drydock iterate <Blueprint> <Target> [BOTH\|SPEC\|TGT] <Scope> <Change>` | Update spec and target together | STUBBED | STUB TESTED | test_cli.py::TestStubs — exits 2, no files written |
| 24 | `drydock analyze <Blueprint> [<Target>]` | Read-only advisory on gaps and drift | STUBBED | STUB TESTED | test_cli.py::TestStubs — exits 2, no files written |
| 25 | `drydock import <Blueprint> <Target> --format <auto\|source\|speckit>` | Reverse-engineer project into specification | STUBBED | STUB TESTED | test_cli.py::TestStubs — exits 2, no files written |

## Summary

| Category | Count |
|---|---|
| Total commands | 25 |
| IMPLEMENTED | 10 |
| STUBBED | 15 |
| FUNCTIONAL TESTED | 10 |
| STUB TESTED | 15 |
| NOT STARTED | 0 |
| UNTESTED | 0 |

Drydock is command-complete only when every row shows `IMPLEMENTED` and `FUNCTIONAL TESTED`.

## Platform Notes

PowerShell launcher (`bin/drydock.ps1`) is structurally defined and syntactically valid.
Runtime verification requires a Windows or PowerShell-on-Linux environment; not verified in WSL.

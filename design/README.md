# Drydock Design

Behavior rules and working notes for each `drydock` command. AGENTS.md §Design defines the file
layout, section ownership, and precedence: code > `design/` > `docs/Drydock_Specification.md`.

## Commands

| Command | File | Modules | Prompts | Topics |
|---|---|---|---|---|
| `analyze` | [analyze.md](commands/analyze.md) | `analyze.py` | `analyze.md` | foundations |
| `build` | [build.md](commands/build.md) | `build.py`, `build_run.py`, `build_plan.py`, `acceptance.py` | `build.md` | acceptance_criteria, foundations |
| `config` | [config.md](commands/config.md) | `config.py`, `model_config.py` | — | — |
| `diagnose` | [diagnose.md](commands/diagnose.md) | `diagnose_command.py` | `diagnose*.md` | — |
| `document` | [document.md](commands/document.md) | `target_documentation.py`, `build_documentation.py` | `document_generate.md` | — |
| `import` | [import.md](commands/import.md) | `cli.py` (`cmd_import`) | `import_compass.md` | — |
| `init` | [init.md](commands/init.md) | `cli.py` (`cmd_init`) | — | — |
| `plan` | [plan.md](commands/plan.md) | `planning_session.py`, `plan_*.py`, `database_contract.py`, `manifest.py` | `plan_*.md` | foundations, acceptance_criteria |
| `publish` | [publish.md](commands/publish.md) | `cli.py` (`cmd_publish`) | — | — |
| `refit` | [refit.md](commands/refit.md) | `refit.py`, `lineage.py` | `refit*.md`, `lineage_attribute.md` | — |
| `report` | [report.md](commands/report.md) | `report_render.py` | — | — |
| `rigging` | [rigging.md](commands/rigging.md) | `rigging_compact.py`, `rigging_contract.py` | `rigging_compact_*.md` | foundations |
| `run` | [run.md](commands/run.md) | `quarterdeck_state.py` | — | — |
| `score` | [score.md](commands/score.md) | `score*.py`, `sea_trials.py` | `score_*.md` | acceptance_criteria |
| `status` | [status.md](commands/status.md) | `status.py` | — | — |
| `uat` | [uat.md](commands/uat.md) | `uat.py`, `uat_report.py` | `uat_diagnostic.md` | acceptance_criteria |
| `validate` | [validate.md](commands/validate.md) | `cli.py` (`cmd_validate`) | — | — |

## Topics

| Topic | File | Governs |
|---|---|---|
| Acceptance criteria | [acceptance_criteria.md](topics/acceptance_criteria.md) | plan, build, score, uat |
| Foundations | [foundations.md](topics/foundations.md) | plan, build, rigging, analyze |

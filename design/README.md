# Drydock Design

Behavior rules and working notes for each `drydock` command. AGENTS.md §Design defines the file
layout, section ownership, and precedence: code > `design/` > `docs/Drydock_Specification.md`.
`tests/test_design_coverage.py` requires a file here for every top-level command.

## Commands

| Command | File | Modules | Prompts | Topics |
|---|---|---|---|---|
| `analyze` | [analyze.md](commands/analyze.md) | `analyze.py`, `sea_trials.py`, `technology_stack.py` | `analyze.md` | foundations |
| `build` | [build.md](commands/build.md) | `build.py`, `build_run.py`, `build_plan.py`, `acceptance.py`, `lineage.py`, `model_config.py` | `build.md` | acceptance_criteria, foundations |
| `config` | [config.md](commands/config.md) | `config.py`, `model_config.py`, `calibration.py` | — | — |
| `diagnose` | [diagnose.md](commands/diagnose.md) | `diagnose_command.py`, `diagnose_*.py`, `ac_repair.py` | `diagnose_report.md`, `diagnose_ac_repair.md`, `diagnose.md` | acceptance_criteria |
| `document` | [document.md](commands/document.md) | `target_documentation.py`, `readme_generate.py` | `document_generate.md` | — |
| `import` | [import.md](commands/import.md) | `import_markdown.py`, `import_source.py`, `import_speckit.py`, `source_refit.py` | `import_compass.md` | — |
| `init` | [init.md](commands/init.md) | `init_target.py`, `standard_artifacts.py`, `target_git.py`, `skills.py` | — | — |
| `plan` | [plan.md](commands/plan.md) | `planning_session.py`, `plan_*.py`, `database_contract.py`, `manifest.py` | `plan_*.md`, `BLUEPRINTS_CONTRACT.md`, `MANIFEST_CONTRACT.md` | foundations, acceptance_criteria |
| `prompt` | [prompt.md](commands/prompt.md) | `prompt_review.py` | `prompt_review.md` | — |
| `publish` | [publish.md](commands/publish.md) | `build_documentation.py`, `markdown_render.py` | — | — |
| `refit` | [refit.md](commands/refit.md) | `refit.py`, `refit_ticket.py`, `change_ticket.py`, `manifest_edit.py` | `refit*.md` | — |
| `report` | [report.md](commands/report.md) | `report.py`, `report_render.py`, `llm_report.py` | — | — |
| `rigging` | [rigging.md](commands/rigging.md) | `rigging_compact.py`, `rigging_update.py`, `rigging_verify.py`, `rigging_manifest.py` | `rigging_compact_*.md` | foundations |
| `run` | [run.md](commands/run.md) | `quarterdeck_run.py`, `quarterdeck_state.py`, `QuarterDeck/app.py` | — | foundations |
| `score` | [score.md](commands/score.md) | `score*.py`, `scorecard.py`, `sea_trials.py` | `score_*.md` | acceptance_criteria |
| `status` | [status.md](commands/status.md) | `status.py`, `project_status.py` | — | acceptance_criteria |
| `survey` | [survey.md](commands/survey.md) | `survey.py` | `survey.md`, `survey_import.md` | — |
| `uat` | [uat.md](commands/uat.md) | `uat.py`, `uat_report.py` | `uat_diagnostic.md` | acceptance_criteria |
| `validate` | [validate.md](commands/validate.md) | `validate_specification.py` | — | — |

## Topics

| Topic | File | Governs |
|---|---|---|
| Acceptance criteria | [acceptance_criteria.md](topics/acceptance_criteria.md) | build, score, plan, diagnose, status, uat |
| Foundations | [foundations.md](topics/foundations.md) | plan, rigging, build, run, analyze |

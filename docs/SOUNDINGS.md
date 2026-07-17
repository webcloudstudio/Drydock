# Drydock Soundings

| Capability | State | Verification evidence |
|---|---|---|
| Structured Sea Trials acceptance contract | DONE | `tests/test_sea_trials.py`; `tests/test_analyze.py` |
| EARS notation for assertion criteria | DONE | `tests/test_sea_trials.py::test_each_ears_pattern_is_accepted`; `::test_criterion_not_matching_its_declared_pattern_is_rejected`; `::test_assertion_type_without_a_pattern_is_rejected`; `::test_qualitative_criterion_must_not_declare_a_pattern` |
| Project guardrails with a hard completion gate | DONE | `tests/test_sea_trials.py::test_guardrail_must_use_the_unwanted_pattern`; `tests/test_build_score.py::test_breached_guardrail_blocks_completion`; `::test_guardrail_without_evidence_is_breached`; `::test_held_guardrail_needs_no_story_coverage_and_gate_completes` |
| Embedded Sea Trials reader documentation | DONE | `tests/test_sea_trials.py::test_normalization_replaces_stale_documentation_and_is_idempotent`; `::test_documentation_prose_does_not_overwrite_the_preceding_criterion_fields`; `tests/test_analyze.py::test_emitted_sea_trials_carry_the_reader_documentation`; `tests/test_quarterdeck.py::test_sea_trials_renderer_boxes_documentation_blocks`; `::test_ordinary_markdown_pages_do_not_box_h3_headings` |
| Sea Trials validated before any analyze write | DONE | `tests/test_analyze.py::test_malformed_sea_trials_writes_nothing_and_fails_the_run`; `::test_malformed_sea_trials_raises`; `::test_model_owned_sea_trials_questionnaire_is_rejected` |
| Planning acceptance traceability | DONE | `tests/test_planning_session.py`; `tests/test_build_plan.py` |
| Evidence-bound `drydock build score` | DONE | `tests/test_build_score.py`; `tests/test_cli.py`; full test, lint, and format gates |
| Non-deterministic verification discount | DONE | `tests/test_build_score.py::test_required_assertions_judged_only_by_the_model_lose_coverage_score` |
| Code-bound score freshness in build status | DONE | `tests/test_build_score.py`; `tests/test_cli.py` |

"""Per-criterion acceptance status store, lineage history, board columns, and FLAKY."""

import json

from drydock.acceptance import (
    FLAKY_FAILURE_PREFIX,
    MALFORMED_FAILURE_PREFIX,
    AcceptanceObservation,
    AcceptanceRunResult,
    ProgrammaticAcceptance,
    is_terminal_check_failure,
)
from drydock.acceptance_status import (
    ACCEPTANCE_STATUS_EVIDENCE,
    ERROR_BASELINE_RED,
    ERROR_ENVIRONMENT,
    ERROR_MALFORMED,
    ERROR_PRODUCT_MISSING,
    ERROR_VACUOUS,
    STATUS_ALWAYS_PASSES,
    STATUS_ERROR,
    STATUS_FLAKY,
    STATUS_PREBUILD_PASSES,
    STATUS_VALID,
    acceptance_history,
    classify_baseline,
    current_status,
    prepassed_ids,
    read_acceptance_status,
    record_baseline_status,
    record_status,
)
from drydock.build_run import _settle_flaky
from drydock.standard_artifacts import Sounding, load_soundings, render_soundings


def _check(check_id="ac", code="assert run() == 3\n", *, full_suite=False):
    return ProgrammaticAcceptance(check_id, "SPEC.md", "intent", code, full_suite=full_suite)


def _observation(check_id="ac", *, passed=False, error=None, stderr="", skipped=False, ok=True):
    return AcceptanceObservation(
        check_id,
        "SPEC.md",
        "intent",
        passed,
        0 if passed else 1,
        "",
        stderr,
        error=error,
        skipped=skipped,
        integrity_ok=ok,
        integrity_reasons=() if ok else ("assert True",),
    )


def _result(check_id="ac", *, passed=False, binding=True, skipped=False):
    return AcceptanceRunResult(
        check_id,
        "SPEC.md",
        "intent",
        passed,
        0 if passed else 1,
        "",
        "",
        skipped=skipped,
        binding=binding,
    )


# --- Baseline classification -----------------------------------------------------------------


def test_missing_product_is_a_valid_red():
    status = classify_baseline(
        _observation(stderr="ModuleNotFoundError: No module named 'app'"), _check()
    )
    assert (status.status, status.error_code) == (STATUS_VALID, ERROR_PRODUCT_MISSING)


def test_an_ordinary_red_is_valid():
    status = classify_baseline(_observation(stderr="AssertionError"), _check())
    assert (status.status, status.error_code) == (STATUS_VALID, ERROR_BASELINE_RED)


def test_missing_environment_is_an_error_not_a_red():
    status = classify_baseline(
        _observation(skipped=True, error="unverified acceptance: x"), _check()
    )
    assert (status.status, status.error_code) == (STATUS_ERROR, ERROR_ENVIRONMENT)


def test_a_criterion_dying_in_its_own_frame_is_malformed():
    status = classify_baseline(
        _observation(error=f"{MALFORMED_FAILURE_PREFIX}: NameError"), _check()
    )
    assert (status.status, status.error_code) == (STATUS_ERROR, ERROR_MALFORMED)


def test_green_before_the_build_is_prebuild_passes_or_always_passes():
    assert classify_baseline(_observation(passed=True), _check()).status == STATUS_PREBUILD_PASSES
    vacuous = classify_baseline(_observation(passed=True, ok=False), _check())
    assert (vacuous.status, vacuous.error_code) == (STATUS_ALWAYS_PASSES, ERROR_VACUOUS)


def test_a_baseline_that_never_ran_records_nothing():
    observation = _observation(error="baseline unavailable: authorized Target tooling")
    assert classify_baseline(observation, _check()) is None


# --- Store merge rules -----------------------------------------------------------------------


def test_store_round_trips_and_feeds_prepassed_ids(tmp_path):
    check = _check()
    record_baseline_status(tmp_path, {"ac": classify_baseline(_observation(passed=True), check)})

    statuses = read_acceptance_status(tmp_path)
    assert statuses["ac"].status == STATUS_PREBUILD_PASSES
    assert prepassed_ids(statuses, [check]) == frozenset({"ac"})
    payload = json.loads((tmp_path / ACCEPTANCE_STATUS_EVIDENCE).read_text(encoding="utf-8"))
    assert payload["criteria"]["ac"]["status"] == STATUS_PREBUILD_PASSES


def test_an_edited_criterion_has_no_current_status(tmp_path):
    record_baseline_status(tmp_path, {"ac": classify_baseline(_observation(), _check())})
    statuses = read_acceptance_status(tmp_path)
    assert current_status(statuses, _check(code="assert run() == 4\n")) is None
    assert prepassed_ids(statuses, [_check(code="assert run() == 4\n")]) == frozenset()


def test_a_terminal_status_survives_a_baseline_while_the_code_is_unchanged(tmp_path):
    check = _check()
    record_status(tmp_path, check, STATUS_FLAKY, "verdict-changed", "")
    record_baseline_status(tmp_path, {"ac": classify_baseline(_observation(), check)})
    assert read_acceptance_status(tmp_path)["ac"].status == STATUS_FLAKY

    edited = _check(code="assert run() == 4\n")
    record_baseline_status(tmp_path, {"ac": classify_baseline(_observation(), edited)})
    assert read_acceptance_status(tmp_path)["ac"].status == STATUS_VALID


def test_a_resumed_baseline_keeps_the_first_build_status(tmp_path):
    check = _check()
    record_baseline_status(tmp_path, {"ac": classify_baseline(_observation(), check)})
    # The resumed tree holds the block's own partial work, which now satisfies the criterion.
    merged = record_baseline_status(
        tmp_path, {"ac": classify_baseline(_observation(passed=True), check)}, resume=True
    )
    assert merged["ac"].status == STATUS_VALID


def test_a_resumed_baseline_rechecks_an_error(tmp_path):
    check = _check()
    record_baseline_status(
        tmp_path, {"ac": classify_baseline(_observation(skipped=True, error="x"), check)}
    )
    merged = record_baseline_status(
        tmp_path, {"ac": classify_baseline(_observation(), check)}, resume=True
    )
    assert merged["ac"].status == STATUS_VALID


# --- Lineage history and board columns -------------------------------------------------------


def test_history_reports_previous_passes_and_the_last_block(tmp_path):
    rows = [
        {"block": "b1", "details": {"acceptance": [{"check_id": "a", "passed": True}]}},
        {
            "block": "b2",
            "details": {
                "acceptance": [
                    {"check_id": "a", "passed": False},
                    {"check_id": "b", "passed": False},
                    {"check_id": "c", "passed": True, "skipped": True},
                ]
            },
        },
    ]
    (tmp_path / "BUILD_LINEAGE.jsonl").write_text(
        "".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8"
    )

    history = acceptance_history(tmp_path)

    assert history["a"].previously_passed and history["a"].last_block == "b2"
    assert not history["b"].previously_passed
    assert "c" not in history


def test_history_without_lineage_is_empty(tmp_path):
    assert acceptance_history(tmp_path) == {}


def test_board_round_trips_the_new_columns(tmp_path):
    row = Sounding(
        "ac",
        "SPEC.md",
        "text",
        "✓ PASS",
        "ok",
        "now",
        binding="no",
        baseline="VALID product-missing",
        previously_passed="yes",
        last_block="b2",
    )
    path = tmp_path / "SOUNDINGS.md"
    path.write_text(render_soundings([row]), encoding="utf-8")
    assert load_soundings(path)["ac"] == row


def test_a_board_written_before_the_new_columns_still_loads(tmp_path):
    path = tmp_path / "SOUNDINGS.md"
    path.write_text(
        "| Status | Blueprint | AC Id | Text | Evidence | Verified At |\n"
        "|---|---|---|---|---|---|\n"
        "| ✓ PASS | SPEC.md | ac | text | ok | now |\n",
        encoding="utf-8",
    )
    assert load_soundings(path)["ac"].verified == "✓ PASS"


# --- FLAKY -----------------------------------------------------------------------------------


def _flaky(acceptance, checks, *, rerun_passes, tree_after=None):
    return _settle_flaky(
        acceptance,
        checks,
        rerun=lambda selected: tuple(
            _result(check.check_id, passed=rerun_passes) for check in selected
        ),
        tree_before={"a.py": 1},
        snapshot=lambda: tree_after if tree_after is not None else {"a.py": 1},
    )


def test_a_fail_that_passes_on_an_unchanged_tree_is_flaky():
    settled, flaky = _flaky((_result(),), (_check(),), rerun_passes=True)
    assert flaky == ("ac",)
    assert settled[0].skipped and settled[0].error.startswith(FLAKY_FAILURE_PREFIX)
    assert is_terminal_check_failure(settled[0].error)


def test_a_changed_tree_keeps_the_original_fail():
    settled, flaky = _flaky((_result(),), (_check(),), rerun_passes=True, tree_after={"a.py": 2})
    assert flaky == ()
    assert not settled[0].skipped


def test_a_consistent_fail_is_not_flaky():
    assert _flaky((_result(),), (_check(),), rerun_passes=False)[1] == ()


def test_suite_bound_and_non_binding_criteria_are_not_rerun():
    reran: list = []

    def rerun(selected):
        reran.extend(selected)
        return ()

    _settle_flaky(
        (_result("suite"), _result("typed", binding=False)),
        (_check("suite", full_suite=True), _check("typed")),
        rerun=rerun,
        tree_before={},
        snapshot=dict,
    )
    assert reran == []


def test_a_resumed_baseline_never_records_prebuild_passes_for_a_gap(tmp_path):
    check = _check()
    merged = record_baseline_status(
        tmp_path, {"ac": classify_baseline(_observation(passed=True), check)}, resume=True
    )
    assert "ac" not in merged


# --- Exclusion -------------------------------------------------------------------------------


def test_only_criteria_that_can_measure_the_product_run(tmp_path):
    from drydock.acceptance import EXCLUDED_FAILURE_PREFIX
    from drydock.acceptance_status import STATUS_UNFIXABLE, excluded_criteria
    from drydock.build_run import _run_valid_criteria

    checks = (_check("valid"), _check("dead"), _check("prebuilt"), _check("broken"))
    record_baseline_status(
        tmp_path,
        {
            "valid": classify_baseline(_observation("valid"), checks[0]),
            "prebuilt": classify_baseline(_observation("prebuilt", passed=True), checks[2]),
            "broken": classify_baseline(
                _observation("broken", error=f"{MALFORMED_FAILURE_PREFIX}: x"), checks[3]
            ),
        },
    )
    record_status(tmp_path, checks[1], STATUS_UNFIXABLE, "repair-impossible", "")
    excluded = excluded_criteria(read_acceptance_status(tmp_path), checks)
    ran: list = []

    def run(selected):
        ran.extend(check.check_id for check in selected)
        return tuple(_result(check.check_id, passed=True) for check in selected)

    results = _run_valid_criteria(checks, excluded, run)

    # PREBUILD_PASSES keeps running: it may be regression coverage of existing behavior.
    assert ran == ["valid", "prebuilt"]
    assert [result.check_id for result in results] == ["valid", "dead", "prebuilt", "broken"]
    dead = results[1]
    assert dead.skipped and dead.error.startswith(EXCLUDED_FAILURE_PREFIX)
    assert "UNFIXABLE" in dead.error


def test_a_vacuous_criterion_is_always_passes_even_when_red_at_baseline():
    code = "try:\n    assert run() == 3\nexcept Exception:\n    pass\n"
    status = classify_baseline(_observation(stderr="NameError"), _check(code=code))
    assert status.status == STATUS_ALWAYS_PASSES


# --- Empty-directory baseline ----------------------------------------------------------------


def test_passing_with_no_product_is_prebuild_passes_and_still_runs():
    from drydock.acceptance_status import ERROR_EMPTY_TREE, excluded_criteria

    check = _check()
    status = classify_baseline(_observation(passed=True), check, empty=_observation(passed=True))
    assert (status.status, status.error_code) == (STATUS_PREBUILD_PASSES, ERROR_EMPTY_TREE)
    # It runs after the block, but a pass with nothing built cannot verify its story.
    assert excluded_criteria({"ac": status}, [check]) == {}
    assert prepassed_ids({"ac": status}, [check]) == frozenset({"ac"})


def test_existing_behavior_is_valid_prepassed_and_keeps_running():
    from drydock.acceptance_status import ERROR_EXISTING_BEHAVIOR, excluded_criteria

    check = _check()
    status = classify_baseline(_observation(passed=True), check, empty=_observation())
    assert (status.status, status.error_code) == (STATUS_VALID, ERROR_EXISTING_BEHAVIOR)
    assert prepassed_ids({"ac": status}, [check]) == frozenset({"ac"})
    assert excluded_criteria({"ac": status}, [check]) == {}


def test_without_an_empty_run_a_current_pass_keeps_running():
    from drydock.acceptance_status import ERROR_CURRENT_TREE, excluded_criteria

    check = _check()
    status = classify_baseline(_observation(passed=True), check)
    assert status.error_code == ERROR_CURRENT_TREE
    assert excluded_criteria({"ac": status}, [check]) == {}


def test_a_resumed_empty_tree_pass_is_still_recorded(tmp_path):
    check = _check()
    merged = record_baseline_status(
        tmp_path,
        {
            "ac": classify_baseline(
                _observation(passed=True), check, empty=_observation(passed=True)
            )
        },
        resume=True,
    )
    assert merged["ac"].status == STATUS_PREBUILD_PASSES


def test_the_empty_baseline_holds_staged_inputs_and_no_product(tmp_path):
    from drydock.acceptance_status import observe_empty_baseline
    from drydock.source_roles import StagedAsset

    asset = tmp_path / "suite.txt"
    asset.write_text("cases\n", encoding="utf-8")
    product = tmp_path / "build" / "app.txt"
    product.parent.mkdir()
    product.write_text("built\n", encoding="utf-8")
    checks = (
        _check("staged", "from pathlib import Path\nassert Path('sources/suite.txt').is_file()\n"),
        _check("product", "from pathlib import Path\nassert Path('app.txt').is_file()\n"),
    )
    staged = (StagedAsset(source=asset, relative_path="sources/suite.txt", sha256=""),)

    observed = {
        item.check_id: item
        for item in observe_empty_baseline(
            checks, target_dir=tmp_path, blueprint_dir=tmp_path, staged=staged
        )
    }

    assert observed["staged"].passed
    assert not observed["product"].passed

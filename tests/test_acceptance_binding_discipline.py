"""Binding discipline: only binding criteria verify, progress, regress, or drive repair."""

from drydock.acceptance import AcceptanceRunResult
from drydock.build_run import (
    NON_BINDING_FINDING,
    PREPASSED_FINDING,
    UNEXAMINED_FINDING,
    AttemptRecord,
    _acceptance_progress,
    _binding_progress_view,
    _drives_repair,
    _unverified_finding,
)


def _result(check_id, *, passed, binding=True, skipped=False, stdout=""):
    return AcceptanceRunResult(
        check_id=check_id,
        source="SPEC.md",
        intent=check_id,
        passed=passed,
        return_code=0 if passed else 1,
        stdout=stdout,
        stderr="",
        skipped=skipped,
        binding=binding,
    )


def _record(executed, passed, tallies=()):
    return AttemptRecord(
        index=0,
        execution_id=None,
        model=None,
        passed_checks=len(passed),
        total_checks=len(executed),
        passed_check_ids=tuple(passed),
        passed_cases=None,
        total_cases=None,
        case_tallies=tuple(tallies),
        status="failed",
        executed_check_ids=tuple(executed),
    )


def test_binding_pass_not_prepassed_verifies():
    assert _unverified_finding((_result("a", passed=True),), frozenset()) is None


def test_story_without_criteria_is_not_demoted():
    assert _unverified_finding((), frozenset()) is None


def test_no_criterion_ran_reports_unexamined():
    checks = (_result("a", passed=False, skipped=True),)
    assert _unverified_finding(checks, frozenset()) == UNEXAMINED_FINDING


def test_only_non_binding_passes_report_non_binding():
    checks = (_result("a", passed=True, binding=False),)
    assert _unverified_finding(checks, frozenset()) == NON_BINDING_FINDING


def test_only_prepassed_binding_passes_report_prepassed():
    checks = (_result("a", passed=True), _result("b", passed=True, binding=False))
    assert _unverified_finding(checks, frozenset({"a"})) == PREPASSED_FINDING


def test_one_fresh_binding_pass_verifies_beside_prepassed():
    checks = (_result("a", passed=True), _result("b", passed=True))
    assert _unverified_finding(checks, frozenset({"a"})) is None


def test_disputed_never_drives_repair():
    assert not _drives_repair(_result("a", passed=False, binding=False))
    assert _drives_repair(_result("a", passed=False))
    assert _drives_repair(_result("a", passed=False, skipped=True, binding=False))
    assert not _drives_repair(_result("a", passed=True))


def test_progress_view_ignores_non_binding_and_unverified():
    acceptance = (
        _result("a", passed=True),
        _result("b", passed=True, binding=False),
        _result("c", passed=False, skipped=True),
    )
    executed, passed, _ = _binding_progress_view(acceptance)
    assert executed == ("a",)
    assert passed == ("a",)


def test_non_binding_flip_is_not_progress():
    previous = _record(executed=("a",), passed=())
    acceptance = (_result("a", passed=False), _result("b", passed=True, binding=False))
    assert _acceptance_progress(previous, acceptance) == (False, False)


def test_binding_superset_is_progress():
    previous = _record(executed=("a", "b"), passed=("a",))
    acceptance = (_result("a", passed=True), _result("b", passed=True))
    assert _acceptance_progress(previous, acceptance) == (True, False)


def test_changed_executed_set_is_not_progress():
    # "b" settled UNVERIFIED last pass; it running now is not movement on the product.
    previous = _record(executed=("a",), passed=("a",))
    acceptance = (_result("a", passed=True), _result("b", passed=True))
    assert _acceptance_progress(previous, acceptance) == (False, False)


def test_first_pass_has_no_progress_signal():
    assert _acceptance_progress(None, (_result("a", passed=True),)) == (False, False)

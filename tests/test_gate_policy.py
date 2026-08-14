"""Unit tests for the release gate fold."""

from __future__ import annotations

import pytest

from drydock.gate_policy import (
    ERROR,
    FAILED,
    MANUAL,
    MET,
    NOT_MET,
    PASSED,
    GateOutcome,
    RunFacts,
    TrialFacts,
    fold,
    settle_trial,
)


def trial(criterion_id: str, **kwargs) -> TrialFacts:
    return TrialFacts(criterion_id=criterion_id, **kwargs)


def test_rejects_an_unknown_trial_verdict():
    with pytest.raises(ValueError):
        TrialFacts(criterion_id="st-001", graded="INCONCLUSIVE")


def test_pending_is_not_a_trial_verdict():
    """PENDING was doing two jobs — a criterion no machine can settle, and a project that is not
    built yet — and one word for both is how a finished project read as though it had questions."""
    with pytest.raises(ValueError):
        TrialFacts(criterion_id="st-001", graded="PENDING")


def test_all_met_passes_and_exits_zero():
    outcome = fold(RunFacts("T", (trial("st-001", graded=MET), trial("st-002", graded=MET))))
    assert outcome.verdict == PASSED
    assert outcome.exit_code == 0


def test_a_manual_criterion_attests_and_does_not_withhold_the_pass():
    outcome = fold(RunFacts("T", (trial("st-001", graded=MET), trial("st-002", graded=MANUAL))))
    assert outcome.verdict == PASSED
    assert outcome.exit_code == 0
    assert outcome.ids_with(MANUAL) == ("st-002",)


def test_one_not_met_fails_the_run():
    outcome = fold(
        RunFacts(
            "T",
            (
                trial("st-001", graded=MANUAL),
                trial("st-002", graded=NOT_MET, citations=("suite=FAIL",)),
            ),
        )
    )
    assert outcome.verdict == FAILED
    assert outcome.exit_code == 1


def test_not_met_without_a_citation_becomes_manual():
    """NOT MET requires the grader to have looked and to cite what it saw. A verdict with no
    citation reports on the grader's own blindness, not on the product."""
    outcome = settle_trial(trial("st-001", graded=NOT_MET))
    assert outcome.verdict == MANUAL
    assert "did not look" in outcome.basis


def test_not_met_with_a_citation_survives():
    outcome = settle_trial(trial("st-001", graded=NOT_MET, citations=("app/templates/ is empty",)))
    assert outcome.verdict == NOT_MET


def test_an_unbuilt_capability_is_a_demonstration_and_fails():
    """Seeing nothing where something was required is looking. An unbuilt criterion gets an F,
    which is what retiring PENDING is for."""
    outcome = fold(
        RunFacts("T", (trial("st-001", graded=NOT_MET, citations=("probe: GET / → 404",)),))
    )
    assert outcome.verdict == FAILED


def test_a_deterministic_failure_cannot_be_argued_away():
    outcome = settle_trial(
        trial("st-001", graded=MET, demonstrated_failure="126 red conformance cases")
    )
    assert outcome.verdict == NOT_MET
    assert "126 red conformance cases" in outcome.basis


def test_a_governed_gate_pass_pins_met_over_a_manual_grade():
    outcome = settle_trial(trial("st-001", graded=MANUAL, governed_pass=True))
    assert outcome.verdict == MET
    assert outcome.basis == "governed gate passed"


def test_a_demonstrated_failure_outranks_a_governed_pass():
    outcome = settle_trial(
        trial("st-001", graded=MET, governed_pass=True, demonstrated_failure="red case")
    )
    assert outcome.verdict == NOT_MET


def test_a_guardrail_is_graded_exactly_like_any_other_criterion():
    """Type: guardrail is reporting metadata. It must not acquire an inference ban, a separate
    vocabulary, or absolute-prohibition logic."""
    ordinary = settle_trial(trial("st-001", graded=MANUAL))
    guard = settle_trial(trial("st-001", graded=MANUAL, guardrail=True))
    assert ordinary.verdict == guard.verdict == MANUAL
    assert ordinary.basis == guard.basis


def test_a_run_level_demonstrated_failure_fails_the_run():
    """A governed acceptance gate that ran and came back red is a product failure that binds to
    no single criterion. It still fails the run."""
    outcome = fold(
        RunFacts(
            "T",
            (trial("st-001", graded=MET),),
            demonstrated_failures=("Governed acceptance gate failed: full exited 1",),
        )
    )
    assert outcome.verdict == FAILED
    assert "Governed acceptance gate failed" in outcome.statement


def test_hygiene_is_reported_and_never_reaches_the_verdict():
    outcome = fold(
        RunFacts(
            "T",
            (trial("st-001", graded=MET),),
            reported=("Build directory has uncommitted changes",),
        )
    )
    assert outcome.verdict == PASSED
    assert outcome.reported == ("Build directory has uncommitted changes",)
    assert "uncommitted" in outcome.statement


def test_error_is_computed_first_and_claims_nothing_about_the_product():
    outcome = fold(
        RunFacts(
            "T",
            (trial("st-001", graded=NOT_MET, citations=("x=FAIL",)),),
            kit_faults=("Staged build asset was modified: bin/test.sh",),
        )
    )
    assert outcome.verdict == ERROR
    assert outcome.exit_code == 1
    assert outcome.trials == ()
    assert "says nothing about the product" in outcome.statement


def test_no_criteria_at_all_passes_vacuously():
    assert fold(RunFacts("T")).verdict == PASSED


def test_the_statement_lists_every_criterion_and_what_was_observed():
    outcome = fold(
        RunFacts(
            "ReadingList",
            (
                trial("st-001", graded=MET, citations=("app/main.py:3 imports Flask",)),
                trial("st-002", graded=NOT_MET, citations=("probe: GET / → 404",)),
            ),
        )
    )
    lines = outcome.statement.splitlines()
    assert lines[0] == "ReadingList: FAILED — 1 of 2"
    assert "st-001  MET       app/main.py:3 imports Flask" in outcome.statement
    assert "st-002  NOT MET   probe: GET / → 404" in outcome.statement


def test_exit_code_covers_every_terminal_verdict():
    for verdict, expected in ((PASSED, 0), (FAILED, 1), (ERROR, 1)):
        assert GateOutcome("T", verdict).exit_code == expected

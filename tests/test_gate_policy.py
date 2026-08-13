"""Unit tests for the release gate fold."""

from __future__ import annotations

import pytest

from drydock.gate_policy import (
    ERROR,
    FAILED,
    MET,
    NOT_MET,
    PASSED,
    PENDING,
    PENDING_MANUAL_VERIFICATION,
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


def test_all_met_passes_and_exits_zero():
    outcome = fold(RunFacts("T", (trial("st-001", graded=MET), trial("st-002", graded=MET))))
    assert outcome.verdict == PASSED
    assert outcome.exit_code == 0


def test_one_pending_yields_pending_manual_verification_and_exits_zero():
    outcome = fold(RunFacts("T", (trial("st-001", graded=MET), trial("st-002", graded=PENDING))))
    assert outcome.verdict == PENDING_MANUAL_VERIFICATION
    assert outcome.exit_code == 0
    assert outcome.ids_with(PENDING) == ("st-002",)


def test_a_demonstrated_failure_dominates_pending():
    outcome = fold(
        RunFacts(
            "T",
            (
                trial("st-001", graded=PENDING),
                trial("st-002", graded=NOT_MET, citations=("suite=FAIL",)),
            ),
        )
    )
    assert outcome.verdict == FAILED
    assert outcome.exit_code == 1


def test_not_met_without_a_citation_becomes_pending():
    """Absence of evidence yields PENDING, never NOT MET. Drydock fails a project by exhibiting
    a failure, and 'I have no proof it holds' is not a demonstration."""
    outcome = settle_trial(trial("st-001", graded=NOT_MET))
    assert outcome.verdict == PENDING
    assert "without citing" in outcome.basis


def test_not_met_with_a_citation_survives():
    outcome = settle_trial(trial("st-001", graded=NOT_MET, citations=("FEATURE.md:check=FAIL",)))
    assert outcome.verdict == NOT_MET


def test_a_deterministic_failure_cannot_be_argued_away():
    outcome = settle_trial(
        trial("st-001", graded=MET, demonstrated_failure="126 red conformance cases")
    )
    assert outcome.verdict == NOT_MET
    assert "126 red conformance cases" in outcome.basis


def test_a_governed_gate_pass_pins_met_over_a_pending_grade():
    outcome = settle_trial(trial("st-001", graded=PENDING, governed_pass=True))
    assert outcome.verdict == MET
    assert outcome.basis == "governed gate passed"


def test_a_demonstrated_failure_outranks_a_governed_pass():
    outcome = settle_trial(
        trial("st-001", graded=MET, governed_pass=True, demonstrated_failure="red case")
    )
    assert outcome.verdict == NOT_MET


def test_a_guardrail_is_graded_exactly_like_any_other_criterion():
    """Type: guardrail is reporting metadata. An unproven prohibition is an open question, and
    it must not acquire an inference ban, a separate vocabulary, or absolute-prohibition logic."""
    ordinary = settle_trial(trial("st-001", graded=PENDING))
    guard = settle_trial(trial("st-001", graded=PENDING, guardrail=True))
    assert ordinary.verdict == guard.verdict == PENDING
    assert ordinary.basis == guard.basis


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


def test_statement_counts_met_criteria():
    outcome = fold(
        RunFacts("ReadingList", (trial("st-001", graded=MET), trial("st-002", graded=PENDING)))
    )
    assert outcome.statement.splitlines()[0] == (
        "ReadingList: PENDING MANUAL VERIFICATION — 1 of 2 project criteria met"
    )


def test_exit_code_covers_every_terminal_verdict():
    for verdict, expected in (
        (PASSED, 0),
        (PENDING_MANUAL_VERIFICATION, 0),
        (FAILED, 1),
        (ERROR, 1),
    ):
        assert GateOutcome("T", verdict).exit_code == expected

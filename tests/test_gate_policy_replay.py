"""Policy replay of the release gate over the recorded UAT corpus.

The corpus is 18 runs of three fixtures produced over six days by materially different software.
Their recorded verdicts are not comparable across versions, but their evidence is, and the gate is
a pure function over evidence — so the corpus is replayable as policy, and every subsequent change
to the fold is validated against 18 runs at zero token cost instead of against one fresh run.

The frozen facts live in ``tests/fixtures/uat_corpus.json`` because ``uat/*/runs/`` is not
committed. ``test_frozen_corpus_matches_the_live_corpus`` re-extracts from the live runs when they
are present, so the freeze cannot silently drift from what actually happened.
"""

from __future__ import annotations

import pytest
from uat_corpus import (
    LIVE_CORPUS_ROOT,
    extract_run_facts,
    facts_to_dict,
    iter_live_runs,
    load_corpus,
)

from drydock.gate_policy import (
    FAILED,
    MET,
    NOT_MET,
    PASSED,
    PENDING,
    PENDING_MANUAL_VERIFICATION,
    RunFacts,
    TrialFacts,
    fold,
)

CORPUS = load_corpus()
SCORED = [entry for entry in CORPUS if entry["reached_gate"]]


def test_the_corpus_is_the_whole_recorded_record():
    assert len(CORPUS) == 18
    assert len(SCORED) == 10
    assert {entry["fixture"] for entry in CORPUS} == {"CommonMark", "ReadingList", "Toml"}


def test_a_run_that_never_reached_the_gate_offers_no_facts():
    """Eight runs failed in plan or build. They carry no gate verdict at all — which is a
    different statement from a product failure, and the distinction the run record could not make
    without reading logs."""
    unscored = [entry for entry in CORPUS if not entry["reached_gate"]]
    assert len(unscored) == 8
    assert all(entry["facts"] is None for entry in unscored)
    assert all(entry["expected_verdict"] is None for entry in unscored)


@pytest.mark.parametrize("entry", SCORED, ids=[f"{e['fixture']}-{e['run_id']}" for e in SCORED])
def test_replay_produces_the_expected_verdict(entry):
    outcome = fold(entry["facts"])
    assert outcome.verdict == entry["expected_verdict"], entry["note"]


def _entry(fixture: str, run_id: str) -> dict:
    return next(e for e in SCORED if e["fixture"] == fixture and e["run_id"] == run_id)


def test_readinglist_20260813_reports_honestly():
    """The run that motivated the model. 26 of 26 assertions passed and every criterion but one
    was met; the one exception is a prohibition the grader declined to infer. The recorded run
    reported FAILED and exited 1, on that plus an uncommitted build directory."""
    outcome = fold(_entry("ReadingList", "20260813.160121")["facts"])
    assert outcome.verdict == PENDING_MANUAL_VERIFICATION
    assert outcome.exit_code == 0
    assert outcome.ids_with(PENDING) == ("st-008",)
    assert outcome.ids_with(NOT_MET) == ()
    assert "Build directory has uncommitted changes" in outcome.reported


def test_commonmark_20260812_passes_with_an_open_manifest_block():
    outcome = fold(_entry("CommonMark", "20260812.171514")["facts"])
    assert outcome.verdict == PASSED
    assert any("Manifest work is not closed" in note for note in outcome.reported)


def test_every_failed_replay_names_a_cited_artifact():
    """The corpus check on the asymmetry rule: no run in six days of recorded history fails
    without an artifact exhibiting the failure."""
    for entry in SCORED:
        outcome = fold(entry["facts"])
        if outcome.verdict != FAILED:
            continue
        failed = [item for item in outcome.trials if item.verdict == NOT_MET]
        assert failed
        assert all(item.citations for item in failed), entry["run_id"]


def test_no_recorded_run_was_unjudgeable():
    assert all(not entry["facts"].kit_faults for entry in SCORED)


def test_hygiene_alone_never_decides_a_replayed_verdict():
    """Six of the ten scored runs carried a hygiene or plan-state blocker. Stripping them changes
    no verdict, which is what makes removing them from the release path safe."""
    carried = [entry for entry in SCORED if entry["facts"].reported]
    assert len(carried) >= 6
    for entry in carried:
        stripped = RunFacts(entry["facts"].target, entry["facts"].trials)
        assert fold(stripped).verdict == fold(entry["facts"]).verdict


# --- UC-008: a completed product that is genuinely defective -------------------------------
#
# Across 18 runs there is no such case. Every failure was a stall, a gate, a criterion, or Drydock
# itself, so nothing in the recorded record constrains the model against becoming a rubber stamp.
# The corpus cannot supply the case, so it is constructed.


def _uc008_facts() -> RunFacts:
    """A finished build: Manifest closed, hygiene clean, automated acceptance green in aggregate,
    and one criterion with a check that demonstrably fails."""
    return RunFacts(
        target="UC008",
        trials=(
            TrialFacts("st-001", graded=MET, citations=("FEATURE-Add.md:add-round-trip=PASS",)),
            TrialFacts("st-002", graded=MET, citations=("FEATURE-List.md:list-order=PASS",)),
            TrialFacts(
                "st-003",
                graded=NOT_MET,
                citations=("FEATURE-Remove.md:remove-round-trip=FAIL",),
                criterion="A removed book does not appear on a subsequent read.",
            ),
        ),
    )


def test_uc008_a_completed_but_defective_product_reports_failed():
    outcome = fold(_uc008_facts())
    assert outcome.verdict == FAILED
    assert outcome.exit_code == 1
    assert outcome.ids_with(NOT_MET) == ("st-003",)


def test_uc008_a_grader_cannot_reason_a_red_case_back_to_met():
    """The rubber-stamp guard. Deterministic evidence is monotonic downward only: the grader may
    move PENDING to MET, and may never move a demonstrated failure to MET."""
    facts = _uc008_facts()
    optimistic = RunFacts(
        facts.target,
        tuple(
            TrialFacts(
                criterion_id=item.criterion_id,
                graded=MET,
                citations=item.citations,
                demonstrated_failure=(
                    "remove-round-trip exited 1" if item.criterion_id == "st-003" else ""
                ),
            )
            for item in facts.trials
        ),
    )
    outcome = fold(optimistic)
    assert outcome.verdict == FAILED
    assert outcome.ids_with(NOT_MET) == ("st-003",)


def test_uc008_defect_hidden_behind_a_governed_gate_pass_still_fails():
    facts = _uc008_facts()
    with_gate = RunFacts(
        facts.target,
        tuple(
            TrialFacts(
                criterion_id=item.criterion_id,
                graded=item.graded,
                citations=item.citations,
                governed_pass=True,
                demonstrated_failure=(
                    "remove-round-trip exited 1" if item.criterion_id == "st-003" else ""
                ),
            )
            for item in facts.trials
        ),
    )
    assert fold(with_gate).verdict == FAILED


def test_uc008_without_the_defect_passes():
    """The control: the same run with the failing check green must pass, or the case above proves
    only that the fold is pessimistic."""
    facts = _uc008_facts()
    clean = RunFacts(
        facts.target,
        tuple(
            TrialFacts(item.criterion_id, graded=MET, citations=("check=PASS",))
            for item in facts.trials
        ),
    )
    assert fold(clean).verdict == PASSED


# --- freeze integrity ----------------------------------------------------------------------


@pytest.mark.skipif(
    not list(LIVE_CORPUS_ROOT.glob("*/runs/*/result.json")),
    reason="uat/*/runs is not committed; the frozen corpus is authoritative here",
)
def test_frozen_corpus_matches_the_live_corpus():
    live = {
        (fixture, run_id): (None if record is None else extract_run_facts(record, target=fixture))
        for fixture, run_id, record in iter_live_runs()
    }
    frozen = {(entry["fixture"], entry["run_id"]): entry["facts"] for entry in CORPUS}
    assert set(live) == set(frozen), "regenerate with: python tests/uat_corpus.py"
    for key, facts in live.items():
        if facts is None:
            assert frozen[key] is None
        else:
            assert facts_to_dict(facts) == facts_to_dict(frozen[key])

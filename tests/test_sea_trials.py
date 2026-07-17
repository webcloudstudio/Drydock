"""Tests for structured project acceptance in SEA_TRIALS.md."""

from __future__ import annotations

import json

from drydock.sea_trials import parse_sea_trials_text, project_questions


def test_parses_structured_trial_and_questions():
    document = parse_sea_trials_text(
        """# Sea Trials: Demo

## st-latency: Fast response
Type: outcome
Required: yes
Criterion: Median response time is at most 100 ms.
Verification: measurement
Command: ["python", "measure.py"]
Baseline: 180
Operator: <=
Target: 100
Unit: ms

QUESTIONS:
- q-latency-baseline: Which representative workload defines the baseline?
"""
    )

    trial = document.trials[0]
    assert trial.criterion_id == "st-latency"
    assert trial.command == ("python", "measure.py")
    assert trial.baseline == 180
    assert trial.target == 100
    assert document.questions[0].question_id == "q-latency-baseline"


def test_legacy_table_is_imported_as_qualitative_acceptance():
    document = parse_sea_trials_text(
        """# Sea Trials: Demo

| ID | Criterion | Method | Evidence |
|---|---|---|---|
| st-001 | Navigation is clear | Review | screenshot.md |
"""
    )

    assert document.trials[0].trial_type == "qualitative"
    assert document.trials[0].verification == "llm"


def test_projects_questions_and_preserves_answers(tmp_path):
    path = tmp_path / "discovery-sea-trials.json"
    path.write_text(
        json.dumps({"questions": [{"id": "q-one", "answer": "Known workload"}]}),
        encoding="utf-8",
    )
    document = parse_sea_trials_text(
        """# Sea Trials: Demo

## st-one: One
Type: qualitative
Required: yes
Criterion: The workflow is understandable.
Verification: llm

QUESTIONS:
- q-one: Which workload applies?
"""
    )

    project_questions(document, path)

    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["state"] == "answered"
    assert payload["questions"][0]["answer"] == "Known workload"

"""Tests for structured project acceptance in SEA_TRIALS.md."""

from __future__ import annotations

import json

import pytest

from drydock.errors import SpecificationError
from drydock.sea_trials import (
    EARS_PATTERNS,
    normalize_sea_trials_text,
    parse_sea_trials_text,
    project_questions,
)


def _trial(**fields: str) -> str:
    body = "".join(f"{key.replace('_', ' ').title()}: {value}\n" for key, value in fields.items())
    return f"# Sea Trials: Demo\n\n## st-001: Example\n{body}"


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


@pytest.mark.parametrize(
    ("pattern", "criterion"),
    [
        ("ubiquitous", "The system shall record every order."),
        ("event", "When an order is placed, the system shall record it."),
        ("state", "While the queue is draining, the system shall reject new orders."),
        ("option", "Where audit logging is enabled, the system shall record every order."),
        ("unwanted", "If the payload contains personal data, then the system shall omit it."),
    ],
)
def test_each_ears_pattern_is_accepted(pattern, criterion):
    document = parse_sea_trials_text(
        _trial(
            type="technical",
            required="yes",
            criterion=criterion,
            verification="proof",
            pattern=pattern,
        )
    )

    assert document.trials[0].pattern == pattern


def test_every_ears_pattern_is_covered_by_a_test():
    assert set(EARS_PATTERNS) == {"ubiquitous", "event", "state", "option", "unwanted"}


def test_criterion_not_matching_its_declared_pattern_is_rejected():
    with pytest.raises(SpecificationError, match="does not match the event EARS pattern"):
        parse_sea_trials_text(
            _trial(
                type="behavioral",
                required="yes",
                criterion="Orders get recorded eventually.",
                verification="proof",
                pattern="event",
            )
        )


def test_assertion_type_without_a_pattern_is_rejected():
    with pytest.raises(SpecificationError, match="is missing Pattern"):
        parse_sea_trials_text(
            _trial(
                type="technical",
                required="yes",
                criterion="The system shall record orders.",
                verification="proof",
            )
        )


def test_qualitative_criterion_must_not_declare_a_pattern():
    with pytest.raises(SpecificationError, match="must not declare a Pattern"):
        parse_sea_trials_text(
            _trial(
                type="qualitative",
                required="yes",
                criterion="The workflow is understandable.",
                verification="llm",
                pattern="ubiquitous",
            )
        )


def test_guardrail_must_use_the_unwanted_pattern():
    with pytest.raises(SpecificationError, match="must use Pattern: unwanted"):
        parse_sea_trials_text(
            _trial(
                type="guardrail",
                required="yes",
                criterion="The system shall omit personal data.",
                verification="evidence",
                pattern="ubiquitous",
            )
        )


def test_documentation_prose_does_not_overwrite_the_preceding_criterion_fields():
    """An h3 block ends a criterion. Without that, `Type:` prose would rewrite the real field."""
    document = parse_sea_trials_text(
        """# Sea Trials: Demo

## st-001: Example
Type: behavioral
Required: yes
Criterion: When an order is placed, the system shall record it.
Verification: proof
Pattern: event

### Fields
Type: this field declares the category.
Verification: llm means independent judgment.
"""
    )

    trial = document.trials[0]
    assert trial.trial_type == "behavioral"
    assert trial.verification == "proof"


def test_normalization_replaces_stale_documentation_and_is_idempotent():
    source = """# Sea Trials: Demo

### Stale heading
Text a previous version embedded.

## st-001: Example
Type: qualitative
Required: yes
Criterion: The workflow is understandable.
Verification: llm
"""

    normalized = normalize_sea_trials_text(source)

    assert "Stale heading" not in normalized
    assert "### Notation — EARS" in normalized
    assert normalized.startswith("# Sea Trials: Demo")
    assert normalize_sea_trials_text(normalized) == normalized
    assert parse_sea_trials_text(normalized).trials[0].criterion_id == "st-001"


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

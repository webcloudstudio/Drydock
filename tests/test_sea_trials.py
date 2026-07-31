"""Tests for structured project acceptance in SEA_TRIALS.md."""

from __future__ import annotations

import json

import pytest

from drydock.errors import SpecificationError
from drydock.sea_trials import (
    EARS_PATTERNS,
    is_stack_selection_question,
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


@pytest.mark.parametrize(
    ("question_id", "text"),
    [
        ("q-st-001-stack", "Which representative workload defines the baseline?"),
        ("q-st-001-baseline", "Select the applicable Rigging stack components before planning."),
        ("q-st-002-baseline", "Choose the stack components that apply."),
    ],
)
def test_stack_selection_questions_are_detected(question_id, text):
    assert is_stack_selection_question(question_id, text) is True


@pytest.mark.parametrize(
    ("question_id", "text"),
    [
        ("q-latency-baseline", "Which representative workload defines the baseline?"),
        ("q-st-001-target", "What throughput target is required at launch?"),
    ],
)
def test_measurement_questions_are_not_treated_as_stack(question_id, text):
    assert is_stack_selection_question(question_id, text) is False


def test_stack_question_is_dropped_from_parsed_questions():
    document = parse_sea_trials_text(
        """# Sea Trials: Demo

## st-001: Full conformance
Type: outcome
Required: yes
Criterion: The parser passes every case in the full conformance test suite.
Verification: proof
Command: ["python", "run.py"]

QUESTIONS:
- q-st-001-baseline: Which test-suite edition defines the baseline?
- q-st-001-stack: Select the applicable Rigging stack components before planning.
"""
    )

    ids = [question.question_id for question in document.questions]
    assert ids == ["q-st-001-baseline"]


def test_stack_question_is_stripped_from_normalized_text():
    normalized = normalize_sea_trials_text(
        """# Sea Trials: Demo

## st-001: Full conformance
Type: outcome
Required: yes
Criterion: The parser passes every case in the full conformance test suite.
Verification: proof
Command: ["python", "run.py"]

QUESTIONS:
- q-st-001-stack: Select the applicable Rigging stack components before planning.
"""
    )

    assert "q-st-001-stack" not in normalized
    # The bare QUESTIONS: block header is dropped once its only question is removed. The prose
    # mention inside the canonical reader documentation is not a block header.
    assert not any(line.strip() == "QUESTIONS:" for line in normalized.splitlines())


def test_trial_after_questions_block_is_parsed():
    document = parse_sea_trials_text(
        """# Sea Trials: Demo

## st-001: First
Type: technical
Required: yes
Criterion: When the system starts, the system shall log a ready message.
Verification: proof
Pattern: event
QUESTIONS:
- q-st-001-target: Which environment defines the baseline?

## st-002: Second
Type: technical
Required: yes
Criterion: When the system stops, the system shall flush its buffers.
Verification: proof
Pattern: event
"""
    )

    assert [trial.criterion_id for trial in document.trials] == ["st-001", "st-002"]
    assert document.questions[0].question_id == "q-st-001-target"


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
    assert document.trials[0].notation == "ears"


def test_every_ears_pattern_is_covered_by_a_test():
    assert set(EARS_PATTERNS) == {"ubiquitous", "event", "state", "option", "unwanted"}


@pytest.mark.parametrize(
    ("pattern", "criterion"),
    [
        ("ubiquitous", "Marina shall register every repository beneath PROJECTS_DIR."),
        ("event", "When a user registers a repository, Marina shall present the project."),
        ("state", "While a scan is running, Marina shall reject a second scan."),
        ("option", "Where AWS is configured, Marina shall report backend health."),
        ("unwanted", "If a remote carries a credential, then Marina shall redact it."),
    ],
)
def test_proper_noun_system_notates_ears(pattern, criterion):
    # A proper-noun system name takes no article. Requiring the literal "the" classified correct
    # EARS as non-conforming and drove a wasted repair pass on Marina's Sea Trials.
    document = parse_sea_trials_text(
        _trial(
            type="behavioral",
            required="yes",
            criterion=criterion,
            verification="proof",
            pattern=pattern,
        )
    )

    assert document.trials[0].notation == "ears"


def test_criterion_not_matching_its_declared_pattern_notates_other():
    # Notation describes; it never blocks. The criterion stands exactly as written.
    document = parse_sea_trials_text(
        _trial(
            type="behavioral",
            required="yes",
            criterion="Orders get recorded eventually.",
            verification="proof",
            pattern="event",
        )
    )

    trial = document.trials[0]
    assert trial.criterion == "Orders get recorded eventually."
    assert trial.pattern == "event"
    assert trial.notation == "other"


def test_unrecognized_pattern_name_notates_other_without_raising():
    document = parse_sea_trials_text(
        _trial(
            type="technical",
            required="yes",
            criterion="The system shall record orders.",
            verification="proof",
            pattern="whenever",
        )
    )

    trial = document.trials[0]
    assert trial.pattern == ""
    assert trial.notation == "other"


def test_assertion_type_without_a_pattern_notates_other():
    document = parse_sea_trials_text(
        _trial(
            type="technical",
            required="yes",
            criterion="Conversion completes without manual intervention.",
            verification="proof",
        )
    )

    assert document.trials[0].notation == "other"


def test_qualitative_criterion_may_declare_a_pattern():
    # Pattern is decorative on every type: it is notated from conformance, never rejected.
    document = parse_sea_trials_text(
        _trial(
            type="qualitative",
            required="yes",
            criterion="The workflow is understandable.",
            verification="llm",
            pattern="ubiquitous",
        )
    )

    assert document.trials[0].trial_type == "qualitative"
    # The prose carries no `shall`, so it does not match the pattern it names: `other`, not an error.
    assert document.trials[0].notation == "other"


def test_positive_ubiquitous_guardrail_is_accepted():
    # Whether a guardrail reads as a prohibition is editorial, judged by the scoring prompt. It is
    # not a notation question: this sentence matches its declared pattern, so it is `ears`.
    document = parse_sea_trials_text(
        _trial(
            type="guardrail",
            required="yes",
            criterion="The system shall omit personal data.",
            verification="evidence",
            pattern="ubiquitous",
        )
    )

    assert document.trials[0].trial_type == "guardrail"
    assert document.trials[0].notation == "ears"


def test_negative_ubiquitous_guardrail_is_accepted():
    # An unconditional blanket prohibition has no trigger; it reads naturally as a negative
    # ubiquitous criterion ("The <system> shall not/never <X>") and must validate.
    document = parse_sea_trials_text(
        _trial(
            type="guardrail",
            required="yes",
            criterion=(
                "The filter shall not modify files, persist state, or make network calls "
                "while converting input."
            ),
            verification="proof",
            pattern="ubiquitous",
        )
    )
    assert document.trials[0].trial_type == "guardrail"
    assert document.trials[0].pattern == "ubiquitous"


def test_conditional_unwanted_guardrail_is_accepted():
    document = parse_sea_trials_text(
        _trial(
            type="guardrail",
            required="yes",
            criterion="If personal data is logged, then the system shall omit it.",
            verification="proof",
            pattern="unwanted",
        )
    )
    assert document.trials[0].pattern == "unwanted"


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

### Guardrails
A guardrail is permanent.
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
    assert "### Guardrails" in normalized
    assert "### Notation — EARS" not in normalized
    assert "### Types" not in normalized
    assert "### Fields" not in normalized
    assert normalized.startswith("# Sea Trials: Demo")
    assert normalize_sea_trials_text(normalized) == normalized
    assert parse_sea_trials_text(normalized).trials[0].criterion_id == "st-001"


def test_normalization_formats_populated_fields_on_aligned_lines():
    normalized = normalize_sea_trials_text(
        """# Sea Trials: Demo

## st-001: Privacy
Type: guardrail Required: yes Criterion: If personal data is logged, then the system shall omit it. Verification: proof Pattern: unwanted Command: Evidence: Baseline: Operator: Target: Unit:
"""
    )

    assert "Type:      guardrail" in normalized
    assert "Required:  yes" in normalized
    assert "Criterion: If personal data is logged, then the system shall omit it." in normalized
    assert "Verification: proof" in normalized
    assert "Pattern:   unwanted" in normalized
    assert "Notation:  ears" in normalized
    assert "Command:" not in normalized


def test_normalization_writes_derived_notation_over_an_authored_value():
    # Notation is Drydock's field. A model-authored or hand-edited value is always replaced by the
    # value derived from the criterion's own Pattern and prose.
    normalized = normalize_sea_trials_text(
        """# Sea Trials: Demo

## st-001: Example
Type: behavioral
Required: yes
Criterion: Orders get recorded eventually.
Verification: proof
Pattern: event
Notation: ears
"""
    )

    assert "Notation:  other" in normalized
    assert "Notation:  ears" not in normalized
    assert normalize_sea_trials_text(normalized) == normalized
    assert parse_sea_trials_text(normalized).trials[0].notation == "other"


def test_normalization_notates_a_criterion_that_declares_no_pattern():
    normalized = normalize_sea_trials_text(
        """# Sea Trials: Demo

## st-001: Example
Type: qualitative
Required: no
Criterion: Browsing 200 projects stays responsive on a laptop.
Verification: llm
"""
    )

    assert "Notation:  other" in normalized
    assert normalize_sea_trials_text(normalized) == normalized


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


def test_projection_preserves_commander_notes_and_resolution(tmp_path):
    path = tmp_path / "discovery-sea-trials.json"
    path.write_text(
        json.dumps({
            "questions": [{"id": "q-one", "answer": "Known workload"}],
            "resolution": "Commander accepted",
            "additional_notes": "Measured against the 2026 baseline.",
        }),
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
    assert payload["resolution"] == "Commander accepted"
    assert payload["additional_notes"] == "Measured against the 2026 baseline."


def test_answered_projection_survives_a_rerun_without_questions(tmp_path):
    """A regenerated SEA_TRIALS.md must not delete answers the Commander already gave."""
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
"""
    )

    assert project_questions(document, path) == path
    assert json.loads(path.read_text(encoding="utf-8"))["questions"][0]["answer"] == (
        "Known workload"
    )


def test_unanswered_projection_is_removed_when_questions_disappear(tmp_path):
    path = tmp_path / "discovery-sea-trials.json"
    path.write_text(
        json.dumps({"questions": [{"id": "q-one", "answer": ""}]}),
        encoding="utf-8",
    )
    document = parse_sea_trials_text(
        """# Sea Trials: Demo

## st-one: One
Type: qualitative
Required: yes
Criterion: The workflow is understandable.
Verification: llm
"""
    )

    assert project_questions(document, path) is None
    assert not path.exists()


# ---------------------------------------------------------------------------
# Extract: and literal-argv Command:
# ---------------------------------------------------------------------------

_MEASUREMENT = """# Sea Trials: Demo

## st-004: Correctness score
Type: outcome
Required: yes
Criterion: The converter achieves the passing-example threshold.
Verification: measurement
Command: ["python3", "sources/spec_tests.py", "--spec", "sources/spec.txt"]
Extract: ^(\\d+) passed
Operator: >=
Target: 652
Unit: examples
"""


def test_extract_round_trips_through_parse():
    trial = parse_sea_trials_text(_MEASUREMENT).trials[0]

    assert trial.extract == r"^(\d+) passed"
    assert trial.command == ("python3", "sources/spec_tests.py", "--spec", "sources/spec.txt")
    assert trial.target == 652.0


def test_complete_suite_is_a_proof_gate_without_a_numeric_target():
    document = parse_sea_trials_text(
        """# Sea Trials: Demo

## st-conformance: Complete conformance
Type: outcome
Required: yes
Criterion: The converter passes every case in the supplied complete conformance suite.
Verification: proof
Command: ["python3", "sources/spec_tests.py", "--spec", "sources/spec.txt"]
"""
    )

    trial = document.trials[0]
    assert trial.verification == "proof"
    assert trial.command == ("python3", "sources/spec_tests.py", "--spec", "sources/spec.txt")
    assert trial.target is None


def test_complete_suite_measurement_is_rejected():
    text = """# Sea Trials: Demo

## st-conformance: Complete conformance
Type: outcome
Required: yes
Criterion: The converter passes every case in the supplied complete conformance suite.
Verification: measurement
Command: ["python3", "sources/spec_tests.py"]
Extract: ^(\\d+) passed
Operator: ==
Target: 652
Unit: examples
"""

    with pytest.raises(SpecificationError, match="complete-suite requirement.*Verification: proof"):
        parse_sea_trials_text(text)


def test_extract_is_optional():
    text = _MEASUREMENT.replace("Extract: ^(\\d+) passed\n", "")

    assert parse_sea_trials_text(text).trials[0].extract == ""


def test_invalid_extract_regex_is_rejected():
    text = _MEASUREMENT.replace("Extract: ^(\\d+) passed", "Extract: ^(\\d+ passed")

    with pytest.raises(SpecificationError, match="not a valid regular expression"):
        parse_sea_trials_text(text)


def test_extract_without_a_capture_group_is_rejected():
    text = _MEASUREMENT.replace("Extract: ^(\\d+) passed", "Extract: ^\\d+ passed")

    with pytest.raises(SpecificationError, match="must capture the measured value"):
        parse_sea_trials_text(text)


def test_command_placeholder_is_rejected():
    """Nothing resolves <candidate-command>; a placeholder silently never runs."""
    text = _MEASUREMENT.replace('"--spec", "sources/spec.txt"', '"<candidate-command>"')

    with pytest.raises(SpecificationError, match="literal argv"):
        parse_sea_trials_text(text)

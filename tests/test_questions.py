"""Canonical planning-question parsing, persistence, and story-local gates."""

from __future__ import annotations

import json

import pytest

from drydock.errors import SpecificationError
from drydock.manifest import DrydockManifest
from drydock.plan_feedback import (
    apply_manifest_dispositions,
    harvest_answered_questions,
    load_feedback,
    render_feedback_prompt,
    update_feedback_answer,
)
from drydock.question_gates import approve_story_questions, synchronize_manifest_question_gates
from drydock.questions import (
    answer_question,
    normalize_questions_first,
    parse_questions,
    validate_questions_document,
)


def _blueprint(
    *, status: str = "open", answer: str = "", body: str = "## Behavior\n\nDo it.\n"
) -> str:
    answer_text = f"\n{answer}\n" if answer else "\n"
    return (
        "# FEATURE: Color\n\n"
        "| Field | Value |\n|---|---|\n| Type | FEATURE |\n\n"
        "## Questions\n\n"
        "### Q-001: Presentation color\n\n"
        "- Origin: plan\n"
        f"- Status: {status}\n\n"
        "#### Question\n\nWhat color should it be?\n\n"
        f"#### Answer\n{answer_text}\n"
        f"{body}"
    )


def _manifest() -> str:
    return """# MANIFEST: Demo
state: approved

## feature 1: Delivery
id: delivery
summary: Deliver the product.
state: pending

## story 1: Color
id: color
parent: delivery
summary: Apply the presentation color.
implements: FEATURE-Color.md, UI.md
instructions: Apply the Blueprint.
state: pending

## story 2: Independent
id: independent
parent: delivery
summary: Build unrelated behavior.
implements: FEATURE-Independent.md
instructions: Apply the Blueprint.
state: pending

## story 3: Consumer
id: consumer
summary: Consume color behavior.
implements: FEATURE-Consumer.md
instructions: Apply the Blueprint.
depends: color
state: pending
"""


def test_canonical_question_contract_and_first_section_normalization():
    text = _blueprint(body="## Behavior\n\nDo it.\n")
    question = validate_questions_document(text, require_first_section=True)[0]

    assert question.question_id == "Q-001"
    assert question.origin == "plan"
    assert question.status == "open"

    moved = text.replace("## Questions", "## Behavior\n\nDo it.\n\n## Questions", 1)
    with pytest.raises(SpecificationError, match="before every other"):
        validate_questions_document(moved, require_first_section=True)
    normalized = normalize_questions_first(moved)
    assert normalized.index("## Questions") < normalized.index("## Behavior")


@pytest.mark.parametrize("heading", ["## Open Questions", "## Question", "QUESTIONS:"])
def test_alternate_question_headings_are_rejected(heading):
    with pytest.raises(SpecificationError, match="non-canonical"):
        parse_questions(_blueprint().replace("## Questions", heading))


def test_answer_writes_authoritative_blueprint_and_ungates_story(tmp_path):
    target = tmp_path / "Demo"
    blueprint = target / "blueprint"
    blueprint.mkdir(parents=True)
    (target / "MANIFEST.md").write_text(_manifest(), encoding="utf-8")
    (blueprint / "FEATURE-Color.md").write_text(_blueprint(), encoding="utf-8")
    (blueprint / "UI.md").write_text(
        _blueprint(body="## UI\n\nRender it.\n").replace("Q-001", "Q-002"),
        encoding="utf-8",
    )
    for name in ("FEATURE-Independent.md", "FEATURE-Consumer.md"):
        (blueprint / name).write_text(
            _blueprint(status="answered", answer="Known.").replace("Q-001", f"Q-{name[:3]}"),
            encoding="utf-8",
        )

    plan = synchronize_manifest_question_gates(target / "MANIFEST.md", blueprint)
    color = plan.node("color")
    assert color.state == "blocked/questions"
    assert color.fields["questions"] == "2 open, 0 answered"
    assert [node.block_id for node in plan.buildable_steps()] == ["independent"]

    answer_question(blueprint / "FEATURE-Color.md", "Q-001", "Blue")
    answer_question(blueprint / "UI.md", "Q-002", "Navy")
    plan = synchronize_manifest_question_gates(target / "MANIFEST.md", blueprint)
    assert plan.node("color").state == "pending"
    assert plan.node("color").fields["questions"] == "0 open, 2 answered"
    assert [node.block_id for node in plan.buildable_steps()] == ["delivery"]


def test_manifest_approval_is_current_only_and_not_feedback(tmp_path):
    target = tmp_path / "Demo"
    blueprint = target / "blueprint"
    blueprint.mkdir(parents=True)
    (target / "MANIFEST.md").write_text(_manifest(), encoding="utf-8")
    (blueprint / "FEATURE-Color.md").write_text(_blueprint(), encoding="utf-8")

    synchronize_manifest_question_gates(target / "MANIFEST.md", blueprint)
    approved = approve_story_questions(target / "MANIFEST.md", "color")

    assert approved.node("color").state == "pending"
    assert approved.node("color").fields["questions_approved"] == "true"
    assert load_feedback(target) == ()


def test_answered_feedback_survives_blueprint_rename_and_requires_explicit_retirement(tmp_path):
    target = tmp_path / "Demo"
    blueprint = target / "blueprint"
    blueprint.mkdir(parents=True)
    original = blueprint / "FEATURE-Color.md"
    original.write_text(_blueprint(status="answered", answer="Blue"), encoding="utf-8")

    first = harvest_answered_questions(target)
    original.rename(blueprint / "SCREEN-Appearance.md")
    second = harvest_answered_questions(target)

    assert len(first) == len(second) == 1
    assert first[0].decision_id == second[0].decision_id
    assert second[0].source_blueprint == "blueprint/SCREEN-Appearance.md"
    assert second[0].subject == "Presentation color"
    assert "Decision: Blue" in render_feedback_prompt(second)

    retained = apply_manifest_dispositions(target, "")
    assert retained[0].status == "active"
    retired = apply_manifest_dispositions(
        target,
        f"{second[0].decision_id} retired Product no longer has a visual surface.",
    )
    assert retired[0].status == "retired"
    assert retired[0].reason == "Product no longer has a visual surface."


def test_answered_feedback_ignores_unformatted_imported_sources(tmp_path):
    target = tmp_path / "Demo"
    blueprint = target / "blueprint"
    sources = blueprint / "sources"
    sources.mkdir(parents=True)
    (blueprint / "FEATURE-Color.md").write_text(
        _blueprint(status="answered", answer="Blue"), encoding="utf-8"
    )
    (sources / "ARCHITECTURE.md").write_text(
        "# Architecture\n\n## Open Questions\n\nAnything can go here.\n",
        encoding="utf-8",
    )

    decisions = harvest_answered_questions(target)

    assert len(decisions) == 1
    assert decisions[0].source_blueprint == "blueprint/FEATURE-Color.md"


def test_realized_blueprint_remains_authoritative_after_source_rename(tmp_path):
    target = tmp_path / "Demo"
    blueprint = target / "blueprint"
    blueprint.mkdir(parents=True)
    source = blueprint / "FEATURE-Color.md"
    source.write_text(_blueprint(status="answered", answer="Blue"), encoding="utf-8")
    decision = harvest_answered_questions(target)[0]
    source.unlink()
    (blueprint / "SCREEN-Appearance.md").write_text(
        _blueprint(status="answered", answer="Blue"), encoding="utf-8"
    )
    apply_manifest_dispositions(
        target,
        f"{decision.decision_id} applied SCREEN-Appearance.md Presentation section",
    )

    with pytest.raises(ValueError, match="authoritative artifact"):
        update_feedback_answer(target, decision.decision_id, "Red")


def test_corrupt_feedback_store_is_never_silently_replaced(tmp_path):
    target = tmp_path / "Demo"
    path = target / "QuarterDeck" / "planning-feedback.json"
    path.parent.mkdir(parents=True)
    path.write_text("not json\n", encoding="utf-8")

    with pytest.raises(SpecificationError, match="Invalid persistent Plan feedback"):
        harvest_answered_questions(target)
    assert path.read_text(encoding="utf-8") == "not json\n"


def test_answered_analyze_questionnaire_enters_plan_feedback(tmp_path):
    target = tmp_path / "Demo"
    questionnaire_dir = target / "QuarterDeck" / "questionnaires"
    questionnaire_dir.mkdir(parents=True)
    (questionnaire_dir / "discovery-style.json").write_text(
        json.dumps({
            "questions": [
                {
                    "id": "presentation_color",
                    "label": "Presentation Color",
                    "prompt": "What color should it be?",
                    "answer": "Blue",
                }
            ]
        }),
        encoding="utf-8",
    )

    decisions = harvest_answered_questions(target)

    assert len(decisions) == 1
    assert decisions[0].origin == "analyze-questionnaire"
    assert decisions[0].subject == "Presentation Color"
    assert "Apply each" in render_feedback_prompt(decisions)


def test_transitive_dependent_is_not_buildable_when_question_owner_is_blocked(tmp_path):
    target = tmp_path / "Demo"
    blueprint = target / "blueprint"
    blueprint.mkdir(parents=True)
    (target / "MANIFEST.md").write_text(_manifest(), encoding="utf-8")
    (blueprint / "FEATURE-Color.md").write_text(_blueprint(), encoding="utf-8")
    for name in ("FEATURE-Independent.md", "FEATURE-Consumer.md"):
        (blueprint / name).write_text(
            _blueprint(status="answered", answer="Known."), encoding="utf-8"
        )

    plan = synchronize_manifest_question_gates(target / "MANIFEST.md", blueprint)

    assert plan.node("color").state == "blocked/questions"
    assert plan.node("consumer").state == "pending"
    assert tuple(node.block_id for node in plan.buildable_steps()) == ("independent",)
    reloaded = DrydockManifest.load(target / "MANIFEST.md", compatibility=True)
    assert reloaded.node("color").state == "blocked/questions"

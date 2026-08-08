"""Canonical planning-question parsing, persistence, and story-local gates."""

from __future__ import annotations

import json

import pytest

from drydock.decisions import Decision, load_decisions, write_decisions
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


def _decision(
    decision_id: str, story: str, *, severity: str = "blocking", answer: str = ""
) -> Decision:
    return Decision(
        id=decision_id,
        type="text",
        severity=severity,
        origin="plan",
        blueprint="FEATURE-Color.md",
        story=story,
        status="answered" if answer else "open",
        archived=False,
        title="Presentation color",
        description="What color should it be?",
        options=(),
        system_choice="unset",
        override_text=answer or None,
    )


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


def test_questions_normalization_keeps_consecutive_header_tables_before_questions():
    text = _blueprint(body="## Behavior\n\nDo it.\n")
    empty_questions = "## Questions\n\n- None.\n\n"
    text = text[: text.index("## Questions")] + empty_questions + text[text.index("## Behavior") :]
    second_table = "| Route | /items |\n| Parent | Items |\n\n"
    moved = text.replace("## Behavior", second_table + "## Behavior")

    normalized = normalize_questions_first(moved)

    assert normalized.index("| Route | /items |") < normalized.index("## Questions")
    validate_questions_document(normalized, require_first_section=True)


@pytest.mark.parametrize("heading", ["## Open Questions", "## Question", "QUESTIONS:"])
def test_alternate_question_headings_are_rejected(heading):
    with pytest.raises(SpecificationError, match="non-canonical"):
        parse_questions(_blueprint().replace("## Questions", heading))


def test_answered_decision_ungates_its_story(tmp_path):
    target = tmp_path / "Demo"
    blueprint = target / "blueprint"
    blueprint.mkdir(parents=True)
    (target / "MANIFEST.md").write_text(_manifest(), encoding="utf-8")
    write_decisions(
        target / "DECISIONS.json",
        (_decision("color-hue", "color"), _decision("color-shade", "color")),
    )

    plan = synchronize_manifest_question_gates(target / "MANIFEST.md", blueprint)
    assert plan.node("color").state == "blocked/questions"
    assert [node.block_id for node in plan.buildable_steps()] == ["independent"]

    write_decisions(
        target / "DECISIONS.json",
        (
            _decision("color-hue", "color", answer="Blue"),
            _decision("color-shade", "color", answer="Navy"),
        ),
    )
    plan = synchronize_manifest_question_gates(target / "MANIFEST.md", blueprint)

    assert plan.node("color").state == "pending"
    assert [node.block_id for node in plan.buildable_steps()] == ["delivery"]


def test_story_local_approval_escape_hatch_is_rejected(tmp_path):
    # A story governed by a blocking decision is released by answering it, not by approving
    # the story for the current Manifest.
    target = tmp_path / "Demo"
    blueprint = target / "blueprint"
    blueprint.mkdir(parents=True)
    (target / "MANIFEST.md").write_text(_manifest(), encoding="utf-8")
    write_decisions(target / "DECISIONS.json", (_decision("color-hue", "color"),))

    synchronize_manifest_question_gates(target / "MANIFEST.md", blueprint)

    with pytest.raises(SpecificationError, match="answer the decision"):
        approve_story_questions(target / "MANIFEST.md", "color")
    assert load_feedback(target) == ()


def test_material_plan_decision_is_visible_without_blocking_story(tmp_path):
    target = tmp_path / "Demo"
    blueprint = target / "blueprint"
    blueprint.mkdir(parents=True)
    (target / "MANIFEST.md").write_text(_manifest(), encoding="utf-8")
    write_decisions(
        target / "DECISIONS.json",
        (_decision("color-hue", "color", severity="material"),),
    )

    plan = synchronize_manifest_question_gates(target / "MANIFEST.md", blueprint)

    assert plan.node("color").state == "pending"
    assert load_decisions(target / "DECISIONS.json")[0].severity == "material"


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


def test_feedback_store_appends_commander_answer_revisions(tmp_path):
    target = tmp_path / "Demo"
    blueprint = target / "blueprint"
    blueprint.mkdir(parents=True)
    path = blueprint / "FEATURE-Color.md"
    path.write_text(_blueprint(status="answered", answer="Blue"), encoding="utf-8")

    harvest_answered_questions(target)
    path.write_text(_blueprint(status="answered", answer="Green"), encoding="utf-8")
    harvest_answered_questions(target)

    payload = json.loads(
        (target / "QuarterDeck" / "planning-feedback.json").read_text(encoding="utf-8")
    )
    assert payload["schema_version"] == 2
    assert [event["answer"] for event in payload["history"]] == ["Blue", "Green"]


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


def test_transitive_dependent_is_not_buildable_when_decision_owner_is_blocked(tmp_path):
    target = tmp_path / "Demo"
    blueprint = target / "blueprint"
    blueprint.mkdir(parents=True)
    (target / "MANIFEST.md").write_text(_manifest(), encoding="utf-8")
    write_decisions(target / "DECISIONS.json", (_decision("color-hue", "color"),))

    plan = synchronize_manifest_question_gates(target / "MANIFEST.md", blueprint)

    assert plan.node("color").state == "blocked/questions"
    assert plan.node("consumer").state == "pending"
    assert tuple(node.block_id for node in plan.buildable_steps()) == ("independent",)
    reloaded = DrydockManifest.load(target / "MANIFEST.md", compatibility=True)
    assert reloaded.node("color").state == "blocked/questions"

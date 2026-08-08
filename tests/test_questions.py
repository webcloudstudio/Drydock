"""Story-local execution gates projected from DECISIONS.json."""

from __future__ import annotations

import pytest

from drydock.decisions import Decision, load_decisions, write_decisions
from drydock.errors import SpecificationError
from drydock.manifest import DrydockManifest
from drydock.question_gates import approve_story_questions, synchronize_manifest_question_gates


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

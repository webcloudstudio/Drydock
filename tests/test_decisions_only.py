import json

from drydock.acceptance_requirements import project_plan_requirement_decisions
from drydock.decisions import Decision, load_decisions, questionnaire_decisions, write_decisions
from drydock.question_gates import synchronize_manifest_question_gates


def test_questionnaire_answer_is_promoted_to_decisions_json(tmp_path):
    target = tmp_path / "Demo"
    questionnaire = target / "QuarterDeck" / "questionnaires"
    questionnaire.mkdir(parents=True)
    (questionnaire / "discovery-identity.json").write_text(
        json.dumps({
            "questions": [{"id": "display_name", "label": "Name", "prompt": "?", "answer": "Demo"}]
        }),
        encoding="utf-8",
    )

    decisions = questionnaire_decisions(target)

    assert decisions[0].origin == "analyze-questionnaire"
    assert decisions[0].answer == "Demo"
    assert (target / "DECISIONS.json").is_file()
    assert not (target / "QuarterDeck" / "planning-feedback.json").exists()


def test_unavailable_acceptance_tooling_creates_blocking_decision(tmp_path):
    blocks = {
        "FEATURE-Health.md": "# FEATURE: Health\n\n## Programmatic Acceptance\n\n### health\nhealth check\nRequires: executable=missing-tool; scope=test\n\n```python\nassert True\n```\n"
    }

    decisions = project_plan_requirement_decisions(
        {**blocks, "MANIFEST.md": ""}, target_dir=tmp_path, build_dir=tmp_path / "build"
    )

    assert decisions[0].severity == "blocking"
    assert decisions[0].blueprint == "FEATURE-Health.md"
    assert "missing-tool" in decisions[0].description
    assert "health" in decisions[0].description


def test_manifest_gate_reads_only_unanswered_blocking_decisions(tmp_path):
    target = tmp_path / "Demo"
    blueprint = target / "blueprint"
    blueprint.mkdir(parents=True)
    (target / "MANIFEST.md").write_text(
        "# MANIFEST: Demo\n\n## story 1: Health\nid: health\nimplements: FEATURE-Health.md\nstate: pending\n",
        encoding="utf-8",
    )
    write_decisions(
        target / "DECISIONS.json",
        (
            Decision(
                "auth",
                "text",
                "blocking",
                "plan",
                "FEATURE-Health.md",
                "health",
                "open",
                False,
                "Authorize tool",
                "Use tool",
                (),
                "not authorized",
            ),
        ),
    )

    gated = synchronize_manifest_question_gates(target / "MANIFEST.md", blueprint)

    assert gated.node("health").state == "blocked/questions"
    decision = load_decisions(target / "DECISIONS.json")[0]
    write_decisions(
        target / "DECISIONS.json",
        (Decision(**{**decision.__dict__, "override_text": "Authorize tool"}),),
    )
    assert (
        synchronize_manifest_question_gates(target / "MANIFEST.md", blueprint).node("health").state
        == "pending"
    )

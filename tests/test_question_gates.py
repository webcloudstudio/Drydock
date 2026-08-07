"""Tests for projecting blocking decisions into Manifest story gates, and for --override."""

from __future__ import annotations

from drydock.build_plan import parse_build_plan
from drydock.decisions import Decision, write_decisions
from drydock.override import STORY_QUESTION, WaivedGate
from drydock.question_gates import synchronize_manifest_question_gates

_MANIFEST = """# MANIFEST: Demo
state: draft

## story 1: Foundation
id: foundation
implements: DATABASE.md
instructions: |
  Build the database.
state: pending
"""


def _decision(*, story: str = "foundation", answer: str = "") -> Decision:
    return Decision(
        id="d-1",
        type="tooling",
        severity="blocking",
        origin="plan",
        blueprint="DATABASE.md",
        story=story,
        status="recommended",
        archived=False,
        title="Which database engine?",
        description="Pick one.",
        options=(),
        system_choice="sqlite",
        commander_direction=(answer or None),
    )


def _setup(tmp_path, *, answer: str = "", state: str = "pending"):
    target_dir = tmp_path / "target"
    blueprint = target_dir / "blueprint"
    blueprint.mkdir(parents=True)
    manifest_path = target_dir / "MANIFEST.md"
    manifest_path.write_text(_MANIFEST.replace("state: pending", f"state: {state}"), "utf-8")
    write_decisions(target_dir / "DECISIONS.json", (_decision(answer=answer),))
    return manifest_path, blueprint


def _state(manifest_path, block_id):
    return parse_build_plan(manifest_path).by_id()[block_id].state


def test_unanswered_blocking_decision_gates_its_story(tmp_path):
    manifest_path, blueprint = _setup(tmp_path)

    synchronize_manifest_question_gates(manifest_path, blueprint)

    assert _state(manifest_path, "foundation") == "blocked/questions"


def test_override_leaves_the_story_pending_and_records_a_waiver(tmp_path):
    manifest_path, blueprint = _setup(tmp_path)
    waivers: list[WaivedGate] = []

    synchronize_manifest_question_gates(manifest_path, blueprint, override=True, waivers=waivers)

    assert _state(manifest_path, "foundation") == "pending"
    assert [(w.kind, w.subject) for w in waivers] == [(STORY_QUESTION, "foundation")]
    assert waivers[0].detail == "Which database engine?"


def test_override_releases_a_story_already_parked_on_questions(tmp_path):
    manifest_path, blueprint = _setup(tmp_path, state="blocked/questions")
    waivers: list[WaivedGate] = []

    synchronize_manifest_question_gates(manifest_path, blueprint, override=True, waivers=waivers)

    assert _state(manifest_path, "foundation") == "pending"
    assert len(waivers) == 1


def test_an_answered_decision_records_no_waiver_under_override(tmp_path):
    manifest_path, blueprint = _setup(tmp_path, answer="Use sqlite.")
    waivers: list[WaivedGate] = []

    synchronize_manifest_question_gates(manifest_path, blueprint, override=True, waivers=waivers)

    assert _state(manifest_path, "foundation") == "pending"
    assert waivers == []

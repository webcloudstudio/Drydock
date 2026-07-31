from __future__ import annotations

from drydock.build_decisions import parse_build_decisions, record_build_decisions
from drydock.questions import parse_questions


def _spec() -> str:
    return """# FEATURE: Color

| Field | Value |
|---|---|
| Type | FEATURE |

## Questions

- None.

## Programmatic Acceptance

- None. No programmatic surface.
"""


def test_build_decision_is_recorded_only_in_owning_blueprint(tmp_path):
    blueprint = tmp_path / "blueprint"
    blueprint.mkdir()
    path = blueprint / "FEATURE-Color.md"
    path.write_text(_spec(), encoding="utf-8")
    report = """<blueprint-decisions>
[{"spec":"FEATURE-Color.md","severity":"Material","subject":"Color choice","decision":"Red and green were possible. I implemented green. Is that acceptable, or should this change on replan?"}]
</blueprint-decisions>
RESULT: SUCCESS
"""

    written = record_build_decisions(
        report,
        blueprint_dir=blueprint,
        allowed_specs=frozenset({"FEATURE-Color.md"}),
    )

    assert written == (path,)
    decision = parse_questions(path.read_text(encoding="utf-8"), source=str(path))[0]
    assert decision.origin == "build"
    assert decision.severity == "material"
    assert decision.status == "open"


def test_build_decision_rejects_unowned_spec_and_blocking_severity(tmp_path):
    report = """<blueprint-decisions>
[
  {"spec":"FEATURE-Other.md","severity":"Material","subject":"Other","decision":"Changed."},
  {"spec":"FEATURE-Color.md","severity":"Blocking","subject":"Color","decision":"Stopped."}
]
</blueprint-decisions>
"""

    decisions = parse_build_decisions(report, frozenset({"FEATURE-Color.md"}))

    assert decisions == ()

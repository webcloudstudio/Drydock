from __future__ import annotations

from drydock.build_decisions import parse_build_decisions, record_build_decisions
from drydock.decisions import load_decisions


def _spec() -> str:
    return """# FEATURE: Color

| Field | Value |
|---|---|
| Type | FEATURE |

## Programmatic Acceptance

- None. No programmatic surface.
"""


def test_build_decision_is_recorded_in_decisions_json_for_the_owning_blueprint(tmp_path):
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

    decisions_path = tmp_path / "DECISIONS.json"
    assert written == (decisions_path,)
    decision = load_decisions(decisions_path)[0]
    assert decision.blueprint == "FEATURE-Color.md"
    assert decision.origin == "build"
    assert decision.severity == "material"
    assert decision.status == "recommended"


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

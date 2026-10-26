"""Delegated repair and stalled-loop regressions, using temporary Targets only."""

import difflib
import json
from dataclasses import replace

import pytest

from drydock.decisions import Decision, load_decisions, write_decisions
from drydock.diagnose_apply import resolve
from drydock.diagnose_evidence import collect
from drydock.diagnose_repair import validate_acceptance_repair
from drydock.diagnose_report import assemble, verify
from drydock.errors import write_error_record
from drydock.prompts import load_prompt
from drydock.question_gates import synchronize_manifest_question_gates
from drydock.status import completion_check, execution_state
from tests.test_diagnose_command import _run, fake_runner, repairable, workspace  # noqa: F401

BROKEN = """# Screen
=== AC context ===
Intent: Preserve context.
assert True
## User Acceptance
- Context stays selected.
=== END AC context ===
"""
FIXED = """# Screen
=== AC context ===
Intent: Preserve context.
assert True
=== END AC context ===
## User Acceptance
- Context stays selected.
"""


def decision(**kwargs):
    item = Decision(
        id="acceptance-SCREEN-A.md-context-malformed",
        type="text",
        severity="blocking",
        origin="plan",
        blueprint="SCREEN-A.md",
        story="screen-a",
        status="open",
        archived=False,
        title="Context cannot execute",
        description="invalid syntax (line 4)",
        options=(),
        system_choice="not answered",
    )
    return replace(item, **kwargs)


def answer(before=BROKEN, after=FIXED, importance="routine"):
    diff = "".join(
        difflib.unified_diff(
            before.splitlines(keepends=True),
            after.splitlines(keepends=True),
            fromfile="a/blueprint/SCREEN-A.md",
            tofile="b/blueprint/SCREEN-A.md",
        )
    )
    return f"""### Root Cause
Markdown is inside the Python criterion.
### Details
- SCREEN-A.md contains an incorrectly placed END AC marker.
### Commander Feedback Requested
None.
### Repair Proposal
#### 1. Correct the acceptance boundary
File: blueprint/SCREEN-A.md
Why: Preserve the executable criterion and move Markdown outside it.
Importance: {importance}
```diff
{diff}```
"""


@pytest.fixture
def stalled(repairable):  # noqa: F811 — imported pytest fixture
    target = repairable / "targets" / "Demo"
    (target / "blueprint" / "SCREEN-A.md").write_text(BROKEN)
    write_decisions(target / "DECISIONS.json", (decision(),))
    (target / "PROJECT_STATUS.jsonl").write_text(
        json.dumps({"label": "BUILT", "result": "pass", "at": "2026-09-15T00:00:00Z"}) + "\n"
    )
    return target


def test_complete_decisions_in_prompt_once_including_commander_guidance(stalled):
    write_decisions(
        stalled / "DECISIONS.json",
        (
            decision(),
            decision(
                id="human",
                severity="material",
                status="answered",
                commander_direction="Preserve the context behavior.",
                description="Keep the approved behavior.",
            ),
        ),
    )
    bundle = collect("Demo", stalled.parent.parent, stalled)
    prompt = assemble(bundle, load_prompt("diagnose_report").body).rendered_text
    assert prompt.count("invalid syntax (line 4)") == 1
    assert prompt.count("Preserve the context behavior.") == 1
    assert "stalled:" in prompt
    assert "delegated Commander authority" in prompt
    assert bundle.stop is None


def test_blocker_linked_blueprint_is_available_even_without_failed_manifest(stalled):
    path = stalled / "MANIFEST.md"
    path.write_text(path.read_text().replace("blocked/questions", "closed/verified"))
    bundle = collect("Demo", stalled.parent.parent, stalled)
    assert "blueprint/SCREEN-A.md" in {item.name for item in bundle.blueprints}
    assert execution_state(stalled)[0] == "stalled"
    assert not completion_check("Demo", stalled).complete


def test_routine_repair_releases_gate_prints_diff_and_annotates_report(stalled, monkeypatch):
    monkeypatch.setattr("drydock.target_git.commit_target", lambda *a, **kw: "test-commit")
    result, output = _run(
        stalled.parent.parent,
        monkeypatch,
        target="Demo",
        mode="apply",
        runner=fake_runner(answer()),
    )
    assert result.exit_code == 0
    assert "+=== END AC context ===" in output
    assert "routine repair(s) annotated" in output
    assert "Repair outcome: buildable" in output
    records = load_decisions(stalled / "DECISIONS.json")
    assert len(records) == 1 and records[0].archived
    synchronize_manifest_question_gates(stalled / "MANIFEST.md", stalled / "blueprint")
    assert execution_state(stalled)[0] == "buildable"
    report = result.report_path.read_text()
    assert "Applied (routine)" in report
    assert "Retired repaired authoring blocker" in report


def test_no_proposal_for_stalled_target_is_unsuccessful(stalled, monkeypatch):
    text = answer().split("### Repair Proposal")[0] + "### Repair Proposal\nNone.\n"
    result, output = _run(
        stalled.parent.parent, monkeypatch, target="Demo", mode="apply", runner=fake_runner(text)
    )
    assert result.exit_code == 1
    assert "no repair applied; stalled" in output


def test_recorded_ac_failure_still_enters_delegated_repair(stalled, monkeypatch):
    (stalled / "PROJECT_STATUS.jsonl").write_text(
        json.dumps({"label": "BUILT", "result": "fail", "at": "2026-09-15T00:00:00Z"}) + "\n"
    )
    write_error_record(
        stalled,
        command="build",
        phase="BUILD",
        classification="programmatic acceptance failed",
        detail="Invalid criterion.",
        recovery="Repair acceptance.",
    )
    monkeypatch.setattr("drydock.target_git.commit_target", lambda *a, **kw: "test-commit")
    runner = fake_runner(answer())
    result, _ = _run(stalled.parent.parent, monkeypatch, target="Demo", mode="apply", runner=runner)
    assert result.exit_code == 0 and len(runner.seen) == 1


def test_repair_preserves_explicit_commander_direction(stalled, monkeypatch):
    write_decisions(
        stalled / "DECISIONS.json", (decision(commander_direction="Preserve behavior."),)
    )
    monkeypatch.setattr("drydock.target_git.commit_target", lambda *a, **kw: "test-commit")
    _run(
        stalled.parent.parent,
        monkeypatch,
        target="Demo",
        mode="apply",
        runner=fake_runner(answer()),
    )
    (record,) = load_decisions(stalled / "DECISIONS.json")
    assert record.commander_direction == "Preserve behavior." and not record.archived


def test_important_repair_creates_nonblocking_review_record(stalled):
    bundle = collect("Demo", stalled.parent.parent, stalled)
    outcome = resolve(
        verify(answer(importance="important"), bundle).amendments, stalled, mode="apply"
    )
    assert outcome.applied
    record = next(
        item for item in load_decisions(stalled / "DECISIONS.json") if item.origin == "diagnose"
    )
    assert record.status == "recommended"
    assert not record.blocks_execution and not record.is_human_authored


def test_important_recording_failure_is_visible(stalled, monkeypatch):
    bundle = collect("Demo", stalled.parent.parent, stalled)

    def fail(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr("drydock.diagnose_apply.write_decisions", fail)
    outcome = resolve(
        verify(answer(importance="important"), bundle).amendments, stalled, mode="apply"
    )
    assert outcome.applied and outcome.review_error == "disk full"


def test_invalid_or_removed_ac_is_rejected():
    assert validate_acceptance_repair(BROKEN, BROKEN, "SCREEN-A.md")
    assert validate_acceptance_repair(FIXED, "# No checks\n", "SCREEN-A.md")


def test_recommended_decision_does_not_gate_story(stalled):
    write_decisions(stalled / "DECISIONS.json", (decision(status="recommended"),))
    synchronize_manifest_question_gates(stalled / "MANIFEST.md", stalled / "blueprint")
    assert execution_state(stalled)[0] == "buildable"

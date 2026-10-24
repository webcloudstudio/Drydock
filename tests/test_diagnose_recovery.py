"""Delegated repair and stalled-loop regressions, using temporary Targets only."""

import difflib
import json
import os
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

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


@pytest.mark.parametrize(
    "scenario",
    [
        "stalled",
        "failed-build",
        "unresolved",
        "false-success",
        "complete",
        "blocked",
        "provider-limit",
        "diagnose-limit",
    ],
)
def test_recovery_loop(tmp_path, scenario):
    """The fake CLI models state changes; no real build or LLM executes."""
    executable = tmp_path / "drydock"
    executable.write_text(
        f"#!{sys.executable}\n"
        + """
import json, os, pathlib, sys
root = pathlib.Path(os.environ["FAKE_ROOT"])
scenario = os.environ["SCENARIO"]
args = sys.argv[1:]
with (root / "calls").open("a") as out:
    out.write(json.dumps(args) + "\\n")
state_file = root / "state"
state = state_file.read_text() if state_file.exists() else (
    "complete" if scenario == "complete" else "buildable" if scenario in {"failed-build", "provider-limit"} else "stalled"
)
if args[:2] == ["config", "env"]:
    print("DRYDOCK_TARGET_DIR=" + str(root))
    if scenario == "blocked": (root / "BLOCKERS.md").write_text("quota")
    sys.exit(0)
if args[0] == "status":
    if (root / "BLOCKERS.md").exists():
        print("BLOCKED: Demo (build: provider rate limit: quota exhausted)")
        sys.exit(1)
    sys.exit(0 if state == ("buildable" if "--ready" in args else "complete") else 1)
if args[0] == "diagnose":
    if scenario == "diagnose-limit":
        (root / "BLOCKERS.md").write_text("quota")
        sys.exit(1)
    if scenario == "unresolved": sys.exit(1)
    if scenario != "false-success": state_file.write_text("buildable")
    sys.exit(0)
if args[0] == "build":
    if scenario == "provider-limit":
        (root / "BLOCKERS.md").write_text("quota")
        sys.exit(1)
    if scenario == "failed-build" and not (root / "failed").exists():
        (root / "failed").touch()
        state_file.write_text("stalled")
        sys.exit(1)
    state_file.write_text("complete")
"""
    )
    executable.chmod(0o755)
    script = Path(__file__).resolve().parents[1] / "drydock_build_loop.sh"
    env = dict(
        os.environ,
        PATH=f"{tmp_path}:{os.environ['PATH']}",
        FAKE_ROOT=str(tmp_path),
        SCENARIO=scenario,
        DRYDOCK_RUNNER_MAX_BUILDS="3",
    )
    result = subprocess.run(
        ["bash", str(script), "Demo", "--model", "test"], env=env, capture_output=True, text=True
    )
    halted = scenario in {"blocked", "provider-limit", "diagnose-limit"}
    assert result.returncode == (1 if halted or scenario in {"unresolved", "false-success"} else 0)
    calls = [json.loads(line) for line in (tmp_path / "calls").read_text().splitlines()]
    repairs = [call for call in calls if call[0] == "diagnose"]
    assert len(repairs) == (0 if scenario in {"complete", "blocked", "provider-limit"} else 1)
    if repairs:
        assert repairs[0] == ["diagnose", "Demo", "--apply", "--model", "test"]
    if halted:
        assert result.stdout.rstrip().endswith("provider rate limit: quota exhausted)")
        assert not result.stderr
        assert calls[-1] == ["status", "Demo", "--ready"]

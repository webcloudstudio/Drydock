"""Stabilization S1: actual execution, criterion outcomes, Manifest state, console and status agree.

One table drives every scenario through ``build_target`` with a fake provider and real criteria.
Each row states what was executed, the outcome each criterion must report, the persisted story
state, the console tally, and the completion verdict ``drydock status`` derives from the Manifest.
"""

from __future__ import annotations

from pathlib import Path

import pytest

import drydock.build_run as br
from drydock.build_plan import parse_build_plan
from drydock.build_run import build_target
from drydock.status import RETRYABLE, completion_check
from tests.test_build_run import FakeResult, _setup, _success_report, make_runner

_APPROVED_ONE_STORY = """# MANIFEST: Demo
state: approved

## story 1: Foundation
id: foundation
implements: DATABASE.md
instructions: |
  Build the database.
state: pending
"""

_TWO_CRITERIA = (
    "DB SPEC CONTENT\n\n"
    "## Programmatic Acceptance\n\n"
    "### foundation-file\n"
    "Foundation writes its marker.\n\n"
    "```python\n"
    "from pathlib import Path\n"
    "assert Path('foundation.txt').is_file()\n"
    "```\n\n"
    "### foundation-extra\n"
    "Foundation writes a second file it never writes.\n\n"
    "```python\n"
    "from pathlib import Path\n"
    "assert Path('never.txt').is_file()\n"
    "```\n"
)

_ONE_CRITERION = (
    "DB SPEC CONTENT\n\n"
    "## Programmatic Acceptance\n\n"
    "### foundation-file\n"
    "Foundation writes its marker.\n\n"
    "```python\n"
    "from pathlib import Path\n"
    "assert Path('foundation.txt').is_file()\n"
    "```\n"
)


def _verification_only_runner(prompt, working_directory, **kwargs):
    return FakeResult(text=_success_report(changed=(), summary="Already satisfied."))


# scenario, Blueprint, runner, pre-existing marker, executor dropped, outcomes, state, console
_MATRIX = [
    ("success", _ONE_CRITERION, make_runner, False, False, ["PASS"], "closed/verified", "1/1"),
    (
        "no-run",
        _ONE_CRITERION,
        make_runner,
        False,
        True,
        ["UNVERIFIED"],
        "closed/implemented",
        "0/1",
    ),
    (
        "partial",
        _TWO_CRITERIA,
        make_runner,
        False,
        False,
        ["PASS", "FAIL"],
        "closed/failed",
        "1/2",
    ),
    (
        "failure",
        _ONE_CRITERION,
        lambda: make_runner(ok=False),
        False,
        False,
        [],
        "closed/failed",
        None,
    ),
    (
        "verification-only",
        _ONE_CRITERION,
        lambda: _verification_only_runner,
        True,
        False,
        ["PASS"],
        "closed/implemented",
        "1/1",
    ),
]


@pytest.mark.parametrize(
    ("scenario", "blueprint", "runner", "prebuilt", "dropped", "outcomes", "state", "tally"),
    _MATRIX,
    ids=[row[0] for row in _MATRIX],
)
def test_execution_outcomes_manifest_console_and_status_agree(
    tmp_path, monkeypatch, scenario, blueprint, runner, prebuilt, dropped, outcomes, state, tally
):
    target_dir, build_dir = _setup(tmp_path, manifest=_APPROVED_ONE_STORY)
    (target_dir / "blueprint" / "DATABASE.md").write_text(blueprint, encoding="utf-8")
    if prebuilt:
        build_dir.mkdir(parents=True, exist_ok=True)
        (build_dir / "foundation.txt").write_text("built foundation\n", encoding="utf-8")
    if dropped:
        # The executor returns nothing for a selected criterion: absence is never a pass.
        monkeypatch.setattr(br, "run_programmatic_acceptance", lambda checks, **kwargs: ())
    messages: list[str] = []

    result = build_target(
        "Demo",
        target_dir,
        build_dir=build_dir,
        runner=runner(),
        repair_attempts=0,
        on_text=messages.append,
    )

    step = result.steps[0]
    assert [check.outcome for check in step.acceptance] == outcomes
    assert step.status == ("failed" if state == "closed/failed" else "built")
    persisted = parse_build_plan(target_dir / "MANIFEST.md").by_id()["foundation"]
    assert persisted.state == state
    if state != "closed/verified":
        assert persisted.fields.get("finding")
    if tally is not None:
        assert any(line.strip().startswith(f"status  {tally} checks passed") for line in messages)
    check = completion_check("Demo", target_dir)
    assert check.complete is (state == "closed/verified")
    assert check.verified == (1 if state == "closed/verified" else 0)
    if not check.complete:
        assert check.outcome == RETRYABLE
        assert dict(check.state_counts) == {state: 1}
    if state == "closed/failed":
        assert "failed: foundation" in check.reason


def test_absent_results_are_reported_as_not_executed(tmp_path, monkeypatch):
    target_dir, build_dir = _setup(tmp_path, manifest=_APPROVED_ONE_STORY)
    (target_dir / "blueprint" / "DATABASE.md").write_text(_ONE_CRITERION, encoding="utf-8")
    monkeypatch.setattr(br, "run_programmatic_acceptance", lambda checks, **kwargs: ())

    result = build_target("Demo", target_dir, build_dir=build_dir, runner=make_runner())

    (check,) = result.steps[0].acceptance
    assert check.error is not None and "not executed" in check.error
    evidence = Path(target_dir / "evidence" / "foundation.md").read_text(encoding="utf-8")
    assert "UNVERIFIED: foundation-file" in evidence


@pytest.mark.parametrize(
    ("command", "phase", "buildable", "kept"),
    [
        ("plan", "plan verify", True, False),
        ("plan", "plan verify", False, True),
        ("build", "build", True, True),
    ],
    ids=["repaired-plan-clears", "unbuildable-keeps", "other-owner-keeps"],
)
def test_a_buildable_repair_retires_only_the_plan_verify_error(
    tmp_path, command, phase, buildable, kept
):
    """DrydockStats 20261026.011913: status kept a plan error that the repair had disproved."""
    from drydock.cli import _settle_plan_state
    from drydock.errors import read_error_record, write_error_record

    target_dir, _ = _setup(tmp_path, manifest=_APPROVED_ONE_STORY)
    write_error_record(
        target_dir,
        command=command,
        phase=phase,
        classification="plan cannot be built as written",
        detail="d",
        recovery="r",
    )

    _settle_plan_state(target_dir, buildable=buildable)

    assert (read_error_record(target_dir) is not None) is kept

"""Stabilization S4: one connected multi-block build recovery scenario with a fake provider.

Block ``foundation`` installs a guard its criterion proves. Block ``service`` is graded by a
four-case conformance criterion. Its calls make a partial gain, regress the guard, recover it,
go flat until the budget ends, and a later build resumes and finishes. Earlier accepted work,
per-check denominators, attempt history and the recovery command must stay truthful throughout.
"""

from __future__ import annotations

from pathlib import Path

from drydock.build_run import build_target
from drydock.errors import read_error_record
from tests.test_build_run import FakeResult, _setup, _state, _success_report, _write_markers

_GUARD = (
    "DB SPEC CONTENT\n\n## Programmatic Acceptance\n\n=== AC db-guard ===\n"
    "Intent: The guard the foundation installs stays installed.\n\n"
    "from pathlib import Path\n"
    'assert Path("guard.txt").read_text().strip() == "on"\n'
    "=== END AC db-guard ===\n"
)
_CONFORMANCE = (
    "SVC SPEC CONTENT\n\n## Programmatic Acceptance\n\n=== AC conformance ===\n"
    "Intent: All four supplied cases pass.\n\n"
    "from pathlib import Path\n"
    'score = int(Path("score.txt").read_text())\n'
    'print(f"{score} passed, {4 - score} failed")\n'
    "assert score == 4\n=== END AC conformance ===\n"
)


def _runner(plan: list[tuple[int, bool]]):
    """Service call n writes ``plan[n]`` = (score, guard installed)."""
    calls: list[dict] = []

    def runner(prompt, working_directory, **kwargs):
        work = Path(working_directory)
        work.mkdir(parents=True, exist_ok=True)
        step = kwargs["parameters"]["step"]
        if step == "foundation":
            (work / "guard.txt").write_text("on\n", encoding="utf-8")
        else:
            score, guard = plan[sum(1 for call in calls if call["step"] == "service")]
            (work / "score.txt").write_text(str(score), encoding="utf-8")
            if guard:
                (work / "guard.txt").write_text("on\n", encoding="utf-8")
            else:
                (work / "guard.txt").unlink(missing_ok=True)
        _write_markers(prompt, work)
        calls.append({"step": step, "prompt": prompt, **kwargs})
        return FakeResult(text=_success_report(changed=(f"{step}.txt",)))

    runner.calls = calls  # type: ignore[attr-defined]
    return runner


def _lineage_attempts(target_dir, step):
    import json

    records = [
        json.loads(line)
        for line in (target_dir / "BUILD_LINEAGE.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    return [record for record in records if json.dumps(record).count(f'"{step}"')]


def test_partial_regression_recovery_exhaustion_and_resume(tmp_path):
    target_dir, build_dir = _setup(tmp_path)
    (target_dir / "blueprint" / "DATABASE.md").write_text(_GUARD, encoding="utf-8")
    (target_dir / "blueprint" / "SERVICE.md").write_text(_CONFORMANCE, encoding="utf-8")
    lines: list[str] = []
    # gain, gain, green-but-regressed, recovered guard with a lost case, flat -> stall stop
    first = _runner([(2, True), (3, True), (4, False), (3, True), (3, True)])

    build_target(
        "Demo",
        target_dir,
        build_dir=build_dir,
        runner=first,
        repair_attempts=4,
        on_text=lines.append,
    )

    lines = [line for message in lines for line in message.splitlines()]
    assert _state(target_dir, "foundation") == "closed/verified"
    assert _state(target_dir, "service") == "closed/failed"
    checks = [line.strip() for line in lines if line.strip().startswith("check=conformance")]
    assert checks == [
        "check=conformance  FAIL  cases=2/4 passed",
        "check=conformance  FAIL  cases=3/4 passed  change=+1",
        "check=conformance  PASS  cases=4/4 passed  change=+1",
        "check=conformance  FAIL  cases=3/4 passed  change=-1",
        "check=conformance  FAIL  cases=3/4 passed  change=+0",
    ]
    assert "regression sweep: 1 prior criteria · 1 regressed" in lines
    # The regression is measured, not agent-reported, and it leads the next repair prompt.
    assert "repair: attempt 3/4 · 1 failing check(s) (1 regressed)" in lines
    service_prompts = [call["prompt"] for call in first.calls if call["step"] == "service"]
    assert "Regression" in service_prompts[3]
    assert "  STOP  reason=stall  flat_calls=2" in lines
    evidence = (target_dir / "evidence" / "service.md").read_text(encoding="utf-8")
    for row in (
        "- attempt 0 (initial build): failed; 0/1 checks; 2/4 cases;",
        "- attempt 2 (repair 2): failed; 1/1 checks; 4/4 cases;",
        "reason: acceptance regression: db-guard",
        "stopped: deterministic acceptance score did not improve on 2 consecutive calls",
    ):
        assert row in evidence
    record = read_error_record(target_dir)
    assert record is not None
    assert "Run: drydock build Demo" in record.recovery
    assert "--step foundation" not in record.recovery
    history = len(_lineage_attempts(target_dir, "service"))
    assert history >= 5

    second = _runner([(4, True)])
    build_target("Demo", target_dir, build_dir=build_dir, runner=second)

    assert [call["step"] for call in second.calls] == ["service"]
    assert second.calls[0]["parameters"]["attempt"] == 0
    assert _state(target_dir, "foundation") == "closed/verified"
    assert _state(target_dir, "service") == "closed/verified"
    assert len(_lineage_attempts(target_dir, "service")) > history

"""Tests for evidence-bound build scoring and its completion gate."""

from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from drydock.build_score import _measure, score_evidence_state, score_target


@dataclass
class FakeRun:
    text: str
    ok: bool = True
    execution_id: str = "exec-score"


def _git(path: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(path), *args], check=True, capture_output=True)


def _target(
    tmp_path: Path,
    *,
    measurement: bool = False,
    guardrail: bool = False,
    guardrail_evidence: bool = True,
    vacuous_proof: bool = False,
) -> tuple[Path, Path]:
    target_dir = tmp_path / "targets" / "Demo"
    blueprint_dir = target_dir / "blueprint"
    build_dir = tmp_path / "build" / "Demo"
    blueprint_dir.mkdir(parents=True)
    build_dir.mkdir(parents=True)
    (target_dir / "METADATA.md").write_text(f"build_dir: {build_dir}\n", encoding="utf-8")
    (target_dir / "MANIFEST.md").write_text(
        """# MANIFEST: Demo
state: closed

## story 1: Implement behavior
id: implementation
state: closed/verified
accepts: st-proof
""",
        encoding="utf-8",
    )
    proof_body = (
        "assert True"
        if vacuous_proof
        else 'from pathlib import Path\nassert Path("marker.txt").read_text(encoding="utf-8") == "built\\n"'
    )
    (blueprint_dir / "FEATURES.md").write_text(
        f"""# Features

## Programmatic Acceptance

### built-marker
Sea Trials: st-proof
The build contains its marker.

```python
{proof_body}
```
""",
        encoding="utf-8",
    )
    sea = """# Sea Trials: Demo

## st-proof: Built behavior
Type: behavioral
Required: yes
Criterion: The built artifact shall contain its marker.
Verification: proof
Pattern: ubiquitous
"""
    if measurement:
        sea += f"""

## st-speed: Faster operation
Type: outcome
Required: yes
Criterion: Observed duration is no more than 10 ms.
Verification: measurement
Command: ["{sys.executable}", "-c", "import json; print(json.dumps({{'value': 20, 'unit': 'ms'}}))"]
Baseline: 30
Operator: <=
Target: 10
Unit: ms
"""
    if guardrail:
        # No story accepts st-privacy: a guardrail is never implemented by one.
        sea += """

## st-privacy: No personal data in logs
Type: guardrail
Required: yes
Criterion: If a request carries personal data, then the system shall omit it from all logs.
Verification: evidence
Pattern: unwanted
Evidence: evidence/privacy-scan.md
"""
        if guardrail_evidence:
            scan = target_dir / "evidence" / "privacy-scan.md"
            scan.parent.mkdir(parents=True, exist_ok=True)
            scan.write_text("Log scan found no personal data.\n", encoding="utf-8")
    (target_dir / "SEA_TRIALS.md").write_text(sea, encoding="utf-8")
    (build_dir / "marker.txt").write_text("built\n", encoding="utf-8")
    _git(build_dir, "init")
    _git(build_dir, "config", "user.email", "test@example.com")
    _git(build_dir, "config", "user.name", "Test")
    _git(build_dir, "add", ".")
    _git(build_dir, "commit", "-m", "build")
    return target_dir, build_dir


def _runner(
    *,
    proof_verdict: str = "FAIL",
    measurement: bool = False,
    guardrail_verdict: str | None = None,
):
    criteria = [
        {
            "id": "st-proof",
            "verdict": proof_verdict,
            "rationale": "model guess",
            "evidence": [],
        }
    ]
    if measurement:
        criteria.append({
            "id": "st-speed",
            "verdict": "PASS",
            "rationale": "model guess",
            "evidence": [],
        })
    if guardrail_verdict is not None:
        criteria.append({
            "id": "st-privacy",
            "verdict": guardrail_verdict,
            "rationale": "scan reviewed",
            "evidence": ["evidence/privacy-scan.md"],
        })
    payload = {
        "dimensions": {
            "specification_completeness": 90,
            "implementation_coverage": 90,
            "test_coverage": 90,
            "documentation_coverage": 90,
            "blueprint_drift": 90,
            "build_quality": 90,
            "acceptance_criteria_coverage": 90,
        },
        "criteria": criteria,
        "improvements": ["Add a second workload."],
    }
    return lambda *args, **kwargs: FakeRun(json.dumps(payload))


def test_code_bound_proof_overrides_model_and_gate_completes(tmp_path):
    target_dir, build_dir = _target(tmp_path)

    result = score_target("Demo", target_dir, runner=_runner())

    assert result.complete is True
    assert result.score == 90
    assert result.criteria[0].verdict == "PASS"
    assert result.exit_code() == 0
    assert result.evidence_path.is_file()
    assert score_evidence_state("Demo", target_dir).state == "current"

    (build_dir / "marker.txt").write_text("changed\n", encoding="utf-8")
    state = score_evidence_state("Demo", target_dir)
    assert state.state == "stale"
    assert "build code changed" in state.reasons


def test_vacuous_proof_is_warned_on_but_does_not_block_completion(tmp_path):
    target_dir, _ = _target(tmp_path, vacuous_proof=True)

    result = score_target("Demo", target_dir, runner=_runner(proof_verdict="PASS"))

    verdict = {item.criterion_id: item for item in result.criteria}["st-proof"]
    assert verdict.verdict == "PASS"
    assert verdict.rationale == "model guess"
    assert "warning: proof passed but failed integrity" in verdict.evidence[0]
    assert result.complete is True
    assert result.blockers == ()
    assert any("vacuous" in warning for warning in result.warnings)


def test_failed_measurement_overrides_model_and_blocks_completion(tmp_path):
    target_dir, _ = _target(tmp_path, measurement=True)

    result = score_target("Demo", target_dir, runner=_runner(measurement=True))

    verdicts = {item.criterion_id: item.verdict for item in result.criteria}
    assert verdicts["st-speed"] == "FAIL"
    assert result.complete is False
    assert "Required Sea Trial st-speed is FAIL" in result.blockers
    assert result.improvements[0].startswith("Resolve st-speed (FAIL):")


def test_held_guardrail_needs_no_story_coverage_and_gate_completes(tmp_path):
    target_dir, _ = _target(tmp_path, guardrail=True)

    result = score_target("Demo", target_dir, runner=_runner(guardrail_verdict="PASS"))

    assert result.complete is True
    assert not any("coverage" in blocker for blocker in result.blockers)
    scorecard = (target_dir / "SCORECARD.md").read_text(encoding="utf-8")
    assert "| st-privacy | guardrail |" in scorecard
    assert "| absolute | HELD |" in scorecard


def test_breached_guardrail_blocks_completion(tmp_path):
    target_dir, _ = _target(tmp_path, guardrail=True)

    result = score_target("Demo", target_dir, runner=_runner(guardrail_verdict="FAIL"))

    assert result.complete is False
    assert result.exit_code() == 1
    assert "Guardrail st-privacy is BREACHED" in "\n".join(result.blockers)
    assert "| absolute | BREACHED |" in (target_dir / "SCORECARD.md").read_text(encoding="utf-8")


def test_guardrail_without_evidence_is_unproven_and_blocks(tmp_path):
    """An unproven never is not held: missing evidence fails the gate rather than passing it.

    It is reported as UNPROVEN, not BREACHED — nothing showed the prohibition violated.
    """
    target_dir, _ = _target(tmp_path, guardrail=True, guardrail_evidence=False)

    result = score_target("Demo", target_dir, runner=_runner(guardrail_verdict="PASS"))

    verdicts = {item.criterion_id: item.verdict for item in result.criteria}
    assert verdicts["st-privacy"] == "INCONCLUSIVE"
    assert result.complete is False
    blockers = "\n".join(result.blockers)
    assert "Guardrail st-privacy is UNPROVEN" in blockers
    assert "BREACHED" not in blockers
    assert "| absolute | UNPROVEN |" in (target_dir / "SCORECARD.md").read_text(encoding="utf-8")


def test_required_assertions_judged_only_by_the_model_lose_coverage_score(tmp_path):
    target_dir, _ = _target(tmp_path)
    sea = (target_dir / "SEA_TRIALS.md").read_text(encoding="utf-8")
    (target_dir / "SEA_TRIALS.md").write_text(
        sea.replace("Verification: proof", "Verification: llm"), encoding="utf-8"
    )

    result = score_target("Demo", target_dir, runner=_runner())

    # The only required assertion rests on llm judgment: 90 -> 45, tripping the <60 gate.
    assert result.dimensions["acceptance_criteria_coverage"] == 45
    assert result.complete is False
    assert "Technical dimensions below 60: acceptance_criteria_coverage" in result.blockers


# ---------------------------------------------------------------------------
# Extract: reading a measurement from a harness's own stdout
# ---------------------------------------------------------------------------


# Reproduces the real CommonMark harness contract: human-readable stdout, and an exit status
# carrying the failure count.
def _harness(passed: int, failed: int) -> str:
    return (
        f"import sys; print('{passed} passed, {failed} failed, 0 errored, 0 skipped'); "
        f"sys.exit({failed})"
    )


def _suite_trial(passed: int, failed: int, *, target: float, extract: str = r"^(\d+) passed"):
    from drydock.sea_trials import parse_sea_trials_text

    command = json.dumps([sys.executable, "-c", _harness(passed, failed)])
    text = f"""# Sea Trials: Demo

## st-suite: Correctness score
Type: outcome
Required: yes
Criterion: The converter achieves the passing-example threshold.
Verification: measurement
Command: {command}
Extract: {extract}
Operator: >=
Target: {target}
Unit: examples
"""
    return parse_sea_trials_text(text).trials[0]


def test_extract_reads_the_count_from_a_failing_harness(tmp_path):
    """The harness exits non-zero because examples failed. That is the measurement, not a
    malfunction -- the old code discarded it as INCONCLUSIVE before reading stdout."""
    trial = _suite_trial(640, 12, target=652)

    result = _measure(trial, target_dir=tmp_path, build_dir=tmp_path)

    assert result.status == "FAIL"
    assert result.value == 640.0
    assert result.unit == "examples"
    assert result.return_code == 12


def test_extract_passes_when_the_threshold_is_met(tmp_path):
    trial = _suite_trial(652, 0, target=652)

    result = _measure(trial, target_dir=tmp_path, build_dir=tmp_path)

    assert result.status == "PASS"
    assert result.value == 652.0


def test_extract_below_a_relaxed_threshold_still_passes(tmp_path):
    trial = _suite_trial(640, 12, target=600)

    assert _measure(trial, target_dir=tmp_path, build_dir=tmp_path).status == "PASS"


def test_non_matching_extract_is_inconclusive_not_a_silent_pass(tmp_path):
    trial = _suite_trial(640, 12, target=652, extract=r"^(\d+) conforming")

    result = _measure(trial, target_dir=tmp_path, build_dir=tmp_path)

    assert result.status == "INCONCLUSIVE"
    assert "did not match" in result.detail


def test_without_extract_a_failing_command_remains_inconclusive(tmp_path):
    """Regression: the JSON measurement path is unchanged."""
    from drydock.sea_trials import parse_sea_trials_text

    command = json.dumps([sys.executable, "-c", "import sys; print('nope'); sys.exit(3)"])
    trial = parse_sea_trials_text(
        f"""# Sea Trials: Demo

## st-x: Thing
Type: outcome
Required: yes
Criterion: A thing is measured.
Verification: measurement
Command: {command}
Operator: >=
Target: 1
"""
    ).trials[0]

    result = _measure(trial, target_dir=tmp_path, build_dir=tmp_path)

    assert result.status == "INCONCLUSIVE"
    assert result.return_code == 3

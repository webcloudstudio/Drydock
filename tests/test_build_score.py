"""Tests for evidence-bound build scoring and its completion gate."""

from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from drydock.build_score import score_evidence_state, score_target


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

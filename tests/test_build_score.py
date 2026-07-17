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


def _target(tmp_path: Path, *, measurement: bool = False) -> tuple[Path, Path]:
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
    (blueprint_dir / "FEATURES.md").write_text(
        """# Features

## Programmatic Acceptance

### built-marker
Sea Trials: st-proof
The build contains its marker.

```python
from pathlib import Path
assert Path("marker.txt").read_text(encoding="utf-8") == "built\\n"
```
""",
        encoding="utf-8",
    )
    sea = """# Sea Trials: Demo

## st-proof: Built behavior
Type: behavioral
Required: yes
Criterion: The built artifact contains its marker.
Verification: proof
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
    (target_dir / "SEA_TRIALS.md").write_text(sea, encoding="utf-8")
    (build_dir / "marker.txt").write_text("built\n", encoding="utf-8")
    _git(build_dir, "init")
    _git(build_dir, "config", "user.email", "test@example.com")
    _git(build_dir, "config", "user.name", "Test")
    _git(build_dir, "add", ".")
    _git(build_dir, "commit", "-m", "build")
    return target_dir, build_dir


def _runner(*, measurement: bool = False):
    criteria = [{"id": "st-proof", "verdict": "FAIL", "rationale": "model guess", "evidence": []}]
    if measurement:
        criteria.append({
            "id": "st-speed",
            "verdict": "PASS",
            "rationale": "model guess",
            "evidence": [],
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


def test_failed_measurement_overrides_model_and_blocks_completion(tmp_path):
    target_dir, _ = _target(tmp_path, measurement=True)

    result = score_target("Demo", target_dir, runner=_runner(measurement=True))

    verdicts = {item.criterion_id: item.verdict for item in result.criteria}
    assert verdicts["st-speed"] == "FAIL"
    assert result.complete is False
    assert "Required Sea Trial st-speed is FAIL" in result.blockers
    assert result.improvements[0].startswith("Resolve st-speed (FAIL):")

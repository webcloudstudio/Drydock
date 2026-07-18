"""Tests for scoring: deterministic per-AC verification and the LLM release gate."""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path

from drydock.build_score import DIMENSIONS
from drydock.score import score_release, verify_acs
from drydock.standard_artifacts import load_soundings


@dataclass
class FakeRun:
    text: str
    ok: bool = True
    execution_id: str = "exec-release"


def _runner(*, proof_verdict: str = "PASS"):
    payload = {
        "dimensions": {name: 90 for name in DIMENSIONS},
        "criteria": [
            {"id": "st-proof", "verdict": proof_verdict, "rationale": "model guess", "evidence": []}
        ],
        "improvements": ["Broaden coverage."],
    }
    return lambda *args, **kwargs: FakeRun(json.dumps(payload))


def _git(path: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(path), *args], check=True, capture_output=True)


def _target(tmp_path: Path, *, proof: str, committed: bool = True) -> tuple[Path, Path]:
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
id: work
state: closed/verified
implements: FEATURES.md

## ac 1: System starts
id: system-starts
parent: work
state: closed/verified
""",
        encoding="utf-8",
    )
    (blueprint_dir / "FEATURES.md").write_text(
        f"""# Features

## Programmatic Acceptance

### built-marker
Sea Trials: st-proof
The build contains its marker.

```python
{proof}
```
""",
        encoding="utf-8",
    )
    (target_dir / "SEA_TRIALS.md").write_text(
        """# Sea Trials: Demo

## st-proof: Built behavior
Type: behavioral
Required: yes
Criterion: The built artifact shall contain its marker.
Verification: proof
Pattern: ubiquitous
""",
        encoding="utf-8",
    )
    (build_dir / "marker.txt").write_text("built\n", encoding="utf-8")
    _git(build_dir, "init")
    _git(build_dir, "config", "user.email", "t@example.com")
    _git(build_dir, "config", "user.name", "T")
    if committed:
        _git(build_dir, "add", ".")
        _git(build_dir, "commit", "-m", "build")
    return target_dir, build_dir


_REAL_PROOF = 'from pathlib import Path\nassert Path("marker.txt").read_text() == "built\\n"'
_FAILING_PROOF = 'from pathlib import Path\nassert Path("marker.txt").read_text() == "nope"'


def test_verify_acs_marks_pass_and_stamps_soundings(tmp_path):
    target_dir, _ = _target(tmp_path, proof=_REAL_PROOF)

    report = verify_acs("Demo", target_dir)

    assert report.exit_code() == 0
    verdict = report.verdicts[0]
    # Rows are keyed by the Blueprint assertion, tagged with its source file — not the ac block.
    assert verdict.criterion_id == "built-marker"
    assert verdict.status == "PASS"
    rows = load_soundings(target_dir / "SOUNDINGS.md")
    assert rows["built-marker"].blueprint == "FEATURES.md"
    assert rows["built-marker"].verified == "✓ PASS"
    assert rows["built-marker"].verified_at == report.verified_at


def test_verify_acs_marks_fail_and_exits_nonzero(tmp_path):
    target_dir, _ = _target(tmp_path, proof=_FAILING_PROOF)

    report = verify_acs("Demo", target_dir)

    assert report.exit_code() == 1
    assert report.verdicts[0].status == "FAIL"
    assert load_soundings(target_dir / "SOUNDINGS.md")["built-marker"].verified == "✗ FAIL"


def test_verify_acs_demotes_vacuous_proof_to_unverified(tmp_path):
    target_dir, _ = _target(tmp_path, proof="assert True")

    report = verify_acs("Demo", target_dir)

    assert report.exit_code() == 0  # UNVERIFIED is not a hard failure
    verdict = report.verdicts[0]
    assert verdict.status == "UNVERIFIED"
    assert "integrity" in verdict.evidence
    row = load_soundings(target_dir / "SOUNDINGS.md")["built-marker"]
    assert row.verified == "— UNVERIFIED"
    assert row.verified_at == ""


def test_release_score_completes_and_writes_scorecard(tmp_path):
    target_dir, _ = _target(tmp_path, proof=_REAL_PROOF)

    # The model guesses FAIL; the passing code-bound proof overrides it to PASS.
    result = score_release("Demo", target_dir, runner=_runner(proof_verdict="FAIL"))

    assert result.complete
    assert result.exit_code() == 0
    assert result.criteria[0].verdict == "PASS"
    scorecard = (target_dir / "SCORECARD.md").read_text(encoding="utf-8")
    assert "# Build Scorecard: Demo" in scorecard
    assert (target_dir / "evidence" / "score-release.json").is_file()


def test_release_score_fails_on_failing_proof(tmp_path):
    target_dir, _ = _target(tmp_path, proof=_FAILING_PROOF)

    # The model guesses PASS; the failing proof overrides it and blocks release.
    result = score_release("Demo", target_dir, runner=_runner(proof_verdict="PASS"))

    assert not result.complete
    assert result.exit_code() == 1
    assert result.criteria[0].verdict == "FAIL"
    assert any("st-proof" in blocker for blocker in result.blockers)


def test_release_score_blocks_on_dirty_worktree(tmp_path):
    target_dir, build_dir = _target(tmp_path, proof=_REAL_PROOF)
    (build_dir / "marker.txt").write_text("changed\n", encoding="utf-8")

    result = score_release("Demo", target_dir, runner=_runner())

    assert not result.complete
    assert any("uncommitted changes" in blocker for blocker in result.blockers)

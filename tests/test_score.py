"""Tests for deterministic, LLM-free scoring: per-AC verification and the release gate."""

from __future__ import annotations

import subprocess
from pathlib import Path

from drydock.score import deterministic_gate, verify_acs
from drydock.standard_artifacts import load_soundings


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
    assert verdict.criterion_id == "system-starts"
    assert verdict.status == "PASS"
    rows = load_soundings(target_dir / "SOUNDINGS.md")
    assert rows["system-starts"].verified == "✓ PASS"
    assert rows["system-starts"].verified_at == report.verified_at


def test_verify_acs_marks_fail_and_exits_nonzero(tmp_path):
    target_dir, _ = _target(tmp_path, proof=_FAILING_PROOF)

    report = verify_acs("Demo", target_dir)

    assert report.exit_code() == 1
    assert report.verdicts[0].status == "FAIL"
    assert load_soundings(target_dir / "SOUNDINGS.md")["system-starts"].verified == "✗ FAIL"


def test_verify_acs_demotes_vacuous_proof_to_unverified(tmp_path):
    target_dir, _ = _target(tmp_path, proof="assert True")

    report = verify_acs("Demo", target_dir)

    assert report.exit_code() == 0  # UNVERIFIED is not a hard failure
    verdict = report.verdicts[0]
    assert verdict.status == "UNVERIFIED"
    assert "integrity" in verdict.evidence
    row = load_soundings(target_dir / "SOUNDINGS.md")["system-starts"]
    assert row.verified == "— UNVERIFIED"
    assert row.verified_at == ""


def test_release_gate_passes_when_all_deterministic_hold(tmp_path):
    target_dir, _ = _target(tmp_path, proof=_REAL_PROOF)

    result = deterministic_gate("Demo", target_dir)

    assert result.passed
    assert result.exit_code() == 0
    assert result.blockers == ()


def test_release_gate_fails_on_failing_proof(tmp_path):
    target_dir, _ = _target(tmp_path, proof=_FAILING_PROOF)

    result = deterministic_gate("Demo", target_dir)

    assert not result.passed
    assert any("FAILED its proof" in b for b in result.blockers)


def test_release_gate_fails_on_vacuous_proof(tmp_path):
    target_dir, _ = _target(tmp_path, proof="assert True")

    result = deterministic_gate("Demo", target_dir)

    assert result.passed
    assert result.blockers == ()


def test_release_gate_fails_on_dirty_worktree(tmp_path):
    target_dir, build_dir = _target(tmp_path, proof=_REAL_PROOF)
    (build_dir / "marker.txt").write_text("changed\n", encoding="utf-8")

    result = deterministic_gate("Demo", target_dir)

    assert not result.passed
    assert any("uncommitted changes" in b for b in result.blockers)

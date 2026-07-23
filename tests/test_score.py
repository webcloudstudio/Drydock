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


def _scoped_target(tmp_path: Path) -> Path:
    """A two-feature target: Alpha's proof passes, Beta's fails. One proof per feature/story."""
    target_dir = tmp_path / "targets" / "Demo"
    blueprint_dir = target_dir / "blueprint"
    build_dir = tmp_path / "build" / "Demo"
    blueprint_dir.mkdir(parents=True)
    build_dir.mkdir(parents=True)
    (target_dir / "METADATA.md").write_text(f"build_dir: {build_dir}\n", encoding="utf-8")
    (target_dir / "MANIFEST.md").write_text(
        """# MANIFEST: Demo
state: closed

## feature 1: Alpha
id: feat-alpha
state: closed/verified

## story 1: Alpha work
id: alpha
parent: feat-alpha
implements: ALPHA.md
state: closed/verified

## feature 2: Beta
id: feat-beta
state: closed/failed

## story 2: Beta work
id: beta
parent: feat-beta
implements: BETA.md
state: closed/failed
""",
        encoding="utf-8",
    )
    (blueprint_dir / "ALPHA.md").write_text(
        "# Alpha\n\n## Programmatic Acceptance\n\n### alpha-proof\nAlpha holds.\n\n"
        '```python\nfrom pathlib import Path\nassert Path("marker.txt").read_text() == "built\\n"\n```\n',
        encoding="utf-8",
    )
    (blueprint_dir / "BETA.md").write_text(
        "# Beta\n\n## Programmatic Acceptance\n\n### beta-proof\nBeta holds.\n\n"
        '```python\nfrom pathlib import Path\nassert Path("marker.txt").read_text() == "nope"\n```\n',
        encoding="utf-8",
    )
    (build_dir / "marker.txt").write_text("built\n", encoding="utf-8")
    return target_dir


def test_verify_acs_scopes_to_a_named_feature_and_skips_soundings(tmp_path):
    target_dir = _scoped_target(tmp_path)

    report = verify_acs("Demo", target_dir, step_id="feat-beta")

    # Only Beta's assertion is in scope; Alpha's is not verified in this run.
    assert [v.criterion_id for v in report.verdicts] == ["beta-proof"]
    assert report.verdicts[0].status == "FAIL"
    assert report.verdicts[0].source == "BETA.md"
    assert report.exit_code() == 1
    assert report.scope == "feat-beta"
    assert report.scope_name == "Beta"
    # A scoped run is a read-only view; it must not rewrite the full board.
    assert report.wrote_soundings is False
    assert not (target_dir / "SOUNDINGS.md").exists()


def test_verify_acs_scopes_to_a_single_story(tmp_path):
    target_dir = _scoped_target(tmp_path)

    report = verify_acs("Demo", target_dir, step_id="alpha")

    assert [v.criterion_id for v in report.verdicts] == ["alpha-proof"]
    assert report.verdicts[0].status == "PASS"
    assert report.exit_code() == 0
    assert report.scope == "alpha"


def test_verify_acs_unknown_step_lists_valid_ids(tmp_path):
    from drydock.errors import SpecificationError

    target_dir = _scoped_target(tmp_path)

    try:
        verify_acs("Demo", target_dir, step_id="nope")
    except SpecificationError as exc:
        assert "unknown --step 'nope'" in str(exc)
        assert "feat-beta" in str(exc)
    else:
        raise AssertionError("expected SpecificationError for unknown step")


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


def _add_proof_guardrail(target_dir: Path, *, linked: bool) -> None:
    """Append a required proof-verified guardrail, optionally linked to a proof."""
    sea = target_dir / "SEA_TRIALS.md"
    sea.write_text(
        sea.read_text(encoding="utf-8")
        + """
## st-never: No side effects
Type: guardrail
Required: yes
Criterion: If the build runs, then the build shall not write outside its directory.
Verification: proof
Pattern: unwanted
""",
        encoding="utf-8",
    )
    if linked:
        features = target_dir / "blueprint" / "FEATURES.md"
        features.write_text(
            features.read_text(encoding="utf-8")
            + """
### no-side-effects
Sea Trials: st-never
Conversion writes nothing.

```python
from pathlib import Path
assert not Path("side-effect.txt").exists()
```
""",
            encoding="utf-8",
        )


def _guardrail_runner(*, guardrail_verdict: str = "PASS"):
    payload = {
        "dimensions": {name: 90 for name in DIMENSIONS},
        "criteria": [
            {"id": "st-proof", "verdict": "PASS", "rationale": "model guess", "evidence": []},
            {
                "id": "st-never",
                "verdict": guardrail_verdict,
                "rationale": "model guess",
                "evidence": [],
            },
        ],
        "improvements": ["Broaden coverage."],
    }
    return lambda *args, **kwargs: FakeRun(json.dumps(payload))


def test_unlinked_proof_guardrail_reports_coverage_gap_not_a_breach(tmp_path):
    """A proof-verified guardrail that no proof references is a traceability gap.

    The model cannot rescue it by asserting PASS, and the report names the real defect
    instead of claiming the prohibition was violated.
    """
    target_dir, _ = _target(tmp_path, proof=_REAL_PROOF)
    _add_proof_guardrail(target_dir, linked=False)

    result = score_release("Demo", target_dir, runner=_guardrail_runner())

    blockers = "\n".join(result.blockers)
    assert "Required Sea Trials lack implementation/proof coverage: st-never" in blockers
    assert "Guardrail st-never is UNPROVEN" in blockers
    assert "BREACHED" not in blockers
    assert result.complete is False


def test_linked_proof_guardrail_holds(tmp_path):
    target_dir, _ = _target(tmp_path, proof=_REAL_PROOF)
    _add_proof_guardrail(target_dir, linked=True)

    result = score_release("Demo", target_dir, runner=_guardrail_runner())

    verdicts = {item.criterion_id: item.verdict for item in result.criteria}
    assert verdicts["st-never"] == "PASS"
    assert not any("st-never" in blocker for blocker in result.blockers)
    assert "| absolute | HELD |" in (target_dir / "SCORECARD.md").read_text(encoding="utf-8")


_STAGED_ANALYSIS = """# ANALYSIS

## Source Roles

| Path | Role | Plan disposition | Build disposition |
|---|---|---|---|
| sources/spec.txt | normative specification and conformance corpus | context | stage |
"""


def _with_staged_kit(tmp_path, *, build_content: str) -> Path:
    target_dir, build_dir = _target(tmp_path, proof=_REAL_PROOF, committed=False)
    sources = target_dir / "blueprint" / "sources"
    sources.mkdir(parents=True)
    (sources / "spec.txt").write_text("CORPUS\n" * 200, encoding="utf-8")
    (target_dir / "ANALYSIS.md").write_text(_STAGED_ANALYSIS, encoding="utf-8")
    (build_dir / "sources").mkdir(parents=True, exist_ok=True)
    (build_dir / "sources" / "spec.txt").write_text(build_content, encoding="utf-8")
    _git(build_dir, "add", ".")
    _git(build_dir, "commit", "-m", "build")
    return target_dir


def test_release_score_blocks_when_a_staged_asset_was_substituted(tmp_path):
    """The 117-byte-corpus regression: a build that graded itself against a kit it authored
    must not be scorable."""
    target_dir = _with_staged_kit(tmp_path, build_content="# 2 examples\n")

    result = score_release("Demo", target_dir, runner=_runner())

    assert not result.complete
    assert any("Staged build asset was modified" in b for b in result.blockers)
    assert any("sources/spec.txt" in b for b in result.blockers)
    # Scoring reports; it never repairs the artifact under judgment.
    build_spec = tmp_path / "build" / "Demo" / "sources" / "spec.txt"
    assert build_spec.read_text(encoding="utf-8") == "# 2 examples\n"


def test_release_score_accepts_an_intact_staged_kit(tmp_path):
    target_dir = _with_staged_kit(tmp_path, build_content="CORPUS\n" * 200)

    result = score_release("Demo", target_dir, runner=_runner())

    assert not any("Staged build asset" in b for b in result.blockers)
    assert result.complete

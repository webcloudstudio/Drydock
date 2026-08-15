"""Tests for scoring: deterministic per-AC verification and the LLM release gate."""

from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest

from drydock.errors import SpecificationError
from drydock.gate_policy import ERROR, FAILED, MANUAL, MET, NOT_MET, PASSED
from drydock.score import PROBE_DIR, score_release, verify_acs
from drydock.standard_artifacts import load_soundings


@dataclass
class FakeRun:
    text: str
    ok: bool = True
    execution_id: str = "exec-release"


def _runner(*, proof_verdict: str = "PASS"):
    payload = {
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


def test_verify_acs_attributes_each_verdict_to_its_story_and_feature(tmp_path):
    target_dir = _scoped_target(tmp_path)

    report = verify_acs("Demo", target_dir)

    owners = {v.criterion_id: (v.feature, v.story) for v in report.verdicts}
    assert owners["alpha-proof"] == ("feat-alpha", "alpha")
    assert owners["beta-proof"] == ("feat-beta", "beta")


def test_score_ac_lists_every_verdict_with_owner(tmp_path, capsys, monkeypatch):
    from drydock import cli

    target_dir = _scoped_target(tmp_path)
    monkeypatch.setattr("drydock.config.require_target_dir", lambda target: target_dir)

    exit_code = cli.cmd_score_ac("Demo")

    out = capsys.readouterr().out
    assert exit_code == 1
    # Every AC is listed, passing ones as a single line with no detail.
    assert "✓ PASS" in out and "alpha-proof" in out and "feat-alpha/alpha" in out
    assert "✗ FAIL" in out and "beta-proof" in out and "feat-beta/beta" in out
    assert "ALPHA.md" in out and "BETA.md" in out


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


def test_a_prepassed_criterion_is_reported_separately_and_does_not_fail_the_run():
    """Green now and green before its block built. A weaker claim than PASS, but not a defect:
    a criterion measuring a deliverable that already existed reads identically, and only the
    author can tell which it is. So it is named, not gated."""
    from drydock.acceptance import AcceptanceObservation
    from drydock.score import FAIL, PASS, PREPASSED, AcReport, AcVerdict, _observation_verdict

    observation = AcceptanceObservation("leaf-blocks", "FEATURE-Leaf.md", "intent", True, 0, "", "")
    status, _, _ = _observation_verdict(observation)
    assert status == PASS

    report = AcReport(
        target="commonmark",
        verdicts=(
            AcVerdict("leaf-blocks", "intent", PREPASSED, "green at baseline too"),
            AcVerdict("leaf-references", "intent", PASS, ""),
        ),
        soundings_path=Path("SOUNDINGS.md"),
        verified_at="now",
    )

    assert report.exit_code() == 0
    assert (
        AcReport(
            target="t",
            verdicts=(AcVerdict("x", "i", FAIL, "boom"),),
            soundings_path=Path("SOUNDINGS.md"),
            verified_at="now",
        ).exit_code()
        == 1
    )


# --- score release: the gate observes the finished tree ------------------------------------
#
# Score observes; it does not read reports. Every record the build left behind is history — an
# assertion that passed at block 3 is a statement about the tree as it stood at block 3 — so the
# verdict is assembled from what Drydock can observe now, and from a grader that was handed the
# tree with tools.


def _release_runner(verdicts: dict[str, str] | None = None, *, calls: list | None = None):
    """A grader that returns the supplied verdicts and records how it was invoked."""

    def runner(prompt_text, working_directory, **kwargs):
        if calls is not None:
            calls.append({"prompt": prompt_text, "cwd": working_directory, **kwargs})
        payload = {
            "criteria": [
                {"id": key, "verdict": value, "rationale": "observed", "evidence": []}
                for key, value in (verdicts or {"st-proof": MET}).items()
            ],
            "improvements": ["Broaden coverage."],
        }
        return FakeRun(json.dumps(payload))

    return runner


def _with_command(target_dir: Path, argv: list[str]) -> None:
    sea = target_dir / "SEA_TRIALS.md"
    sea.write_text(
        sea.read_text(encoding="utf-8") + f"Command: {json.dumps(argv)}\n", encoding="utf-8"
    )


def test_release_passes_and_writes_the_listing(tmp_path):
    target_dir, _ = _target(tmp_path, proof=_REAL_PROOF)

    result = score_release("Demo", target_dir, runner=_release_runner())

    assert result.verdict == PASSED
    assert result.complete
    assert result.exit_code() == 0
    assert result.criteria[0].verdict == MET
    assert result.statement.splitlines()[0] == "Demo: PASSED — 1 of 1"
    scorecard = (target_dir / "SCORECARD.md").read_text(encoding="utf-8")
    assert "# Release Scorecard: Demo" in scorecard
    assert "- Verdict: PASSED" in scorecard
    record = json.loads(
        (target_dir / "evidence" / "score-release.json").read_text(encoding="utf-8")
    )
    assert record["verdict"] == PASSED
    assert record["verdict_line"] == "Demo: PASSED — 1 of 1"


def test_a_criterion_command_is_run_now_and_its_red_exit_pins_not_met(tmp_path):
    """A trial that names a command is settled by running that command against the final tree.
    The grader may not argue a red exit into a pass."""
    target_dir, _ = _target(tmp_path, proof=_REAL_PROOF)
    _with_command(target_dir, [sys.executable, "-c", "raise SystemExit(1)"])

    result = score_release("Demo", target_dir, runner=_release_runner({"st-proof": MET}))

    assert result.verdict == FAILED
    assert result.exit_code() == 1
    assert result.criteria[0].verdict == NOT_MET
    assert any("exited 1" in item for item in result.criteria[0].evidence)


def test_a_green_command_pins_met_over_an_unsettled_grade(tmp_path):
    target_dir, _ = _target(tmp_path, proof=_REAL_PROOF)
    _with_command(target_dir, [sys.executable, "-c", "pass"])

    result = score_release("Demo", target_dir, runner=_release_runner({"st-proof": MANUAL}))

    assert result.verdict == PASSED
    assert result.criteria[0].verdict == MET


def test_the_grader_is_handed_the_build_tree_with_tools_and_an_ephemeral_probe_directory(tmp_path):
    """The probe is the safe place for a model to author a test: it is written after the code
    exists, against source the grader can read, and it is discarded after one verdict."""
    target_dir, build_dir = _target(tmp_path, proof=_REAL_PROOF)
    calls: list = []
    seen: dict = {}

    def runner(prompt_text, working_directory, **kwargs):
        seen["probe_present"] = (build_dir / PROBE_DIR).is_dir()
        (build_dir / PROBE_DIR / "probe.py").write_text("print(1)\n", encoding="utf-8")
        return _release_runner(calls=calls)(prompt_text, working_directory, **kwargs)

    result = score_release("Demo", target_dir, runner=runner)

    assert result.verdict == PASSED
    assert calls[0]["cwd"] == build_dir
    assert calls[0]["allow_tools"] is True
    assert seen["probe_present"] is True
    assert not (build_dir / PROBE_DIR).exists()
    facts = json.loads(calls[0]["prompt"].split("```json\n")[-1].split("\n```")[0])
    assert facts["probe_directory"] == PROBE_DIR
    assert facts["build_directory"] == str(build_dir)


def test_the_probe_directory_is_removed_even_when_the_grader_returns_nothing(tmp_path):
    target_dir, build_dir = _target(tmp_path, proof=_REAL_PROOF)

    with pytest.raises(SpecificationError):
        score_release("Demo", target_dir, runner=lambda *a, **k: FakeRun("", ok=False))

    assert not (build_dir / PROBE_DIR).exists()


def test_no_record_the_build_left_behind_reaches_the_verdict(tmp_path):
    """A failing story assertion, a failed Manifest block, and a stale proof tag are all history.
    The release verdict is about the tree as it stands now."""
    target_dir, _ = _target(tmp_path, proof=_FAILING_PROOF)
    manifest = target_dir / "MANIFEST.md"
    manifest.write_text(
        manifest.read_text(encoding="utf-8").replace(
            "id: work\nstate: closed/verified", "id: work\nstate: closed/failed"
        ),
        encoding="utf-8",
    )
    calls: list = []

    result = score_release("Demo", target_dir, runner=_release_runner(calls=calls))

    assert result.verdict == PASSED
    assert result.blockers == ()
    facts = json.loads(calls[0]["prompt"].split("```json\n")[-1].split("\n```")[0])
    assert "programmatic_acceptance" not in facts
    assert "manifest" not in facts


def test_verification_proof_no_longer_selects_a_lookup(tmp_path):
    """D-016. The grader's verdict used to be discarded and replaced by whether a model-authored
    assertion happened to carry a `Sea Trials:` tag, which reported five met criteria as blocked.
    ``Verification: proof`` now selects nothing."""
    target_dir, _ = _target(tmp_path, proof=_REAL_PROOF)
    features = target_dir / "blueprint" / "FEATURES.md"
    features.write_text(
        features.read_text(encoding="utf-8").replace("Sea Trials: st-proof\n", ""),
        encoding="utf-8",
    )

    result = score_release("Demo", target_dir, runner=_release_runner({"st-proof": MET}))

    assert result.verdict == PASSED
    assert not any("coverage" in blocker for blocker in result.blockers)


def test_not_met_without_a_citation_attests_rather_than_failing(tmp_path):
    target_dir, _ = _target(tmp_path, proof=_REAL_PROOF)

    result = score_release("Demo", target_dir, runner=_release_runner({"st-proof": NOT_MET}))

    assert result.verdict == PASSED
    assert result.criteria[0].verdict == MANUAL
    assert any("st-proof" in item for item in result.attestations)


def test_an_observed_absence_fails_the_release(tmp_path):
    """UC-008 must keep working: a grader that looked and cited what it saw fails the project."""
    target_dir, _ = _target(tmp_path, proof=_REAL_PROOF)

    def runner(prompt_text, working_directory, **kwargs):
        payload = {
            "criteria": [
                {
                    "id": "st-proof",
                    "verdict": NOT_MET,
                    "rationale": "no marker",
                    "evidence": ["probe: marker.txt does not exist"],
                }
            ],
            "improvements": [],
        }
        return FakeRun(json.dumps(payload))

    result = score_release("Demo", target_dir, runner=runner)

    assert result.verdict == FAILED
    assert result.exit_code() == 1
    assert any("st-proof is NOT MET" in blocker for blocker in result.blockers)


def test_release_score_reports_a_dirty_worktree_and_does_not_block(tmp_path):
    """Git state is reported, never gating.

    The case: a run passed every Sea Trial and every assertion, then failed the release because
    Drydock had run the project's own test suite and the suite wrote a database file into the
    tree. A gate may only block on a fault domain it can distinguish, and a dirty worktree cannot
    distinguish a defective product from tidy bookkeeping.
    """
    target_dir, build_dir = _target(tmp_path, proof=_REAL_PROOF)
    (build_dir / "instance").mkdir()
    (build_dir / "instance" / "app.sqlite3").write_bytes(b"\x00" * 16)

    result = score_release("Demo", target_dir, runner=_release_runner())

    assert result.verdict == PASSED
    assert result.exit_code() == 0
    assert not any("uncommitted changes" in blocker for blocker in result.blockers)
    assert any("uncommitted changes" in warning for warning in result.warnings)


def _add_guardrail(target_dir: Path) -> None:
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


def test_a_guardrail_is_graded_like_any_other_criterion(tmp_path):
    """Type: guardrail is reporting metadata. An unsettleable prohibition attests; it does not
    acquire a separate vocabulary or fail a release for want of positive proof."""
    target_dir, _ = _target(tmp_path, proof=_REAL_PROOF)
    _add_guardrail(target_dir)

    result = score_release(
        "Demo", target_dir, runner=_release_runner({"st-proof": MET, "st-never": MANUAL})
    )

    assert result.verdict == PASSED
    assert result.exit_code() == 0
    assert any("st-never needs manual verification" in item for item in result.attestations)
    scorecard = (target_dir / "SCORECARD.md").read_text(encoding="utf-8")
    assert "| st-never | guardrail |" in scorecard


def test_an_observed_guardrail_breach_fails_the_release(tmp_path):
    target_dir, _ = _target(tmp_path, proof=_REAL_PROOF)
    _add_guardrail(target_dir)

    def runner(prompt_text, working_directory, **kwargs):
        payload = {
            "criteria": [
                {"id": "st-proof", "verdict": MET, "rationale": "ok", "evidence": []},
                {
                    "id": "st-never",
                    "verdict": NOT_MET,
                    "rationale": "writes outside",
                    "evidence": ["probe: wrote /tmp/side-effect.txt"],
                },
            ],
            "improvements": [],
        }
        return FakeRun(json.dumps(payload))

    result = score_release("Demo", target_dir, runner=runner)

    assert result.verdict == FAILED
    assert result.exit_code() == 1


_STAGED_ANALYSIS = """# ANALYSIS

## Source Roles

| Path | Role | Plan disposition | Build disposition |
|---|---|---|---|
| sources/spec.txt | normative specification and conformance test suite | context | stage |
"""


def _with_staged_kit(tmp_path, *, build_content: str) -> Path:
    target_dir, build_dir = _target(tmp_path, proof=_REAL_PROOF, committed=False)
    sources = target_dir / "blueprint" / "sources"
    sources.mkdir(parents=True)
    (sources / "spec.txt").write_text("EXAMPLE\n" * 200, encoding="utf-8")
    (target_dir / "ANALYSIS.md").write_text(_STAGED_ANALYSIS, encoding="utf-8")
    (build_dir / "sources").mkdir(parents=True, exist_ok=True)
    (build_dir / "sources" / "spec.txt").write_text(build_content, encoding="utf-8")
    _git(build_dir, "add", ".")
    _git(build_dir, "commit", "-m", "build")
    return target_dir


def test_a_substituted_staged_asset_is_an_error_not_a_product_failure(tmp_path):
    """The 117-byte-suite regression. The thing being scored is not the thing that was built, so
    no verdict about the product is available — and Drydock says exactly that."""
    target_dir = _with_staged_kit(tmp_path, build_content="# 2 examples\n")

    result = score_release("Demo", target_dir, runner=_release_runner())

    assert result.verdict == ERROR
    assert result.exit_code() == 1
    assert result.criteria == ()
    assert "says nothing about the product" in result.statement
    # Scoring reports; it never repairs the artifact under judgment.
    build_spec = tmp_path / "build" / "Demo" / "sources" / "spec.txt"
    assert build_spec.read_text(encoding="utf-8") == "# 2 examples\n"


def test_release_score_accepts_an_intact_staged_kit(tmp_path):
    target_dir = _with_staged_kit(tmp_path, build_content="EXAMPLE\n" * 200)

    result = score_release("Demo", target_dir, runner=_release_runner())

    assert result.verdict == PASSED


def test_a_failed_criterion_reports_the_assertion_and_what_the_check_observed():
    """The score board's one-line cell is a table entry, not a diagnosis.

    Observed in the CommonMark UAT of 2026-08-15: every failing criterion read ``AssertionError``
    and nothing else, while the tally that explained it sat unused in the check's stdout.
    """
    from drydock.acceptance import AcceptanceObservation
    from drydock.score import FAIL, _observation_verdict

    observation = AcceptanceObservation(
        "block-input-tabs",
        "FEATURE-Block-Input.md",
        "intent",
        False,
        1,
        "10 passed, 1 failed, 0 errored, 644 skipped\n",
        '  File "block-input-tabs.py", line 11, in <module>\n'
        "    assert result.returncode == 0\nAssertionError\n",
    )

    status, evidence, detail = _observation_verdict(observation)

    assert status == FAIL
    assert evidence == "assert result.returncode == 0 → AssertionError"
    block = "\n".join(detail)
    assert "process exit code: 1" in block
    assert "10 passed, 1 failed" in block

"""Tests for the LLM-driven ``drydock plan create`` (planning_session.create_plan).

A fake runner supplies canned delimited-block output; no API credits are spent.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import pytest

from drydock.errors import SpecificationError
from drydock.planning_session import _answered_spike, create_plan

_ANALYSIS = """# Blueprint Analysis: Example
generated: 2026-06-16
blueprint: bp

Quality: Questions
  stories: 2
  stack: python

## Story List

Project type: `cli`

| ID | Story | File |
|---|---|---|
| arch | Architecture | ARCHITECTURE.md |
| status | Status command | FEATURE-Status.md |
"""

_SPEC_HEADER = """# {ftype}: {name}

| Field       | Value |
|-------------|-------|
| Version     | 20260616 V1 |
| Description | {name} contract. |
| Depends On  | |
| Provides    | drydock status |
| Phase       | 1 |

## Acceptance Criteria

- {ac}

## Guardrails

- None.

## Open Questions

- None.
"""


def _manifest(story_state: str = "pending", implements: str = "FEATURE-Status.md") -> str:
    return f"""# MANIFEST: Example
updated: 2026-06-16
plan_hash: test
state: draft

## feature 1: Status
id: feature-status
summary: Deliver the status command.
state: pending

## story 1: Deliver Status
id: story-status
parent: feature-status
summary: Build the status command.
implements: {implements}
scope: both
state: {story_state}

## ac 1: Status command exits successfully
id: ac-status-exits
parent: story-status
kind: assertion
state: pending
"""


def _llm_output(manifest: str | None = None) -> str:
    arch = _SPEC_HEADER.format(ftype="ARCHITECTURE", name="Example", ac="None.")
    feature = _SPEC_HEADER.format(
        ftype="FEATURE", name="Status", ac="Status command exits successfully."
    )
    compass = "# Foundation\nARCHITECTURE.md\n#\nFEATURE-Status.md\n"
    return (
        f"=== ARCHITECTURE.md ===\n{arch}\n=== END ARCHITECTURE.md ===\n"
        f"=== FEATURE-Status.md ===\n{feature}\n=== END FEATURE-Status.md ===\n"
        f"=== BUILD_PLAN_COMPASS.md ===\n{compass}\n=== END BUILD_PLAN_COMPASS.md ===\n"
        f"=== MANIFEST.md ===\n{manifest or _manifest()}\n=== END MANIFEST.md ===\n"
    )


@dataclass
class FakeRun:
    ok: bool = True
    text: str = ""
    execution_id: str = "exec-fake"


def _fake(text: str):
    return lambda *a, **k: FakeRun(text=text)


def _make_target(tmp_path: Path, *, analysis: str | None = _ANALYSIS) -> Path:
    target_dir = tmp_path / "Example"
    sources = target_dir / "blueprint" / "sources"
    sources.mkdir(parents=True)
    (sources / "request.md").write_text("# Request\n\nBuild a status command.\n", encoding="utf-8")
    if analysis is not None:
        (target_dir / "ANALYSIS.md").write_text(analysis, encoding="utf-8")
    return target_dir


def test_authors_specs_compass_and_manifest(tmp_path):
    target_dir = _make_target(tmp_path)
    result = create_plan("Example", "Example", tmp_path, runner=_fake(_llm_output()))

    bp = target_dir / "blueprint"
    assert (bp / "ARCHITECTURE.md").is_file()
    assert (bp / "FEATURE-Status.md").is_file()
    assert (bp / "BUILD_PLAN_COMPASS.md").is_file()
    assert (target_dir / "MANIFEST.md").is_file()
    assert result.plan.state == "draft"
    assert {p.name for p in result.authored_files} == {"ARCHITECTURE.md", "FEATURE-Status.md"}
    assert result.warnings == ()
    # QuarterDeck projection written.
    assert (target_dir / "QuarterDeck" / "tickets.json").is_file()
    assert (target_dir / "QuarterDeck" / "console.yaml").is_file()


def test_replan_does_not_preserve_prior_states(tmp_path):
    target_dir = _make_target(tmp_path)
    # A prior plan left story-status implemented.
    (target_dir / "MANIFEST.md").write_text(_manifest(story_state="implemented"), encoding="utf-8")

    create_plan("Example", "Example", tmp_path, runner=_fake(_llm_output()))

    text = (target_dir / "MANIFEST.md").read_text(encoding="utf-8")
    assert "id: story-status\n" in text
    # Single-directional regenerate: the fresh plan is authored as-is (pending); no state merge.
    assert "state: implemented" not in text
    assert "state: pending" in text


def test_blocked_quality_refuses_before_llm(tmp_path):
    blocked = _ANALYSIS.replace("Quality: Questions", "Quality: Blocked")
    _make_target(tmp_path, analysis=blocked)

    def _boom(*a, **k):  # must never be called
        raise AssertionError("LLM runner called despite Blocked analysis")

    with pytest.raises(SpecificationError, match="Blocked"):
        create_plan("Example", "Example", tmp_path, runner=_boom)


def test_blockers_file_present_refuses(tmp_path):
    target_dir = _make_target(tmp_path)
    (target_dir / "BLOCKERS.md").write_text("# Blockers\n\n- Q?\n", encoding="utf-8")
    with pytest.raises(SpecificationError, match="BLOCKERS.md"):
        create_plan("Example", "Example", tmp_path, runner=_fake(_llm_output()))


def test_missing_analysis_refuses(tmp_path):
    _make_target(tmp_path, analysis=None)
    with pytest.raises(SpecificationError, match="ANALYSIS.md"):
        create_plan("Example", "Example", tmp_path, runner=_fake(_llm_output()))


def test_plan_create_blocked_block_refuses(tmp_path):
    _make_target(tmp_path)
    out = "=== PLAN_CREATE_BLOCKED.txt ===\nBlocked.\n=== END PLAN_CREATE_BLOCKED.txt ===\n"
    with pytest.raises(SpecificationError, match="cannot proceed"):
        create_plan("Example", "Example", tmp_path, runner=_fake(out))


def test_integrity_missing_implements_is_fatal(tmp_path):
    _make_target(tmp_path)
    out = _llm_output(_manifest(implements="GHOST.md"))
    with pytest.raises(SpecificationError, match="implements missing spec file"):
        create_plan("Example", "Example", tmp_path, runner=_fake(out))


def test_integrity_unknown_dependency_is_fatal(tmp_path):
    _make_target(tmp_path)
    manifest = _manifest().replace(
        "scope: both\nstate: pending", "scope: both\ndepends: ghost-id\nstate: pending"
    )
    with pytest.raises(SpecificationError, match="unknown id"):
        create_plan("Example", "Example", tmp_path, runner=_fake(_llm_output(manifest)))


def test_story_without_acceptance_is_fatal(tmp_path):
    _make_target(tmp_path)
    # Drop the ac block — a story with no acceptance gate must not be emitted.
    manifest = _manifest().split("## ac 1:")[0].rstrip() + "\n"
    with pytest.raises(SpecificationError, match="no acceptance check"):
        create_plan("Example", "Example", tmp_path, runner=_fake(_llm_output(manifest)))


def test_missing_manifest_block_refuses(tmp_path):
    _make_target(tmp_path)
    out = "=== ARCHITECTURE.md ===\n# ARCHITECTURE: X\n=== END ARCHITECTURE.md ===\n"
    with pytest.raises(SpecificationError, match="missing === MANIFEST.md"):
        create_plan("Example", "Example", tmp_path, runner=_fake(out))


def test_failed_run_refuses(tmp_path):
    _make_target(tmp_path)
    with pytest.raises(SpecificationError, match="execution failed"):
        create_plan(
            "Example", "Example", tmp_path, runner=lambda *a, **k: FakeRun(ok=False, text="")
        )


def _write_spike(path: Path, questions: list[dict]) -> Path:
    path.write_text(
        json.dumps({"id": path.stem, "title": "Spike", "questions": questions}),
        encoding="utf-8",
    )
    return path


def test_answered_spike_keeps_only_answered_questions(tmp_path):
    spike = _write_spike(
        tmp_path / "spike-x.json",
        [
            {"id": "a", "prompt": "?", "answer": "yes"},
            {"id": "b", "prompt": "?"},
            {"id": "c", "prompt": "?", "answer": "   "},
        ],
    )
    result = _answered_spike(spike)
    assert [q["id"] for q in result["questions"]] == ["a"]


def test_answered_spike_returns_none_when_unanswered(tmp_path):
    spike = _write_spike(
        tmp_path / "spike-y.json",
        [{"id": "a", "prompt": "?"}, {"id": "b", "prompt": "?", "answer": ""}],
    )
    assert _answered_spike(spike) is None

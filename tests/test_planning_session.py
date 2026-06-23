"""Tests for the LLM-driven ``drydock plan create`` (planning_session.create_plan).

A fake runner supplies canned delimited-block output; no API credits are spent.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import pytest

from drydock.errors import SpecificationError
from drydock.planning_session import (
    _answered_discovery,
    _assemble_prompt,
    _parse_blocks,
    create_plan,
    ensure_feedback_file,
)


def test_default_feedback_heading_is_plan_compass(tmp_path):
    assert ensure_feedback_file(tmp_path) == "# Plan Compass\n"


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
    return (
        f"=== ARCHITECTURE.md ===\n{arch}\n=== END ARCHITECTURE.md ===\n"
        f"=== FEATURE-Status.md ===\n{feature}\n=== END FEATURE-Status.md ===\n"
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
    assert not (target_dir / "BUILD_COMPASS.md").exists()
    assert (target_dir / "MANIFEST.md").is_file()
    assert result.plan.state == "draft"
    assert {p.name for p in result.authored_files} == {"ARCHITECTURE.md", "FEATURE-Status.md"}
    assert result.warnings == ()
    # QuarterDeck projection written.
    assert (target_dir / "QuarterDeck" / "tickets.json").is_file()
    assert (target_dir / "QuarterDeck" / "console.yaml").is_file()


def test_cli_overrides_are_passed_to_runner(tmp_path):
    _make_target(tmp_path)
    calls = []

    def runner(*a, **k):
        calls.append(k)
        return FakeRun(text=_llm_output())

    result = create_plan(
        "Example",
        "Example",
        tmp_path,
        runner=runner,
        model="gpt-5.4",
        llm_provider="codex",
    )

    assert result.plan.state == "draft"
    assert calls[0]["model"] == "gpt-5.4"
    assert calls[0]["llm"] == "codex"


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


def test_integrity_accepts_whitespace_separated_dependencies(tmp_path):
    _make_target(tmp_path)
    manifest = (
        _manifest()
        + """
## story 2: Follow-up
id: story-follow-up
parent: feature-status
summary: Extend the status command.
implements: FEATURE-Status.md
scope: both
depends: story-status story-spike
state: pending

## spike 2: Research
id: story-spike
summary: Investigate a dependency.
state: closed/verified

## ac 2: Follow-up exits successfully
id: ac-follow-up-exits
parent: story-follow-up
kind: assertion
state: pending
"""
    )

    result = create_plan("Example", "Example", tmp_path, runner=_fake(_llm_output(manifest)))

    assert result.plan.by_id()["story-follow-up"].depends == ("story-status", "story-spike")


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


def test_missing_required_block_explains_required_response_contract(tmp_path):
    _make_target(tmp_path)
    out = "=== ARCHITECTURE.md ===\n# ARCHITECTURE: X\n=== END ARCHITECTURE.md ===\n"

    with pytest.raises(SpecificationError, match="only delimited artifact blocks"):
        create_plan("Example", "Example", tmp_path, runner=_fake(out))


def test_simulated_write_calls_recover_plan_artifacts(tmp_path):
    target_dir = _make_target(tmp_path)
    blueprint_dir = target_dir / "blueprint"
    output = _llm_output()
    calls = []
    for name, content in _parse_blocks(output).items():
        path = target_dir / name if name == "MANIFEST.md" else blueprint_dir / name
        calls.append(
            '<invoke name="Write">\n'
            f'<parameter name="file_path">{path}</parameter>\n'
            f'<parameter name="content">{content}</parameter>\n'
            "</invoke>"
        )

    result = create_plan("Example", "Example", tmp_path, runner=_fake("\n".join(calls)))

    assert result.plan.state == "draft"
    assert (target_dir / "MANIFEST.md").is_file()
    assert (blueprint_dir / "FEATURE-Status.md").is_file()


def test_failed_run_refuses(tmp_path):
    _make_target(tmp_path)
    with pytest.raises(SpecificationError, match="execution failed"):
        create_plan(
            "Example", "Example", tmp_path, runner=lambda *a, **k: FakeRun(ok=False, text="")
        )


def _write_discovery(path: Path, questions: list[dict]) -> Path:
    path.write_text(
        json.dumps({"id": path.stem, "title": "Discovery", "questions": questions}),
        encoding="utf-8",
    )
    return path


def test_answered_discovery_keeps_only_answered_questions(tmp_path):
    discovery = _write_discovery(
        tmp_path / "discovery-x.json",
        [
            {"id": "a", "prompt": "?", "answer": "yes"},
            {"id": "b", "prompt": "?"},
            {"id": "c", "prompt": "?", "answer": "   "},
        ],
    )
    result = _answered_discovery(discovery)
    assert [q["id"] for q in result["questions"]] == ["a"]


def test_answered_discovery_returns_none_when_unanswered(tmp_path):
    discovery = _write_discovery(
        tmp_path / "discovery-y.json",
        [{"id": "a", "prompt": "?"}, {"id": "b", "prompt": "?", "answer": ""}],
    )
    assert _answered_discovery(discovery) is None


def test_assemble_prompt_orders_sections_by_input_tokens(tmp_path):
    target_dir = _make_target(tmp_path)
    (target_dir / "COMPASS.md").write_text("# Compass\n\nDirection.\n", encoding="utf-8")
    (target_dir / "SOUNDINGS.md").write_text("# Soundings\n\n- AC.\n", encoding="utf-8")
    blueprint_dir = target_dir / "blueprint"

    result = _assemble_prompt(
        "PROMPT BODY",
        target_dir,
        blueprint_dir,
        _ANALYSIS,
        "2026-06-17",
        feedback_text="Decompose by module.",
        input_tokens=(
            "COMPASS.md",
            "PLAN_COMPASS.md",
            "ANALYSIS.md",
            "SOUNDINGS.md",
            "BLOCKERS.md",
            "TYPED_SPEC",
        ),
    )

    # COMPASS leads the file sections; the standing directive reads next; sources land last.
    order = [
        result.index("## Compass"),
        result.index("## Plan Compass"),
        result.index("ANALYSIS.md (the reviewed plan)"),
        result.index("## SOUNDINGS.md"),
        result.index("Imported source files"),
    ]
    assert order == sorted(order)
    # BLOCKERS.md is the plan-create gate: listed, but never injected as a content section.
    assert "## BLOCKERS.md" not in result


def test_assemble_prompt_reorders_when_tokens_reordered(tmp_path):
    target_dir = _make_target(tmp_path)
    (target_dir / "COMPASS.md").write_text("# Compass\n\nDirection.\n", encoding="utf-8")
    blueprint_dir = target_dir / "blueprint"

    result = _assemble_prompt(
        "BODY",
        target_dir,
        blueprint_dir,
        _ANALYSIS,
        "2026-06-17",
        input_tokens=("ANALYSIS.md", "COMPASS.md"),
    )
    assert result.index("ANALYSIS.md (the reviewed plan)") < result.index("## Compass")


def test_assemble_prompt_injects_plan_compass_instruction_block(tmp_path):
    target_dir = _make_target(tmp_path)
    blueprint_dir = target_dir / "blueprint"

    result = _assemble_prompt(
        "BODY",
        target_dir,
        blueprint_dir,
        _ANALYSIS,
        "2026-06-17",
        feedback_text="Decompose by module.",
        input_tokens=("PLAN_COMPASS.md",),
    )

    assert "## Plan Compass" in result
    assert "standing user steering" in result
    assert "## Plan Compass content" in result


def test_assemble_prompt_labels_source_files_with_fixed_roles(tmp_path):
    target_dir = _make_target(tmp_path)
    blueprint_dir = target_dir / "blueprint"

    result = _assemble_prompt(
        "BODY",
        target_dir,
        blueprint_dir,
        _ANALYSIS,
        "2026-06-17",
        input_tokens=("TYPED_SPEC",),
    )

    assert "### sources/request.md - source reference" in result

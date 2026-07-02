"""Tests for the LLM-driven ``drydock plan create`` (planning_session.create_plan).

A fake runner supplies canned delimited-block output; no API credits are spent.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

import pytest

from drydock.build_plan import AppliedSpecRecord, parse_build_plan
from drydock.errors import SpecificationError
from drydock.planning_session import (
    _answered_discovery,
    _assemble_prompt,
    _load_prior_plan_state,
    _parse_blocks,
    _repair_missing_leading_delimiter,
    _spec_is_dirty,
    create_plan,
    ensure_feedback_file,
)


def test_default_feedback_heading_is_plan_compass(tmp_path):
    assert ensure_feedback_file(tmp_path) == "# Plan Compass\n"


def test_plan_prompt_declares_strict_artifact_contract():
    prompt = (Path(__file__).parents[1] / "prompts" / "plan_create.md").read_text(encoding="utf-8")

    assert "Emit exactly one response mode" in prompt
    assert "### Success Mode" in prompt
    assert "=== PLAN_CREATE_ERROR.txt ===" in prompt
    assert "Never emit `MANIFEST.md` in Error Mode or Blocked Mode" in prompt
    assert "Every `implements:` filename in `MANIFEST.md` must exactly match" in prompt
    assert "Never emit `AGENTS.md`." in prompt


def test_validate_plan_output_rejects_agents_artifact(tmp_path):
    from drydock.planning_session import _validate_plan_output

    manifest = _manifest(implements="AGENTS.md")
    blocks = {
        "MANIFEST.md": manifest,
        "AGENTS.md": "# AGENTS\n",
    }

    with pytest.raises(SpecificationError, match="Forbidden artifact\\(s\\): AGENTS.md"):
        _validate_plan_output(blocks, tmp_path, FakeRun(text=_llm_output(manifest)))


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

## Programmatic Acceptance

- None.

## User Acceptance

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
    stderr: str = ""
    execution_id: str = "exec-fake"


@pytest.fixture(autouse=True)
def fake_compactor(monkeypatch):
    def fake(prompt, working_directory, **kwargs):
        return FakeRun(text="# Compact\n\nBody\n", execution_id="compact-fake")

    monkeypatch.setattr("drydock.rigging_compact.run_prompt", fake)


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
    planning = (target_dir / "QuarterDeck" / "planning-session.md").read_text(encoding="utf-8")
    assert "manifest build tree" in planning
    assert "Approve the complete plan" not in planning


def test_reuse_mode_preserves_existing_spec_bodies_and_plans_from_them(tmp_path):
    target_dir = _make_target(tmp_path)
    blueprint_dir = target_dir / "blueprint"
    architecture = blueprint_dir / "ARCHITECTURE.md"
    feature = blueprint_dir / "FEATURE-Status.md"
    architecture.write_text(
        "# ARCHITECTURE: Example\n\n"
        "| Field       | Value |\n"
        "|-------------|-------|\n"
        "| Version     | 20260630 V1 |\n"
        "| Description | Existing architecture |\n"
        "| Depends On  | |\n"
        "| Provides    | |\n"
        "| Phase       | 1 |\n\n"
        "## Modules\n\n"
        "- Preserve this architecture body.\n",
        encoding="utf-8",
    )
    feature.write_text(
        "# FEATURE: Status\n\n"
        "| Field       | Value |\n"
        "|-------------|-------|\n"
        "| Version     | 20260630 V1 |\n"
        "| Description | Existing status feature |\n"
        "| Depends On  | ARCHITECTURE.md |\n"
        "| Provides    | drydock status |\n"
        "| Phase       | 2 |\n\n"
        "## Trigger\n\n"
        "- Preserve this feature body.\n",
        encoding="utf-8",
    )
    prompt_texts: list[str] = []
    progress: list[str] = []
    manifest = _manifest(implements="ARCHITECTURE.md").replace(
        "## story 1: Deliver Status\n"
        "id: story-status\n"
        "parent: feature-status\n"
        "summary: Build the status command.\n"
        "implements: ARCHITECTURE.md\n"
        "scope: both\n"
        "state: pending\n",
        "## story 1: Architecture Foundation\n"
        "id: foundation\n"
        "parent: feature-status\n"
        "summary: Keep the architecture specification as the foundation.\n"
        "implements: ARCHITECTURE.md\n"
        "scope: both\n"
        "state: pending\n"
        "\n"
        "## ac 1: Architecture foundation exists\n"
        "id: ac-foundation\n"
        "parent: foundation\n"
        "kind: assertion\n"
        "state: pending\n"
        "\n"
        "## story 2: Deliver Status\n"
        "id: story-status\n"
        "parent: feature-status\n"
        "summary: Build the status command.\n"
        "implements: FEATURE-Status.md\n"
        "scope: both\n"
        "depends: foundation\n"
        "state: pending\n",
    )

    def runner(prompt_text, *a, **k):
        prompt_texts.append(prompt_text)
        return FakeRun(text=f"=== MANIFEST.md ===\n{manifest}\n=== END MANIFEST.md ===\n")

    result = create_plan("Example", "Example", tmp_path, runner=runner, on_text=progress.append)

    assert result.plan.state == "draft"
    assert progress[0].startswith(
        "[plan] mode=reuse-manifest-first prompt=plan_reuse existing_specs=2 imported_sources=1"
    )
    assert "reuse-mode: preserving existing Blueprint specs" in "".join(progress)
    assert "# Request" not in prompt_texts[0]
    assert "Preserve this architecture body." in prompt_texts[0]
    assert "Preserve this feature body." in prompt_texts[0]
    assert "Do not emit any existing conformant Blueprint file again." in prompt_texts[0]
    assert "## Programmatic Acceptance" in architecture.read_text(encoding="utf-8")
    assert "## Guardrails" in feature.read_text(encoding="utf-8")
    assert "Preserve this architecture body." in architecture.read_text(encoding="utf-8")
    assert "Preserve this feature body." in feature.read_text(encoding="utf-8")


def test_reuse_mode_normalizes_malformed_existing_spec_header(tmp_path):
    target_dir = _make_target(tmp_path)
    blueprint_dir = target_dir / "blueprint"
    architecture = blueprint_dir / "ARCHITECTURE.md"
    architecture.write_text("Architecture overview only.\n", encoding="utf-8")
    feature = blueprint_dir / "FEATURE-Status.md"
    feature.write_text(
        "# FEATURE: Status\n\n## Trigger\n\n- Existing feature content.\n",
        encoding="utf-8",
    )
    manifest = (
        "# MANIFEST: Example\n"
        "updated: 2026-06-16\n"
        "plan_hash: test\n"
        "state: draft\n\n"
        "## feature 1: Status\n"
        "id: feature-status\n"
        "summary: Deliver the status command.\n"
        "state: pending\n\n"
        "## story 1: Deliver Status\n"
        "id: story-status\n"
        "parent: feature-status\n"
        "summary: Build the status command.\n"
        "implements: FEATURE-Status.md\n"
        "scope: both\n"
        "state: pending\n\n"
        "## ac 1: Status command exits successfully\n"
        "id: ac-status-exits\n"
        "parent: story-status\n"
        "kind: assertion\n"
        "state: pending\n"
    )

    create_plan(
        "Example",
        "Example",
        tmp_path,
        runner=_fake(f"=== MANIFEST.md ===\n{manifest}\n=== END MANIFEST.md ===\n"),
    )

    arch_text = architecture.read_text(encoding="utf-8")
    feature_text = feature.read_text(encoding="utf-8")
    assert arch_text.startswith("# ARCHITECTURE: Architecture")
    assert re.search(r"\| Version\s+\|\s+\d{8} V1 \|", arch_text)
    assert "## Programmatic Acceptance" in arch_text
    assert feature_text.startswith("# FEATURE: Status")
    assert "## Open Questions" in feature_text


def test_plan_adopts_typed_source_specs_then_reuses_them(tmp_path):
    target_dir = _make_target(tmp_path)
    sources_dir = target_dir / "blueprint" / "sources"
    (sources_dir / "ARCHITECTURE.md").write_text(
        "# ARCHITECTURE: Imported Architecture\n\n## Modules\n\n- Imported architecture body.\n",
        encoding="utf-8",
    )
    (sources_dir / "FEATURE-Status.md").write_text(
        "# FEATURE: Imported Status\n\n## Trigger\n\n- Imported feature body.\n",
        encoding="utf-8",
    )
    progress: list[str] = []
    manifest = (
        "# MANIFEST: Example\n"
        "updated: 2026-06-16\n"
        "plan_hash: test\n"
        "state: draft\n\n"
        "## feature 1: Status\n"
        "id: feature-status\n"
        "summary: Deliver the status command.\n"
        "state: pending\n\n"
        "## story 1: Architecture Foundation\n"
        "id: foundation\n"
        "parent: feature-status\n"
        "summary: Keep the architecture specification as the foundation.\n"
        "implements: ARCHITECTURE.md\n"
        "scope: both\n"
        "state: pending\n\n"
        "## ac 1: Architecture foundation exists\n"
        "id: ac-foundation\n"
        "parent: foundation\n"
        "kind: assertion\n"
        "state: pending\n\n"
        "## story 2: Deliver Status\n"
        "id: story-status\n"
        "parent: feature-status\n"
        "summary: Build the status command.\n"
        "implements: FEATURE-Status.md\n"
        "scope: both\n"
        "depends: foundation\n"
        "state: pending\n\n"
        "## ac 2: Status command exits successfully\n"
        "id: ac-status-exits\n"
        "parent: story-status\n"
        "kind: assertion\n"
        "state: pending\n"
    )

    create_plan(
        "Example",
        "Example",
        tmp_path,
        runner=_fake(f"=== MANIFEST.md ===\n{manifest}\n=== END MANIFEST.md ===\n"),
        on_text=progress.append,
    )

    blueprint_dir = target_dir / "blueprint"
    arch = blueprint_dir / "ARCHITECTURE.md"
    feature = blueprint_dir / "FEATURE-Status.md"
    assert arch.is_file()
    assert feature.is_file()
    joined = "".join(progress)
    assert "mode=reuse-manifest-first" in joined
    assert "adopted 2 typed spec file(s) from blueprint/sources into blueprint/" in joined
    assert "Imported architecture body." in arch.read_text(encoding="utf-8")
    assert "Imported feature body." in feature.read_text(encoding="utf-8")


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


def test_full_rewrite_mode_reports_prompt_and_inventory(tmp_path):
    _make_target(tmp_path)
    progress: list[str] = []

    create_plan(
        "Example", "Example", tmp_path, runner=_fake(_llm_output()), on_text=progress.append
    )

    assert progress[0].startswith(
        "[plan] mode=full-rewrite prompt=plan_create existing_specs=0 imported_sources=1"
    )


def test_speckit_source_selects_speckit_prompt(tmp_path):
    target_dir = _make_target(tmp_path)
    sources = target_dir / "blueprint" / "sources"
    (sources / ".specify" / "memory").mkdir(parents=True)
    (sources / ".specify" / "memory" / "constitution.md").write_text(
        "# Constitution\n\nBuild reliable software.\n", encoding="utf-8"
    )
    (sources / "specs" / "status").mkdir(parents=True)
    (sources / "specs" / "status" / "spec.md").write_text(
        "# Feature: Status\n\nUsers can check status.\n", encoding="utf-8"
    )

    progress: list[str] = []
    conversion_report = "# Conversion Report: Example\n\n## Mapped\n\n- None.\n"
    manifest = _manifest()
    text = (
        f"=== ARCHITECTURE.md ===\n"
        f"{_SPEC_HEADER.format(ftype='ARCHITECTURE', name='Example', ac='None.')}\n"
        f"=== END ARCHITECTURE.md ===\n"
        f"=== FEATURE-Status.md ===\n"
        f"{_SPEC_HEADER.format(ftype='FEATURE', name='Status', ac='None.')}\n"
        f"=== END FEATURE-Status.md ===\n"
        f"=== CONVERSION_REPORT.md ===\n{conversion_report}\n=== END CONVERSION_REPORT.md ===\n"
        f"=== MANIFEST.md ===\n{manifest}\n=== END MANIFEST.md ===\n"
    )

    result = create_plan(
        "Example", "Example", tmp_path, runner=_fake(text), on_text=progress.append
    )

    assert progress[0].startswith(
        "[plan] mode=speckit-translate prompt=plan_create_speckit "
        "existing_specs=0 imported_sources=3"
    )
    assert (target_dir / "blueprint" / "CONVERSION_REPORT.md").read_text(
        encoding="utf-8"
    ) == conversion_report
    assert result.plan.project == "Example"


def _manifest_with_applied(story_state: str, spec_name: str, sha256: str, story_id: str) -> str:
    """Build a prior MANIFEST.md with applied_specs in the preamble."""
    return (
        f"# MANIFEST: Example\n"
        f"updated: 2026-06-16\n"
        f"plan_hash: test\n"
        f"state: draft\n"
        f"applied_specs: |\n"
        f"  {spec_name} sha256={sha256} commit=abc123 applied_by={story_id} applied_at=2026-06-01T00:00:00Z\n"
        f"\n"
        f"## feature 1: Status\n"
        f"id: feature-status\n"
        f"summary: Deliver the status command.\n"
        f"state: pending\n"
        f"\n"
        f"## story 1: Deliver Status\n"
        f"id: story-status\n"
        f"parent: feature-status\n"
        f"summary: Build the status command.\n"
        f"implements: {spec_name}\n"
        f"scope: both\n"
        f"state: {story_state}\n"
        f"\n"
        f"## ac 1: Status command exits successfully\n"
        f"id: ac-status-exits\n"
        f"parent: story-status\n"
        f"kind: assertion\n"
        f"state: pending\n"
    )


def _spec_sha256(path: Path) -> str:
    from hashlib import sha256 as _sha256

    return _sha256(path.read_bytes()).hexdigest()


def test_replan_preserves_closed_verified_block_with_clean_file(tmp_path):
    target_dir = _make_target(tmp_path)
    blueprint_dir = target_dir / "blueprint"
    spec_file = blueprint_dir / "FEATURE-Status.md"
    spec_file.parent.mkdir(parents=True, exist_ok=True)
    spec_file.write_text("# Feature\n", encoding="utf-8")

    prior = _manifest_with_applied(
        "closed/verified", "FEATURE-Status.md", _spec_sha256(spec_file), "story-status"
    )
    (target_dir / "MANIFEST.md").write_text(prior, encoding="utf-8")

    create_plan("Example", "Example", tmp_path, runner=_fake(_llm_output()))

    text = (target_dir / "MANIFEST.md").read_text(encoding="utf-8")
    assert "state: closed/verified" in text


def test_replan_resets_dirty_block_to_pending(tmp_path):
    target_dir = _make_target(tmp_path)
    blueprint_dir = target_dir / "blueprint"
    spec_file = blueprint_dir / "FEATURE-Status.md"
    spec_file.parent.mkdir(parents=True, exist_ok=True)
    spec_file.write_text("# Feature\n", encoding="utf-8")

    # Record a stale sha256 so the file appears dirty.
    prior = _manifest_with_applied(
        "closed/verified", "FEATURE-Status.md", "000000000000", "story-status"
    )
    (target_dir / "MANIFEST.md").write_text(prior, encoding="utf-8")

    create_plan("Example", "Example", tmp_path, runner=_fake(_llm_output()))

    text = (target_dir / "MANIFEST.md").read_text(encoding="utf-8")
    assert "state: closed/verified" not in text
    assert "state: pending" in text


def test_replan_restores_applied_specs(tmp_path):
    target_dir = _make_target(tmp_path)
    blueprint_dir = target_dir / "blueprint"
    spec_file = blueprint_dir / "FEATURE-Status.md"
    spec_file.parent.mkdir(parents=True, exist_ok=True)
    spec_file.write_text("# Feature\n", encoding="utf-8")

    prior = _manifest_with_applied(
        "closed/verified", "FEATURE-Status.md", _spec_sha256(spec_file), "story-status"
    )
    (target_dir / "MANIFEST.md").write_text(prior, encoding="utf-8")

    create_plan("Example", "Example", tmp_path, runner=_fake(_llm_output()))

    plan = parse_build_plan(target_dir / "MANIFEST.md")
    assert "FEATURE-Status.md" in plan.applied_specs
    assert plan.applied_specs["FEATURE-Status.md"].applied_by == "story-status"


def test_plan_normalizes_feature_context_and_auto_compacts(tmp_path):
    target_dir = _make_target(tmp_path)
    db = _SPEC_HEADER.format(ftype="DATABASE", name="Example Data", ac="None.")
    manifest = _manifest().replace(
        "scope: both\nstate: pending",
        "scope: both\ncontext: README.md, ARCHITECTURE.md\nstate: pending",
    )
    out = (
        f"=== ARCHITECTURE.md ===\n{_SPEC_HEADER.format(ftype='ARCHITECTURE', name='Example', ac='None.')}\n=== END ARCHITECTURE.md ===\n"
        f"=== DATABASE.md ===\n{db}\n=== END DATABASE.md ===\n"
        f"=== FEATURE-Status.md ===\n{_SPEC_HEADER.format(ftype='FEATURE', name='Status', ac='Status command exits successfully.')}\n=== END FEATURE-Status.md ===\n"
        f"=== MANIFEST.md ===\n{manifest}\n=== END MANIFEST.md ===\n"
    )

    create_plan("Example", "Example", tmp_path, runner=_fake(out))

    text = (target_dir / "MANIFEST.md").read_text(encoding="utf-8")
    assert "context: README.md, ARCHITECTURE_compact.md, DATABASE_compact.md" in text
    assert (target_dir / "blueprint" / "ARCHITECTURE_compact.md").is_file()
    assert (target_dir / "blueprint" / "DATABASE_compact.md").is_file()


def test_replan_preserves_spike_finding(tmp_path):
    spike_manifest = """# MANIFEST: Example
updated: 2026-06-16
plan_hash: test
state: draft

## spike 1: Choose parser
id: spike-parser
summary: Pick the best parser.
state: closed/verified
finding: Use the stdlib csv module.

## story 1: Deliver Status
id: story-status
summary: Build the status command.
implements: FEATURE-Status.md
scope: both
state: pending

## ac 1: Status exits
id: ac-status-exits
parent: story-status
kind: assertion
state: pending
"""
    target_dir = _make_target(tmp_path)
    (target_dir / "MANIFEST.md").write_text(spike_manifest, encoding="utf-8")

    spike_llm = (
        "=== ARCHITECTURE.md ===\n"
        + _SPEC_HEADER.format(ftype="ARCHITECTURE", name="Example", ac="None.")
        + "\n=== END ARCHITECTURE.md ===\n"
        "=== FEATURE-Status.md ===\n"
        + _SPEC_HEADER.format(ftype="FEATURE", name="Status", ac="Status exits.")
        + "\n=== END FEATURE-Status.md ===\n"
        "=== MANIFEST.md ===\n"
        + spike_manifest.replace("finding: Use the stdlib csv module.", "finding:")
        + "\n=== END MANIFEST.md ===\n"
    )
    create_plan("Example", "Example", tmp_path, runner=_fake(spike_llm))

    text = (target_dir / "MANIFEST.md").read_text(encoding="utf-8")
    assert "Use the stdlib csv module" in text


def test_load_prior_plan_state_returns_empty_when_no_manifest(tmp_path):
    specs, states = _load_prior_plan_state(tmp_path / "MANIFEST.md")
    assert specs == {}
    assert states == {}


def test_spec_is_dirty_false_when_no_applied_record(tmp_path):
    assert not _spec_is_dirty("FEATURE.md", tmp_path, {})


def test_spec_is_dirty_true_when_hash_changed(tmp_path):
    spec = tmp_path / "FEATURE.md"
    spec.write_text("changed content", encoding="utf-8")
    record = AppliedSpecRecord(
        path="FEATURE.md",
        sha256="000000000000",
        commit="-",
        applied_by="story-x",
        applied_at="2026-06-01T00:00:00Z",
    )
    assert _spec_is_dirty("FEATURE.md", tmp_path, {"FEATURE.md": record})


def test_spec_is_dirty_false_when_hash_matches(tmp_path):
    from hashlib import sha256

    spec = tmp_path / "FEATURE.md"
    spec.write_text("content", encoding="utf-8")
    digest = sha256(spec.read_bytes()).hexdigest()
    record = AppliedSpecRecord(
        path="FEATURE.md",
        sha256=digest,
        commit="-",
        applied_by="story-x",
        applied_at="2026-06-01T00:00:00Z",
    )
    assert not _spec_is_dirty("FEATURE.md", tmp_path, {"FEATURE.md": record})


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


def test_plan_create_error_block_refuses_without_writes(tmp_path):
    target_dir = _make_target(tmp_path)
    out = (
        "=== PLAN_CREATE_ERROR.txt ===\n"
        "Planning output was not produced.\n"
        "Error type: insufficient-specification\n"
        "Reason:\n"
        "- Missing route ownership.\n"
        "Required action:\n"
        "- Clarify route ownership.\n"
        "=== END PLAN_CREATE_ERROR.txt ===\n"
    )

    with pytest.raises(SpecificationError, match="could not produce a complete plan"):
        create_plan("Example", "Example", tmp_path, runner=_fake(out))

    assert not (target_dir / "MANIFEST.md").exists()
    assert not (target_dir / "blueprint" / "ARCHITECTURE.md").exists()
    assert not (target_dir / "QuarterDeck" / "tickets.json").exists()


def test_integrity_missing_implements_is_fatal(tmp_path):
    target_dir = _make_target(tmp_path)
    out = _llm_output(_manifest(implements="GHOST.md"))
    with pytest.raises(SpecificationError, match="implements missing spec file"):
        create_plan("Example", "Example", tmp_path, runner=_fake(out))
    assert not (target_dir / "MANIFEST.md").exists()
    assert not (target_dir / "blueprint" / "ARCHITECTURE.md").exists()
    assert not (target_dir / "QuarterDeck" / "tickets.json").exists()


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
    target_dir = _make_target(tmp_path)
    out = "=== ARCHITECTURE.md ===\n# ARCHITECTURE: X\n=== END ARCHITECTURE.md ===\n"
    with pytest.raises(SpecificationError, match="missing === MANIFEST.md"):
        create_plan("Example", "Example", tmp_path, runner=_fake(out))
    assert not (target_dir / "blueprint" / "ARCHITECTURE.md").exists()


def test_missing_required_block_explains_required_response_contract(tmp_path):
    _make_target(tmp_path)
    out = "=== ARCHITECTURE.md ===\n# ARCHITECTURE: X\n=== END ARCHITECTURE.md ===\n"

    with pytest.raises(SpecificationError, match="only delimited artifact blocks"):
        create_plan("Example", "Example", tmp_path, runner=_fake(out))


def test_text_outside_blocks_refuses_without_writes(tmp_path):
    target_dir = _make_target(tmp_path)
    out = "Here is the plan:\n" + _llm_output()

    with pytest.raises(SpecificationError, match="Text appeared outside"):
        create_plan("Example", "Example", tmp_path, runner=_fake(out))

    assert not (target_dir / "MANIFEST.md").exists()
    assert not (target_dir / "blueprint" / "FEATURE-Status.md").exists()
    assert not (target_dir / "QuarterDeck" / "tickets.json").exists()


def test_missing_first_delimiter_is_recovered(tmp_path):
    target_dir = _make_target(tmp_path)
    output = _llm_output()
    repaired = output.replace("=== ARCHITECTURE.md ===\n", "", 1)

    result = create_plan("Example", "Example", tmp_path, runner=_fake(repaired))

    assert result.plan.by_id()["story-status"].fields.get("implements") == ("FEATURE-Status.md",)
    assert (target_dir / "MANIFEST.md").exists()
    assert (target_dir / "blueprint" / "ARCHITECTURE.md").exists()


def test_missing_final_delimiter_is_recovered(tmp_path):
    target_dir = _make_target(tmp_path)
    output = _llm_output().replace("\n=== END MANIFEST.md ===\n", "\n", 1)

    result = create_plan("Example", "Example", tmp_path, runner=_fake(output))

    assert result.plan.by_id()["story-status"].fields.get("implements") == ("FEATURE-Status.md",)
    assert (target_dir / "MANIFEST.md").exists()


def test_repair_missing_leading_delimiter_refuses_ordinary_preamble():
    assert _repair_missing_leading_delimiter("Here is the plan.\n" + _llm_output()) is None


def test_transition_text_between_blocks_is_ignored(tmp_path):
    target_dir = _make_target(tmp_path)
    output = _llm_output().replace(
        "=== SCREEN-SETUP-SUMMARY.md ===\n",
        "Continuing with the remaining files next.\n=== SCREEN-SETUP-SUMMARY.md ===\n",
        1,
    )

    result = create_plan("Example", "Example", tmp_path, runner=_fake(output))

    assert result.plan.by_id()["story-status"].fields.get("implements") == ("FEATURE-Status.md",)
    assert (target_dir / "MANIFEST.md").exists()


def test_transition_text_between_write_calls_is_ignored(tmp_path):
    target_dir = _make_target(tmp_path)
    blueprint_dir = target_dir / "blueprint"
    output = _llm_output()
    calls = []
    for index, (name, content) in enumerate(_parse_blocks(output).items()):
        path = target_dir / name if name == "MANIFEST.md" else blueprint_dir / name
        calls.append(
            '<invoke name="Write">\n'
            f'<parameter name="file_path">{path}</parameter>\n'
            f'<parameter name="content">{content}</parameter>\n'
            "</invoke>"
        )
        if index == 0:
            calls.append("Continuing with the remaining files next.")

    result = create_plan("Example", "Example", tmp_path, runner=_fake("\n".join(calls)))

    assert result.plan.by_id()["story-status"].fields.get("implements") == ("FEATURE-Status.md",)
    assert (target_dir / "MANIFEST.md").exists()


def test_duplicate_artifact_block_refuses_without_writes(tmp_path):
    target_dir = _make_target(tmp_path)
    arch = _SPEC_HEADER.format(ftype="ARCHITECTURE", name="Example", ac="None.")
    out = (
        f"=== ARCHITECTURE.md ===\n{arch}\n=== END ARCHITECTURE.md ===\n"
        f"=== ARCHITECTURE.md ===\n{arch}\n=== END ARCHITECTURE.md ===\n"
        f"=== MANIFEST.md ===\n{_manifest(implements='ARCHITECTURE.md')}\n=== END MANIFEST.md ===\n"
    )

    with pytest.raises(SpecificationError, match="Duplicate artifact block"):
        create_plan("Example", "Example", tmp_path, runner=_fake(out))

    assert not (target_dir / "MANIFEST.md").exists()
    assert not (target_dir / "blueprint" / "ARCHITECTURE.md").exists()


def test_simulated_write_calls_are_recovered(tmp_path):
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

    assert result.plan.by_id()["story-status"].fields.get("implements") == ("FEATURE-Status.md",)
    assert (target_dir / "MANIFEST.md").exists()
    assert (blueprint_dir / "FEATURE-Status.md").exists()


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
        result.index('filename="COMPASS.md"'),
        result.index('filename="PLAN_COMPASS.md"'),
        result.index('filename="ANALYSIS.md"'),
        result.index('filename="SOUNDINGS.md"'),
        result.index("Imported source files"),
    ]
    assert order == sorted(order)
    # BLOCKERS.md is the plan-create gate: listed, but never injected as a content section.
    assert 'filename="BLOCKERS.md"' not in result


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
    assert result.index('filename="ANALYSIS.md"') < result.index('filename="COMPASS.md"')


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

    assert 'filename="PLAN_COMPASS.md"' in result
    assert "user steering" in result


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

    assert 'filename="sources/request.md"' in result


def test_assemble_prompt_excludes_listed_source_filenames(tmp_path):
    target_dir = _make_target(tmp_path)
    blueprint_dir = target_dir / "blueprint"
    (blueprint_dir / "sources" / "BUILD_PLAN.md").write_text("ignore me", encoding="utf-8")
    (target_dir / "EXCLUDE_FILES.md").write_text(
        "# Exclude Files\n\n## Excluded files\n- BUILD_PLAN.md\n",
        encoding="utf-8",
    )

    result = _assemble_prompt(
        "BODY",
        target_dir,
        blueprint_dir,
        _ANALYSIS,
        "2026-06-17",
        input_tokens=("TYPED_SPEC",),
    )

    assert 'filename="sources/request.md"' in result
    assert 'filename="sources/BUILD_PLAN.md"' not in result


def test_assemble_prompt_includes_change_tickets_in_typed_spec(tmp_path):
    target_dir = _make_target(tmp_path)
    blueprint_dir = target_dir / "blueprint"
    changes_dir = blueprint_dir / "changes"
    changes_dir.mkdir(parents=True)
    (changes_dir / "TICKET-001-AddCopy.md").write_text(
        "# Change Ticket: Add Copy\n\nAmends: FEATURE-Status.md\n",
        encoding="utf-8",
    )

    result = _assemble_prompt(
        "BODY",
        target_dir,
        blueprint_dir,
        _ANALYSIS,
        "2026-06-30",
        input_tokens=("TYPED_SPEC",),
    )

    assert 'filename="changes/TICKET-001-AddCopy.md"' in result
    assert "Change tickets" in result
    assert "Amends:" in result


def test_assemble_prompt_omits_change_ticket_section_when_no_changes(tmp_path):
    target_dir = _make_target(tmp_path)
    blueprint_dir = target_dir / "blueprint"

    result = _assemble_prompt(
        "BODY",
        target_dir,
        blueprint_dir,
        _ANALYSIS,
        "2026-06-30",
        input_tokens=("TYPED_SPEC",),
    )

    assert "Change tickets" not in result
    assert "ignore me" not in result

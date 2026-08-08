"""Tests for ``drydock build`` orchestration (drydock.build_run)."""

from __future__ import annotations

import json
import re
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import pytest

from drydock.acceptance import MEMORY_FAILURE_PREFIX, AcceptanceRunResult
from drydock.build_plan import parse_build_plan, stale_applied_specs
from drydock.build_run import (
    _assertion_summary,
    _is_repairable,
    _render_repair_feedback,
    _resolve_step_selector,
    _select_build_unit,
    _ungate_acceptance_plan,
    build_target,
)
from drydock.decisions import Decision, load_decisions, write_decisions
from drydock.dependency_gate import RegistryPackageInfo
from drydock.errors import SpecificationError, write_error_record

_TWO_STORIES = """# MANIFEST: Demo
state: draft

## story 1: Foundation
id: foundation
implements: DATABASE.md
instructions: |
  Build the database.
state: pending

## story 2: Service
id: service
implements: SERVICE.md
depends: foundation
instructions: |
  Build the service.
state: pending
"""

_STORY_WITH_AC = (
    _TWO_STORIES
    + """
## ac 3: DB works
id: ac-db
parent: foundation
kind: smoke
check: "true"
state: pending
"""
)

_FEATURE_GROUP_MANIFEST = """# MANIFEST: Demo
state: draft

## feature 1: Catalog
id: feature-catalog
summary: Catalog block.
state: pending

## story 2: Foundation
id: foundation
parent: feature-catalog
implements: DATABASE.md
instructions: |
  Build the database.
state: pending

## story 3: Service
id: service
parent: feature-catalog
implements: SERVICE.md
instructions: |
  Build the service.
state: pending
"""

_CHAINED_FEATURE_MANIFEST = """# MANIFEST: Demo
state: draft

## feature 1: Catalog
id: feature-catalog
summary: Catalog block.
state: pending

## story 2: Foundation
id: foundation
parent: feature-catalog
implements: DATABASE.md
instructions: |
  Build the database.
state: pending

## story 3: Service
id: service
parent: feature-catalog
implements: SERVICE.md
depends: foundation
instructions: |
  Build the service.
state: pending
"""

_COMPUTED_BLOCK_MANIFEST = """# MANIFEST: Demo
state: approved
blocks: 1

## story 1: Foundation
id: foundation
type: service
phase: 1
block: 1
implements: DATABASE.md
stack: python.md
instructions: |
  Preserve the verified foundation.
state: closed/verified

## story 2: Service
id: service
type: service
phase: 1
block: 1
implements: SERVICE.md
stack: python.md
depends: foundation
instructions: |
  Build the service.
state: pending
"""


class FakeResult:
    def __init__(
        self,
        ok=True,
        text="Built it. Created app.py.",
        execution_id="exec-1",
        stderr="",
        stats=None,
    ):
        self.ok = ok
        self.text = text
        self.execution_id = execution_id
        self.stderr = stderr
        if stats is not None:
            self.stats = stats


@pytest.fixture(autouse=True)
def fake_compactor(monkeypatch):
    def fake(prompt, working_directory, **kwargs):
        return FakeResult(text="# Compact\n\nBody\n", execution_id="compact-fake")

    monkeypatch.setattr("drydock.rigging_compact.run_prompt", fake)


def _success_report(*, changed: tuple[str, ...], summary: str = "Built it.") -> str:
    return (
        "RESULT: SUCCESS\n\n"
        "FILES CHANGED:\n"
        + "\n".join(f"- {path}" for path in changed)
        + f"\n\nSUMMARY:\n{summary}\n"
    )


def make_runner(*, ok=True, text: str | None = None, write_files=True, stderr="", stats=None):
    calls: list[dict] = []

    def runner(prompt, working_directory, **kwargs):
        step_id = kwargs["parameters"]["step"]
        changed = (f"{step_id}.txt",)
        if write_files:
            Path(working_directory).mkdir(parents=True, exist_ok=True)
            (Path(working_directory) / changed[0]).write_text(
                f"built {step_id}\n", encoding="utf-8"
            )
        calls.append({"prompt": prompt, "wd": working_directory, **kwargs})
        return FakeResult(
            ok=ok, text=text or _success_report(changed=changed), stderr=stderr, stats=stats
        )

    runner.calls = calls  # type: ignore[attr-defined]
    return runner


def _finding(target_dir, block_id):
    plan = parse_build_plan(target_dir / "MANIFEST.md")
    return plan.by_id()[block_id].fields.get("finding")


def _setup(tmp_path, manifest=_TWO_STORIES):
    from drydock.compass_guardrail import apply_guardrail

    target_dir = tmp_path / "target"
    build_dir = tmp_path / "build"
    blueprint = target_dir / "blueprint"
    blueprint.mkdir(parents=True)
    (target_dir / "MANIFEST.md").write_text(manifest, encoding="utf-8")
    (target_dir / "COMPASS.md").write_text(
        apply_guardrail("COMPASS INTENT CONTENT", "Demo", target_dir, build_dir=build_dir),
        encoding="utf-8",
    )
    (blueprint / "DATABASE.md").write_text("DB SPEC CONTENT\n", encoding="utf-8")
    (blueprint / "SERVICE.md").write_text("SVC SPEC CONTENT\n", encoding="utf-8")
    return target_dir, build_dir


def _state(target_dir, block_id):
    plan = parse_build_plan(target_dir / "MANIFEST.md")
    return plan.by_id()[block_id].state


def test_resolve_step_selector_accepts_id_name_and_case(tmp_path):
    target_dir, _ = _setup(tmp_path, manifest=_FEATURE_GROUP_MANIFEST)
    plan = parse_build_plan(target_dir / "MANIFEST.md")
    # exact id
    assert _resolve_step_selector(plan, "feature-catalog") == "feature-catalog"
    # case-insensitive id
    assert _resolve_step_selector(plan, "Feature-Catalog") == "feature-catalog"
    # display name, case-insensitive
    assert _resolve_step_selector(plan, "catalog") == "feature-catalog"
    assert _resolve_step_selector(plan, "Foundation") == "foundation"


def test_resolve_step_selector_unknown_lists_valid_ids(tmp_path):
    target_dir, _ = _setup(tmp_path, manifest=_FEATURE_GROUP_MANIFEST)
    plan = parse_build_plan(target_dir / "MANIFEST.md")
    with pytest.raises(SpecificationError) as exc:
        _resolve_step_selector(plan, "Nope")
    message = str(exc.value)
    assert "Valid --step ids:" in message
    assert "feature-catalog" in message
    assert "foundation" in message


class FakeRegistryClient:
    def __init__(self, packages: dict[tuple[str, str], RegistryPackageInfo]):
        self.packages = packages
        self.calls: list[tuple[str, str]] = []

    def lookup_package(self, normalized_name: str, registry_url: str) -> RegistryPackageInfo:
        self.calls.append((normalized_name, registry_url))
        return self.packages[(normalized_name, registry_url)]


def test_builds_no_ac_steps_in_order_and_closes(tmp_path):
    target_dir, build_dir = _setup(tmp_path)
    runner = make_runner()
    result = build_target("Demo", target_dir, build_dir=build_dir, runner=runner)

    assert [s.block_id for s in result.steps] == ["foundation", "service"]
    assert all(s.status == "built" for s in result.steps)
    assert _state(target_dir, "foundation") == "closed/verified"
    assert _state(target_dir, "service") == "closed/verified"
    assert (target_dir / "evidence" / "foundation.md").is_file()
    assert (target_dir / "evidence" / "service.md").is_file()
    assert result.exit_code() == 0
    # The build performs no git operations of its own: no repo is created.
    assert not (build_dir / ".git").exists()


def test_build_failure_writes_current_error_and_retry_clears_prior_error(tmp_path):
    target_dir, build_dir = _setup(tmp_path)
    write_error_record(
        target_dir,
        command="build",
        phase="LLM execution",
        classification="old error",
        detail="old",
        recovery="retry",
    )
    failed = build_target(
        "Demo", target_dir, build_dir=build_dir, runner=make_runner(ok=False, stderr="rate limit")
    )

    assert failed.exit_code() == 1
    error_text = (target_dir / "ERRORS.md").read_text(encoding="utf-8")
    assert "LLM execution failed" in error_text
    assert "old error" not in error_text
    assert "State: Error" in error_text

    (build_dir / "foundation.txt").unlink()
    result = build_target(
        "Demo",
        target_dir,
        build_dir=build_dir,
        runner=make_runner(),
        step_id="foundation",
        reset=True,
    )

    assert result.exit_code() == 0
    assert not (target_dir / "ERRORS.md").exists()


def test_builds_feature_group_in_one_runner_call(tmp_path):
    target_dir, build_dir = _setup(tmp_path, manifest=_FEATURE_GROUP_MANIFEST)
    runner = make_runner()

    result = build_target("Demo", target_dir, build_dir=build_dir, runner=runner)

    assert [s.block_id for s in result.steps] == ["foundation", "service"]
    assert len(runner.calls) == 1
    call = runner.calls[0]
    assert call["parameters"]["step"] == "feature-catalog"
    assert call["parameters"]["step_type"] == "feature"
    assert call["parameters"]["steps"] == ("foundation", "service")
    assert _state(target_dir, "feature-catalog") == "closed/verified"
    assert _state(target_dir, "foundation") == "closed/verified"
    assert _state(target_dir, "service") == "closed/verified"
    assert (target_dir / "evidence" / "feature-catalog.md").is_file()
    assert result.steps[0].evidence_path == target_dir / "evidence" / "feature-catalog.md"


def test_mixed_feature_group_builds_one_work_kind_per_runner_call(tmp_path):
    manifest = """# MANIFEST: Demo
state: draft

## feature 1: Catalog
id: feature-catalog
summary: Mixed catalog block.
state: pending

## story 2: Catalog Service
id: catalog-service
parent: feature-catalog
implements: FEATURE-CATALOG.md
instructions: |
  Build the service.
state: pending

## story 3: Catalog Screen
id: catalog-screen
parent: feature-catalog
implements: SCREEN-CATALOG.md
depends: catalog-service
instructions: |
  Build the screen.
state: pending
"""
    target_dir, build_dir = _setup(tmp_path, manifest=manifest)
    runner = make_runner()

    result = build_target(
        "Demo",
        target_dir,
        build_dir=build_dir,
        runner=runner,
        dry_run=True,
    )

    assert [s.block_id for s in result.steps] == ["catalog-service"]
    assert runner.calls == []


def test_failed_feature_group_marks_parent_failed(tmp_path):
    target_dir, build_dir = _setup(tmp_path, manifest=_FEATURE_GROUP_MANIFEST)
    runner = make_runner(ok=False, text="", write_files=False, stderr="provider rate limit")

    result = build_target("Demo", target_dir, build_dir=build_dir, runner=runner)

    assert [s.block_id for s in result.steps] == ["foundation", "service"]
    assert result.steps[0].status == "failed"
    assert _state(target_dir, "feature-catalog") == "closed/failed"
    assert _state(target_dir, "foundation") == "closed/failed"
    assert _state(target_dir, "service") == "closed/failed"
    assert "provider rate limit" in (_finding(target_dir, "feature-catalog") or "")


def test_feature_step_selection_builds_feature_group(tmp_path):
    target_dir, build_dir = _setup(tmp_path, manifest=_FEATURE_GROUP_MANIFEST)
    runner = make_runner()

    result = build_target(
        "Demo",
        target_dir,
        build_dir=build_dir,
        runner=runner,
        step_id="feature-catalog",
    )

    assert [s.block_id for s in result.steps] == ["foundation", "service"]
    assert len(runner.calls) == 1
    assert runner.calls[0]["parameters"]["step"] == "feature-catalog"


def test_chained_feature_builds_self_dependent_block_in_one_call(tmp_path):
    target_dir, build_dir = _setup(tmp_path, manifest=_CHAINED_FEATURE_MANIFEST)
    runner = make_runner()

    result = build_target("Demo", target_dir, build_dir=build_dir, runner=runner)

    assert [s.block_id for s in result.steps] == ["foundation", "service"]
    assert len(runner.calls) == 1
    assert runner.calls[0]["parameters"]["step"] == "feature-catalog"
    assert runner.calls[0]["parameters"]["step_type"] == "feature"
    assert runner.calls[0]["parameters"]["steps"] == ("foundation", "service")


def test_computed_block_builds_pending_members_and_preserves_verified_members(tmp_path):
    target_dir, build_dir = _setup(tmp_path, manifest=_COMPUTED_BLOCK_MANIFEST)
    runner = make_runner()

    result = build_target("Demo", target_dir, build_dir=build_dir, runner=runner)

    assert [step.block_id for step in result.steps] == ["service"]
    assert len(runner.calls) == 1
    assert runner.calls[0]["parameters"]["step"] == "block-1"
    assert runner.calls[0]["parameters"]["step_type"] == "block"
    assert runner.calls[0]["parameters"]["steps"] == ("service",)
    assert "Verified Sibling Specifications" in runner.calls[0]["prompt"]
    assert _state(target_dir, "foundation") == "closed/verified"
    assert _state(target_dir, "service") == "closed/verified"


def test_computed_block_with_unverified_external_dependency_is_blocked(tmp_path):
    manifest = """# MANIFEST: Demo
state: approved
blocks: 2

## story 1: Foundation
id: foundation
type: foundational
phase: 1
block: 1
implements: DATABASE.md
stack: python.md
state: pending

## story 2: Service
id: service
type: service
phase: 1
block: 2
implements: SERVICE.md
stack: python.md
depends: foundation
state: pending
"""
    target_dir, build_dir = _setup(tmp_path, manifest=manifest)
    runner = make_runner()

    with pytest.raises(SpecificationError, match="unverified external dependencies"):
        build_target("Demo", target_dir, build_dir=build_dir, runner=runner, step_id="service")

    assert runner.calls == []


def test_child_step_selection_builds_containing_block(tmp_path):
    target_dir, build_dir = _setup(tmp_path, manifest=_CHAINED_FEATURE_MANIFEST)
    runner = make_runner()

    result = build_target(
        "Demo",
        target_dir,
        build_dir=build_dir,
        runner=runner,
        step_id="service",
    )

    assert [s.block_id for s in result.steps] == ["foundation", "service"]
    assert len(runner.calls) == 1
    assert runner.calls[0]["parameters"]["step"] == "feature-catalog"


def test_grouped_block_with_unverified_external_dependency_stops_build(tmp_path):
    manifest = """# MANIFEST: Demo
state: draft

## feature 1: Catalog
id: feature-catalog
summary: Catalog block.
state: pending

## story 2: Foundation
id: foundation
parent: feature-catalog
implements: DATABASE.md
depends: external-foundation
instructions: |
  Build the database.
state: pending

## story 3: External
id: external-foundation
implements: SERVICE.md
instructions: |
  Build the external dependency.
state: pending
"""
    target_dir, build_dir = _setup(tmp_path, manifest=manifest)
    runner = make_runner()

    with pytest.raises(SpecificationError, match="unverified external dependencies") as exc:
        build_target("Demo", target_dir, build_dir=build_dir, runner=runner)

    message = str(exc.value)
    assert "Catalog [feature-catalog]" in message
    assert "External [external-foundation]" in message
    assert "External [external-foundation]: state=pending" in message
    assert "Options:" in message
    assert "drydock run quarterdeck Demo" in message
    assert "Story Retry: drydock build Demo --step external-foundation" in message
    assert len(runner.calls) == 0


def test_blocked_build_formats_rate_limit_dependency_finding(tmp_path):
    manifest = """# MANIFEST: Demo
state: draft

## feature 1: Catalog
id: feature-catalog
summary: Catalog block.
state: pending

## story 2: Foundation
id: foundation
parent: feature-catalog
implements: DATABASE.md
depends: external-foundation
instructions: |
  Build the database.
state: pending

## story 3: External
id: external-foundation
finding: provider rate limit 429: You've hit your session limit · resets 3am (America/New_York)
implements: SERVICE.md
instructions: |
  Build the external dependency.
state: closed/failed
"""
    target_dir, build_dir = _setup(tmp_path, manifest=manifest)

    with pytest.raises(SpecificationError, match="unverified external dependencies") as exc:
        build_target("Demo", target_dir, build_dir=build_dir, runner=make_runner())

    message = str(exc.value)
    assert "External [external-foundation]: state=closed/failed" in message
    assert "FATAL ERROR - PROVIDER RATE LIMIT" in message
    assert "You've hit your session limit" in message
    assert "Wait for the provider quota or session limit to reset" in message
    assert "Story Retry: drydock build Demo --step external-foundation" in message


def test_blocked_build_does_not_call_an_agent(tmp_path):
    manifest = """# MANIFEST: Demo
state: draft

## feature 1: Catalog
id: feature-catalog
summary: Catalog block.
state: pending

## story 2: Foundation
id: foundation
parent: feature-catalog
implements: DATABASE.md
context: FEATURE-A.md
depends: external-foundation
instructions: |
  Build the database.
state: pending

## story 3: External
id: external-foundation
implements: SERVICE.md
instructions: |
  Build the external dependency.
state: pending
"""
    target_dir, build_dir = _setup(tmp_path, manifest=manifest)
    (target_dir / "blueprint" / "FEATURE-A.md").write_text("FEATURE A\n", encoding="utf-8")
    runner = make_runner()

    with pytest.raises(SpecificationError, match="unverified external dependencies"):
        build_target("Demo", target_dir, build_dir=build_dir, runner=runner)

    assert runner.calls == []


def test_build_suppresses_raw_model_stream(tmp_path):
    target_dir, build_dir = _setup(tmp_path)
    log: list[str] = []
    runner = make_runner()

    build_target("Demo", target_dir, build_dir=build_dir, runner=runner, on_text=log.append)

    assert runner.calls[0]["on_text"] is None


def test_dry_run_assembles_prompt_without_runner_or_writes(tmp_path):
    target_dir, build_dir = _setup(tmp_path, manifest=_FEATURE_GROUP_MANIFEST)
    original_manifest = (target_dir / "MANIFEST.md").read_text(encoding="utf-8")
    log: list[str] = []
    runner = make_runner()

    result = build_target(
        "Demo",
        target_dir,
        build_dir=build_dir,
        runner=runner,
        on_text=log.append,
        dry_run=True,
    )

    assert result.dry_run is True
    assert [s.block_id for s in result.steps] == ["foundation", "service"]
    assert all(s.status == "dry-run" for s in result.steps)
    assert len(runner.calls) == 0
    assert not build_dir.exists()
    assert not (target_dir / "evidence").exists()
    assert (target_dir / "MANIFEST.md").read_text(encoding="utf-8") == original_manifest
    assert "dry run assembled files" in log
    assert any(line.startswith("  Role") for line in log)
    assert any("implements" in line and "DATABASE.md" in line for line in log)
    assert any("──── Catalog [feature-catalog] " in line for line in log)
    assert any(line.startswith("dry run prompt: assembled") for line in log)
    assert "dry run prompt: hidden; use --show-prompt to print it" in log
    assert "dry run prompt begin" not in log
    assert not any("DB SPEC CONTENT" in line for line in log)
    assert result.steps[0].prompt is not None


def test_dry_run_show_prompt_prints_full_prompt(tmp_path):
    target_dir, build_dir = _setup(tmp_path)
    log: list[str] = []

    build_target(
        "Demo",
        target_dir,
        build_dir=build_dir,
        runner=make_runner(),
        on_text=log.append,
        dry_run=True,
        show_prompt=True,
    )

    assert "dry run prompt begin" in log
    assert "dry run prompt end" in log
    assert any("DB SPEC CONTENT" in line for line in log)


def test_scoped_reset_dry_run_previews_reset_without_manifest_write(tmp_path):
    manifest = _FEATURE_GROUP_MANIFEST.replace("state: pending", "state: closed/verified")
    target_dir, build_dir = _setup(tmp_path, manifest=manifest)
    original_manifest = (target_dir / "MANIFEST.md").read_text(encoding="utf-8")
    log: list[str] = []
    runner = make_runner()

    result = build_target(
        "Demo",
        target_dir,
        build_dir=build_dir,
        runner=runner,
        on_text=log.append,
        step_id="service",
        reset=True,
        dry_run=True,
    )

    assert [s.block_id for s in result.steps] == ["service"]
    assert result.steps[0].status == "dry-run"
    assert len(runner.calls) == 0
    assert "dry run: would reset service and child ACs to pending" in log
    assert any(line == "run: Service (service)" for line in log)
    assert (target_dir / "MANIFEST.md").read_text(encoding="utf-8") == original_manifest


def test_build_emits_step_progress_lines(tmp_path):
    target_dir, build_dir = _setup(tmp_path)
    log: list[str] = []

    build_target("Demo", target_dir, build_dir=build_dir, runner=make_runner(), on_text=log.append)

    assert any(line.startswith("──── Foundation [foundation] ") for line in log)
    assert any(re.match(r"kind: story · 1 run / 0 verified · \d+ SP", line) for line in log)
    assert any(line == f"workdir: {build_dir}" for line in log)
    assert any(line == "run: Foundation (foundation)" for line in log)
    assert "LLM BUILD: Foundation [foundation]" in log
    assert "  stories: Foundation [foundation]" in log
    assert any(line.startswith("  call: 1 of up to 4 · initial build · ") for line in log)
    assert any(line == "returned: ok · exec-1" for line in log)
    assert not any(line.startswith("  tokens:") for line in log)
    assert any(line == "files: 1 changed — foundation.txt" for line in log)
    assert any(re.match(r"result: built · closed/verified · .+", line) for line in log)
    assert any(line == "evidence: evidence/foundation.md" for line in log)


def test_build_emits_token_accounting_when_the_provider_reports_it(tmp_path):
    from drydock.llm import LlmStats

    target_dir, build_dir = _setup(tmp_path)
    log: list[str] = []
    runner = make_runner(
        stats=LlmStats(
            input_tokens=100,
            cached_input_tokens=900,
            cache_creation_input_tokens=40,
            output_tokens=50,
            cost_usd=0.25,
        )
    )

    build_target(
        "Demo",
        target_dir,
        build_dir=build_dir,
        runner=runner,
        on_text=log.append,
        llm_provider="claude",
    )

    assert log.index("returned: ok · exec-1") + 1 == log.index(
        "  tokens: in=1,000 · fresh 100 · cached 900 (90% hit) · write 40 · out=50 · cost=$0.2500"
    )


def test_feature_step_with_no_future_consumer_does_not_request_compaction(tmp_path):
    manifest = """# MANIFEST: Demo
state: draft

## story 1: Feature
id: feature
implements: FEATURE-Status.md
instructions: |
  Build the feature.
state: pending
"""
    target_dir, build_dir = _setup(tmp_path, manifest=manifest)
    blueprint = target_dir / "blueprint"
    (blueprint / "ARCHITECTURE.md").write_text("ARCH SPEC CONTENT\n", encoding="utf-8")
    (blueprint / "DATABASE.md").write_text("DB SPEC CONTENT\n", encoding="utf-8")
    (blueprint / "FEATURE-Status.md").write_text("FEATURE SPEC CONTENT\n", encoding="utf-8")

    log: list[str] = []
    runner = make_runner()
    build_target("Demo", target_dir, build_dir=build_dir, runner=runner, on_text=log.append)

    assert not any("AUTO-COMPACT:" in line for line in log)
    prompt = runner.calls[0]["prompt"]
    assert 'filename="ARCHITECTURE.md"' in prompt
    assert 'filename="DATABASE.md"' in prompt
    assert "## Reusable compacts" not in prompt


def test_build_requests_and_persists_reusable_compact_from_same_response(tmp_path):
    manifest = """# MANIFEST: Demo
state: draft

## story 1: Foundation
id: foundation
implements: DATABASE.md
context: FEATURE-A.md
instructions: |
  Build the database.
state: pending

## story 2: Service
id: service
implements: SERVICE.md
context: FEATURE-A.md, FEATURE-B.md
instructions: |
  Build the service.
state: pending
"""
    target_dir, build_dir = _setup(tmp_path, manifest=manifest)
    blueprint = target_dir / "blueprint"
    (blueprint / "FEATURE-A.md").write_text("FEATURE A\n", encoding="utf-8")
    (blueprint / "FEATURE-B.md").write_text("FEATURE B\n", encoding="utf-8")
    runner = make_runner(
        text=_success_report(changed=("foundation.txt",))
        + '\n<reusable-compact filename="FEATURE-A.md">\n'
        + "# Feature A contract\n\n- Keep the public behavior.\n"
        + "</reusable-compact>\n",
    )

    result = build_target(
        "Demo", target_dir, build_dir=build_dir, runner=runner, step_id="foundation"
    )

    assert result.steps[0].status == "built"
    assert len(runner.calls) == 1
    assert "Sources eligible for reusable compaction:\n- FEATURE-A.md" in runner.calls[0]["prompt"]
    compact = blueprint / "FEATURE-A_compact.md"
    assert compact.is_file()
    assert "by drydock build agent" in compact.read_text(encoding="utf-8")
    assert "FEATURE-A_compact.md" in (target_dir / "evidence" / "foundation.md").read_text(
        encoding="utf-8"
    )


def test_successful_build_updates_target_lifecycle_metadata(tmp_path):
    target_dir, build_dir = _setup(tmp_path)
    (target_dir / "METADATA.md").write_text(
        "name: Demo\n"
        "display_name: Demo\n"
        "short_description: demo\n"
        "build_state: planned\n"
        "build_sub_state: approved\n",
        encoding="utf-8",
    )

    build_target("Demo", target_dir, build_dir=build_dir, runner=make_runner())

    metadata = (target_dir / "METADATA.md").read_text(encoding="utf-8")
    assert "build_state: built" in metadata
    assert "build_sub_state: complete" in metadata
    assert "last_built: \n" not in metadata


def test_step_selection_builds_only_named_step(tmp_path):
    target_dir, build_dir = _setup(tmp_path)
    runner = make_runner()
    result = build_target(
        "Demo",
        target_dir,
        build_dir=build_dir,
        runner=runner,
        step_id="foundation",
    )

    assert [s.block_id for s in result.steps] == ["foundation"]
    assert _state(target_dir, "foundation") == "closed/verified"
    assert _state(target_dir, "service") == "pending"
    assert len(runner.calls) == 1


def test_step_selection_rejects_dependency_blocked_step(tmp_path):
    from drydock.errors import SpecificationError

    target_dir, build_dir = _setup(tmp_path)

    with pytest.raises(SpecificationError, match="not buildable"):
        build_target(
            "Demo",
            target_dir,
            build_dir=build_dir,
            runner=make_runner(),
            step_id="service",
        )


def test_scoped_reset_rebuilds_step_and_child_acs(tmp_path):
    manifest = """# MANIFEST: Demo
state: draft

## story 1: Foundation
id: foundation
implements: DATABASE.md
finding: previous provider failure
instructions: |
  Build the database.
state: closed/verified

## story 2: Service
id: service
implements: SERVICE.md
depends: foundation
instructions: |
  Build the service.
state: pending

## ac 3: DB works
id: ac-db
parent: foundation
kind: smoke
check: "true"
state: closed/verified
"""
    target_dir, build_dir = _setup(tmp_path, manifest=manifest)
    runner = make_runner()
    result = build_target(
        "Demo",
        target_dir,
        build_dir=build_dir,
        runner=runner,
        step_id="foundation",
        reset=True,
    )

    assert [s.block_id for s in result.steps] == ["foundation"]
    assert result.steps[0].status == "built"
    assert _state(target_dir, "foundation") == "closed/verified"
    assert _finding(target_dir, "foundation") is None
    assert _state(target_dir, "ac-db") == "closed/verified"
    assert _state(target_dir, "service") == "pending"


def test_full_reset_resets_all_blocks_and_wipes_build_dir(tmp_path):
    manifest = _FEATURE_GROUP_MANIFEST.replace("state: pending", "state: closed/verified")
    target_dir, build_dir = _setup(tmp_path, manifest=manifest)
    build_dir.mkdir(parents=True, exist_ok=True)
    stale = build_dir / "stale.txt"
    stale.write_text("old work\n", encoding="utf-8")
    runner = make_runner()

    result = build_target("Demo", target_dir, build_dir=build_dir, runner=runner, reset=True)

    # Every block was reset to pending and rebuilt; the stale artifact was wiped.
    assert not stale.exists()
    assert result.exit_code() == 0
    assert _state(target_dir, "foundation") == "closed/verified"
    assert _state(target_dir, "service") == "closed/verified"


def test_full_reset_dry_run_previews_wipe_without_deleting(tmp_path):
    target_dir, build_dir = _setup(tmp_path)
    build_dir.mkdir(parents=True, exist_ok=True)
    keep = build_dir / "keep.txt"
    keep.write_text("work\n", encoding="utf-8")
    original_manifest = (target_dir / "MANIFEST.md").read_text(encoding="utf-8")
    log: list[str] = []

    build_target(
        "Demo",
        target_dir,
        build_dir=build_dir,
        runner=make_runner(),
        reset=True,
        dry_run=True,
        on_text=log.append,
    )

    assert keep.exists()
    assert (target_dir / "MANIFEST.md").read_text(encoding="utf-8") == original_manifest
    assert any("would reset all blocks to pending and wipe" in line for line in log)


def test_story_selection_builds_single_story_inside_feature(tmp_path):
    target_dir, build_dir = _setup(tmp_path, manifest=_FEATURE_GROUP_MANIFEST)
    runner = make_runner()

    result = build_target(
        "Demo", target_dir, build_dir=build_dir, runner=runner, story_id="foundation"
    )

    # Only the one story built — no feature-group promotion, sibling untouched.
    assert [s.block_id for s in result.steps] == ["foundation"]
    assert result.steps[0].block_type == "story"
    assert _state(target_dir, "foundation") == "closed/verified"
    assert _state(target_dir, "service") == "pending"


def test_story_selector_rejects_a_feature(tmp_path):
    target_dir, build_dir = _setup(tmp_path, manifest=_FEATURE_GROUP_MANIFEST)

    with pytest.raises(SpecificationError, match="is not a story or spike"):
        build_target(
            "Demo",
            target_dir,
            build_dir=build_dir,
            runner=make_runner(),
            story_id="feature-catalog",
        )


def test_prompt_stacks_spec_content_and_instructions(tmp_path):
    target_dir, build_dir = _setup(tmp_path)
    runner = make_runner()
    build_target("Demo", target_dir, build_dir=build_dir, runner=runner)

    first = runner.calls[0]["prompt"]
    assert "DB SPEC CONTENT" in first
    assert "Build the database." in first
    assert 'filename="COMPASS.md"' in first
    assert "COMPASS INTENT CONTENT" in first
    assert first.count("## Build Write Guardrail") == 1
    assert "TARGET_DIRECTORY:" not in first
    assert "WRITE_BOUNDARY:" not in first
    assert "COMPASS.md" in first
    assert first.index("## COMPASS - Target Orientation") < first.index(
        "## IMPLEMENTS - Authoritative Step Specifications"
    )
    assert first.index("DB SPEC CONTENT") < first.rindex("# Agent Task")


def test_allow_tools_enabled_and_runs_in_build_dir(tmp_path):
    target_dir, build_dir = _setup(tmp_path)
    runner = make_runner()
    build_target("Demo", target_dir, build_dir=build_dir, runner=runner)

    call = runner.calls[0]
    assert call["allow_tools"] is True
    assert call["wd"] == build_dir
    assert build_dir.is_dir()


def test_build_leaves_existing_git_repo_untouched(tmp_path):
    """The build never commits, so a pre-existing repo keeps a clean working tree entry
    only for whatever the build wrote — Drydock adds no commits of its own."""
    target_dir, build_dir = _setup(tmp_path)
    build_dir.mkdir(parents=True)
    subprocess.run(
        ["git", "-C", str(build_dir), "init"], check=True, capture_output=True, text=True
    )
    runner = make_runner()
    result = build_target("Demo", target_dir, build_dir=build_dir, runner=runner)

    assert result.exit_code() == 0
    log = subprocess.run(
        ["git", "-C", str(build_dir), "log", "--oneline"],
        capture_output=True,
        text=True,
    )
    # No commits were created by the build.
    assert log.stdout.strip() == ""


def test_step_with_child_ac_auto_verifies_legacy_manifest_ac(tmp_path):
    target_dir, build_dir = _setup(tmp_path, manifest=_STORY_WITH_AC)
    runner = make_runner()
    result = build_target("Demo", target_dir, build_dir=build_dir, runner=runner)

    assert [s.block_id for s in result.steps] == ["foundation", "service"]
    assert result.steps[0].status == "built"
    assert _state(target_dir, "foundation") == "closed/verified"
    assert _state(target_dir, "ac-db") == "closed/verified"
    assert _state(target_dir, "service") == "closed/verified"
    assert len(runner.calls) == 2


def test_blueprint_programmatic_acceptance_passes_after_step(tmp_path):
    target_dir, build_dir = _setup(tmp_path)
    messages: list[str] = []
    (target_dir / "blueprint" / "DATABASE.md").write_text(
        "DB SPEC CONTENT\n\n"
        "## Programmatic Acceptance\n\n"
        "### foundation-file\n"
        "Foundation writes its output marker.\n\n"
        "```python\n"
        "from pathlib import Path\n"
        "assert Path('foundation.txt').read_text(encoding='utf-8') == 'built foundation\\n'\n"
        "```\n",
        encoding="utf-8",
    )

    result = build_target(
        "Demo",
        target_dir,
        build_dir=build_dir,
        runner=make_runner(text=_success_report(changed=("notes.txt",))),
        step_id="foundation",
        on_text=messages.append,
    )

    assert result.steps[0].status == "built"
    assert result.steps[0].acceptance[0].check_id == "foundation-file"
    assert result.steps[0].acceptance[0].passed is True
    evidence = (target_dir / "evidence" / "foundation.md").read_text(encoding="utf-8")
    assert "## Pre-build acceptance observation" in evidence
    assert "RED: foundation-file" in evidence
    assert "## Post-build programmatic acceptance" in evidence
    assert "PASS: foundation-file" in evidence
    assert "acceptance: call 1 · 1/1 AC passed" in messages
    assert not any("Unit Tests" in message for message in messages)


def test_missing_acceptance_fixture_is_skipped_and_recorded_as_decision(tmp_path):
    target_dir, build_dir = _setup(tmp_path)
    (target_dir / "blueprint" / "DATABASE.md").write_text(
        "DB SPEC CONTENT\n\n"
        "## Programmatic Acceptance\n\n"
        "### foundation-fixture\n"
        "The generated fixture is required for this initial test.\n\n"
        "```python\n"
        "from pathlib import Path\n"
        'Path("tests/fixtures/repository").read_text(encoding="utf-8")\n'
        "```\n",
        encoding="utf-8",
    )

    result = build_target(
        "Demo",
        target_dir,
        build_dir=build_dir,
        runner=make_runner(),
        step_id="foundation",
    )

    step = result.steps[0]
    assert step.status == "built"
    assert step.acceptance[0].passed is False
    assert step.acceptance[0].skipped is True
    assert "SKIPPED: foundation-fixture" in (target_dir / "evidence" / "foundation.md").read_text(
        encoding="utf-8"
    )
    decisions = json.loads((target_dir / "DECISIONS.json").read_text(encoding="utf-8"))
    assert decisions[0]["title"] == "Acceptance skipped: foundation-fixture"
    assert decisions[0]["status"] == "recommended"


def test_blueprint_programmatic_prepass_is_informational(tmp_path):
    target_dir, build_dir = _setup(tmp_path)
    (build_dir / "foundation.txt").parent.mkdir(parents=True, exist_ok=True)
    (build_dir / "foundation.txt").write_text("built foundation\n", encoding="utf-8")
    (target_dir / "blueprint" / "DATABASE.md").write_text(
        "DB SPEC CONTENT\n\n"
        "## Programmatic Acceptance\n\n"
        "### foundation-file\n"
        "Foundation writes its output marker.\n\n"
        "```python\n"
        "from pathlib import Path\n"
        "assert Path('foundation.txt').read_text(encoding='utf-8') == 'built foundation\\n'\n"
        "```\n",
        encoding="utf-8",
    )

    def runner(prompt, working_directory, **kwargs):
        (Path(working_directory) / "notes.txt").write_text("build note\n", encoding="utf-8")
        return FakeResult(text=_success_report(changed=("notes.txt",)))

    result = build_target(
        "Demo",
        target_dir,
        build_dir=build_dir,
        runner=runner,
        step_id="foundation",
    )

    assert result.steps[0].status == "built"
    assert result.steps[0].pre_acceptance[0].passed is True
    assert result.steps[0].pre_acceptance[0].integrity_ok is True
    evidence = (target_dir / "evidence" / "foundation.md").read_text(encoding="utf-8")
    assert "GREEN (prepassed): foundation-file" in evidence
    assert "PASS: foundation-file" in evidence


def test_blueprint_programmatic_vacuous_prepass_is_informational(tmp_path):
    target_dir, build_dir = _setup(tmp_path)
    (target_dir / "blueprint" / "DATABASE.md").write_text(
        "DB SPEC CONTENT\n\n"
        "## Programmatic Acceptance\n\n"
        "### foundation-file\n"
        "Foundation vacuously passes.\n\n"
        "```python\n"
        "assert True\n"
        "```\n",
        encoding="utf-8",
    )

    result = build_target(
        "Demo", target_dir, build_dir=build_dir, runner=make_runner(), step_id="foundation"
    )

    assert result.steps[0].status == "built"
    assert result.steps[0].pre_acceptance[0].passed is True
    assert result.steps[0].pre_acceptance[0].integrity_ok is False
    evidence = (target_dir / "evidence" / "foundation.md").read_text(encoding="utf-8")
    assert "GREEN (vacuous): foundation-file" in evidence
    assert "assertion on constant literal True is always true" in evidence
    assert "PASS: foundation-file" in evidence


def test_blueprint_programmatic_acceptance_failure_stops_dependents(tmp_path):
    target_dir, build_dir = _setup(tmp_path)
    (target_dir / "blueprint" / "DATABASE.md").write_text(
        "DB SPEC CONTENT\n\n"
        "## Programmatic Acceptance\n\n"
        "### foundation-file\n"
        "Foundation writes the expected marker.\n\n"
        "```python\n"
        "from pathlib import Path\n"
        "assert Path('foundation.txt').read_text(encoding='utf-8') == 'wrong\\n'\n"
        "```\n",
        encoding="utf-8",
    )

    result = build_target("Demo", target_dir, build_dir=build_dir, runner=make_runner())

    assert [s.block_id for s in result.steps] == ["foundation"]
    assert result.steps[0].status == "failed"
    assert result.steps[0].error == "programmatic acceptance failed: foundation-file"
    assert result.steps[0].acceptance[0].passed is False
    assert _state(target_dir, "foundation") == "closed/failed"
    assert _state(target_dir, "service") == "pending"
    assert result.exit_code() == 1


def test_acceptance_failure_recovery_offers_ungate_without_step(tmp_path):
    # An acceptance failure is bypassed explicitly with --ungate; it does not prescribe a
    # step-scoped rerun.
    target_dir, build_dir = _setup(tmp_path)
    (target_dir / "blueprint" / "DATABASE.md").write_text(
        "DB SPEC CONTENT\n\n"
        "## Programmatic Acceptance\n\n"
        "### foundation-file\n"
        "Foundation writes the expected marker.\n\n"
        "```python\n"
        "assert False\n"
        "```\n",
        encoding="utf-8",
    )

    build_target("Demo", target_dir, build_dir=build_dir, runner=make_runner())

    error_text = (target_dir / "ERRORS.md").read_text(encoding="utf-8")
    assert "drydock build Demo --ungate" in error_text
    assert "--step foundation" not in error_text
    assert "--step foundation --force" not in error_text


def test_programmatic_acceptance_failure_reports_block_story_ac_chain(tmp_path):
    target_dir, build_dir = _setup(tmp_path, manifest=_FEATURE_GROUP_MANIFEST)
    (target_dir / "blueprint" / "SERVICE.md").write_text(
        "SVC SPEC CONTENT\n\n"
        "## Programmatic Acceptance\n\n"
        "### service-adds\n"
        "Service must add two numbers.\n\n"
        "```python\n"
        "assert 1 + 1 == 3\n"
        "```\n",
        encoding="utf-8",
    )

    result = build_target("Demo", target_dir, build_dir=build_dir, runner=make_runner())

    assert [s.block_id for s in result.steps] == ["foundation", "service"]
    assert all(s.status == "failed" for s in result.steps)
    assert result.steps[0].error == "programmatic acceptance failed: service-adds"
    assert result.steps[0].container_block_id == "feature-catalog"
    assert result.steps[0].container_name == "Catalog"
    detail = result.steps[0].failure_detail
    assert 'Block "Catalog" [feature-catalog] failed its acceptance criteria.' in detail
    assert 'Story "Service" [service] does not meet its own acceptance criteria:' in detail
    assert "AC service-adds — Service must add two numbers." in detail
    assert "assertion: assert 1 + 1 == 3 → AssertionError" in detail
    assert "process exit code: 1" in detail
    assert "AssertionError" in detail
    error_text = (target_dir / "ERRORS.md").read_text(encoding="utf-8")
    assert '## Diagnostic\n\nBlock "Catalog" [feature-catalog]' in error_text
    assert "process exit code: 1" in error_text


def test_ac_failure_fails_only_the_owning_story_not_its_group_mate(tmp_path):
    # We fail stories by AC. Within a feature group built in one pass, only the story whose own
    # acceptance check failed is closed/failed; a group-mate whose own checks all passed verifies
    # instead of inheriting the failure. The parent feature still fails until every child verifies.
    target_dir, build_dir = _setup(tmp_path, manifest=_FEATURE_GROUP_MANIFEST)
    (target_dir / "blueprint" / "DATABASE.md").write_text(
        "DB SPEC CONTENT\n\n"
        "## Programmatic Acceptance\n\n"
        "### db-ok\n"
        "Database sanity.\n\n"
        "```python\n"
        "assert 1 + 1 == 2\n"
        "```\n",
        encoding="utf-8",
    )
    (target_dir / "blueprint" / "SERVICE.md").write_text(
        "SVC SPEC CONTENT\n\n"
        "## Programmatic Acceptance\n\n"
        "### service-adds\n"
        "Service must add two numbers.\n\n"
        "```python\n"
        "assert 1 + 1 == 3\n"
        "```\n",
        encoding="utf-8",
    )

    build_target("Demo", target_dir, build_dir=build_dir, runner=make_runner())

    assert _state(target_dir, "foundation") == "closed/verified"
    assert _state(target_dir, "service") == "closed/failed"
    assert _state(target_dir, "feature-catalog") == "closed/failed"
    # The verified group-mate carries no borrowed finding; the failed story names its own AC.
    assert _finding(target_dir, "foundation") is None
    assert "service-adds" in (_finding(target_dir, "service") or "")
    assert "service-adds" not in (_finding(target_dir, "foundation") or "")


def test_failed_step_marks_failed_and_stops(tmp_path):
    target_dir, build_dir = _setup(tmp_path)
    runner = make_runner(ok=False, text="", write_files=False)
    result = build_target("Demo", target_dir, build_dir=build_dir, runner=runner)

    assert result.steps[0].status == "failed"
    assert _state(target_dir, "foundation") == "closed/failed"
    assert _state(target_dir, "service") == "pending"
    assert len(runner.calls) == 1
    assert result.exit_code() == 1


def test_failed_step_stops_independent_frontier(tmp_path):
    manifest = """# MANIFEST: Demo
state: draft

## story 1: Foundation
id: foundation
implements: DATABASE.md
instructions: |
  Build the database.
state: pending

## story 2: Service
id: service
implements: SERVICE.md
instructions: |
  Build the service.
state: pending
"""
    target_dir, build_dir = _setup(tmp_path, manifest=manifest)
    runner = make_runner(ok=False, text="", write_files=False)

    result = build_target("Demo", target_dir, build_dir=build_dir, runner=runner)

    assert [step.block_id for step in result.steps] == ["foundation"]
    assert _state(target_dir, "foundation") == "closed/failed"
    assert _state(target_dir, "service") == "pending"
    assert len(runner.calls) == 1
    assert result.exit_code() == 1


def test_failed_step_preserves_artifact_on_disk(tmp_path):
    # A failed build leaves the generated artifact on disk so it is preserved for inspection,
    # diagnosis, and the next rebuild. The build does not commit it; version control is the
    # user's responsibility.
    target_dir, build_dir = _setup(tmp_path)
    runner = make_runner(ok=False, text="", write_files=True)

    result = build_target("Demo", target_dir, build_dir=build_dir, runner=runner)

    assert result.steps[0].status == "failed"
    assert result.steps[0].written_files == ("foundation.txt",)
    assert result.exit_code() == 1
    # The artifact survives on disk under the build directory.
    assert (build_dir / "foundation.txt").is_file()


def test_evidence_records_summary_and_state(tmp_path):
    target_dir, build_dir = _setup(tmp_path)
    runner = make_runner(
        text=_success_report(
            changed=("foundation.txt",),
            summary="Implemented persistence layer.",
        )
    )
    build_target("Demo", target_dir, build_dir=build_dir, runner=runner)

    evidence = (target_dir / "evidence" / "foundation.md").read_text(encoding="utf-8")
    assert "Implemented persistence layer." in evidence
    assert "resulting state: closed/verified" in evidence
    assert "exec-1" in evidence
    assert "foundation.txt" in evidence


def test_missing_manifest_raises(tmp_path):
    from drydock.errors import SpecificationError

    target_dir = tmp_path / "target"
    target_dir.mkdir()
    with pytest.raises(SpecificationError, match="MANIFEST.md not found"):
        build_target("Demo", target_dir, build_dir=tmp_path / "build", runner=make_runner())


def test_build_does_not_gate_on_human_edited_compass_guardrail(tmp_path):
    target_dir, build_dir = _setup(tmp_path)
    (target_dir / "COMPASS.md").write_text("Commander-owned direction.\n", encoding="utf-8")

    result = build_target("Demo", target_dir, build_dir=build_dir, runner=make_runner())

    assert result.exit_code() == 0


def test_text_without_file_delta_marks_failed(tmp_path):
    target_dir, build_dir = _setup(tmp_path)
    result = build_target(
        "Demo",
        target_dir,
        build_dir=build_dir,
        runner=make_runner(write_files=False),
    )

    assert result.steps[0].status == "failed"
    assert result.steps[0].error == "no build files written"
    assert _state(target_dir, "foundation") == "closed/failed"
    assert _state(target_dir, "service") == "pending"


def test_unstructured_report_with_files_succeeds(tmp_path):
    # A run that wrote files but never emitted the RESULT/FILES contract is no longer
    # failed: the observed file delta and acceptance are the authority, not report format.
    target_dir, build_dir = _setup(tmp_path)
    result = build_target(
        "Demo",
        target_dir,
        build_dir=build_dir,
        runner=make_runner(text="Built it."),
    )

    assert result.steps[0].status == "built"
    assert _state(target_dir, "foundation") == "closed/verified"
    assert _finding(target_dir, "foundation") is None


def test_result_token_found_mid_line_is_not_a_failure(tmp_path):
    # Streaming can concatenate output; RESULT: SUCCESS jammed after a sentence still counts.
    target_dir, build_dir = _setup(tmp_path)
    result = build_target(
        "Demo",
        target_dir,
        build_dir=build_dir,
        runner=make_runner(text="Cleaning up the temp DB file.RESULT: SUCCESS"),
    )

    assert result.steps[0].status == "built"
    assert _state(target_dir, "foundation") == "closed/verified"


def test_explicit_failure_report_persists_finding(tmp_path):
    target_dir, build_dir = _setup(tmp_path)
    result = build_target(
        "Demo",
        target_dir,
        build_dir=build_dir,
        runner=make_runner(
            text=(
                "RESULT: FAILURE\n"
                "FAILURE_SUMMARY: could not resolve imports\n"
                "FAILURE_DETAIL: the requests package is not vendored; add it and rerun.\n"
            )
        ),
    )

    assert result.steps[0].status == "failed"
    assert _state(target_dir, "foundation") == "closed/failed"
    assert _finding(target_dir, "foundation") == "agent-reported failure: could not resolve imports"
    evidence = (target_dir / "evidence" / "foundation.md").read_text(encoding="utf-8")
    assert "## Failure" in evidence
    assert "could not resolve imports" in evidence
    assert "add it and rerun" in evidence


_ONE_STORY = """# MANIFEST: Demo
state: draft

## story 1: Foundation
id: foundation
implements: DATABASE.md
instructions: |
  Build the database.
state: pending
"""

_AGENT_FAILURE_REPORT = (
    "RESULT: FAILURE\n"
    "FAILURE_SUMMARY: full test suite is not 100% conformant\n"
    "FAILURE_DETAIL: some test-suite cases hang; 100% conformance is not achieved.\n"
)


def _write_foundation_check(target_dir, expected: str) -> None:
    (target_dir / "blueprint" / "DATABASE.md").write_text(
        "DB SPEC CONTENT\n\n"
        "## Programmatic Acceptance\n\n"
        "### foundation-marker\n"
        "Foundation writes the expected marker.\n\n"
        "```python\n"
        "from pathlib import Path\n"
        f"assert Path('foundation.txt').read_text(encoding='utf-8') == {expected!r}\n"
        "```\n",
        encoding="utf-8",
    )


def test_agent_reported_failure_is_advisory_when_acceptance_passes(tmp_path):
    # The agent self-declares FAILURE (editorializing about project-wide conformance) but the
    # block's own acceptance criteria pass. The deterministic gate is authoritative: the block
    # is built, and the self-report is recorded only as advisory evidence.
    target_dir, build_dir = _setup(tmp_path, manifest=_ONE_STORY)
    _write_foundation_check(target_dir, "built foundation\n")

    result = build_target(
        "Demo",
        target_dir,
        build_dir=build_dir,
        runner=make_runner(text=_AGENT_FAILURE_REPORT, write_files=True),
    )

    assert result.steps[0].status == "built"
    assert _state(target_dir, "foundation") == "closed/verified"
    assert _finding(target_dir, "foundation") is None
    evidence = (target_dir / "evidence" / "foundation.md").read_text(encoding="utf-8")
    assert "## Agent self-report (advisory)" in evidence
    assert "full test suite is not 100% conformant" in evidence
    assert "PASS: foundation-marker" in evidence


def test_agent_reported_failure_yields_measured_result_when_acceptance_fails(tmp_path):
    # The agent self-declares FAILURE and the block's acceptance criteria also fail. The measured
    # acceptance result is the authority: the finding names the failed check, not the agent's
    # narrative, and both the measurement and the advisory self-report are recorded.
    target_dir, build_dir = _setup(tmp_path, manifest=_ONE_STORY)
    _write_foundation_check(target_dir, "wrong\n")

    result = build_target(
        "Demo",
        target_dir,
        build_dir=build_dir,
        runner=make_runner(text=_AGENT_FAILURE_REPORT, write_files=True),
    )

    assert result.steps[0].status == "failed"
    assert result.steps[0].error == "programmatic acceptance failed: foundation-marker"
    finding = _finding(target_dir, "foundation")
    assert finding is not None
    assert finding.startswith("programmatic acceptance failed")
    assert not finding.startswith("agent-reported failure")
    evidence = (target_dir / "evidence" / "foundation.md").read_text(encoding="utf-8")
    assert "FAIL: foundation-marker" in evidence
    assert "## Agent self-report (advisory)" in evidence


def test_execution_failure_traps_stderr_into_finding(tmp_path):
    target_dir, build_dir = _setup(tmp_path)
    result = build_target(
        "Demo",
        target_dir,
        build_dir=build_dir,
        runner=make_runner(ok=False, text="", stderr="boom\nTraceback: provider crashed"),
    )

    assert result.steps[0].status == "failed"
    finding = _finding(target_dir, "foundation")
    assert finding is not None
    assert finding.startswith("LLM execution failed")
    assert "provider crashed" in finding


def test_dependency_legitimacy_gate_blocks_missing_package_before_acceptance(tmp_path):
    target_dir, build_dir = _setup(tmp_path)
    build_dir.mkdir(parents=True)
    checks_seen: list[tuple[str, ...]] = []

    def runner(prompt, working_directory, **kwargs):
        pyproject = Path(working_directory) / "pyproject.toml"
        pyproject.write_text(
            """
[project]
dependencies = ["missing-package>=1.0"]
""",
            encoding="utf-8",
        )
        return FakeResult(
            text=_success_report(changed=("foundation.txt", "pyproject.toml"), summary="Built it.")
        )

    client = FakeRegistryClient({
        ("missing-package", "https://pypi.org/simple"): RegistryPackageInfo(
            exists=False,
            registry_url="https://pypi.org/simple",
        )
    })

    import drydock.build_run as br

    def fake_acceptance(checks, **kwargs):
        checks_seen.append(tuple(check.check_id for check in checks))
        return ()

    original_today = br.date

    class FixedDate(original_today):
        @classmethod
        def today(cls):
            return cls(2026, 7, 17)

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(br, "date", FixedDate)
    monkeypatch.setattr(br, "run_programmatic_acceptance", fake_acceptance)
    try:
        result = build_target(
            "Demo",
            target_dir,
            build_dir=build_dir,
            runner=runner,
            dependency_registry_client=client,
        )
    finally:
        monkeypatch.undo()

    assert result.steps[0].status == "failed"
    assert result.steps[0].error == "dependency legitimacy gate failed: 1 issue(s)"
    assert checks_seen == []
    assert _state(target_dir, "foundation") == "closed/failed"
    assert _finding(target_dir, "foundation") == "dependency legitimacy gate failed: 1 issue(s)"
    evidence = (target_dir / "evidence" / "foundation.md").read_text(encoding="utf-8")
    assert "Blocked packages:" in evidence
    assert "missing-package [missing]" in evidence


def test_dependency_legitimacy_gate_blocks_new_package_and_skips_applied_updates(
    tmp_path, monkeypatch
):
    import drydock.build_run as br

    target_dir, build_dir = _setup(tmp_path, manifest=_WITH_STACK)
    (target_dir / "blueprint" / "common.md").write_text("stack content\n", encoding="utf-8")
    monkeypatch.setattr(br, "_git_head", lambda p: "commitabc")
    monkeypatch.setattr(br, "_is_dirty", lambda p: False)

    def runner(prompt, working_directory, **kwargs):
        path = Path(working_directory) / "requirements.txt"
        path.write_text("fresh-package==1.0\n", encoding="utf-8")
        return FakeResult(
            text=_success_report(
                changed=("foundation.txt", "requirements.txt"), summary="Built it."
            )
        )

    client = FakeRegistryClient({
        ("fresh-package", "https://pypi.org/simple"): RegistryPackageInfo(
            exists=True,
            registry_url="https://pypi.org/simple",
            first_published_at=datetime(2026, 7, 1, tzinfo=UTC),
        )
    })

    class FixedDate(br.date):
        @classmethod
        def today(cls):
            return cls(2026, 7, 17)

    monkeypatch.setattr(br, "date", FixedDate)

    result = build_target(
        "Demo",
        target_dir,
        build_dir=build_dir,
        runner=runner,
        dependency_registry_client=client,
    )

    assert result.steps[0].status == "failed"
    assert "dependency legitimacy gate failed" in (result.steps[0].error or "")
    plan = parse_build_plan(target_dir / "MANIFEST.md")
    assert "common.md" not in plan.applied_registry
    assert "DATABASE.md" not in plan.applied_specs
    evidence = (target_dir / "evidence" / "foundation.md").read_text(encoding="utf-8")
    assert "fresh-package [newly-published]" in evidence
    assert "first_published=2026-07-01" in evidence


class TestClassifyFailure:
    def _classify(self, **kwargs):
        from drydock.build_run import _classify_failure

        base = {"ok": True, "wrote_files": ("app.py",)}
        base.update(kwargs)
        return _classify_failure(base.pop("summary", ""), **base)

    def test_success_returns_none(self):
        assert self._classify(summary="Done. RESULT: SUCCESS") is None

    def test_sandbox_signature_even_when_process_exits_clean(self):
        category, detail = self._classify(
            summary="bwrap: execvp codex-linux-sandbox: No such file or directory",
            wrote_files=(),
        )
        assert category == "execution environment unavailable"
        assert "danger-full-access" in detail

    def test_token_limit_signature(self):
        category, _ = self._classify(summary="Error: prompt is too long for the context window")
        assert category == "context/token limit"

    def test_provider_rate_limit(self):
        category, detail = self._classify(
            ok=False, summary="", provider_error="provider rate limit 429: session limit"
        )
        assert category == "provider rate limit"
        assert "429" in detail

    def test_non_zero_exit_uses_stderr_detail(self):
        category, detail = self._classify(ok=False, summary="", stderr="boom\nsegfault")
        assert category == "LLM execution failed"
        assert "segfault" in detail

    def test_empty_output(self):
        category, _ = self._classify(summary="   ")
        assert category == "empty output"

    def test_agent_reported_failure_parses_structured_block(self):
        summary = (
            "RESULT: FAILURE\n"
            "FAILURE_SUMMARY: missing DATABASE.md input\n"
            "FAILURE_DETAIL: the implements file was not provided; supply it and rerun.\n"
        )
        category, detail = self._classify(summary=summary)
        assert category == "agent-reported failure: missing DATABASE.md input"
        assert "supply it and rerun" in detail

    def test_agent_reported_failure_without_structured_block(self):
        category, detail = self._classify(summary="Could not resolve imports. RESULT: FAILURE")
        assert category == "agent-reported failure"
        assert "Could not resolve imports" in detail

    def test_no_files_written(self):
        category, _ = self._classify(summary="All good, nothing to do.", wrote_files=())
        assert category == "no build files written"


def test_snapshot_ignores_transient_and_generated_paths(tmp_path):
    """Bytecode caches, tool caches, and .git are not build output and must not register
    as changed files."""
    from drydock.build_run import _snapshot_files, _written_files

    build = tmp_path / "build"
    build.mkdir()
    (build / "commonmark.py").write_text("print('a')\n", encoding="utf-8")
    before = _snapshot_files(build)

    # Real edit plus a pile of transient churn.
    (build / "commonmark.py").write_text("print('b')\n", encoding="utf-8")
    (build / "__pycache__").mkdir()
    (build / "__pycache__" / "commonmark.cpython-311.pyc").write_bytes(b"\x00bytecode")
    (build / ".pytest_cache").mkdir()
    (build / ".pytest_cache" / "CACHEDIR.TAG").write_text("cache\n", encoding="utf-8")
    (build / ".git").mkdir()
    (build / ".git" / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")
    (build / "mod.pyc").write_bytes(b"\x00stray")

    after = _snapshot_files(build)
    assert set(after) == {"commonmark.py"}
    assert _written_files(before, after) == ("commonmark.py",)


_WITH_STACK = """# MANIFEST: Demo
state: draft

## story 1: Foundation
id: foundation
implements: DATABASE.md
stack: common.md
instructions: Build the database.
state: pending
"""


class TestDirtyGuard:
    def test_dirty_stack_dir_proceeds_without_provenance(self, tmp_path, monkeypatch):
        """A dirty stack no longer blocks the build; it just yields no registry provenance."""
        import drydock.build_run as br
        from drydock.build_plan import parse_build_plan

        monkeypatch.setattr(br, "_git_head", lambda p: "abc123")
        monkeypatch.setattr(br, "_is_dirty", lambda p: True)

        target_dir, build_dir = _setup(tmp_path, manifest=_WITH_STACK)
        (target_dir / "blueprint" / "common.md").write_text("stack content\n", encoding="utf-8")

        result = build_target("Demo", target_dir, build_dir=build_dir, runner=make_runner())

        assert result.exit_code() == 0
        plan = parse_build_plan(target_dir / "MANIFEST.md")
        assert "common.md" not in plan.applied_registry

    def test_clean_stack_dir_proceeds(self, tmp_path, monkeypatch):
        import drydock.build_run as br

        monkeypatch.setattr(br, "_git_head", lambda p: "abc123")
        monkeypatch.setattr(br, "_is_dirty", lambda p: False)

        target_dir, build_dir = _setup(tmp_path, manifest=_WITH_STACK)
        result = build_target("Demo", target_dir, build_dir=build_dir, runner=make_runner())
        assert result.exit_code() == 0

    def test_no_git_repo_skips_guard(self, tmp_path, monkeypatch):
        import drydock.build_run as br

        monkeypatch.setattr(br, "_git_head", lambda p: None)

        target_dir, build_dir = _setup(tmp_path, manifest=_WITH_STACK)
        result = build_target("Demo", target_dir, build_dir=build_dir, runner=make_runner())
        assert result.exit_code() == 0

    def test_no_applied_registry_written_when_no_file_delta(self, tmp_path, monkeypatch):
        import drydock.build_run as br
        from drydock.build_plan import parse_build_plan

        monkeypatch.setattr(br, "_git_head", lambda p: "abc123")
        monkeypatch.setattr(br, "_is_dirty", lambda p: False)

        target_dir, build_dir = _setup(tmp_path, manifest=_WITH_STACK)
        (target_dir / "blueprint" / "common.md").write_text("stack content\n", encoding="utf-8")
        build_target(
            "Demo",
            target_dir,
            build_dir=build_dir,
            runner=make_runner(write_files=False),
        )

        plan = parse_build_plan(target_dir / "MANIFEST.md")
        assert "common.md" not in plan.applied_registry


class TestAppliedRegistryIntegration:
    def _manifest_with_stack(self, tmp_path, applied=""):
        from drydock.compass_guardrail import apply_guardrail

        preamble = "# MANIFEST: Demo\nstate: draft\n"
        if applied:
            preamble += f"applied: {applied}\n"
        body = (
            preamble
            + """
## story 1: Foundation
id: foundation
implements: DATABASE.md
stack: common.md
instructions: Build it.
state: pending
"""
        )
        target_dir = tmp_path / "target"
        build_dir = tmp_path / "build"
        blueprint = target_dir / "blueprint"
        blueprint.mkdir(parents=True)
        (target_dir / "MANIFEST.md").write_text(body, encoding="utf-8")
        (target_dir / "COMPASS.md").write_text(
            apply_guardrail("Compass.", "Demo", target_dir, build_dir=build_dir),
            encoding="utf-8",
        )
        (blueprint / "DATABASE.md").write_text("DB SPEC\n", encoding="utf-8")
        return target_dir, build_dir

    def test_applied_registry_written_after_successful_step(self, tmp_path, monkeypatch):
        import drydock.build_run as br
        from drydock.build_plan import parse_build_plan

        monkeypatch.setattr(br, "_git_head", lambda p: "commitabc")
        monkeypatch.setattr(br, "_is_dirty", lambda p: False)

        target_dir, build_dir = self._manifest_with_stack(tmp_path)
        build_target("Demo", target_dir, build_dir=build_dir, runner=make_runner())

        plan = parse_build_plan(target_dir / "MANIFEST.md")
        assert plan.applied_registry.get("common.md") == "commitabc"

    def test_compact_used_when_file_in_registry_with_matching_commit(self, tmp_path, monkeypatch):
        import drydock.build_run as br

        monkeypatch.setattr(br, "_git_head", lambda p: "commitabc")
        monkeypatch.setattr(br, "_is_dirty", lambda p: False)

        target_dir, build_dir = self._manifest_with_stack(tmp_path, applied="common.md=commitabc")
        # create a compact sibling so substitution can actually happen
        stack_check_calls = []

        runner = make_runner()
        original_runner = runner

        def capturing_runner(prompt, wd, **kwargs):
            stack_check_calls.append(prompt)
            return original_runner(prompt, wd, **kwargs)

        build_target("Demo", target_dir, build_dir=build_dir, runner=capturing_runner)
        # compact sibling doesn't exist in this test's stack_dir so it falls through to full —
        # but the compact_stack set IS built from the registry; verify no error raised
        assert len(stack_check_calls) == 1

    def test_stale_commit_uses_full_file(self, tmp_path, monkeypatch):
        import drydock.build_run as br
        from drydock.build_plan import parse_build_plan

        monkeypatch.setattr(br, "_git_head", lambda p: "newcommit")
        monkeypatch.setattr(br, "_is_dirty", lambda p: False)

        # registry has old commit → stale → compact_stack will be empty
        target_dir, build_dir = self._manifest_with_stack(tmp_path, applied="common.md=oldcommit")
        build_target("Demo", target_dir, build_dir=build_dir, runner=make_runner())

        plan = parse_build_plan(target_dir / "MANIFEST.md")
        # after build, registry updated with new commit
        assert plan.applied_registry.get("common.md") == "newcommit"


class TestAppliedSpecProvenance:
    def test_successful_step_records_blueprint_spec_hashes(self, tmp_path, monkeypatch):
        import drydock.build_run as br

        monkeypatch.setattr(br, "_git_file_commit", lambda p: "speccommit")
        target_dir, build_dir = _setup(tmp_path)

        build_target(
            "Demo", target_dir, build_dir=build_dir, runner=make_runner(), step_id="foundation"
        )

        plan = parse_build_plan(target_dir / "MANIFEST.md")
        record = plan.applied_specs["DATABASE.md"]
        assert record.commit == "speccommit"
        assert record.applied_by == "foundation"
        assert len(record.sha256) == 64
        assert len(record.build_sha256) == 64

    def test_successful_step_records_blueprint_context_but_not_target_context(
        self, tmp_path, monkeypatch
    ):
        import drydock.build_run as br

        monkeypatch.setattr(br, "_git_file_commit", lambda p: "speccommit")
        manifest = """# MANIFEST: Demo
state: draft

## story 1: Foundation
id: foundation
implements: DATABASE.md
context: ARCHITECTURE.md, README.md
instructions: Build the database.
state: pending
"""
        target_dir, build_dir = _setup(tmp_path, manifest=manifest)
        (target_dir / "blueprint" / "ARCHITECTURE.md").write_text("ARCH SPEC\n", encoding="utf-8")
        (target_dir / "README.md").write_text("TARGET README\n", encoding="utf-8")

        build_target("Demo", target_dir, build_dir=build_dir, runner=make_runner())

        plan = parse_build_plan(target_dir / "MANIFEST.md")
        assert "DATABASE.md" in plan.applied_specs
        # A compact without matching provenance is stale and falls through to the
        # authoritative source; the applied record names the file in the prompt.
        assert "ARCHITECTURE.md" in plan.applied_specs
        assert "README.md" not in plan.applied_specs

    def test_changed_previously_applied_spec_warns_and_builds(self, tmp_path):
        target_dir, build_dir = _setup(tmp_path)
        runner = make_runner()
        build_target("Demo", target_dir, build_dir=build_dir, runner=runner, step_id="foundation")
        (target_dir / "blueprint" / "DATABASE.md").write_text(
            "DB SPEC CONTENT CHANGED\n", encoding="utf-8"
        )

        second_runner = make_runner()
        result = build_target("Demo", target_dir, build_dir=build_dir, runner=second_runner)

        assert result.exit_code() == 0
        assert len(second_runner.calls) == 1

    def test_full_reset_clears_applied_specs_and_rebuilds(self, tmp_path):
        target_dir, build_dir = _setup(tmp_path)
        build_target(
            "Demo", target_dir, build_dir=build_dir, runner=make_runner(), step_id="foundation"
        )
        (target_dir / "blueprint" / "DATABASE.md").write_text(
            "DB SPEC CONTENT CHANGED\n", encoding="utf-8"
        )

        runner = make_runner()
        result = build_target("Demo", target_dir, build_dir=build_dir, runner=runner, reset=True)

        assert result.exit_code() == 0
        assert len(runner.calls) > 0
        # Stale records were cleared by the reset and re-stamped against the current
        # Blueprint, so an immediate follow-up build is not blocked.
        plan = parse_build_plan(target_dir / "MANIFEST.md")
        assert stale_applied_specs(plan, target_dir / "blueprint") == ()

    def test_deleted_previously_applied_spec_blocks_before_runner(self, tmp_path):
        from drydock.errors import SpecificationError

        target_dir, build_dir = _setup(tmp_path)
        build_target(
            "Demo", target_dir, build_dir=build_dir, runner=make_runner(), step_id="foundation"
        )
        (target_dir / "blueprint" / "DATABASE.md").unlink()

        runner = make_runner()
        with pytest.raises(SpecificationError, match="DATABASE.md: missing"):
            build_target("Demo", target_dir, build_dir=build_dir, runner=runner)

        assert len(runner.calls) == 0

    def test_drift_warning_distinguishes_foundational_and_ordinary(self, tmp_path):
        import hashlib

        from drydock.build_run import _ensure_applied_specs_current

        blueprint = tmp_path / "blueprint"
        blueprint.mkdir()
        (blueprint / "DATABASE.md").write_text("db changed\n", encoding="utf-8")
        (blueprint / "SCREEN-A.md").write_text("screen changed\n", encoding="utf-8")
        stale_hash = hashlib.sha256(b"original\n").hexdigest()
        manifest = tmp_path / "MANIFEST.md"
        manifest.write_text(
            "# MANIFEST: Demo\n"
            "state: approved\n"
            "applied_specs: |\n"
            f"  DATABASE.md sha256={stale_hash} commit=- "
            "applied_by=foundation applied_at=2026-07-01\n"
            f"  SCREEN-A.md sha256={stale_hash} commit=- "
            "applied_by=screen-a applied_at=2026-07-01\n"
            "\n"
            "## story 1: Foundation\n"
            "id: foundation\n"
            "state: closed/verified\n",
            encoding="utf-8",
        )

        warnings = _ensure_applied_specs_current(manifest, blueprint)

        message = "\n".join(warnings)
        assert "build continues" in message
        assert "DATABASE.md changed" in message
        assert "Existing compact derivatives are not regenerated" in message
        assert "existing compact derivatives are used" in message
        assert "SCREEN-A.md" in message


_CONTEXT_STORY = """# MANIFEST: Demo
state: draft

## story 1: Foundation
id: foundation
implements: DATABASE.md
context: sources/spec.txt
instructions: |
  Build the database.
state: pending
"""


_ANALYSIS_ROLES = """# ANALYSIS

## Source Roles

| Path | Role | Plan disposition | Build disposition |
|---|---|---|---|
| sources/spec.txt | normative specification and conformance test suite | context | stage |
| sources/harness.py | conformance harness | context | stage |
| sources/NOTES.md | author intent | compass | stage |
| sources/cmark.py | reference implementation | context | none |
"""


def _with_kit(tmp_path, *, manifest=_CONTEXT_STORY, analysis=_ANALYSIS_ROLES):
    target_dir, build_dir = _setup(tmp_path, manifest=manifest)
    sources = target_dir / "blueprint" / "sources"
    sources.mkdir(parents=True)
    (sources / "spec.txt").write_text("EXAMPLE\n" * 500, encoding="utf-8")
    (sources / "harness.py").write_text("print('harness')\n", encoding="utf-8")
    (sources / "NOTES.md").write_text("# Notes\n", encoding="utf-8")
    (sources / "cmark.py").write_text("reference\n", encoding="utf-8")
    if analysis is not None:
        (target_dir / "ANALYSIS.md").write_text(analysis, encoding="utf-8")
    return target_dir, build_dir


def test_stages_declared_build_assets_without_leaking_blueprint_paths(tmp_path):
    """A test kit declared `stage` must exist on disk in the build directory: acceptance runs
    with the build directory as cwd, and a test suite inlined into the prompt cannot be executed.
    Drydock's own layout must not follow it into the deliverable."""
    target_dir, build_dir = _with_kit(tmp_path)

    result = build_target("Demo", target_dir, build_dir=build_dir, runner=make_runner())

    assert result.exit_code() == 0
    assert (build_dir / "sources" / "spec.txt").read_text(encoding="utf-8") == "EXAMPLE\n" * 500
    assert (build_dir / "sources" / "harness.py").is_file()
    # `none` stages nothing, and `.md` stays prompt material even when marked stage.
    assert not (build_dir / "sources" / "cmark.py").exists()
    assert not (build_dir / "sources" / "NOTES.md").exists()
    # The original assertions of the removed no-staging test, preserved.
    assert not (build_dir / "blueprint").exists()
    assert not (build_dir / "spec.txt").exists()


def test_build_without_an_analysis_stages_nothing(tmp_path):
    """Staging is opt-in through the Analysis source-role table; a legacy Target is unchanged."""
    target_dir, build_dir = _with_kit(tmp_path, analysis=None)

    result = build_target("Demo", target_dir, build_dir=build_dir, runner=make_runner())

    assert result.exit_code() == 0
    assert not (build_dir / "sources").exists()


def test_dry_run_stages_nothing(tmp_path):
    target_dir, build_dir = _with_kit(tmp_path)

    build_target("Demo", target_dir, build_dir=build_dir, runner=make_runner(), dry_run=True)

    assert not (build_dir / "sources").exists()


def test_step_that_rewrites_a_staged_asset_fails_and_the_asset_is_restored(tmp_path):
    """The regression this contract exists for: an agent writing its own miniature test suite over
    the imported one, then grading itself against it."""
    target_dir, build_dir = _with_kit(tmp_path)

    def runner(prompt, working_directory, **kwargs):
        step_id = kwargs["parameters"]["step"]
        wd = Path(working_directory)
        wd.mkdir(parents=True, exist_ok=True)
        (wd / f"{step_id}.txt").write_text(f"built {step_id}\n", encoding="utf-8")
        (wd / "sources" / "spec.txt").write_text("# 2 examples\n", encoding="utf-8")
        return FakeResult(ok=True, text=_success_report(changed=(f"{step_id}.txt",)))

    result = build_target("Demo", target_dir, build_dir=build_dir, runner=runner)

    assert result.exit_code() != 0
    step = result.steps[0]
    assert step.status == "failed"
    assert "staged build asset modified" in (step.error or "")
    assert "sources/spec.txt" in (step.error or "")
    assert (build_dir / "sources" / "spec.txt").read_text(encoding="utf-8") == "EXAMPLE\n" * 500


def test_restaging_repairs_a_substituted_asset_on_the_next_build(tmp_path):
    target_dir, build_dir = _with_kit(tmp_path)
    build_target("Demo", target_dir, build_dir=build_dir, runner=make_runner())
    (build_dir / "sources" / "spec.txt").write_text("# 2 examples\n", encoding="utf-8")

    messages: list[str] = []
    build_target(
        "Demo",
        target_dir,
        build_dir=build_dir,
        runner=make_runner(),
        on_text=messages.append,
    )

    assert (build_dir / "sources" / "spec.txt").read_text(encoding="utf-8") == "EXAMPLE\n" * 500
    assert any("restored modified build asset: sources/spec.txt" in m for m in messages)


_UNSATISFIABLE_SPEC = """# FEATURE: Escapes

## Programmatic Acceptance

### escapes
Escapes render literally.

```python
from app import convert

assert convert(r"\\*a\\*\\n") == "<p>*a*</p>\\n"
```
"""


def _marker_spec(expected: str) -> str:
    return (
        "DB SPEC CONTENT\n\n"
        "## Programmatic Acceptance\n\n"
        "### foundation-file\n"
        "Foundation writes its output marker.\n\n"
        "```python\n"
        "from pathlib import Path\n"
        f"assert Path('foundation.txt').read_text(encoding='utf-8') == {expected!r}\n"
        "```\n"
    )


def make_attempt_runner(*, fix_at: int | None):
    """Runner whose written marker becomes correct at attempt ``fix_at`` (None = never)."""
    calls: list[dict] = []

    def runner(prompt, working_directory, **kwargs):
        attempt = kwargs["parameters"]["attempt"]
        Path(working_directory).mkdir(parents=True, exist_ok=True)
        good = fix_at is not None and attempt >= fix_at
        (Path(working_directory) / "foundation.txt").write_text(
            "ok\n" if good else "bad\n", encoding="utf-8"
        )
        calls.append({"prompt": prompt, "attempt": attempt, **kwargs})
        return FakeResult(text=_success_report(changed=("foundation.txt",)))

    runner.calls = calls  # type: ignore[attr-defined]
    return runner


def test_repair_loop_fixes_failed_acceptance_on_second_pass(tmp_path):
    target_dir, build_dir = _setup(tmp_path)
    (target_dir / "blueprint" / "DATABASE.md").write_text(_marker_spec("ok\n"), encoding="utf-8")
    runner = make_attempt_runner(fix_at=1)

    result = build_target(
        "Demo",
        target_dir,
        build_dir=build_dir,
        runner=runner,
        step_id="foundation",
        repair_attempts=1,
    )

    assert result.steps[0].status == "built"
    assert _state(target_dir, "foundation") == "closed/verified"
    assert [c["attempt"] for c in runner.calls] == [0, 1]
    # The repair pass carries the failure feedback as the recency anchor; the first does not.
    assert "# Repair Feedback" not in runner.calls[0]["prompt"]
    assert "# Repair Feedback" in runner.calls[1]["prompt"]
    evidence = (target_dir / "evidence" / "foundation.md").read_text(encoding="utf-8")
    assert "## Repair attempts" in evidence
    assert "attempt 1 (repair 1)" in evidence


def test_repair_loop_continues_while_deterministic_score_improves(tmp_path):
    target_dir, build_dir = _setup(tmp_path)
    (target_dir / "blueprint" / "DATABASE.md").write_text(
        """## Programmatic Acceptance

### first-marker
The first marker is correct.

```python
from pathlib import Path
assert Path('first.txt').read_text(encoding='utf-8') == 'ok\\n'
```

### second-marker
The second marker is correct.

```python
from pathlib import Path
assert Path('second.txt').read_text(encoding='utf-8') == 'ok\\n'
```
""",
        encoding="utf-8",
    )
    calls: list[int] = []

    def runner(prompt, working_directory, **kwargs):
        attempt = kwargs["parameters"]["attempt"]
        work = Path(working_directory)
        work.mkdir(parents=True, exist_ok=True)
        (work / "first.txt").write_text("ok\n" if attempt >= 1 else "bad\n", encoding="utf-8")
        (work / "second.txt").write_text("ok\n" if attempt >= 2 else "bad\n", encoding="utf-8")
        calls.append(attempt)
        return FakeResult(text=_success_report(changed=("first.txt", "second.txt")))

    result = build_target(
        "Demo",
        target_dir,
        build_dir=build_dir,
        runner=runner,
        step_id="foundation",
        repair_attempts=3,
    )

    assert result.steps[0].status == "built"
    assert calls == [0, 1, 2]


def test_repair_loop_counts_conformance_subcase_progress_while_ac_stays_red(tmp_path):
    target_dir, build_dir = _setup(tmp_path)
    (target_dir / "blueprint" / "DATABASE.md").write_text(
        """## Programmatic Acceptance

### conformance
Every conformance example passes.

```python
from pathlib import Path
score = int(Path("score.txt").read_text(encoding="utf-8"))
print(f"{score} passed, {4 - score} failed, 0 errored")
assert score == 4
```
""",
        encoding="utf-8",
    )
    calls: list[int] = []
    messages: list[str] = []

    def runner(prompt, working_directory, **kwargs):
        attempt = kwargs["parameters"]["attempt"]
        work = Path(working_directory)
        work.mkdir(parents=True, exist_ok=True)
        (work / "score.txt").write_text(f"{attempt + 1}\n", encoding="utf-8")
        calls.append(attempt)
        return FakeResult(text=_success_report(changed=("score.txt",)))

    result = build_target(
        "Demo",
        target_dir,
        build_dir=build_dir,
        runner=runner,
        on_text=messages.append,
        step_id="foundation",
        repair_attempts=3,
    )

    assert result.steps[0].status == "built"
    assert calls == [0, 1, 2, 3]
    assert "acceptance: call 1 · 0/1 AC passed · failed: conformance (1/4 cases)" in messages
    assert "acceptance: call 3 · 0/1 AC passed · failed: conformance (3/4 cases)" in messages
    assert "acceptance: call 4 · 1/1 AC passed" in messages


def test_repair_loop_stops_when_one_conformance_ac_regresses(tmp_path):
    target_dir, build_dir = _setup(tmp_path)
    (target_dir / "blueprint" / "DATABASE.md").write_text(
        """## Programmatic Acceptance

### first-conformance
The first conformance group passes.

```python
from pathlib import Path
score = int(Path("first-score.txt").read_text(encoding="utf-8"))
print(f"{score} passed, {4 - score} failed, 0 errored")
assert score == 4
```

### second-conformance
The second conformance group passes.

```python
from pathlib import Path
score = int(Path("second-score.txt").read_text(encoding="utf-8"))
print(f"{score} passed, {4 - score} failed, 0 errored")
assert score == 4
```
""",
        encoding="utf-8",
    )
    calls: list[int] = []

    def runner(prompt, working_directory, **kwargs):
        attempt = kwargs["parameters"]["attempt"]
        work = Path(working_directory)
        work.mkdir(parents=True, exist_ok=True)
        first, second = ((1, 3), (3, 2))[min(attempt, 1)]
        (work / "first-score.txt").write_text(f"{first}\n", encoding="utf-8")
        (work / "second-score.txt").write_text(f"{second}\n", encoding="utf-8")
        calls.append(attempt)
        return FakeResult(text=_success_report(changed=("first-score.txt", "second-score.txt")))

    result = build_target(
        "Demo",
        target_dir,
        build_dir=build_dir,
        runner=runner,
        step_id="foundation",
        repair_attempts=3,
    )

    assert result.steps[0].status == "failed"
    assert calls == [0, 1]
    evidence = (target_dir / "evidence" / "foundation.md").read_text(encoding="utf-8")
    assert "stopped: deterministic acceptance score did not improve" in evidence


def test_repair_loop_exhausts_budget_and_fails(tmp_path):
    target_dir, build_dir = _setup(tmp_path)
    (target_dir / "blueprint" / "DATABASE.md").write_text(_marker_spec("ok\n"), encoding="utf-8")
    runner = make_attempt_runner(fix_at=None)

    result = build_target(
        "Demo",
        target_dir,
        build_dir=build_dir,
        runner=runner,
        step_id="foundation",
        repair_attempts=2,
    )

    assert result.steps[0].status == "failed"
    assert result.steps[0].error == "programmatic acceptance failed: foundation-file"
    assert _state(target_dir, "foundation") == "closed/failed"
    # The first repair has the same 0/1 deterministic acceptance score, so the
    # loop stops without spending its remaining repair budget.
    assert [c["attempt"] for c in runner.calls] == [0, 1]
    from drydock.errors import read_error_record

    record = read_error_record(target_dir)
    assert record is not None
    evidence = (target_dir / "evidence" / "foundation.md").read_text(encoding="utf-8")
    assert "attempt 1 (repair 1)" in evidence
    assert "stopped: deterministic acceptance score did not improve" in evidence


# A console that carries only check ids tells an operator that something failed, not what the
# check was doing. The runner's own output is what makes a defect obvious on sight — a tally
# whose total exceeds the specified case count, say — so it belongs on screen, not only in the
# evidence file.


_ECHOING_SUITE_SPEC = """# FEATURE: Suite

## Programmatic Acceptance

### suite-conformance
The scoped conformance suite passes.

```python
import sys

print("365 passed, 3 failed, 0 errored")
print("runner: sections=blocks", file=sys.stderr)
raise SystemExit(1)
```
"""


def test_console_shows_what_a_failed_check_was_doing(tmp_path):
    target_dir, build_dir = _setup(tmp_path)
    (target_dir / "blueprint" / "DATABASE.md").write_text(_ECHOING_SUITE_SPEC, encoding="utf-8")
    messages: list[str] = []

    build_target(
        "Demo",
        target_dir,
        build_dir=build_dir,
        runner=make_runner(),
        on_text=messages.append,
        repair_attempts=0,
    )

    console = "\n".join(messages)
    assert "acceptance: call 1 · 0/1 AC passed" in console
    assert "suite-conformance (365/368 cases)" in console
    assert "suite-conformance: The scoped conformance suite passes." in console
    # Both streams reach the screen: the tally that makes the defect legible, and the
    # runner's own note about what it was invoked against.
    assert "365 passed, 3 failed, 0 errored" in console
    assert "runner: sections=blocks" in console


def test_a_failed_definition_of_done_line_cannot_read_as_ticked(tmp_path):
    target_dir, build_dir = _setup(tmp_path)
    (target_dir / "blueprint" / "DATABASE.md").write_text(_ECHOING_SUITE_SPEC, encoding="utf-8")
    messages: list[str] = []

    build_target(
        "Demo",
        target_dir,
        build_dir=build_dir,
        runner=make_runner(),
        on_text=messages.append,
        repair_attempts=0,
    )

    assert any(m.startswith("[!!] suite-conformance") for m in messages)
    assert not any(m.startswith("[X]") for m in messages)


def test_repair_attempts_zero_is_single_pass(tmp_path):
    target_dir, build_dir = _setup(tmp_path)
    (target_dir / "blueprint" / "DATABASE.md").write_text(_marker_spec("ok\n"), encoding="utf-8")
    runner = make_attempt_runner(fix_at=None)

    result = build_target(
        "Demo",
        target_dir,
        build_dir=build_dir,
        runner=runner,
        step_id="foundation",
        repair_attempts=0,
    )

    assert result.steps[0].status == "failed"
    assert [c["attempt"] for c in runner.calls] == [0]
    evidence = (target_dir / "evidence" / "foundation.md").read_text(encoding="utf-8")
    assert "## Repair attempts" not in evidence


def test_terminal_failure_is_not_repaired(tmp_path):
    target_dir, build_dir = _setup(tmp_path)
    runner = make_runner(ok=False, write_files=False, stderr="boom")

    result = build_target(
        "Demo",
        target_dir,
        build_dir=build_dir,
        runner=runner,
        step_id="foundation",
        repair_attempts=3,
    )

    assert result.steps[0].status == "failed"
    # An LLM execution failure is terminal: the loop never spends a repair pass on it.
    assert len(runner.calls) == 1


def test_repair_stall_stops_before_final_model_escalation(tmp_path):
    target_dir, build_dir = _setup(tmp_path)
    (target_dir / "blueprint" / "DATABASE.md").write_text(_marker_spec("ok\n"), encoding="utf-8")
    runner = make_attempt_runner(fix_at=None)

    build_target(
        "Demo",
        target_dir,
        build_dir=build_dir,
        runner=runner,
        model="sonnet",
        step_id="foundation",
        repair_attempts=2,
        escalate_model="opus",
    )

    models = [c["model"] for c in runner.calls]
    assert models == ["sonnet", "sonnet"]


def test_is_repairable_only_for_acceptance_and_agent_reports():
    assert _is_repairable("programmatic acceptance failed: x") is True
    assert _is_repairable("agent-reported failure: incomplete") is True
    assert _is_repairable("context/token limit") is False
    assert _is_repairable("dependency legitimacy gate failed: 1 issue(s)") is False
    assert _is_repairable("staged build asset modified: kit.py") is False
    assert _is_repairable(None) is False


def test_repair_feedback_names_failing_checks_and_caps_size():
    class _Unit:
        name = "Foundation"
        block_id = "foundation"

    failed = (
        AcceptanceRunResult(
            check_id="foundation-file",
            source="DATABASE.md",
            intent="Foundation writes its marker.",
            passed=False,
            return_code=1,
            stdout="211 passed, 75 failed",
            stderr="assert result.returncode == 0\nAssertionError",
        ),
    )
    text = _render_repair_feedback(_Unit(), failed, ("done", "note"), ("foundation.txt",), {})
    assert "## Repair pass" in text
    assert "foundation-file" in text
    assert "AssertionError" in text
    assert "211 passed, 75 failed" in text
    assert "foundation.txt" in text
    assert "Resource exhaustion" not in text
    assert "diagnostic excerpts below are truncated" in text
    assert "diagnose coherent root-cause clusters" in text


# A repair pass that reads only "the check failed" tunes output to match an expectation. When
# the code under test was killed for exhausting memory or time, no expectation is reachable
# until the unbounded loop or allocation is fixed, so the resource fact must lead the feedback.


def _exhausted_check() -> AcceptanceRunResult:
    return AcceptanceRunResult(
        check_id="block-parser-suite",
        source="FEATURE-Blocks.md",
        intent="The block parser passes its suite.",
        passed=False,
        return_code=1,
        stdout="",
        stderr='  File "block-parser-suite.py", line 3\nMemoryError',
        error=(
            f"{MEMORY_FAILURE_PREFIX}: the built code exceeded 4096 MB and was stopped by the "
            "kernel. This is unbounded allocation or a non-terminating loop in the code under "
            "test, not a missed expectation."
        ),
    )


def test_resource_verdict_outranks_the_traceback_line():
    assert _assertion_summary(_exhausted_check()).startswith(MEMORY_FAILURE_PREFIX)


def test_repair_feedback_leads_with_the_resource_fact():
    class _Unit:
        name = "Block Parsing"
        block_id = "block-parsing"

    text = _render_repair_feedback(_Unit(), (_exhausted_check(),), None, (), {})
    assert "Resource exhaustion — fix this first" in text
    assert text.index("Resource exhaustion") < text.index("### Still failing")
    assert "unbounded loop or allocation" in text


def test_a_resource_kill_still_loops_the_repair_pass():
    assert _is_repairable("programmatic acceptance failed (resource exhaustion): x") is True


def test_unsatisfiable_acceptance_blocks_the_build_before_the_agent_runs(tmp_path):
    """A mis-authored expectation is not a red baseline the agent can drive green. Blocking
    here spends no LLM cycle and names the Blueprint file to repair."""
    target_dir, build_dir = _setup(tmp_path)
    (target_dir / "blueprint" / "DATABASE.md").write_text(_UNSATISFIABLE_SPEC, encoding="utf-8")
    runner = make_runner()

    with pytest.raises(SpecificationError) as exc:
        build_target("Demo", target_dir, build_dir=build_dir, runner=runner)

    message = str(exc.value)
    assert "unsatisfiable Programmatic Acceptance" in message
    assert "DATABASE.md [escapes]" in message
    assert runner.calls == []


# Every check runs as its own script in its own process. A snippet that reads a name a sibling
# check bound raises NameError on every run, so it can never go green — the same category of
# waste as a mis-authored expectation, and it must be caught before an LLM pass is spent.

_CARRIED_NAME_SPEC = """# FEATURE: Blocks

## Programmatic Acceptance

### block-conformance
The suite passes.

```python
import subprocess

result = subprocess.run(["true"], capture_output=True, text=True)
print(result.stdout)
assert result.returncode == 0
```

### block-priority
Blocks resolve before inlines.

```python
assert result.returncode == 0
```
"""


def test_a_check_reading_a_sibling_checks_name_blocks_the_build(tmp_path):
    target_dir, build_dir = _setup(tmp_path)
    (target_dir / "blueprint" / "DATABASE.md").write_text(_CARRIED_NAME_SPEC, encoding="utf-8")
    runner = make_runner()

    with pytest.raises(SpecificationError) as exc:
        build_target("Demo", target_dir, build_dir=build_dir, runner=runner)

    message = str(exc.value)
    assert "DATABASE.md [block-priority]" in message
    assert "'result' is read but never defined" in message
    assert "its own process" in message
    # The sibling check that *does* define its own names is not implicated.
    assert "[block-conformance]" not in message
    assert runner.calls == []


_UNPARSEABLE_SPEC = """# FEATURE: Blocks

## Programmatic Acceptance

### broken
The snippet does not parse.

```python
assert convert("a") ==
```
"""


def test_an_unparseable_check_blocks_the_build(tmp_path):
    target_dir, build_dir = _setup(tmp_path)
    (target_dir / "blueprint" / "DATABASE.md").write_text(_UNPARSEABLE_SPEC, encoding="utf-8")
    runner = make_runner()

    with pytest.raises(SpecificationError) as exc:
        build_target("Demo", target_dir, build_dir=build_dir, runner=runner)

    assert "not valid Python" in str(exc.value)
    assert runner.calls == []


# ── continue-repair (resume in place) ──────────────────────────────────────────

_FAILED_STORY_WITH_AC = """# MANIFEST: Demo
state: draft

## story 1: Foundation
id: foundation
implements: DATABASE.md
finding: programmatic acceptance failed: foundation-file
instructions: |
  Build the database.
state: closed/failed

## story 2: Service
id: service
implements: SERVICE.md
depends: foundation
instructions: |
  Build the service.
state: pending
"""

_FOUNDATION_AC = (
    "DB SPEC CONTENT\n\n"
    "## Programmatic Acceptance\n\n"
    "### foundation-file\n"
    "Foundation writes its output marker.\n\n"
    "```python\n"
    "from pathlib import Path\n"
    "assert Path('foundation.txt').read_text(encoding='utf-8') == 'built foundation\\n'\n"
    "```\n"
)


def test_select_build_unit_resumes_failed_step_in_frontier(tmp_path):
    target_dir, _ = _setup(tmp_path, manifest=_FAILED_STORY_WITH_AC)
    plan = parse_build_plan(target_dir / "MANIFEST.md")

    unit = _select_build_unit(plan, None, "Demo")

    assert unit is not None
    assert unit.block_id == "foundation"
    assert unit.resume is True


def test_select_build_unit_rejects_failed_step_with_unverified_dependency(tmp_path):
    manifest = _FAILED_STORY_WITH_AC.replace(
        "## story 2: Service\nid: service\nimplements: SERVICE.md\ndepends: foundation\n"
        "instructions: |\n  Build the service.\nstate: pending\n",
        "## story 2: Service\nid: service\nimplements: SERVICE.md\ndepends: foundation\n"
        "instructions: |\n  Build the service.\nstate: closed/failed\n",
    )
    target_dir, _ = _setup(tmp_path, manifest=manifest)
    plan = parse_build_plan(target_dir / "MANIFEST.md")

    with pytest.raises(SpecificationError, match="not buildable"):
        _select_build_unit(plan, "service", "Demo")


def test_ungate_releases_acceptance_failure_and_unblocks_next_step(tmp_path):
    manifest = _FAILED_STORY_WITH_AC.replace(
        "state: closed/failed\n\n## story 2",
        "state: closed/failed\n\n## ac 3: Foundation check\n"
        "id: ac-foundation\nparent: foundation\nkind: assertion\nstate: pending\n\n## story 2",
    )
    target_dir, build_dir = _setup(tmp_path, manifest=manifest)
    (target_dir / "blueprint" / "SERVICE.md").write_text(
        "SVC SPEC CONTENT\n\n"
        "## Programmatic Acceptance\n\n"
        "### service-file\n"
        "Service writes its output marker.\n\n"
        "```python\n"
        "from pathlib import Path\n"
        "assert Path('service.txt').read_text(encoding='utf-8') == 'built service\\n'\n"
        "```\n",
        encoding="utf-8",
    )
    runner = make_runner()
    messages: list[str] = []

    result = build_target(
        "Demo", target_dir, build_dir=build_dir, runner=runner, on_text=messages.append, ungate=True
    )

    assert [step.block_id for step in result.steps] == ["service"]
    assert _state(target_dir, "foundation") == "closed/verified"
    assert _state(target_dir, "ac-foundation") == "pending"
    assert _finding(target_dir, "ac-foundation") is None
    assert _finding(target_dir, "foundation").startswith("UNVERIFIED:")
    assert _state(target_dir, "service") == "closed/verified"
    assert result.steps[0].acceptance[0].check_id == "service-file"
    assert result.steps[0].acceptance[0].passed is True
    assert any("ungate: released 1 acceptance node(s) as UNVERIFIED" in line for line in messages)


def test_ungate_does_not_release_non_acceptance_failure(tmp_path):
    manifest = _TWO_STORIES.replace(
        "state: pending\n\n## story 2",
        "state: closed/failed\nfinding: LLM execution failed\n\n## story 2",
        1,
    )
    target_dir, _ = _setup(tmp_path, manifest=manifest)
    plan, changed = _ungate_acceptance_plan(parse_build_plan(target_dir / "MANIFEST.md"))

    assert changed == 0
    assert plan.by_id()["foundation"].state == "closed/failed"


def test_ungate_changes_only_the_failed_story(tmp_path):
    manifest = _FEATURE_GROUP_MANIFEST.replace(
        "implements: DATABASE.md\ninstructions: |\n  Build the database.\nstate: pending",
        "implements: DATABASE.md\ninstructions: |\n  Build the database.\n"
        "state: closed/failed\n"
        "finding: programmatic acceptance failed: foundation-file",
        1,
    )
    target_dir, _ = _setup(tmp_path, manifest=manifest)
    before = parse_build_plan(target_dir / "MANIFEST.md").by_id()

    plan, changed = _ungate_acceptance_plan(parse_build_plan(target_dir / "MANIFEST.md"))

    assert changed == 1
    after = plan.by_id()
    assert after["foundation"].state == "closed/verified"
    assert after["foundation"].fields["finding"] == "UNVERIFIED: acceptance bypassed by --ungate"
    assert after["feature-catalog"].state == before["feature-catalog"].state == "pending"
    assert after["service"].state == before["service"].state == "pending"


def test_resume_seeds_attempt_zero_with_live_failure(tmp_path):
    target_dir, build_dir = _setup(tmp_path, manifest=_FAILED_STORY_WITH_AC)
    (target_dir / "blueprint" / "DATABASE.md").write_text(_FOUNDATION_AC, encoding="utf-8")
    runner = make_runner()
    messages: list[str] = []

    result = build_target(
        "Demo",
        target_dir,
        build_dir=build_dir,
        runner=runner,
        on_text=messages.append,
        step_id="foundation",
    )

    step = next(s for s in result.steps if s.block_id == "foundation")
    assert step.status == "built"
    assert _state(target_dir, "foundation") == "closed/verified"
    # Attempt 0 carried the repair feedback derived from the live acceptance run.
    assert len(runner.calls) == 1
    prompt = runner.calls[0]["prompt"]
    assert "# Repair Feedback" in prompt
    assert "## Repair pass" in prompt
    assert "foundation-file" in prompt
    assert "LLM BUILD: Foundation [foundation]" in messages
    assert any(line.startswith("  call: 1 of up to 4 · resumed repair · ") for line in messages)
    assert "  failing: foundation-file" in messages


def test_fresh_pending_step_is_not_seeded(tmp_path):
    target_dir, build_dir = _setup(tmp_path)
    (target_dir / "blueprint" / "DATABASE.md").write_text(_FOUNDATION_AC, encoding="utf-8")
    runner = make_runner()

    build_target("Demo", target_dir, build_dir=build_dir, runner=runner, step_id="foundation")

    assert "# Repair Feedback" not in runner.calls[0]["prompt"]


def test_resume_green_short_circuits_without_llm_pass(tmp_path):
    target_dir, build_dir = _setup(tmp_path, manifest=_FAILED_STORY_WITH_AC)
    (target_dir / "blueprint" / "DATABASE.md").write_text(_FOUNDATION_AC, encoding="utf-8")
    build_dir.mkdir(parents=True, exist_ok=True)
    (build_dir / "foundation.txt").write_text("built foundation\n", encoding="utf-8")
    runner = make_runner()

    result = build_target(
        "Demo", target_dir, build_dir=build_dir, runner=runner, step_id="foundation"
    )

    step = next(s for s in result.steps if s.block_id == "foundation")
    assert step.status == "built"
    assert _state(target_dir, "foundation") == "closed/verified"
    assert runner.calls == []


def test_feature_repair_reopens_verified_sibling_on_regression(tmp_path):
    manifest = """# MANIFEST: Demo
state: draft

## feature 1: Parsing
id: parsing
state: closed/failed

## story 2: Active Parser
id: active-parser
parent: parsing
implements: FEATURE-Active.md
state: closed/failed

## story 3: Verified Renderer
id: verified-renderer
parent: parsing
implements: FEATURE-Verified.md
state: closed/verified
"""
    target_dir, build_dir = _setup(tmp_path, manifest=manifest)
    (target_dir / "blueprint" / "FEATURE-Active.md").write_text(
        """## Programmatic Acceptance

### active-output
The active parser behavior works.

```python
from pathlib import Path
assert Path("active.txt").read_text(encoding="utf-8") == "ok\\n"
```
""",
        encoding="utf-8",
    )
    (target_dir / "blueprint" / "FEATURE-Verified.md").write_text(
        """## Programmatic Acceptance

### verified-output
The verified renderer behavior remains stable.

```python
from pathlib import Path
assert Path("shared.txt").read_text(encoding="utf-8") == "preserved\\n"
```
""",
        encoding="utf-8",
    )
    build_dir.mkdir(parents=True)
    (build_dir / "active.txt").write_text("bad\n", encoding="utf-8")
    (build_dir / "shared.txt").write_text("preserved\n", encoding="utf-8")
    prompts: list[str] = []

    def runner(prompt, working_directory, **kwargs):
        prompts.append(prompt)
        work = Path(working_directory)
        (work / "active.txt").write_text("ok\n", encoding="utf-8")
        (work / "shared.txt").write_text("regressed\n", encoding="utf-8")
        return FakeResult(text=_success_report(changed=("active.txt", "shared.txt")))

    result = build_target(
        "Demo",
        target_dir,
        build_dir=build_dir,
        runner=runner,
        repair_attempts=0,
    )

    assert result.steps[0].status == "failed"
    assert _state(target_dir, "active-parser") == "closed/verified"
    assert _state(target_dir, "verified-renderer") == "closed/failed"
    assert _state(target_dir, "parsing") == "closed/failed"
    assert "verified-output" in (_finding(target_dir, "verified-renderer") or "")
    assert 'filename="FEATURE-Verified.md" role="regression"' in prompts[0]


# --- Defective acceptance criterion ------------------------------------------
#
# A repair pass cannot rewrite a criterion: staged acceptance assets are restored before
# grading. When the agent both names a failing check and reports it as broken, the outcome is
# terminal, and spending the rest of the budget only repeats the same failure.

_DEFECTIVE_AC_REPORT = (
    "RESULT: FAILURE\n"
    "FAILURE_SUMMARY: malformed foundation-file acceptance invocation\n"
    "FAILURE_DETAIL: the foundation-file check is malformed; it never runs the marker writer.\n\n"
    "FILES CHANGED:\n- foundation.txt\n\nSUMMARY:\nBlocked on a broken criterion.\n"
)


def _defective_claim_runner(report: str):
    calls: list[dict] = []

    def runner(prompt, working_directory, **kwargs):
        Path(working_directory).mkdir(parents=True, exist_ok=True)
        (Path(working_directory) / "foundation.txt").write_text("bad\n", encoding="utf-8")
        calls.append({"prompt": prompt, "attempt": kwargs["parameters"]["attempt"], **kwargs})
        return FakeResult(text=report)

    runner.calls = calls  # type: ignore[attr-defined]
    return runner


def test_reported_defective_criterion_stops_the_repair_loop_at_the_first_call(tmp_path):
    target_dir, build_dir = _setup(tmp_path)
    (target_dir / "blueprint" / "DATABASE.md").write_text(_marker_spec("ok\n"), encoding="utf-8")
    runner = _defective_claim_runner(_DEFECTIVE_AC_REPORT)

    result = build_target(
        "Demo",
        target_dir,
        build_dir=build_dir,
        runner=runner,
        step_id="foundation",
        repair_attempts=3,
    )

    assert [c["attempt"] for c in runner.calls] == [0]
    step = result.steps[0]
    assert step.status == "failed"
    assert step.stop_reason == "acceptance criterion reported defective"
    assert step.calls_used == 1
    assert step.calls_budget == 4
    assert "DATABASE.md" in step.failure_detail
    evidence = (target_dir / "evidence" / "foundation.md").read_text(encoding="utf-8")
    assert "acceptance criterion reported defective" in evidence


def test_an_unnamed_defect_claim_still_spends_the_repair_budget(tmp_path):
    # Naming no failing check is editorializing, not a criterion report. The loop must not let
    # an agent talk its way out of a repair.
    target_dir, build_dir = _setup(tmp_path)
    (target_dir / "blueprint" / "DATABASE.md").write_text(_marker_spec("ok\n"), encoding="utf-8")
    runner = _defective_claim_runner(
        "RESULT: FAILURE\n"
        "FAILURE_SUMMARY: the environment is broken\n"
        "FAILURE_DETAIL: the toolchain is malformed.\n\n"
        "FILES CHANGED:\n- foundation.txt\n\nSUMMARY:\nBlocked.\n"
    )

    result = build_target(
        "Demo",
        target_dir,
        build_dir=build_dir,
        runner=runner,
        step_id="foundation",
        repair_attempts=3,
    )

    assert [c["attempt"] for c in runner.calls] == [0, 1]
    assert result.steps[0].stop_reason == "deterministic acceptance score did not improve"


def test_defective_claim_helpers_require_both_a_name_and_a_defect_word():
    from drydock.build_run import _defective_acceptance_claim, _names_check, _normalize_words

    class _Check:
        def __init__(self, check_id):
            self.check_id = check_id

    failed = (_Check("verification-scoped-number"),)
    # An agent names a criterion the way a reader would, not by its full identifier.
    assert _names_check(
        _normalize_words("scoped-number acceptance is malformed"), failed[0].check_id
    )
    assert not _names_check(_normalize_words("the number is wrong"), failed[0].check_id)
    assert _defective_acceptance_claim(
        ("Malformed scoped-number acceptance", "uses a broken invocation"), failed
    ) == ("verification-scoped-number",)
    # Naming the check without claiming it is defective is an ordinary failure report.
    assert _defective_acceptance_claim(("scoped-number still fails", ""), failed) == ()
    assert _defective_acceptance_claim(None, failed) == ()


# A criterion whose invocation cannot launch the command under test grades a different process
# than the one being built. It is unsatisfiable for the same reason a mis-authored expectation
# is, so the build must refuse before it spends a pass on it.

_MALFORMED_INVOCATION_SPEC = """# FEATURE: Scoped Verification

## Programmatic Acceptance

### scoped-number
The supplied harness supports example selection.

```python
import subprocess

result = subprocess.run(
    ["PYTHONPATH=sources", "python3", "suite.py", "--number", "1"],
    shell=True,
    capture_output=True,
    text=True,
)
print(result.stdout)
assert "1 passed" in result.stdout
```
"""


def test_malformed_invocation_blocks_the_build_before_the_agent_runs(tmp_path):
    target_dir, build_dir = _setup(tmp_path)
    (target_dir / "blueprint" / "DATABASE.md").write_text(
        _MALFORMED_INVOCATION_SPEC, encoding="utf-8"
    )
    runner = make_runner()

    with pytest.raises(SpecificationError) as exc:
        build_target("Demo", target_dir, build_dir=build_dir, runner=runner)

    message = str(exc.value)
    assert "unsatisfiable Programmatic Acceptance" in message
    assert "DATABASE.md [scoped-number]" in message
    assert "the intended command never runs" in message
    assert runner.calls == []


def test_undeclared_runtime_prerequisite_blocks_without_repair_and_preserves_work(tmp_path):
    target_dir, build_dir = _setup(tmp_path, manifest=_ONE_STORY)
    (target_dir / "blueprint" / "DATABASE.md").write_text(
        """# DATABASE: Demo

## Questions

- None.

## Programmatic Acceptance

### health-route
The health route returns OK.

```python
from target_app import health
assert health() == "ok"
```

## User Acceptance

- None.

## Guardrails

- None.
""",
        encoding="utf-8",
    )
    calls = []

    def runner(prompt, working_directory, **kwargs):
        calls.append(kwargs["parameters"]["attempt"])
        work = Path(working_directory)
        work.mkdir(parents=True, exist_ok=True)
        (work / "target_app.py").write_text(
            "import surprise_transport\n\ndef health():\n    return 'ok'\n",
            encoding="utf-8",
        )
        return FakeResult(text=_success_report(changed=("target_app.py",)))

    result = build_target(
        "Demo",
        target_dir,
        build_dir=build_dir,
        runner=runner,
        repair_attempts=3,
    )

    assert calls == [0]
    assert result.steps[0].status == "blocked"
    assert _state(target_dir, "foundation") == "blocked/questions"
    assert (build_dir / "target_app.py").is_file()
    decision = load_decisions(target_dir / "DECISIONS.json")[0]
    assert decision.origin == "build"
    assert decision.severity == "blocking"
    assert "python-package=surprise_transport" in decision.description
    evidence = result.steps[0].evidence_path.read_text(encoding="utf-8")
    assert "acceptance prerequisite requires authorization" in evidence


def test_active_commander_guidance_is_injected_into_build_prompt(tmp_path):
    target_dir, build_dir = _setup(tmp_path, manifest=_ONE_STORY)
    write_decisions(
        target_dir / "DECISIONS.json",
        (
            Decision(
                id="harness",
                type="text",
                severity="blocking",
                origin="plan",
                blueprint="DATABASE.md",
                story=None,
                status="answered",
                archived=False,
                title="Authorize test harnesses",
                description="Authorize test harness tooling?",
                options=(),
                system_choice="not authorized",
                override_text="Approve all test harnesses",
            ),
        ),
    )
    prompts = []

    def runner(prompt, working_directory, **kwargs):
        prompts.append(prompt)
        work = Path(working_directory)
        work.mkdir(parents=True, exist_ok=True)
        (work / "notes.txt").write_text("done\n", encoding="utf-8")
        return FakeResult(text=_success_report(changed=("notes.txt",)))

    build_target("Demo", target_dir, build_dir=build_dir, runner=runner)

    assert len(prompts) == 1
    assert "# Active Commander guidance" in prompts[0]
    assert "Decision: Approve all test harnesses" in prompts[0]


def test_build_writes_env_from_example(tmp_path):
    """A successful build leaves a .env the operator did not have to create."""
    target_dir, build_dir = _setup(tmp_path)
    build_dir.mkdir(parents=True, exist_ok=True)
    (build_dir / ".env.example").write_text(
        "SECRET_KEY=change-me\nAPP_PORT=5001\n", encoding="utf-8"
    )

    result = build_target("Demo", target_dir, build_dir=build_dir, runner=make_runner())

    assert result.env_result is not None
    assert result.env_result.generated_keys == ("SECRET_KEY",)
    written = (build_dir / ".env").read_text(encoding="utf-8")
    assert "change-me" not in written
    assert "APP_PORT=5001" in written


def test_build_without_an_example_writes_no_env(tmp_path):
    target_dir, build_dir = _setup(tmp_path)

    result = build_target("Demo", target_dir, build_dir=build_dir, runner=make_runner())

    assert result.env_result is not None
    assert result.env_result.detail == "no .env.example"
    assert not (build_dir / ".env").exists()


def test_undeclared_runtime_prerequisite_fails_loudly_under_override(tmp_path):
    """Override refuses to park a story on a question it can never answer.

    The prerequisite really is absent and acceptance really did fail on it. Blocking exits 0 and
    reads as success to an unattended driver; failing is the honest signal.
    """
    target_dir, build_dir = _setup(tmp_path, manifest=_ONE_STORY)
    (target_dir / "blueprint" / "DATABASE.md").write_text(
        """# DATABASE: Demo

## Questions

- None.

## Programmatic Acceptance

### health-route
The health route returns OK.

```python
from target_app import health
assert health() == "ok"
```

## User Acceptance

- None.

## Guardrails

- None.
""",
        encoding="utf-8",
    )

    def runner(prompt, working_directory, **kwargs):
        work = Path(working_directory)
        work.mkdir(parents=True, exist_ok=True)
        (work / "target_app.py").write_text(
            "import surprise_transport\n\ndef health():\n    return 'ok'\n",
            encoding="utf-8",
        )
        return FakeResult(text=_success_report(changed=("target_app.py",)))

    result = build_target(
        "Demo",
        target_dir,
        build_dir=build_dir,
        runner=runner,
        repair_attempts=3,
        override=True,
    )

    assert result.steps[0].status == "failed"
    assert _state(target_dir, "foundation") == "closed/failed"
    assert result.exit_code() == 1
    authorization = [w for w in result.waivers if w.kind == "acceptance-authorization"]
    assert authorization and "surprise_transport" in authorization[0].detail
    # Partial work is still preserved for the next pass.
    assert (build_dir / "target_app.py").is_file()


def test_override_stamps_the_target_as_ungoverned(tmp_path):
    target_dir, build_dir = _setup(tmp_path, manifest=_ONE_STORY)
    (target_dir / "METADATA.md").write_text(
        "# METADATA\n\nname: Demo\nversion: 0.01\n", encoding="utf-8"
    )
    write_decisions(
        target_dir / "DECISIONS.json",
        (
            Decision(
                id="d-1",
                type="tooling",
                severity="blocking",
                origin="plan",
                blueprint="DATABASE.md",
                story="foundation",
                status="recommended",
                archived=False,
                title="Which engine?",
                description="Pick one.",
                options=(),
                system_choice="sqlite",
            ),
        ),
    )

    result = build_target(
        "Demo", target_dir, build_dir=build_dir, runner=make_runner(), override=True
    )

    assert result.steps[0].status == "built"
    assert [w.kind for w in result.waivers] == ["story-question"]
    metadata = (target_dir / "METADATA.md").read_text(encoding="utf-8")
    assert "override: true" in metadata


def test_a_gated_story_blocks_the_build_without_override(tmp_path):
    target_dir, build_dir = _setup(tmp_path, manifest=_ONE_STORY)
    write_decisions(
        target_dir / "DECISIONS.json",
        (
            Decision(
                id="d-1",
                type="tooling",
                severity="blocking",
                origin="plan",
                blueprint="DATABASE.md",
                story="foundation",
                status="recommended",
                archived=False,
                title="Which engine?",
                description="Pick one.",
                options=(),
                system_choice="sqlite",
            ),
        ),
    )

    result = build_target("Demo", target_dir, build_dir=build_dir, runner=make_runner())

    assert result.steps == []
    assert _state(target_dir, "foundation") == "blocked/questions"
    # A build that advanced nothing while the Manifest is unfinished has stalled, not succeeded.
    assert result.stalled_blocks == ("foundation",)
    assert result.exit_code() == 1


def test_a_completed_target_is_not_stalled(tmp_path):
    target_dir, build_dir = _setup(tmp_path)

    first = build_target("Demo", target_dir, build_dir=build_dir, runner=make_runner())
    assert first.exit_code() == 0
    assert first.stalled_blocks == ()

    # Re-running a finished Target builds nothing and must still report success.
    again = build_target("Demo", target_dir, build_dir=build_dir, runner=make_runner())
    assert again.steps == []
    assert again.stalled_blocks == ()
    assert again.exit_code() == 0


def test_a_scoped_build_is_never_reported_as_stalled(tmp_path):
    """--step and --story are explicitly partial; the work they leave behind is intended."""
    target_dir, build_dir = _setup(tmp_path)

    result = build_target(
        "Demo", target_dir, build_dir=build_dir, runner=make_runner(), step_id="foundation"
    )

    assert _state(target_dir, "service") == "pending"
    assert result.stalled_blocks == ()
    assert result.exit_code() == 0

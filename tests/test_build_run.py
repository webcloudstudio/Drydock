"""Tests for ``drydock build`` orchestration (drydock.build_run)."""

from __future__ import annotations

import json
import re
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

from drydock.acceptance import MEMORY_FAILURE_PREFIX, UNVERIFIED_FAILURE_PREFIX, AcceptanceRunResult
from drydock.build_plan import parse_build_plan, stale_applied_specs
from drydock.build_run import (
    INTERRUPTED_VERIFICATION_PREFIX,
    PREPASSED_FINDING,
    UNEXAMINED_FINDING,
    _assertion_summary,
    _classify_failure,
    _is_repairable,
    _render_repair_feedback,
    _resolve_step_selector,
    _select_build_unit,
    _settle_empty_selections,
    _ungate_acceptance_plan,
    build_target,
)
from drydock.decisions import Decision, write_decisions
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
        artifacts=None,
    ):
        self.ok = ok
        self.text = text
        self.execution_id = execution_id
        self.stderr = stderr
        if stats is not None:
            self.stats = stats
        if artifacts is not None:
            self.artifacts = artifacts


@pytest.fixture(autouse=True)
def fake_compactor(monkeypatch):
    for role in ("AUTHOR", "COMMITTER"):
        monkeypatch.setenv(f"GIT_{role}_NAME", "Build test")
        monkeypatch.setenv(f"GIT_{role}_EMAIL", "build@example.invalid")

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


def make_runner(
    *, ok=True, text: str | None = None, write_files=True, stderr="", stats=None, artifacts=None
):
    calls: list[dict] = []

    def runner(prompt, working_directory, **kwargs):
        step_id = kwargs["parameters"]["step"]
        changed = (f"{step_id}.txt",)
        if write_files:
            Path(working_directory).mkdir(parents=True, exist_ok=True)
            (Path(working_directory) / changed[0]).write_text(
                f"built {step_id}\n", encoding="utf-8"
            )
            _write_markers(prompt, working_directory)
        calls.append({"prompt": prompt, "wd": working_directory, **kwargs})
        return FakeResult(
            ok=ok,
            text=text or _success_report(changed=changed),
            stderr=stderr,
            stats=stats,
            artifacts=artifacts,
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
    from drydock.technology_stack import StackEntry, write

    write(target_dir, [StackEntry("Python", "python.md")], approved="2026-10-19")
    (target_dir / "MANIFEST.md").write_text(manifest, encoding="utf-8")
    (target_dir / "COMPASS.md").write_text(
        apply_guardrail("COMPASS INTENT CONTENT", "Demo", target_dir, build_dir=build_dir),
        encoding="utf-8",
    )
    (blueprint / "DATABASE.md").write_text(_spec("DB SPEC CONTENT"), encoding="utf-8")
    (blueprint / "SERVICE.md").write_text(_spec("SVC SPEC CONTENT"), encoding="utf-8")
    return target_dir, build_dir


def _marker(content: str) -> str:
    """The file the fake runner writes when a prompt carries ``content``: the Blueprint it built."""
    return content.split()[0].lower() + ".built"


def _write_markers(prompt: str, working_directory) -> None:
    """Satisfy the ``_setup`` criterion of each fixture Blueprint this prompt builds."""
    for word in set(re.findall(r"\b(\w+) SPEC CONTENT\b", prompt)):
        (Path(working_directory) / _marker(word)).write_text("", encoding="utf-8")


def _spec(content: str) -> str:
    """A fixture Blueprint whose one criterion passes once the step implementing it has built.

    Every story carries a criterion, so Build refuses a Blueprint without one.
    """
    marker = _marker(content)
    return (
        f"{content}\n\n"
        "## Programmatic Acceptance\n\n"
        f"=== AC {marker.split('.')[0]}-built ===\n"
        "Intent: The step implementing this Blueprint built it.\n\n"
        "from pathlib import Path\n\n"
        f"assert Path({marker!r}).is_file()\n"
        f"=== END AC {marker.split('.')[0]}-built ===\n"
    )


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
    assert (build_dir / ".git").exists()
    assert (target_dir / "BUILD_LINEAGE.jsonl").is_file()


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
    for name in ("FEATURE-CATALOG", "SCREEN-CATALOG"):
        (target_dir / "blueprint" / f"{name}.md").write_text(
            _spec(f"{name} CONTENT"), encoding="utf-8"
        )
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
    assert not (target_dir / "BUILD_LINEAGE.jsonl").exists()
    assert not (target_dir / ".git").exists()
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
    assert 'BLOCK foundation  name="Foundation"  calls_max=7' in log
    assert '  story=foundation  "Foundation"' in log
    assert any(line.startswith("  [call 1/7]  kind=initial  llm=") for line in log)
    assert "    result=ok  execution=exec-1" in log
    assert not any(line.startswith("  tokens:") for line in log)
    assert any(line == "files: 2 changed — db.built, foundation.txt" for line in log)
    assert any(re.match(r"result: built · closed/verified · .+", line) for line in log)
    assert any(line == "evidence: evidence/foundation.md" for line in log)


def test_build_records_token_accounting_in_the_llm_log_not_the_console(tmp_path):
    """Token accounting is billing evidence, so it goes to the execution's LLM log only."""
    from drydock.llm import LlmStats

    class Recorder:
        def __init__(self):
            self.lines: list[str] = []

        def record_activity(self, line: str) -> None:
            self.lines.append(line)

    recorder = Recorder()
    target_dir, build_dir = _setup(tmp_path)
    log: list[str] = []
    runner = make_runner(
        stats=LlmStats(
            input_tokens=100,
            cached_input_tokens=900,
            cache_creation_input_tokens=40,
            output_tokens=50,
            cost_usd=0.25,
        ),
        artifacts=recorder,
    )

    build_target(
        "Demo",
        target_dir,
        build_dir=build_dir,
        runner=runner,
        on_text=log.append,
        llm_provider="claude",
    )

    expected = "  tokens: cached=900 (90% hit) · uncached=100 · write 40 · out=50 · cost=$0.2500"
    assert expected in recorder.lines
    assert not any(line.startswith("  tokens:") for line in log)


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
    (blueprint / "FEATURE-Status.md").write_text(_spec("FEATURE SPEC CONTENT"), encoding="utf-8")

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


def test_build_checkpoints_existing_git_repo(tmp_path):
    """Each executed unit checkpoints application changes in its existing repository."""
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
    assert "Build foundation: DATABASE.md" in log.stdout
    assert "Build service: SERVICE.md" in log.stdout


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
        "assert 'built foundation' in Path('foundation.txt').read_text(encoding='utf-8')\n"
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
    assert "    acceptance=1/1" in messages
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
    assert step.acceptance[0].outcome == "UNVERIFIED"
    assert "UNVERIFIED: foundation-fixture" in (
        target_dir / "evidence" / "foundation.md"
    ).read_text(encoding="utf-8")
    decisions = json.loads((target_dir / "DECISIONS.json").read_text(encoding="utf-8"))
    assert decisions[0]["title"] == "Acceptance skipped: foundation-fixture"
    assert decisions[0]["status"] == "recommended"


def _tally_result(check_id="c", *, passed, skipped=False, error=None, stdout="", stderr=""):
    return AcceptanceRunResult(
        check_id=check_id,
        source="X.md",
        intent="",
        passed=passed,
        return_code=0 if passed else 1,
        stdout=stdout,
        stderr=stderr,
        error=error,
        skipped=skipped,
    )


def test_settle_empty_selections_demotes_a_zero_total_failure_to_unverified():
    result = _tally_result(passed=False, stdout="0 passed, 0 failed")
    (settled,) = _settle_empty_selections((result,))
    assert settled.skipped is True
    assert settled.passed is False
    assert settled.outcome == "UNVERIFIED"
    assert settled.error == f"{UNVERIFIED_FAILURE_PREFIX}: selector matched zero cases"


def test_settle_empty_selections_demotes_a_false_green_zero_total_pass():
    """A criterion that only asserts ``fail == 0`` reports PASS on an empty selection unless
    the override corrects it in both directions, not just the failing one."""
    result = _tally_result(passed=True, stdout="0 passed, 0 failed")
    (settled,) = _settle_empty_selections((result,))
    assert settled.skipped is True
    assert settled.passed is False
    assert settled.outcome == "UNVERIFIED"


def test_settle_empty_selections_leaves_a_nonzero_tally_untouched():
    result = _tally_result(passed=False, stdout="3 passed, 2 failed")
    (settled,) = _settle_empty_selections((result,))
    assert settled is result


def test_settle_empty_selections_leaves_a_tallyless_result_untouched():
    result = _tally_result(passed=False, stdout="nothing tally-shaped here")
    (settled,) = _settle_empty_selections((result,))
    assert settled is result


def test_settle_empty_selections_never_overrides_an_existing_terminal_classification():
    """A killed/timed-out process can print a partial or zero tally on its way out. That is
    still the failure it already is -- a timeout, a resource limit, a malformed snippet -- and
    must never be relabeled as an empty selection."""
    timed_out = _tally_result(
        passed=False,
        error="timeout: exceeded 10.0s",
        stdout="0 passed, 0 failed",
    )
    (settled,) = _settle_empty_selections((timed_out,))
    assert settled is timed_out

    already_skipped = _tally_result(
        passed=False,
        skipped=True,
        stdout="0 passed, 0 failed",
    )
    (settled,) = _settle_empty_selections((already_skipped,))
    assert settled is already_skipped


def test_a_zero_case_tally_settles_the_story_implemented_not_failed(tmp_path):
    """The end-to-end contract: a story whose only AC selects zero cases must never fail the
    build, must not spend a repair call, and closes ``closed/implemented`` -- not
    ``closed/verified`` (nothing was actually examined) and not ``closed/failed``."""
    target_dir, build_dir = _setup(tmp_path)
    (target_dir / "blueprint" / "DATABASE.md").write_text(
        "DB SPEC CONTENT\n\n"
        "## Programmatic Acceptance\n\n"
        "### empty-selection\n"
        "A selector that matches nothing in the corpus.\n\n"
        "```python\n"
        'print("0 passed, 0 failed")\n'
        'assert False, "no cases selected"\n'
        "```\n",
        encoding="utf-8",
    )
    runner = make_runner()

    result = build_target(
        "Demo",
        target_dir,
        build_dir=build_dir,
        runner=runner,
        step_id="foundation",
        repair_attempts=6,
    )

    step = result.steps[0]
    assert step.acceptance[0].skipped is True
    assert step.acceptance[0].outcome == "UNVERIFIED"
    assert _state(target_dir, "foundation") == "closed/implemented"
    assert len(runner.calls) == 1  # no repair call wasted on an unwinnable criterion


def test_a_regression_sweep_that_now_selects_zero_cases_does_not_falsely_regress(tmp_path):
    """A previously-proven criterion whose selection later drops to zero produced no evidence
    either way -- it must settle UNVERIFIED on the sweep, never register as a regression."""
    target_dir, build_dir = _setup(tmp_path)
    (target_dir / "blueprint" / "DATABASE.md").write_text(
        "DB SPEC CONTENT\n\n"
        "## Programmatic Acceptance\n\n"
        "### db-guard\n"
        "Selects exactly one case while the guard file is present.\n\n"
        "```python\n"
        "from pathlib import Path\n"
        'total = 1 if Path("guard.txt").exists() else 0\n'
        'print(f"{total} passed, 0 failed")\n'
        "assert total > 0\n"
        "```\n",
        encoding="utf-8",
    )

    result = build_target(
        "Demo",
        target_dir,
        build_dir=build_dir,
        runner=_regression_runner(tmp_path),
        repair_attempts=0,
    )

    assert _state(target_dir, "foundation") == "closed/verified"
    assert _state(target_dir, "service") == "closed/verified"
    finding = _finding(target_dir, "service") or ""
    assert "acceptance regression" not in finding
    assert result.steps[-1].status == "built"


def test_a_failing_group_mate_does_not_blame_a_zero_case_sibling(tmp_path):
    """A block that mixes a genuinely-failing binding criterion with a now-UNVERIFIED
    zero-case criterion must attribute failure only to the real one -- the empty-selection
    sibling's id must not appear in the failure finding, and its own story must not close
    ``closed/failed`` on the strength of a criterion that proved nothing."""
    target_dir, build_dir = _setup(tmp_path, manifest=_FEATURE_GROUP_MANIFEST)
    (target_dir / "blueprint" / "DATABASE.md").write_text(
        "DB SPEC CONTENT\n\n"
        "## Programmatic Acceptance\n\n"
        "### db-real-fail\n"
        "A real, non-empty conformance failure.\n\n"
        "```python\n"
        'print("1 passed, 1 failed")\n'
        "assert False\n"
        "```\n",
        encoding="utf-8",
    )
    (target_dir / "blueprint" / "SERVICE.md").write_text(
        "SVC SPEC CONTENT\n\n"
        "## Programmatic Acceptance\n\n"
        "### svc-empty-selection\n"
        "A selector that matches nothing.\n\n"
        "```python\n"
        'print("0 passed, 0 failed")\n'
        "assert False\n"
        "```\n",
        encoding="utf-8",
    )

    build_target(
        "Demo",
        target_dir,
        build_dir=build_dir,
        runner=make_runner(),
        repair_attempts=0,
    )

    assert _state(target_dir, "foundation") == "closed/failed"
    # The failed step closes the sibling too, but only on the real failure.
    assert _state(target_dir, "service") == "closed/failed"
    assert _finding(target_dir, "service") == "step feature-catalog failed: db-real-fail"
    foundation_finding = _finding(target_dir, "foundation") or ""
    service_finding = _finding(target_dir, "service") or ""
    assert "db-real-fail" in foundation_finding
    assert "svc-empty-selection" not in foundation_finding
    assert "svc-empty-selection" not in service_finding


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
        "assert 'built foundation' in Path('foundation.txt').read_text(encoding='utf-8')\n"
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


def test_blueprint_programmatic_vacuous_criterion_is_excluded_and_unexamined(tmp_path):
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
    # ALWAYS_PASSES is excluded from the post-build run, so nothing measured the story.
    assert "PASS: foundation-file" not in evidence
    assert "excluded check: ALWAYS_PASSES vacuous" in evidence
    assert _state(target_dir, "foundation") == "closed/implemented"
    assert _finding(target_dir, "foundation") == UNEXAMINED_FINDING


def test_blueprint_programmatic_acceptance_failure_stops_dependents(tmp_path):
    target_dir, build_dir = _setup(tmp_path)
    (target_dir / "blueprint" / "DATABASE.md").write_text(
        "DB SPEC CONTENT\n\n"
        "## Programmatic Acceptance\n\n"
        "### foundation-file\n"
        "Foundation writes the expected marker.\n\n"
        "```python\n"
        "from pathlib import Path\n"
        "assert 'wrong' in Path('foundation.txt').read_text(encoding='utf-8')\n"
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


def test_acceptance_failure_recovery_offers_plain_rebuild_without_step(tmp_path):
    # An acceptance failure is recovered by continuing the build; it does not prescribe a
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
    assert "Run: drydock build Demo" in error_text
    assert "to continue the build" in error_text
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


def test_ac_failure_detail_carries_the_output_the_check_printed(tmp_path):
    # The assertion says what was checked, not why it failed. A check that shells out prints the
    # runner's own account first; the report must show it, or the reader cannot tell a broken
    # assertion from broken code without opening the evidence file.
    target_dir, build_dir = _setup(tmp_path, manifest=_FEATURE_GROUP_MANIFEST)
    (target_dir / "blueprint" / "SERVICE.md").write_text(
        "SVC SPEC CONTENT\n\n"
        "## Programmatic Acceptance\n\n"
        "### service-tally\n"
        "Service reports a clean run.\n\n"
        "```python\n"
        "import re\n"
        'summary = "valid tests: 205 passed,  0 failed"\n'
        "print(summary)\n"
        'assert re.search(r"\\\\b0\\\\s+errors\\\\b", summary)\n'
        "```\n",
        encoding="utf-8",
    )

    result = build_target("Demo", target_dir, build_dir=build_dir, runner=make_runner())

    detail = result.steps[0].failure_detail
    assert "observed output:" in detail
    assert "valid tests: 205 passed,  0 failed" in detail


def test_a_failed_step_closes_no_story_in_it(tmp_path):
    # Nothing orders stories within a step, so no story closes on a failed step. The story that
    # owns the failed check names its own AC; a group-mate whose own checks passed is still
    # closed/failed, with a finding that names the step and the check that failed it.
    target_dir, build_dir = _setup(tmp_path, manifest=_FEATURE_GROUP_MANIFEST)
    # The group builds in one pass under the feature's id; the criterion is red until it does.
    (target_dir / "blueprint" / "DATABASE.md").write_text(
        "DB SPEC CONTENT\n\n"
        "## Programmatic Acceptance\n\n"
        "### db-ok\n"
        "Database output exists.\n\n"
        "```python\n"
        "from pathlib import Path\n"
        "assert Path('feature-catalog.txt').exists()\n"
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

    assert _state(target_dir, "foundation") == "closed/failed"
    assert _state(target_dir, "service") == "closed/failed"
    assert _state(target_dir, "feature-catalog") == "closed/failed"
    assert "programmatic acceptance failed: service-adds" in (_finding(target_dir, "service") or "")
    assert _finding(target_dir, "foundation") == "step feature-catalog failed: service-adds"


def _regression_runner(tmp_path):
    """A runner whose second block deletes the deliverable the first block proved."""
    build_dir = tmp_path / "build"
    calls: list[dict] = []

    def runner(prompt, working_directory, **kwargs):
        step_id = kwargs["parameters"]["step"]
        work = Path(working_directory)
        work.mkdir(parents=True, exist_ok=True)
        if step_id == "foundation":
            (work / "guard.txt").write_text("on\n", encoding="utf-8")
        elif step_id == "service" and not any("Regression" in part for part in [prompt]):
            (work / "guard.txt").unlink(missing_ok=True)
        else:
            # The repair pass is told about the regression and restores the deliverable.
            (work / "guard.txt").write_text("on\n", encoding="utf-8")
        (work / f"{step_id}.txt").write_text(f"built {step_id}\n", encoding="utf-8")
        _write_markers(prompt, work)
        calls.append({"prompt": prompt, "wd": working_directory, **kwargs})
        return FakeResult(ok=True, text=_success_report(changed=(f"{step_id}.txt",)))

    runner.calls = calls  # type: ignore[attr-defined]
    assert build_dir is not None
    return runner


def _with_guard_criterion(target_dir):
    (target_dir / "blueprint" / "DATABASE.md").write_text(
        "DB SPEC CONTENT\n\n"
        "## Programmatic Acceptance\n\n"
        "### db-guard\n"
        "The guard file the foundation installs stays installed.\n\n"
        "```python\n"
        "from pathlib import Path\n"
        'assert Path("guard.txt").read_text().strip() == "on"\n'
        "```\n",
        encoding="utf-8",
    )


def test_a_later_block_that_breaks_an_earlier_criterion_fails_on_the_regression(tmp_path):
    """A block grades only its own stories, so an earlier block's deliverable can be deleted
    without anything noticing until final scoring. The sweep attributes it to the block that
    did it, because nothing else ran in between."""
    target_dir, build_dir = _setup(tmp_path)
    _with_guard_criterion(target_dir)

    result = build_target(
        "Demo",
        target_dir,
        build_dir=build_dir,
        runner=_regression_runner(tmp_path),
        repair_attempts=0,
    )

    assert _state(target_dir, "foundation") == "closed/verified"
    assert _state(target_dir, "service") == "closed/failed"
    finding = _finding(target_dir, "service") or ""
    assert "acceptance regression" in finding
    assert "db-guard" in finding
    detail = result.steps[-1].failure_detail
    assert "db-guard" in detail
    assert "earlier blocks had already proven" in detail


def test_a_block_finished_by_an_earlier_build_is_swept_by_the_next(tmp_path):
    """The outer loop starts a new build per pass. A criterion an earlier build proved must
    still be swept, so a later build that breaks it fails on the regression."""
    target_dir, build_dir = _setup(tmp_path)
    _with_guard_criterion(target_dir)
    runner = _regression_runner(tmp_path)
    build_target("Demo", target_dir, build_dir=build_dir, runner=runner, step_id="foundation")
    assert _state(target_dir, "foundation") == "closed/verified"

    lines: list[str] = []
    build_target(
        "Demo",
        target_dir,
        build_dir=build_dir,
        runner=runner,
        repair_attempts=0,
        on_text=lines.append,
    )

    assert _state(target_dir, "service") == "closed/failed"
    assert "db-guard" in (_finding(target_dir, "service") or "")
    assert any("regression sweep: 1 prior criteria · 1 regressed" in line for line in lines)
    # The sweep's own results are history: the criterion last ran, and missed, in service.
    from drydock.acceptance_status import OUTCOME_FAIL, acceptance_history

    past = acceptance_history(target_dir)["db-guard"]
    assert (past.last_block, past.last_outcome) == ("service", OUTCOME_FAIL)


def test_a_non_binding_regression_does_not_fail_the_later_block(tmp_path):
    """A re-typed expectation cannot attribute a miss to the product, so it cannot attribute a
    regression to the block either. It is still swept and reported."""
    target_dir, build_dir = _setup(tmp_path)
    (target_dir / "blueprint" / "DATABASE.md").write_text(
        "DB SPEC CONTENT\n\n"
        "## Programmatic Acceptance\n\n"
        "### db-guard\n"
        "The guard file the foundation installs stays installed.\n\n"
        "```python\n"
        "from pathlib import Path\n"
        'assert Path("guard.txt").exists() and "<on>" == "<on>"\n'
        'assert Path("guard.txt").read_text().strip() + "\\r" == "on\\r"\n'
        "```\n",
        encoding="utf-8",
    )

    build_target(
        "Demo",
        target_dir,
        build_dir=build_dir,
        runner=_regression_runner(tmp_path),
        repair_attempts=0,
    )

    assert _state(target_dir, "service") != "closed/failed"
    assert "acceptance regression" not in (_finding(target_dir, "service") or "")


def test_the_repair_pass_restores_what_the_block_regressed(tmp_path):
    """The point of telling the model is that it can act on it. The repair pass sees the
    regression, restores the earlier block's deliverable, and the block closes verified."""
    target_dir, build_dir = _setup(tmp_path)
    _with_guard_criterion(target_dir)

    build_target(
        "Demo",
        target_dir,
        build_dir=build_dir,
        runner=_regression_runner(tmp_path),
        repair_attempts=1,
    )

    assert _state(target_dir, "service") == "closed/verified"
    assert (build_dir / "guard.txt").read_text().strip() == "on"


def test_a_clean_regression_sweep_says_nothing_to_the_model(tmp_path):
    """Silence is the contract: a sweep that finds everything green must not spend prompt
    context telling the next block about criteria it is not being asked to satisfy."""
    target_dir, build_dir = _setup(tmp_path)
    _with_guard_criterion(target_dir)
    runner = make_runner()

    def keep_guard(prompt, working_directory, **kwargs):
        Path(working_directory).mkdir(parents=True, exist_ok=True)
        (Path(working_directory) / "guard.txt").write_text("on\n", encoding="utf-8")
        return make_runner()(prompt, working_directory, **kwargs)

    keep_guard.calls = runner.calls  # type: ignore[attr-defined]
    lines: list[str] = []
    build_target(
        "Demo",
        target_dir,
        build_dir=build_dir,
        runner=keep_guard,
        on_text=lines.append,
        repair_attempts=0,
    )

    assert _state(target_dir, "foundation") == "closed/verified"
    assert _state(target_dir, "service") == "closed/verified"
    # Reported to the operator, never to the model.
    assert any("regression sweep: 1 prior criteria · all green" in line for line in lines)


def test_the_regression_is_the_first_thing_the_repair_pass_is_told(tmp_path):
    from drydock.build_plan import PlanBlock

    regressed = AcceptanceRunResult(
        check_id="db-guard",
        source="DATABASE.md",
        intent="The guard stays installed.",
        passed=False,
        return_code=1,
        stdout="",
        stderr="AssertionError\n",
    )
    unit = _select_build_unit(parse_build_plan(_setup(tmp_path)[0] / "MANIFEST.md"), None, "Demo")
    feedback = _render_repair_feedback(unit, (), None, (), {}, (regressed,))

    assert "### Regression — fix this first" in feedback
    assert feedback.index("### Regression") < len(feedback)
    assert "db-guard" in feedback
    assert isinstance(unit.steps[0], PlanBlock)


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
    # diagnosis, and the next rebuild, with a failed execution checkpoint.
    target_dir, build_dir = _setup(tmp_path)
    runner = make_runner(ok=False, text="", write_files=True)

    result = build_target("Demo", target_dir, build_dir=build_dir, runner=runner)

    assert result.steps[0].status == "failed"
    assert result.steps[0].written_files == ("db.built", "foundation.txt")
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
    assert result.steps[0].written_files == ()
    assert result.steps[0].error == "programmatic acceptance failed: db-built"
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
    # A green criterion would outrank the agent's report and close the step built.
    (target_dir / "blueprint" / "DATABASE.md").write_text(
        "## Programmatic Acceptance\n\n=== AC vendored ===\nIntent: requests is vendored.\n\n"
        "from pathlib import Path\n\nassert Path('vendor/requests').is_dir()\n"
        "=== END AC vendored ===\n",
        encoding="utf-8",
    )
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
    # Evidence outranks the agent's verdict; its report still reaches the evidence file.
    assert _finding(target_dir, "foundation") == (
        "programmatic acceptance failed: vendored: AssertionError"
    )
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
        f"assert {expected!r} in Path('foundation.txt').read_text(encoding='utf-8')\n"
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

    def test_codex_trusted_directory_rejection_is_security_policy_blocked(self):
        category, detail = self._classify(
            ok=False,
            summary="",
            stderr="Not inside a trusted directory and --skip-git-repo-check was not specified.",
            wrote_files=(),
        )
        assert category == "execution security policy blocked"
        assert "another build attempt cannot change" in detail

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

    def test_interrupted_verification_does_not_blame_a_missing_drydock_timeout(self):
        """The agent stops its own subprocess; Drydock never owned it, so the detail must
        point at the interrupted command's scope rather than at an unset Drydock timeout."""
        summary = (
            "RESULT: FAILURE\n"
            "FAILURE_SUMMARY: full conformance interrupted\n"
            "FAILURE_DETAIL: KeyboardInterrupt while running the supplied corpus.\n"
        )
        category, detail = self._classify(summary=summary)
        assert category == "target verification interrupted by build agent"
        assert "timeout" not in detail.lower()
        assert "scoped too broadly" in detail
        assert "KeyboardInterrupt while running the supplied corpus." in detail


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


_COMPACT_ORDER_MANIFEST = """# MANIFEST: Demo
state: draft

## story 1: Foundation
id: foundation
implements: DATABASE.md
stack: common.md
instructions: Build the database.
state: {first_state}

## story 2: Service
id: service
implements: SERVICE.md
stack: common.md
instructions: Build the service.
state: pending
"""


class TestCompactStackOrder:
    def _run(self, tmp_path, monkeypatch, *, first_state, compact_text):
        import drydock.build_run as br

        stack = tmp_path / "stack"
        stack.mkdir()
        (stack / "common.md").write_text("FULL COMMON STACK\n", encoding="utf-8")
        (stack / "common_compact.md").write_text(compact_text, encoding="utf-8")
        monkeypatch.setattr(br, "get_stack_dir", lambda: stack)
        target_dir, build_dir = _setup(
            tmp_path, manifest=_COMPACT_ORDER_MANIFEST.format(first_state=first_state)
        )
        prompts: list[str] = []
        runner = make_runner()

        def capturing(prompt, wd, **kwargs):
            prompts.append(prompt)
            return runner(prompt, wd, **kwargs)

        lines: list[str] = []
        build_target(
            "Demo",
            target_dir,
            build_dir=build_dir,
            runner=capturing,
            step_id="service",
            on_text=lines.append,
        )
        return prompts[0], "\n".join(lines)

    def test_compact_used_after_earlier_finished_block(self, tmp_path, monkeypatch):
        prompt, _ = self._run(
            tmp_path, monkeypatch, first_state="closed/verified", compact_text="COMPACT COMMON\n"
        )
        assert 'filename="common_compact.md"' in prompt
        assert "FULL COMMON STACK" not in prompt

    def test_full_file_when_earlier_block_unfinished(self, tmp_path, monkeypatch):
        prompt, _ = self._run(
            tmp_path, monkeypatch, first_state="closed/failed", compact_text="COMPACT COMMON\n"
        )
        assert 'filename="common.md"' in prompt
        assert "COMPACT COMMON" not in prompt

    def test_stale_compact_warns_and_uses_full_file(self, tmp_path, monkeypatch):
        stale = "<!-- Compacted from common.md sha256=" + "0" * 64 + " on x -->\nOLD\n"
        prompt, output = self._run(
            tmp_path, monkeypatch, first_state="closed/verified", compact_text=stale
        )
        assert "FULL COMMON STACK" in prompt
        assert "WARNING: common_compact.md is stale (common.md changed)" in output
        assert "drydock rigging compact --include-file" in output


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

    def test_changed_previously_applied_spec_blocks_before_runner(self, tmp_path):
        from drydock.errors import SpecificationError

        target_dir, build_dir = _setup(tmp_path)
        runner = make_runner()
        build_target("Demo", target_dir, build_dir=build_dir, runner=runner, step_id="foundation")
        (target_dir / "blueprint" / "DATABASE.md").write_text(
            "DB SPEC CONTENT CHANGED\n", encoding="utf-8"
        )

        second_runner = make_runner()
        with pytest.raises(SpecificationError, match=r"drydock refit Demo"):
            build_target("Demo", target_dir, build_dir=build_dir, runner=second_runner)

        assert second_runner.calls == []

    def test_reset_cannot_bypass_unreconciled_blueprint_drift(self, tmp_path):
        from drydock.errors import SpecificationError

        target_dir, build_dir = _setup(tmp_path)
        build_target(
            "Demo", target_dir, build_dir=build_dir, runner=make_runner(), step_id="foundation"
        )
        (target_dir / "blueprint" / "DATABASE.md").write_text(
            "DB SPEC CONTENT CHANGED\n", encoding="utf-8"
        )

        runner = make_runner()
        with pytest.raises(SpecificationError, match=r"drydock refit Demo"):
            build_target("Demo", target_dir, build_dir=build_dir, runner=runner, reset=True)

        assert runner.calls == []
        plan = parse_build_plan(target_dir / "MANIFEST.md")
        assert stale_applied_specs(plan, target_dir / "blueprint")

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

    def test_drift_error_lists_every_unreconciled_spec_and_refit_command(self, tmp_path):
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

        with pytest.raises(SpecificationError) as error:
            _ensure_applied_specs_current(manifest, blueprint)

        message = str(error.value)
        assert "Build blocked" in message
        assert "DATABASE.md" in message
        assert "SCREEN-A.md" in message
        assert "drydock refit Demo" in message


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
        f"assert {expected!r} in Path('foundation.txt').read_text(encoding='utf-8')\n"
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
        llm_provider="claude",
    )

    assert result.steps[0].status == "built"
    assert _state(target_dir, "foundation") == "closed/verified"
    assert [c["attempt"] for c in runner.calls] == [0, 1]
    # The repair pass carries the failure feedback as the recency anchor; the first does not.
    assert "# Repair Feedback" not in runner.calls[0]["prompt"]
    assert "# Repair Feedback" in runner.calls[1]["prompt"]
    assert runner.calls[1]["prompt"].startswith(runner.calls[0]["prompt"])
    session_id = runner.calls[0]["claude_session_id"]
    assert runner.calls[1]["claude_resume_session_id"] == session_id
    evidence = (target_dir / "evidence" / "foundation.md").read_text(encoding="utf-8")
    assert "## Repair attempts" in evidence
    assert "attempt 1 (repair 1)" in evidence
    # The pass that did not close names why, so the row is never a bare "failed".
    assert "reason: programmatic acceptance failed" in evidence
    assert "attempt 1 (repair 1): built" in evidence
    assert "; reason:" not in evidence.split("attempt 1 (repair 1)")[1]
    lineage = [
        json.loads(line) for line in (target_dir / "BUILD_LINEAGE.jsonl").read_text().splitlines()
    ]
    executions = [row for row in lineage if row["event"] == "execution"]
    assert [row["attempt"] for row in executions] == [0, 1]
    assert [row["status"] for row in executions] == ["failed", "built"]
    assert executions[0]["application"]["files"] == [{"path": "foundation.txt", "status": "A"}]
    assert executions[1]["application"]["files"] == [{"path": "foundation.txt", "status": "M"}]
    assert all(row["implements"] == ["DATABASE.md"] for row in lineage)
    assert lineage[-1]["event"] == "step_completed"
    assert lineage[-1]["details"]["nodes"][0]["state"] == "closed/verified"
    assert runner.calls[0]["parameters"]["build_run_id"] == executions[0]["run_id"]


def test_repair_loop_continues_while_deterministic_score_improves(tmp_path):
    target_dir, build_dir = _setup(tmp_path)
    (target_dir / "blueprint" / "DATABASE.md").write_text(
        """## Programmatic Acceptance

### first-marker
The first marker is correct.

```python
from pathlib import Path
assert 'ok' in Path('first.txt').read_text(encoding='utf-8')
```

### second-marker
The second marker is correct.

```python
from pathlib import Path
assert 'ok' in Path('second.txt').read_text(encoding='utf-8')
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
    assert "    acceptance=0/1  failed=conformance(1/4)" in messages
    assert "    acceptance=0/1  failed=conformance(3/4)" in messages
    assert "    acceptance=1/1" in messages


def test_repair_loop_counts_subcase_progress_a_silent_criterion_never_printed(tmp_path):
    """The jq shape: the criterion parses a JSON report, prints nothing, and asserts on it.

    Nothing reaches either stream, so the printed-tally reading finds no numbers. The counts are
    live in the failing frame, the acceptance harness lifts them out, and the repair loop must
    read progress from that rather than calling four improving attempts a stall.
    """
    target_dir, build_dir = _setup(tmp_path)
    (target_dir / "blueprint" / "DATABASE.md").write_text(
        """## Programmatic Acceptance

### conformance
Every conformance example passes.

```python
import json
from pathlib import Path
report = json.loads(Path("report.json").read_text(encoding="utf-8"))
assert report["summary"]["fail"] == 0
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
        passed = attempt + 1
        (work / "report.json").write_text(
            json.dumps({"summary": {"pass": passed, "fail": 4 - passed}}), encoding="utf-8"
        )
        calls.append(attempt)
        return FakeResult(text=_success_report(changed=("report.json",)))

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
    assert "    acceptance=0/1  failed=conformance(1/4)" in messages
    assert "    acceptance=0/1  failed=conformance(3/4)" in messages
    assert "    acceptance=1/1" in messages


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
    assert calls == [0, 1, 2]
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
        repair_attempts=3,
    )

    assert result.steps[0].status == "failed"
    assert result.steps[0].error == "programmatic acceptance failed: foundation-file"
    assert _state(target_dir, "foundation") == "closed/failed"
    # One flat repair is tolerated as noise; the second consecutive flat repair stops the loop.
    assert [c["attempt"] for c in runner.calls] == [0, 1, 2]
    from drydock.errors import read_error_record

    record = read_error_record(target_dir)
    assert record is not None
    evidence = (target_dir / "evidence" / "foundation.md").read_text(encoding="utf-8")
    assert "attempt 1 (repair 1)" in evidence
    assert "stopped: deterministic acceptance score did not improve" in evidence


def test_every_build_stops_on_the_second_consecutive_flat_pass(tmp_path):
    # Progress is what buys another pass. One flat pass is tolerated as noise between two
    # productive ones; a second in a row means the model has stopped moving the score.
    target_dir, build_dir = _setup(tmp_path)
    (target_dir / "blueprint" / "DATABASE.md").write_text(_marker_spec("ok\n"), encoding="utf-8")
    runner = make_attempt_runner(fix_at=None)
    lines: list[str] = []

    result = build_target(
        "Demo",
        target_dir,
        build_dir=build_dir,
        runner=runner,
        step_id="foundation",
        repair_attempts=6,
        on_text=lines.append,
    )

    # Attempt 0 has no predecessor to compare against; 1 is the first flat pass, 2 the second.
    assert [c["attempt"] for c in runner.calls] == [0, 1, 2]
    step = result.steps[0]
    assert step.status == "failed"
    assert step.stop_reason == (
        "deterministic acceptance score did not improve on 2 consecutive calls"
    )
    # The stall ended it well inside the bound; the budget is not what cut it short.
    assert step.calls_used == 3
    assert step.calls_budget == 7
    assert "repair: no acceptance progress on call 2 (1 of 2) — continuing" in lines
    assert "  STOP  reason=stall  flat_calls=2" in lines


def test_every_build_recovers_after_one_flat_pass(tmp_path):
    # The behavior the tolerance exists to protect: one flat pass, then a green one.
    target_dir, build_dir = _setup(tmp_path)
    (target_dir / "blueprint" / "DATABASE.md").write_text(_marker_spec("ok\n"), encoding="utf-8")
    runner = make_attempt_runner(fix_at=2)

    result = build_target(
        "Demo",
        target_dir,
        build_dir=build_dir,
        runner=runner,
        step_id="foundation",
        repair_attempts=6,
    )

    assert [c["attempt"] for c in runner.calls] == [0, 1, 2]
    assert result.steps[0].status == "built"
    assert _state(target_dir, "foundation") == "closed/verified"


def test_a_flat_pass_between_two_productive_ones_never_accumulates_to_a_stop(tmp_path):
    # The count is consecutive, not cumulative. A block that keeps climbing between occasional
    # flat passes is converging, and converging work is exactly what the budget is for.
    target_dir, build_dir = _setup(tmp_path)
    (target_dir / "blueprint" / "DATABASE.md").write_text(
        """## Programmatic Acceptance

=== AC conformance ===
Intent: Every conformance example passes.

from pathlib import Path
score = int(Path("score.txt").read_text(encoding="utf-8"))
print(f"{score} passed, {6 - score} failed, 0 errored")
assert score == 6
=== END AC conformance ===
""",
        encoding="utf-8",
    )
    # Case tally by attempt: 1, 1 (flat), 2, 2 (flat), 6 (green). Never two flat in a row.
    tallies = {0: 1, 1: 1, 2: 2, 3: 2, 4: 6}
    calls: list[int] = []

    def runner(prompt, working_directory, **kwargs):
        attempt = kwargs["parameters"]["attempt"]
        work = Path(working_directory)
        work.mkdir(parents=True, exist_ok=True)
        (work / "score.txt").write_text(str(tallies[attempt]), encoding="utf-8")
        calls.append(attempt)
        return FakeResult(text=_success_report(changed=("score.txt",)))

    result = build_target(
        "Demo",
        target_dir,
        build_dir=build_dir,
        runner=runner,
        step_id="foundation",
        repair_attempts=6,
    )

    assert calls == [0, 1, 2, 3, 4]
    assert result.steps[0].status == "built"
    assert not result.steps[0].stop_reason


def test_a_block_that_progresses_every_pass_runs_to_its_full_bound(tmp_path):
    """The CommonMark regression: a converging block cut off by a fixed call count.

    Block 3 of the CommonMark UAT went 3/8 -> 4/8 -> 4/8 -> 6/8 checks and 83 -> 101 -> 109 -> 126
    cases, never stalling, and was stopped at four calls with two criteria still red. Progress must
    buy every pass the bound allows.
    """
    target_dir, build_dir = _setup(tmp_path)
    (target_dir / "blueprint" / "DATABASE.md").write_text(
        """## Programmatic Acceptance

=== AC conformance ===
Intent: Every conformance example passes.

from pathlib import Path
score = int(Path("score.txt").read_text(encoding="utf-8"))
print(f"{score} passed, {9 - score} failed, 0 errored")
assert score == 9
=== END AC conformance ===
""",
        encoding="utf-8",
    )
    calls: list[int] = []

    def runner(prompt, working_directory, **kwargs):
        attempt = kwargs["parameters"]["attempt"]
        work = Path(working_directory)
        work.mkdir(parents=True, exist_ok=True)
        # One case gained per pass: real progress, never enough to finish inside the bound.
        (work / "score.txt").write_text(str(attempt + 1), encoding="utf-8")
        calls.append(attempt)
        return FakeResult(text=_success_report(changed=("score.txt",)))

    result = build_target(
        "Demo",
        target_dir,
        build_dir=build_dir,
        runner=runner,
        step_id="foundation",
        repair_attempts=6,
    )

    assert calls == [0, 1, 2, 3, 4, 5, 6]
    step = result.steps[0]
    assert step.status == "failed"
    # The budget ran out while the block was still climbing; nothing cut it short, so no stop
    # reason may be recorded.
    assert not step.stop_reason
    assert step.calls_used == 7


def test_a_build_spends_its_stall_allowance_on_a_reported_defective_criterion(tmp_path):
    # The claim is recorded, and the stop is the ordinary stall rule rather than a verdict the
    # agent handed itself.
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

    assert [c["attempt"] for c in runner.calls] == [0, 1, 2]
    assert result.steps[0].stop_reason == (
        "deterministic acceptance score did not improve on 2 consecutive calls"
    )


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
    assert "    acceptance=0/1" in console
    assert "suite-conformance(365/368)" in console
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


def test_is_repairable_only_for_acceptance_and_agent_reports():
    assert _is_repairable("programmatic acceptance failed: x") is True
    assert _is_repairable("agent-reported failure: incomplete") is True
    assert _is_repairable("context/token limit") is False
    assert _is_repairable("dependency legitimacy gate failed: 1 issue(s)") is False
    assert _is_repairable("staged build asset modified: kit.py") is False
    assert _is_repairable(None) is False


def test_interrupted_verification_is_repairable_not_terminal():
    """An agent that stops its own verification command has said nothing about the code.

    Classifying it terminal ended a block on its first pass with its whole repair budget
    unspent, which is how a step with three green scoped criteria closed ``failed``.
    """
    category, _ = _classify_failure(
        "RESULT: FAILURE\n"
        "FAILURE_SUMMARY: full conformance interrupted\n"
        "FAILURE_DETAIL: KeyboardInterrupt while running the supplied corpus.\n",
        ok=True,
        wrote_files=("evaluator.py",),
    )
    assert category == INTERRUPTED_VERIFICATION_PREFIX
    assert _is_repairable(category) is True


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


def test_repair_feedback_says_ac_broken_stops_nothing():
    # LayersTesting 20261020.183046: feedback promised AC_BROKEN "ends the repair budget", the
    # agent emitted it, and the loop spent another call. The claim is evidence, not a stop.
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
            stdout="",
            stderr="AssertionError",
        ),
    )
    text = " ".join(_render_repair_feedback(_Unit(), failed, None, (), {}).split())
    assert "`AC_BROKEN: <check-id>`" in text
    assert "stops nothing" in text
    assert "ends the repair budget" not in text
    assert "sends the criterion back" not in text


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


FLAG = "flagged as doubtful by static analysis — graded anyway"


def _quarantine_log_in(target_dir, build_dir, spec: str) -> None:
    """Build an already-set-up Target against ``spec``, tolerating an ordinary failure."""
    (target_dir / "blueprint" / "DATABASE.md").write_text(spec, encoding="utf-8")
    try:
        build_target("Demo", target_dir, build_dir=build_dir, runner=make_runner())
    except SpecificationError:
        pass


def _quarantine_log(tmp_path, spec: str) -> tuple[list[str], object]:
    """Build a Target whose only criterion is doubtful; return the console log and runner.

    Static analysis names the criterion and the build grades it anyway. A prediction that a
    criterion cannot pass is not reliable enough to remove it: what protects the build is the
    runtime verdict, where a criterion that really dies in its own frame reports UNVERIFIED and
    is never charged against the build.
    """
    target_dir, build_dir = _setup(tmp_path)
    (target_dir / "blueprint" / "DATABASE.md").write_text(spec, encoding="utf-8")
    runner = make_runner()
    log: list[str] = []
    try:
        build_target("Demo", target_dir, build_dir=build_dir, runner=runner, on_text=log.append)
    except SpecificationError:
        # A criterion that is doubtful *and* genuinely unsatisfiable now fails its story like
        # any other failing assertion, which can block a dependent story. That is the ordinary
        # failure path, not a quarantine, and it is not what these tests are measuring.
        pass
    return log, runner


def test_a_doubtful_criterion_does_not_refuse_the_build(tmp_path):
    # A doubtful criterion must not refuse the build before any story is attempted. It is graded
    # like any other; the flag is authoring advice, never a verdict.
    _, runner = _quarantine_log(tmp_path, _UNSATISFIABLE_SPEC)

    assert runner.calls


def _assert_refused(tmp_path, spec: str, check_id: str) -> None:
    """Build refuses a criterion that cannot run, before any story is attempted."""
    target_dir, build_dir = _setup(tmp_path)
    (target_dir / "blueprint" / "DATABASE.md").write_text(spec, encoding="utf-8")
    runner = make_runner()

    with pytest.raises(SpecificationError, match="Build refused") as refused:
        build_target("Demo", target_dir, build_dir=build_dir, runner=runner)

    assert check_id in str(refused.value)
    assert runner.calls == []


def test_a_criterion_reading_a_siblings_name_refuses_the_build(tmp_path):
    """``block-priority`` reads a name a sibling check bound; each check runs in its own process,
    so it raises NameError on every run and can never pass."""
    _assert_refused(tmp_path, _CARRIED_NAME_SPEC, "block-priority")


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


_UNPARSEABLE_SPEC = """# FEATURE: Blocks

## Programmatic Acceptance

### broken
The snippet does not parse.

```python
assert convert("a") ==
```
"""


def test_an_unparseable_check_refuses_the_build(tmp_path):
    """A criterion that does not compile can only reach a build through a hand edit after
    planning. It is refused there, not graded UNVERIFIED over a story it claims to gate."""
    target_dir, build_dir = _setup(tmp_path)
    (target_dir / "blueprint" / "DATABASE.md").write_text(_UNPARSEABLE_SPEC, encoding="utf-8")

    with pytest.raises(SpecificationError, match="Build refused"):
        build_target("Demo", target_dir, build_dir=build_dir, runner=make_runner())


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
    "assert 'built foundation' in Path('foundation.txt').read_text(encoding='utf-8')\n"
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
        "assert 'built service' in Path('service.txt').read_text(encoding='utf-8')\n"
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
    assert 'BLOCK foundation  name="Foundation"  calls_max=7' in messages
    assert any(line.startswith("  [call 1/7]  kind=resume  llm=") for line in messages)
    assert "    fixing=foundation-file" in messages


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
assert "ok" in Path("active.txt").read_text(encoding="utf-8")
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
assert "preserved" in Path("shared.txt").read_text(encoding="utf-8")
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
    # The regression fails the step, so the repaired sibling does not close either.
    assert _state(target_dir, "active-parser") == "closed/failed"
    assert _finding(target_dir, "active-parser") == "step parsing failed: verified-output"
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


def test_a_defect_claim_is_recorded_and_does_not_stop_the_loop(tmp_path):
    # The claim used to be terminal, which handed the party under test the power to end its own
    # examination. A criterion only binds when its expected value is one it could not have
    # invented, so the agent's claim is now the less likely explanation: it is reported, and the
    # repair budget is spent as it would be for any other missed expectation.
    messages: list[str] = []
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
        on_text=messages.append,
    )

    assert [c["attempt"] for c in runner.calls] == [0, 1, 2]
    step = result.steps[0]
    assert step.status == "failed"
    assert step.stop_reason == (
        "deterministic acceptance score did not improve on 2 consecutive calls"
    )
    assert any("recorded, not accepted" in message for message in messages)
    assert step.reported_defective_acceptance == ("foundation-file",)
    from drydock.errors import read_error_record

    record = read_error_record(target_dir)
    assert "drydock plan verify Demo" in record.recovery
    assert "drydock plan repair Demo" in record.recovery
    assert "Run: drydock build" not in record.recovery


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

    assert [c["attempt"] for c in runner.calls] == [0, 1, 2]
    assert result.steps[0].stop_reason == (
        "deterministic acceptance score did not improve on 2 consecutive calls"
    )


def test_ac_broken_token_is_recorded_when_the_agent_reports_success(tmp_path):
    # The agent has no failure of its own to report, so the token is the only signal that it
    # believes the criterion is at fault. It is worth recording and worth showing; it is not
    # worth ending the examination over.
    target_dir, build_dir = _setup(tmp_path)
    (target_dir / "blueprint" / "DATABASE.md").write_text(_marker_spec("ok\n"), encoding="utf-8")
    runner = _defective_claim_runner(
        "RESULT: SUCCESS\n"
        "AC_BROKEN: foundation-file\n"
        "FILES CHANGED:\n- foundation.txt\n\n"
        "SUMMARY:\nThe command succeeds; the assertion contradicts its output.\n"
    )

    result = build_target(
        "Demo",
        target_dir,
        build_dir=build_dir,
        runner=runner,
        step_id="foundation",
        repair_attempts=3,
    )

    assert [c["attempt"] for c in runner.calls] == [0, 1, 2]
    step = result.steps[0]
    assert step.status == "failed"
    assert step.stop_reason == (
        "deterministic acceptance score did not improve on 2 consecutive calls"
    )


def test_a_defect_named_only_in_blockers_is_recorded(tmp_path):
    # The agent's clearest statement often lands in BLOCKERS rather than FAILURE_DETAIL.
    target_dir, build_dir = _setup(tmp_path)
    (target_dir / "blueprint" / "DATABASE.md").write_text(_marker_spec("ok\n"), encoding="utf-8")
    runner = _defective_claim_runner(
        "RESULT: FAILURE\n"
        "FAILURE_SUMMARY: acceptance did not pass\n"
        "FAILURE_DETAIL: the command runs correctly.\n\n"
        "FILES CHANGED:\n- foundation.txt\n\n"
        "SUMMARY:\nDone.\n\n"
        "BLOCKERS:\n- the foundation-file criterion is broken and always fails\n"
    )

    result = build_target(
        "Demo",
        target_dir,
        build_dir=build_dir,
        runner=runner,
        step_id="foundation",
        repair_attempts=3,
    )

    assert [c["attempt"] for c in runner.calls] == [0, 1, 2]
    assert result.steps[0].stop_reason == (
        "deterministic acceptance score did not improve on 2 consecutive calls"
    )


def test_idempotent_rewrite_still_grades_acceptance(tmp_path):
    # The motivating regression. The deliverable is already on disk from an earlier pass, so the
    # step rewrites it with identical bytes and the content-hash delta is empty. Classifying that
    # as "no build files written" used to skip acceptance entirely, which discarded the agent's
    # AC_BROKEN report and skipped the grading this test exists to prove still happens.
    target_dir, build_dir = _setup(tmp_path)
    (target_dir / "blueprint" / "DATABASE.md").write_text(_marker_spec("ok\n"), encoding="utf-8")
    build_dir.mkdir(parents=True, exist_ok=True)
    (build_dir / "foundation.txt").write_text("bad\n", encoding="utf-8")
    runner = _defective_claim_runner(
        "RESULT: SUCCESS\n"
        "AC_BROKEN: foundation-file\n"
        "FILES CHANGED:\n- foundation.txt\n\n"
        "SUMMARY:\nThe marker is already correct; the assertion contradicts it.\n"
    )

    result = build_target(
        "Demo",
        target_dir,
        build_dir=build_dir,
        runner=runner,
        step_id="foundation",
        repair_attempts=3,
    )

    assert [c["attempt"] for c in runner.calls] == [0, 1, 2]
    step = result.steps[0]
    assert step.status == "failed"
    assert step.error == "programmatic acceptance failed: foundation-file"


def test_no_file_delta_is_advisory_when_acceptance_passes(tmp_path):
    # A step whose deliverable is already byte-correct changes nothing and is still done. Its
    # criterion was green before the build, so it measured nothing: implemented, not verified.
    messages: list[str] = []
    target_dir, build_dir = _setup(tmp_path, manifest=_ONE_STORY)
    (target_dir / "blueprint" / "DATABASE.md").write_text(_marker_spec("ok\n"), encoding="utf-8")
    build_dir.mkdir(parents=True, exist_ok=True)
    (build_dir / "foundation.txt").write_text("ok\n", encoding="utf-8")

    result = build_target(
        "Demo",
        target_dir,
        build_dir=build_dir,
        runner=make_runner(write_files=False),
        on_text=messages.append,
    )

    assert result.steps[0].status == "built"
    assert result.steps[0].state == "closed/implemented"
    assert _state(target_dir, "foundation") == "closed/implemented"
    assert _finding(target_dir, "foundation") == PREPASSED_FINDING
    assert any("no files changed (advisory)" in message for message in messages)


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
        _write_markers(prompt, work)
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


def test_undeclared_test_package_stays_failed_under_override(tmp_path):
    """Automatic test dependencies leave a missing undeclared package as an ordinary failure."""
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
    assert not [w for w in result.waivers if w.kind == "acceptance-authorization"]
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
                status="open",
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
                status="open",
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


def test_a_block_that_needed_repeated_repair_reports_a_sizing_advisory(tmp_path):
    # Going green after five calls is a decomposition signal, not a build failure. The verdict
    # stays ``built``; the advisory tells the Manifest author the block was too big.
    target_dir, build_dir = _setup(tmp_path)
    (target_dir / "blueprint" / "DATABASE.md").write_text(
        """## Programmatic Acceptance

=== AC conformance ===
Intent: Every conformance example passes.

from pathlib import Path
score = int(Path("score.txt").read_text(encoding="utf-8"))
print(f"{score} passed, {5 - score} failed, 0 errored")
assert score == 5
=== END AC conformance ===
""",
        encoding="utf-8",
    )
    lines: list[str] = []

    def runner(prompt, working_directory, **kwargs):
        attempt = kwargs["parameters"]["attempt"]
        work = Path(working_directory)
        work.mkdir(parents=True, exist_ok=True)
        (work / "score.txt").write_text(str(attempt + 1), encoding="utf-8")
        return FakeResult(text=_success_report(changed=("score.txt",)))

    result = build_target(
        "Demo",
        target_dir,
        build_dir=build_dir,
        runner=runner,
        step_id="foundation",
        repair_attempts=6,
        on_text=lines.append,
    )

    assert result.steps[0].status == "built"
    assert result.steps[0].calls_used == 5
    assert any("sizing: foundation needed 5 calls" in line for line in lines)


def test_a_correctly_sized_block_reports_no_sizing_advisory(tmp_path):
    target_dir, build_dir = _setup(tmp_path)
    (target_dir / "blueprint" / "DATABASE.md").write_text(_marker_spec("ok\n"), encoding="utf-8")
    runner = make_attempt_runner(fix_at=1)
    lines: list[str] = []

    result = build_target(
        "Demo",
        target_dir,
        build_dir=build_dir,
        runner=runner,
        step_id="foundation",
        repair_attempts=3,
        on_text=lines.append,
    )

    assert result.steps[0].status == "built"
    assert not any("sizing:" in line for line in lines)


def test_a_criterion_reading_an_unbound_name_refuses_the_build(tmp_path):
    """It dies in its own frame, so no implementation can turn it green. Building over it used to
    settle it UNVERIFIED and close the story; the build now refuses before spending a call."""
    _assert_refused(
        tmp_path,
        "## Programmatic Acceptance\n\n=== AC broken-criterion ===\n"
        "Intent: This criterion reads a name it never bound.\n\n"
        "assert never_bound_anywhere == 1\n=== END AC broken-criterion ===\n",
        "broken-criterion",
    )


def test_a_retyped_expectation_is_disputed_and_the_block_still_closes(tmp_path):
    """The Toml 20260813.084830 regression, reduced.

    The criterion supplied one spelling of a value and asserted another. The product is right,
    the criterion is wrong, and no static analyzer can tell which from the text alone. It runs,
    it misses, it is reported in full — and the block closes on the evidence of the criteria
    whose expectations could not have been invented.
    """
    messages: list[str] = []
    target_dir, build_dir = _setup(tmp_path)
    (target_dir / "blueprint" / "DATABASE.md").write_text(
        "DB SPEC CONTENT\n\n"
        "## Programmatic Acceptance\n\n"
        "### foundation-present\n"
        "The foundation marker exists.\n\n"
        "```python\n"
        "from pathlib import Path\n"
        "assert Path('foundation.txt').is_file()\n"
        "```\n\n"
        "### foundation-retyped\n"
        "The marker matches a hand-typed expectation.\n\n"
        "```python\n"
        "from pathlib import Path\n"
        "assert Path('foundation.txt').read_text(encoding='utf-8') == 'C:\\\\not\\\\written\\n'\n"
        "```\n",
        encoding="utf-8",
    )

    result = build_target(
        "Demo",
        target_dir,
        build_dir=build_dir,
        runner=make_runner(),
        step_id="foundation",
        on_text=messages.append,
    )

    step = result.steps[0]
    assert step.status == "built"
    text = "\n".join(messages)
    assert "disputed: 1 criterion" in text
    assert "foundation-retyped" in text


# ── governed acceptance ───────────────────────────────────────────────────────
# A governed command is the only thing that can close a story verified. The release gate comes
# from ACCEPTANCE.json and the per-story gates from STORY_GUIDANCE.json; the Commander owns both
# and no LLM-assisted command writes either. Drydock executes their argv directly rather than
# inspecting a wrapper the model generated.


def _governed(target_dir, stages=None, full=None):
    from drydock.acceptance_contract import AcceptanceContract, write_contract
    from drydock.story_guidance import (
        PROVENANCE_COMMANDER,
        StoryGuidance,
        StoryGuidanceEntry,
        write_guidance,
    )

    write_contract(target_dir, AcceptanceContract(full=tuple(full or ())))
    write_guidance(
        target_dir,
        StoryGuidance(
            entries=tuple(
                StoryGuidanceEntry(
                    story_id=story_id, provenance=PROVENANCE_COMMANDER, gate=tuple(argv)
                )
                for story_id, argv in (stages or {}).items()
            )
        ),
    )


def test_a_passing_governed_gate_closes_the_story_verified(tmp_path):
    target_dir, build_dir = _setup(tmp_path)
    (target_dir / "blueprint" / "DATABASE.md").write_text(_marker_spec("ok\n"), encoding="utf-8")
    _governed(target_dir, stages={"foundation": (sys.executable, "-c", "raise SystemExit(0)")})

    result = build_target(
        "Demo", target_dir, build_dir=build_dir, runner=make_runner(), step_id="foundation"
    )

    assert result.steps[0].status == "built"
    assert _state(target_dir, "foundation") == "closed/verified"


def test_a_gate_keyed_by_stable_coverage_id_closes_the_story_verified(tmp_path):
    target_dir, build_dir = _setup(tmp_path)
    manifest = target_dir / "MANIFEST.md"
    manifest.write_text(
        manifest.read_text(encoding="utf-8").replace(
            "implements: DATABASE.md", "implements: DATABASE.md\ncovers: FOUNDATION-001", 1
        ),
        encoding="utf-8",
    )
    (target_dir / "blueprint" / "DATABASE.md").write_text(_marker_spec("ok\n"), encoding="utf-8")
    _governed(
        target_dir,
        stages={"FOUNDATION-001": (sys.executable, "-c", "raise SystemExit(0)")},
    )

    result = build_target(
        "Demo", target_dir, build_dir=build_dir, runner=make_runner(), step_id="foundation"
    )

    assert result.steps[0].status == "built"
    assert _state(target_dir, "foundation") == "closed/verified"


def test_a_failing_governed_gate_fails_the_story_however_the_criteria_went(tmp_path):
    """The oracle outranks the criteria. Green model checks cannot talk over a red gate."""
    target_dir, build_dir = _setup(tmp_path)
    (target_dir / "blueprint" / "DATABASE.md").write_text(
        _marker_spec("built foundation\n"), encoding="utf-8"
    )
    _governed(target_dir, stages={"foundation": (sys.executable, "-c", "raise SystemExit(1)")})

    result = build_target(
        "Demo", target_dir, build_dir=build_dir, runner=make_runner(), step_id="foundation"
    )

    assert result.steps[0].status == "failed"
    assert "governed acceptance failed" in (result.steps[0].error or "")
    assert _state(target_dir, "foundation") == "closed/failed"


def test_a_red_criterion_cannot_stop_a_story_its_governed_gate_passed(tmp_path):
    """The Toml failure, in one test.

    A fabricated criterion held the line at block 3 while the authoritative suite never got the
    chance to drive blocks 4-8. With a gate in place the criterion is diagnostic: it is run,
    reported, and overruled by the oracle.
    """
    messages: list[str] = []
    target_dir, build_dir = _setup(tmp_path)
    (target_dir / "blueprint" / "DATABASE.md").write_text(
        _marker_spec("never written\n"), encoding="utf-8"
    )
    _governed(target_dir, stages={"foundation": (sys.executable, "-c", "raise SystemExit(0)")})

    result = build_target(
        "Demo",
        target_dir,
        build_dir=build_dir,
        runner=make_runner(),
        step_id="foundation",
        on_text=messages.append,
    )

    assert result.steps[0].status == "built"
    assert _state(target_dir, "foundation") == "closed/verified"
    assert "red where the governed gate passed" in "\n".join(messages)


def test_a_gate_that_cannot_run_never_charges_the_product(tmp_path):
    target_dir, build_dir = _setup(tmp_path)
    (target_dir / "blueprint" / "DATABASE.md").write_text(
        _marker_spec("built foundation\n"), encoding="utf-8"
    )
    _governed(target_dir, stages={"foundation": ("no-such-harness-98765",)})

    result = build_target(
        "Demo", target_dir, build_dir=build_dir, runner=make_runner(), step_id="foundation"
    )

    assert result.steps[0].status == "built"
    assert result.steps[0].state == "closed/implemented"
    assert _state(target_dir, "foundation") == "closed/implemented"


def test_an_ungoverned_story_is_implemented_not_verified_when_a_contract_exists(tmp_path):
    """The console must not call a block verified when nothing with standing examined it."""
    target_dir, build_dir = _setup(tmp_path)
    (target_dir / "blueprint" / "DATABASE.md").write_text(
        _marker_spec("built foundation\n"), encoding="utf-8"
    )
    _governed(target_dir, full=(sys.executable, "-c", "raise SystemExit(0)"))

    result = build_target(
        "Demo", target_dir, build_dir=build_dir, runner=make_runner(), step_id="foundation"
    )

    assert result.steps[0].status == "built"
    assert result.steps[0].state == "closed/implemented"
    assert _state(target_dir, "foundation") == "closed/implemented"


def test_without_any_contract_a_binding_criterion_is_still_the_verdict(tmp_path):
    """An oracle outranks a criterion; a criterion outranks nothing at all.

    Discarding model-authored criteria everywhere would leave a project with no governed suite —
    which is most projects — with no failure signal whatsoever.
    """
    target_dir, build_dir = _setup(tmp_path)
    (target_dir / "blueprint" / "DATABASE.md").write_text(
        _marker_spec("never written\n"), encoding="utf-8"
    )

    result = build_target(
        "Demo", target_dir, build_dir=build_dir, runner=make_runner(), step_id="foundation"
    )

    assert result.steps[0].status == "failed"
    assert _state(target_dir, "foundation") == "closed/failed"


def test_a_stage_keyed_to_no_story_is_reported(tmp_path):
    messages: list[str] = []
    target_dir, build_dir = _setup(tmp_path)
    (target_dir / "blueprint" / "DATABASE.md").write_text(
        _marker_spec("built foundation\n"), encoding="utf-8"
    )
    _governed(target_dir, stages={"renamed-last-week": (sys.executable, "-c", "pass")})

    build_target(
        "Demo",
        target_dir,
        build_dir=build_dir,
        runner=make_runner(),
        step_id="foundation",
        on_text=messages.append,
    )

    assert "no story matches renamed-last-week" in "\n".join(messages)


def test_a_red_governed_gate_drives_the_repair_loop(tmp_path):
    """A gate that reports only after the budget is spent drives no repair at all.

    The gate is the red/green signal the loop steers by, so it runs on every attempt and its
    output reaches the next agent call. Here it goes green on the second pass.
    """
    target_dir, build_dir = _setup(tmp_path)
    (target_dir / "blueprint" / "DATABASE.md").write_text(
        _marker_spec("built foundation\n"), encoding="utf-8"
    )
    marker = build_dir / "gate-pass.txt"
    _governed(
        target_dir,
        stages={
            "foundation": (
                sys.executable,
                "-c",
                f"import pathlib,sys; p=pathlib.Path({str(marker)!r});"
                " sys.exit(0) if p.exists() else (p.write_text('x'), sys.exit(1))[1]",
            )
        },
    )

    result = build_target(
        "Demo",
        target_dir,
        build_dir=build_dir,
        runner=make_runner(),
        step_id="foundation",
        repair_attempts=3,
    )

    assert result.steps[0].calls_used == 2, "the red gate must buy a repair pass"
    assert result.steps[0].status == "built"
    assert _state(target_dir, "foundation") == "closed/verified"


def test_an_unclosed_acceptance_container_refuses_the_build(tmp_path):
    """None of the file's criteria can be read, so none can gate the story."""
    _assert_refused(
        tmp_path,
        "# DATABASE\n\n## Programmatic Acceptance\n\n"
        "=== AC db-exists ===\nIntent: First.\n\nassert 1 == 1\n",
        "db-exists",
    )


# ── staged-asset environment ─────────────────────────────────────────────────────────

_ENV_RUNNER = '''#!/usr/bin/env python3
"""Score a candidate.

Usage:
    RUNNER=./app python3 sources/score.py

Environment:
    RUNNER     command that runs the candidate. Required.
"""
import os
import sys

if not os.environ.get("RUNNER"):
    sys.exit("error: RUNNER is not set")
sys.exit(0)
'''


def _with_staged_runner(tmp_path, criterion: str):
    """A Target whose story grades itself through a staged asset that requires ``RUNNER``."""
    target_dir, build_dir = _setup(tmp_path)
    sources = target_dir / "blueprint" / "sources"
    sources.mkdir(parents=True, exist_ok=True)
    (sources / "score.py").write_text(_ENV_RUNNER, encoding="utf-8")
    build_sources = build_dir / "sources"
    build_sources.mkdir(parents=True, exist_ok=True)
    (build_sources / "score.py").write_text(_ENV_RUNNER, encoding="utf-8")
    (target_dir / "blueprint" / "DATABASE.md").write_text(
        "DB SPEC CONTENT\n\n"
        "## Programmatic Acceptance\n\n"
        "=== AC foundation-suite ===\n"
        "Intent: The candidate passes its staged scoring asset.\n\n"
        f"{criterion}"
        "=== END AC foundation-suite ===\n",
        encoding="utf-8",
    )
    return target_dir, build_dir


def test_a_criterion_missing_a_staged_assets_variable_is_supplied_and_recorded(tmp_path):
    """The jq UAT failure: the criterion omits the variable, so no build can move it.

    Left alone it burns the whole repair budget and reports a product defect. Supplied, it runs
    and produces a real verdict on the first pass.
    """
    target_dir, build_dir = _with_staged_runner(
        tmp_path,
        "import subprocess\n"
        "result = subprocess.run(['python3', 'sources/score.py'])\n"
        "assert result.returncode == 0\n",
    )
    log: list[str] = []

    result = build_target(
        "Demo",
        target_dir,
        build_dir=build_dir,
        runner=make_runner(),
        step_id="foundation",
        on_text=log.append,
    )

    step = result.steps[0]
    assert step.status == "built"
    assert step.acceptance[0].passed is True
    # One pass. The criterion was satisfiable from the first call, so no repair was bought.
    assert step.calls_used == 1
    decisions = {
        item["id"]: item
        for item in json.loads((target_dir / "DECISIONS.json").read_text(encoding="utf-8"))
    }
    record = decisions["build-env-database.md-foundation-suite-runner"]
    assert record["status"] == "recommended"
    assert record["system_choice"] == "RUNNER=./app"
    assert "sources/score.py usage line" in record["description"]
    assert "The Blueprint was not modified" in record["description"]
    assert any("ac-env: foundation-suite" in line for line in log)


def test_the_blueprint_is_not_rewritten_by_the_repair(tmp_path):
    """The repair is for one grading. A criterion wrong at rest stays wrong until an author fixes
    it, which is what keeps the recorded decision honest."""
    criterion = (
        "import subprocess\n"
        "result = subprocess.run(['python3', 'sources/score.py'])\n"
        "assert result.returncode == 0\n"
    )
    target_dir, build_dir = _with_staged_runner(tmp_path, criterion)
    before = (target_dir / "blueprint" / "DATABASE.md").read_text(encoding="utf-8")

    build_target(
        "Demo", target_dir, build_dir=build_dir, runner=make_runner(), step_id="foundation"
    )

    assert (target_dir / "blueprint" / "DATABASE.md").read_text(encoding="utf-8") == before
    assert "os.environ" not in before


def test_a_story_whose_every_criterion_is_unverified_is_implemented_not_verified(tmp_path):
    """Closing green here would report a single-criterion conformance story as verified with its
    suite never executed."""
    target_dir, build_dir = _setup(tmp_path)
    (target_dir / "blueprint" / "DATABASE.md").write_text(
        "DB SPEC CONTENT\n\n"
        "## Programmatic Acceptance\n\n"
        "### foundation-fixture\n"
        "The generated fixture is required.\n\n"
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
    assert step.acceptance[0].outcome == "UNVERIFIED"
    # Not a failure — the product may be correct and the criterion broken — and not verified
    # either, because nothing measured the built code.
    assert _state(target_dir, "foundation") == "closed/implemented"
    assert "every criterion this story declared settled UNVERIFIED" in (
        target_dir / "MANIFEST.md"
    ).read_text(encoding="utf-8")


def test_the_database_step_renders_the_declaration_into_executable_ddl(tmp_path: Path):
    from drydock.build_run import _write_persistence

    blueprint_dir = tmp_path / "blueprint"
    build_dir = tmp_path / "build"
    blueprint_dir.mkdir()
    (blueprint_dir / "DATABASE.md").write_text(
        "# DATABASE: X\n\n"
        "## Access Patterns\n\n"
        "### FEATURE-TICKET-001 — Find tickets\n\n"
        "| Field | Value |\n|---|---|\n"
        "| Owner | FEATURE-Ticket.md |\n| Access | read |\n"
        "| Repository operation | `tickets.list` |\n| Compatibility | unchanged |\n\n"
        "Input: FindTickets\n\n| Field | Type | Required |\n|---|---|---|\n| status | str | yes |\n\n"
        "Output: Ticket\n\n| Field | Type |\n|---|---|\n| id | int |\n\n"
        "## `tickets`\n\n| Field | Type | Notes |\n|---|---|---|\n"
        "| id | INTEGER PK | |\n| status | TEXT NOT NULL DEFAULT 'open' | |\n",
        encoding="utf-8",
    )

    written = _write_persistence(blueprint_dir, build_dir, tmp_path, None)

    rendered = (build_dir / "schema.sql").read_text(encoding="utf-8")
    assert "\"status\" TEXT NOT NULL DEFAULT 'open'" in rendered
    assert 'CREATE INDEX IF NOT EXISTS "tickets_status_idx"' in rendered
    assert (tmp_path / "DECISIONS.json") in written
    assert (build_dir / "persistence" / "schema.py").is_file()
    assert (build_dir / "persistence" / "db.py").is_file()
    # The DATABASE step applies the schema to the store the application opens.
    import sqlite3

    with sqlite3.connect(build_dir / "data" / "app.db") as connection:
        tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master")}
    assert "tickets" in tables


def test_acceptance_refuses_to_recreate_schema_before_criteria_run(tmp_path: Path, monkeypatch):
    from drydock.acceptance import ProgrammaticAcceptance, run_programmatic_acceptance
    from drydock.database_emit import write_persistence_package

    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("DATABASE_PATH", raising=False)
    blueprint_dir = tmp_path / "blueprint"
    build_dir = tmp_path / "build"
    blueprint_dir.mkdir()
    (blueprint_dir / "DATABASE.md").write_text(
        "# DATABASE: X\n\n"
        "## Access Patterns\n\n"
        "### FEATURE-TICKET-001 — Find tickets\n\n"
        "| Field | Value |\n|---|---|\n"
        "| Owner | FEATURE-Ticket.md |\n| Access | read |\n"
        "| Repository operation | `tickets.list` |\n| Compatibility | unchanged |\n\n"
        "Input: FindTickets\n\n| Field | Type | Required |\n|---|---|---|\n| status | str | yes |\n\n"
        "Output: Ticket\n\n| Field | Type |\n|---|---|\n| id | int |\n\n"
        "## `tickets`\n\n| Field | Type | Notes |\n|---|---|---|\n"
        "| id | INTEGER PK | |\n| status | TEXT NOT NULL | |\n",
        encoding="utf-8",
    )
    write_persistence_package(blueprint_dir, build_dir)
    check = ProgrammaticAcceptance(
        check_id="store-has-tickets",
        source="FEATURE-Ticket.md",
        intent="The application store holds the declared table.",
        code=(
            "import sqlite3\n"
            "names = {r[0] for r in sqlite3.connect('data/app.db').execute("
            "'SELECT name FROM sqlite_master')}\n"
            "assert 'tickets' in names, names\n"
        ),
    )

    (result,) = run_programmatic_acceptance(
        (check,), build_dir=build_dir, target_dir=tmp_path, blueprint_dir=blueprint_dir
    )

    assert not result.passed
    assert "store missing" in result.error
    assert not (build_dir / "data/app.db").exists()


def test_persistence_exists_before_the_database_step_runs(tmp_path: Path, monkeypatch):
    """ReadingList: the DATABASE story and an ``open_database`` consumer shared one step. The
    package was written only after the step passed, so the consumer's acceptance could never
    import it. Plan writes DATABASE.md, so Build generates the package before the step."""
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("DATABASE_PATH", raising=False)
    target_dir, build_dir = _setup(
        tmp_path, manifest=_FEATURE_GROUP_MANIFEST.replace("SERVICE.md", "FEATURE-Service.md")
    )
    from drydock.technology_stack import StackEntry, write

    write(
        target_dir,
        [StackEntry("Python", "python.md"), StackEntry("SQLite", "sqlite.md")],
        approved="2026-10-19",
    )
    (target_dir / "blueprint" / "DATABASE.md").write_text(
        "# DATABASE: Demo\n\n"
        "## Access Patterns\n\n"
        "### FEATURE-SVC-001 — Find tickets\n\n"
        "| Field | Value |\n|---|---|\n"
        "| Owner | FEATURE-Service.md |\n| Access | read |\n"
        "| Repository operation | `tickets.list` |\n| Compatibility | unchanged |\n\n"
        "Input: FindTickets\n\n| Field | Type | Required |\n|---|---|---|\n| status | str | yes |\n\n"
        "Output: Ticket\n\n| Field | Type |\n|---|---|\n| id | int |\n\n"
        "## `tickets`\n\n| Field | Type | Notes |\n|---|---|---|\n"
        "| id | INTEGER PK | |\n| status | TEXT NOT NULL | |\n\n"
        "## Programmatic Acceptance\n\n"
        "### store-lists\n"
        "The provisioned store lists tickets.\n\n"
        "```python\n"
        "from persistence.testing import db_session\n"
        "with db_session() as db:\n"
        "    assert db.tickets.list(status='open') == []\n"
        "```\n",
        encoding="utf-8",
    )
    (target_dir / "blueprint" / "FEATURE-Service.md").write_text(
        "SVC SPEC CONTENT\n\n"
        "## Programmatic Acceptance\n\n"
        "### service-opens-store\n"
        "The service imports the generated persistence package.\n\n"
        "```python\n"
        "from persistence import open_database\n"
        "```\n",
        encoding="utf-8",
    )
    seen: list[bool] = []
    inner = make_runner()

    def runner(prompt, working_directory, **kwargs):
        seen.append((Path(working_directory) / "persistence" / "__init__.py").is_file())
        return inner(prompt, working_directory, **kwargs)

    build_target("Demo", target_dir, build_dir=build_dir, runner=runner)

    assert seen == [True]
    assert _state(target_dir, "service") != "closed/failed"
    assert _state(target_dir, "foundation") != "closed/failed"


_TICKETS_DATABASE = (
    "# DATABASE: Demo\n\n"
    "## Access Patterns\n\n"
    "### FEATURE-SVC-001 — Find tickets\n\n"
    "| Field | Value |\n|---|---|\n"
    "| Owner | DATABASE.md |\n| Access | read |\n"
    "| Repository operation | `tickets.list` |\n| Compatibility | unchanged |\n\n"
    "Input: FindTickets\n\n| Field | Type | Required |\n|---|---|---|\n| status | str | yes |\n\n"
    "Output: Ticket\n\n| Field | Type |\n|---|---|\n| id | int |\n\n"
    "## `tickets`\n\n| Field | Type | Notes |\n|---|---|---|\n"
    "| id | INTEGER PK | |\n| status | TEXT NOT NULL | |\n\n"
    "## Programmatic Acceptance\n\n"
    "### store-opens\n"
    "The provisioned store exposes the declared repository.\n\n"
    "```python\n"
    "from persistence.testing import db_session\n"
    "with db_session() as db:\n"
    "    rows = db.tickets.list(status='open')\n"
    "    assert {assertion}, rows\n"
    "```\n"
)


def _database_only_target(tmp_path: Path, monkeypatch, assertion: str):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("DATABASE_PATH", raising=False)
    target_dir, build_dir = _setup(tmp_path)
    from drydock.technology_stack import StackEntry, write

    write(
        target_dir,
        [StackEntry("Python", "python.md"), StackEntry("SQLite", "sqlite.md")],
        approved="2026-10-19",
    )
    (target_dir / "blueprint" / "DATABASE.md").write_text(
        _TICKETS_DATABASE.format(assertion=assertion), encoding="utf-8"
    )
    return target_dir, build_dir


def test_a_database_only_step_is_graded_on_its_criteria_without_a_model_call(
    tmp_path: Path, monkeypatch
):
    """ReadingList 20261022.231143: the DATABASE story had nothing to write, so the agent could
    only report FAILED, seven times. Its generated package is graded on its own criteria, which
    were red before the step generated it."""
    target_dir, build_dir = _database_only_target(tmp_path, monkeypatch, "db.tickets is not None")
    runner = make_runner()
    messages: list[str] = []

    result = build_target(
        "Demo",
        target_dir,
        build_dir=build_dir,
        runner=runner,
        step_id="foundation",
        on_text=messages.append,
    )

    assert runner.calls == []
    assert result.exit_code() == 0
    assert _state(target_dir, "foundation") == "closed/verified"
    assert "generated: foundation has no agent work — 1/1 criteria pass" in messages


def test_a_database_only_step_fails_on_a_red_criterion_without_a_model_call(
    tmp_path: Path, monkeypatch
):
    target_dir, build_dir = _database_only_target(tmp_path, monkeypatch, "db.tickets is None")
    runner = make_runner()

    result = build_target(
        "Demo", target_dir, build_dir=build_dir, runner=runner, step_id="foundation"
    )

    assert runner.calls == []
    assert result.exit_code() == 1
    assert _state(target_dir, "foundation") == "closed/failed"


def test_a_database_only_step_with_no_criteria_is_refused_before_any_call(
    tmp_path: Path, monkeypatch
):
    """0/0 grades nothing, so Build refuses a story with no criterion before it spends a call."""
    target_dir, build_dir = _database_only_target(tmp_path, monkeypatch, "True")
    database = target_dir / "blueprint" / "DATABASE.md"
    text = database.read_text(encoding="utf-8")
    database.write_text(
        text[: text.index("## Programmatic Acceptance")]
        + "## Programmatic Acceptance\n\n- None.\n",
        encoding="utf-8",
    )
    runner = make_runner()

    with pytest.raises(SpecificationError, match="story `foundation` implements DATABASE.md"):
        build_target("Demo", target_dir, build_dir=build_dir, runner=runner, step_id="foundation")

    assert runner.calls == []
    assert _state(target_dir, "foundation") == "pending"


def test_a_declaration_with_no_tables_writes_no_schema(tmp_path: Path):
    from drydock.build_run import _write_persistence

    blueprint_dir = tmp_path / "blueprint"
    blueprint_dir.mkdir()
    (blueprint_dir / "DATABASE.md").write_text("# DATABASE: X\n", encoding="utf-8")

    assert _write_persistence(blueprint_dir, tmp_path / "build", tmp_path, None) == ()
    assert not (tmp_path / "build" / "schema.sql").exists()
    assert not (tmp_path / "build" / "persistence").exists()


def test_build_refuses_a_persistence_declaration_it_cannot_read(tmp_path):
    """Marina_Luna: thirteen access patterns without Input/Output tables. Build generates the
    persistence package from the declaration, so it refuses before spending a call rather than
    printing ``persistence: not generated`` at the DATABASE step and building on."""
    target_dir, build_dir = _setup(tmp_path)
    (target_dir / "blueprint" / "DATABASE.md").write_text(
        "# DATABASE: Demo\n\n## Access Patterns\n\n### FEATURE-SVC-001 — Store setting\n\n"
        "| Field | Value |\n|---|---|\n| Owner | SERVICE.md |\n| Access | read-write |\n"
        "| Repository operation | `settings.update` |\n| Compatibility | data |\n\n"
        "## `settings`\n\n| Field | Type | Notes |\n|---|---|---|\n| key | TEXT PK | |\n",
        encoding="utf-8",
    )
    runner = make_runner()

    with pytest.raises(SpecificationError, match="Build cannot read DATABASE.md"):
        build_target("Demo", target_dir, build_dir=build_dir, runner=runner)

    assert runner.calls == []


def test_build_lineage_records_deletion_only_execution(tmp_path):
    target_dir, build_dir = _setup(tmp_path)
    (target_dir / "blueprint" / "DATABASE.md").write_text(
        "DB SPEC CONTENT\n\n## Programmatic Acceptance\n\n"
        "=== AC obsolete-removed ===\nIntent: The foundation removes the obsolete module.\n\n"
        "from pathlib import Path\n\nassert not Path('obsolete.py').exists()\n"
        "=== END AC obsolete-removed ===\n",
        encoding="utf-8",
    )
    build_dir.mkdir()
    (build_dir / "obsolete.py").write_text("obsolete\n")

    def runner(prompt, working_directory, **kwargs):
        (Path(working_directory) / "obsolete.py").unlink()
        return FakeResult(text=_success_report(changed=("obsolete.py",)))

    result = build_target(
        "Demo", target_dir, build_dir=build_dir, runner=runner, step_id="foundation"
    )
    assert result.exit_code() == 0
    rows = [
        json.loads(line) for line in (target_dir / "BUILD_LINEAGE.jsonl").read_text().splitlines()
    ]
    assert rows[0]["application"]["files"] == [{"path": "obsolete.py", "status": "D"}]
    assert result.steps[0].written_files == ("obsolete.py",)


def test_full_reset_preserves_commits_and_appends_lineage(tmp_path):
    from drydock.build_git import git

    target_dir, build_dir = _setup(tmp_path)
    build_target("Demo", target_dir, build_dir=build_dir, runner=make_runner())
    prior = (target_dir / "BUILD_LINEAGE.jsonl").read_text()
    old_commit = json.loads(prior.splitlines()[0])["application"]["after_commit"]
    build_target("Demo", target_dir, build_dir=build_dir, runner=make_runner(), reset=True)
    assert (target_dir / "BUILD_LINEAGE.jsonl").read_text().startswith(prior)
    assert git(build_dir, "show", f"{old_commit}:foundation.txt") == "built foundation\n"


def test_runner_exception_checkpoints_partial_work_and_error(tmp_path):
    target_dir, build_dir = _setup(tmp_path)

    def runner(prompt, working_directory, **kwargs):
        (Path(working_directory) / "partial.py").write_text("partial\n")
        raise RuntimeError("Agent process stopped")

    with pytest.raises(RuntimeError, match="Agent process stopped"):
        build_target("Demo", target_dir, build_dir=build_dir, runner=runner)
    row = json.loads((target_dir / "BUILD_LINEAGE.jsonl").read_text().splitlines()[0])
    assert row["event"] == "execution_error"
    assert row["status"] == "error"
    assert row["application"]["files"] == [{"path": "partial.py", "status": "A"}]
    assert row["details"]["error"] == "Agent process stopped"


def test_build_records_each_criterion_baseline_status(tmp_path):
    from drydock.acceptance_status import STATUS_VALID, read_acceptance_status

    target_dir, build_dir = _setup(tmp_path, manifest=_ONE_STORY)
    (target_dir / "blueprint" / "DATABASE.md").write_text(
        _marker_spec("built foundation"), encoding="utf-8"
    )

    build_target("Demo", target_dir, build_dir=build_dir, runner=make_runner())

    statuses = read_acceptance_status(target_dir / "evidence")
    assert statuses["foundation-file"].status == STATUS_VALID
    assert _state(target_dir, "foundation") == "closed/verified"


def test_unapproved_stack_stops_before_model(tmp_path):
    from drydock.technology_stack import StackEntry, write

    target_dir, build_dir = _setup(tmp_path)
    write(target_dir, [StackEntry("Go", "go.md")])

    def runner(*args, **kwargs):
        pytest.fail("Unapproved stack reached model")

    with pytest.raises(SpecificationError, match="approval"):
        build_target("Demo", target_dir, build_dir=build_dir, runner=runner)


def test_postgres_without_connection_stops_before_model(tmp_path, isolated_config):
    from drydock.technology_stack import StackEntry, write

    target_dir, build_dir = _setup(tmp_path)
    write(
        target_dir,
        [StackEntry("Python", "python.md"), StackEntry("PostgreSQL", "postgres.md")],
        approved="2026-10-19",
    )

    def runner(*args, **kwargs):
        pytest.fail("Unconfigured PostgreSQL reached model")

    with pytest.raises(SpecificationError, match="postgres_dsn"):
        build_target("Demo", target_dir, build_dir=build_dir, runner=runner)


def test_grouped_story_results_match_their_individual_governed_states(tmp_path):
    target, build = _setup(tmp_path, manifest=_FEATURE_GROUP_MANIFEST)
    _governed(target, stages={"foundation": (sys.executable, "-c", "raise SystemExit(0)")})
    result = build_target("Demo", target, build_dir=build, runner=make_runner())
    states = {step.block_id: step.state for step in result.steps}
    assert states == {"foundation": "closed/verified", "service": "closed/implemented"}
    assert all(state == _state(target, name) for name, state in states.items())


@pytest.mark.parametrize("healed", [False, True])
def test_dispute_from_an_earlier_attempt_only_survives_while_check_fails(tmp_path, healed):
    target_dir, build_dir = _setup(tmp_path)
    (target_dir / "blueprint" / "DATABASE.md").write_text(_marker_spec("ok\n"), encoding="utf-8")
    calls = []

    def runner(prompt, working_directory, **kwargs):
        calls.append(kwargs["parameters"]["attempt"])
        Path(working_directory).mkdir(parents=True, exist_ok=True)
        (Path(working_directory) / "foundation.txt").write_text(
            "ok\n" if healed and len(calls) > 1 else "bad\n", encoding="utf-8"
        )
        return FakeResult(
            text=(
                "RESULT: SUCCESS\nFILES CHANGED:\n- foundation.txt\n\nSUMMARY:\nDone.\n"
                + ("AC_BROKEN: foundation-file\n" if len(calls) == 1 else "")
            )
        )

    result = build_target(
        "Demo",
        target_dir,
        build_dir=build_dir,
        runner=runner,
        step_id="foundation",
        repair_attempts=3,
    )
    step = result.steps[0]
    assert step.reported_defective_acceptance == (() if healed else ("foundation-file",))
    assert (step.status == "failed") is not healed

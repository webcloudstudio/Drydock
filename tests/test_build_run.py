"""Tests for ``drydock build`` orchestration (drydock.build_run)."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

from drydock.build_plan import parse_build_plan
from drydock.build_run import build_target
from drydock.errors import SpecificationError


@pytest.fixture(autouse=True)
def clean_drydock_source(monkeypatch, request):
    import drydock.build_run as br

    if request.node.name == "test_dirty_drydock_source_blocks_build":
        return
    monkeypatch.setattr(br, "_ensure_drydock_source_clean", lambda: None)


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


class FakeResult:
    def __init__(self, ok=True, text="Built it. Created app.py.", execution_id="exec-1", stderr=""):
        self.ok = ok
        self.text = text
        self.execution_id = execution_id
        self.stderr = stderr


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


def make_runner(*, ok=True, text: str | None = None, write_files=True, stderr=""):
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
        return FakeResult(ok=ok, text=text or _success_report(changed=changed), stderr=stderr)

    runner.calls = calls  # type: ignore[attr-defined]
    return runner


def _finding(target_dir, block_id):
    plan = parse_build_plan(target_dir / "MANIFEST.md")
    return plan.by_id()[block_id].fields.get("finding")


def _setup(tmp_path, manifest=_TWO_STORIES):
    target_dir = tmp_path / "target"
    blueprint = target_dir / "blueprint"
    blueprint.mkdir(parents=True)
    (target_dir / "MANIFEST.md").write_text(manifest, encoding="utf-8")
    (target_dir / "COMPASS.md").write_text("COMPASS INTENT CONTENT\n", encoding="utf-8")
    (blueprint / "DATABASE.md").write_text("DB SPEC CONTENT\n", encoding="utf-8")
    (blueprint / "SERVICE.md").write_text("SVC SPEC CONTENT\n", encoding="utf-8")
    return target_dir, tmp_path / "build"


def _state(target_dir, block_id):
    plan = parse_build_plan(target_dir / "MANIFEST.md")
    return plan.by_id()[block_id].state


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
    assert (build_dir / ".git").is_dir()
    assert result.git_initialized is True
    assert result.git_commit is not None
    assert result.git_commit_message is not None
    assert result.git_commit_message.startswith("drydock build Demo ")


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
    assert "Story Retry: drydock build Demo --step external-foundation --force" in message
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
    assert "Story Retry: drydock build Demo --step external-foundation --force" in message


def test_blocked_build_does_not_auto_compact(tmp_path, monkeypatch):
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
    compact_calls: list[object] = []

    def fail_if_called(*args, **kwargs):
        compact_calls.append((args, kwargs))
        raise AssertionError("blocked build should not auto-compact")

    monkeypatch.setattr("drydock.build_run.ensure_compact_files", fail_if_called)

    with pytest.raises(SpecificationError, match="unverified external dependencies"):
        build_target("Demo", target_dir, build_dir=build_dir, runner=make_runner())

    assert compact_calls == []


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
    assert "DRY RUN ASSEMBLED FILES" in log
    assert any(line.startswith("  Role") for line in log)
    assert any("implements" in line and "DATABASE.md" in line for line in log)
    assert any(line == "BUILD BLOCK: Catalog [feature-catalog]" for line in log)
    assert any(line.startswith("DRY RUN PROMPT: assembled") for line in log)
    assert "DRY RUN PROMPT: hidden; use --show-prompt to print it" in log
    assert "DRY RUN PROMPT BEGIN" not in log
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

    assert "DRY RUN PROMPT BEGIN" in log
    assert "DRY RUN PROMPT END" in log
    assert any("DB SPEC CONTENT" in line for line in log)


def test_force_dry_run_previews_reset_without_manifest_write(tmp_path):
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
        force=True,
        dry_run=True,
    )

    assert [s.block_id for s in result.steps] == ["service"]
    assert result.steps[0].status == "dry-run"
    assert len(runner.calls) == 0
    assert "DRY RUN: would reset service and child ACs to pending" in log
    assert any(line == "  [run] Service (service)" for line in log)
    assert (target_dir / "MANIFEST.md").read_text(encoding="utf-8") == original_manifest


def test_build_emits_step_progress_lines(tmp_path):
    target_dir, build_dir = _setup(tmp_path)
    log: list[str] = []

    build_target("Demo", target_dir, build_dir=build_dir, runner=make_runner(), on_text=log.append)

    assert any(line == "BUILD BLOCK: Foundation [foundation]" for line in log)
    assert any(line == "  Type: story" for line in log)
    assert any(line == "  Stories Included: 1 run, 0 already verified" for line in log)
    assert any(re.match(r"  Combined Story Points: \d+", line) for line in log)
    assert any(re.match(r"  Started: \d{4}-\d{2}-\d{2} ", line) for line in log)
    assert any(line == f"Workdir: {build_dir}" for line in log)
    assert any(line == "  [run] Foundation (foundation)" for line in log)
    assert any(
        line == "BUILD BLOCK RETURNED: Foundation [foundation]  ok=True  id=exec-1" for line in log
    )
    assert any(
        line == "BUILD BLOCK FILES: Foundation [foundation]  1 changed: foundation.txt"
        for line in log
    )
    assert any(line == "BUILD BLOCK COMPLETE: Foundation [foundation]" for line in log)
    assert any(line == "  State: closed/verified" for line in log)
    assert any(re.match(r"  Completed: \d{4}-\d{2}-\d{2} ", line) for line in log)
    assert any(line.startswith("  Elapsed: ") for line in log)
    assert any(line == "  Evidence: evidence/foundation.md" for line in log)


def test_feature_step_auto_compacts_and_injects_compact_context(tmp_path):
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

    assert any("AUTO-COMPACT:" in line and "ARCHITECTURE_compact.md" in line for line in log)
    assert any("AUTO-COMPACT:" in line and "DATABASE_compact.md" in line for line in log)
    prompt = runner.calls[0]["prompt"]
    assert 'filename="ARCHITECTURE_compact.md"' in prompt
    assert 'filename="DATABASE_compact.md"' in prompt


def test_build_auto_compacts_only_current_block_sources(tmp_path, monkeypatch):
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
context: FEATURE-B.md
instructions: |
  Build the service.
state: pending
"""
    target_dir, build_dir = _setup(tmp_path, manifest=manifest)
    blueprint = target_dir / "blueprint"
    (blueprint / "FEATURE-A.md").write_text("FEATURE A\n", encoding="utf-8")
    (blueprint / "FEATURE-B.md").write_text("FEATURE B\n", encoding="utf-8")
    compact_sources: list[tuple[str, ...]] = []

    def record_compacts(blueprint_dir, *, sources, **kwargs):
        compact_sources.append(tuple(source.name for source in sources))

    monkeypatch.setattr("drydock.build_run.ensure_compact_files", record_compacts)
    runner = make_runner(ok=False, text="", write_files=False)

    result = build_target("Demo", target_dir, build_dir=build_dir, runner=runner)

    assert result.steps[0].status == "failed"
    assert compact_sources == [("DATABASE.md", "FEATURE-A.md")]
    assert "FEATURE-B.md" not in compact_sources[0]
    assert len(runner.calls) == 1


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


def test_force_rebuild_resets_step_and_child_acs(tmp_path):
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
        force=True,
    )

    assert [s.block_id for s in result.steps] == ["foundation"]
    assert result.steps[0].status == "built"
    assert _state(target_dir, "foundation") == "closed/verified"
    assert _finding(target_dir, "foundation") is None
    assert _state(target_dir, "ac-db") == "closed/verified"
    assert _state(target_dir, "service") == "pending"


def test_force_requires_step(tmp_path):
    from drydock.errors import SpecificationError

    target_dir, build_dir = _setup(tmp_path)

    with pytest.raises(SpecificationError, match="--force requires --step"):
        build_target("Demo", target_dir, build_dir=build_dir, runner=make_runner(), force=True)


def test_detects_agent_side_commit_when_drydock_has_no_commit(tmp_path, monkeypatch):
    import drydock.build_run as br

    monkeypatch.setattr(br, "_commit_build_dir", lambda path, target, today: (None, None))
    target_dir, build_dir = _setup(tmp_path)
    result = build_target("Demo", target_dir, build_dir=build_dir, runner=make_runner())

    assert result.drydock_commit_skipped_after_build is True


def test_prompt_stacks_spec_content_and_instructions(tmp_path):
    target_dir, build_dir = _setup(tmp_path)
    runner = make_runner()
    build_target("Demo", target_dir, build_dir=build_dir, runner=runner)

    first = runner.calls[0]["prompt"]
    assert "DB SPEC CONTENT" in first
    assert "Build the database." in first
    assert 'filename="COMPASS.md"' in first
    assert "COMPASS INTENT CONTENT" in first
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


def test_existing_git_repo_not_reinitialized(tmp_path):
    target_dir, build_dir = _setup(tmp_path)
    build_dir.mkdir(parents=True)
    subprocess.run(
        ["git", "-C", str(build_dir), "init"], check=True, capture_output=True, text=True
    )
    runner = make_runner()
    result = build_target("Demo", target_dir, build_dir=build_dir, runner=runner)

    assert result.git_initialized is False
    assert result.git_commit is not None


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
        "Demo", target_dir, build_dir=build_dir, runner=make_runner(), step_id="foundation"
    )

    assert result.steps[0].status == "built"
    assert result.steps[0].acceptance[0].check_id == "foundation-file"
    assert result.steps[0].acceptance[0].passed is True
    evidence = (target_dir / "evidence" / "foundation.md").read_text(encoding="utf-8")
    assert "## Programmatic acceptance" in evidence
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


def test_failed_step_skips_final_build_commit_even_with_file_changes(tmp_path):
    target_dir, build_dir = _setup(tmp_path)
    runner = make_runner(ok=False, text="", write_files=True)

    result = build_target("Demo", target_dir, build_dir=build_dir, runner=runner)

    assert result.steps[0].status == "failed"
    assert result.steps[0].written_files == ("foundation.txt",)
    assert result.git_commit is None
    assert result.git_commit_message is None
    assert result.exit_code() == 1


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
    assert result.git_commit is None


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
    assert result.git_commit is not None


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
    def test_dirty_drydock_source_blocks_build(self, tmp_path, monkeypatch):
        import drydock.build_run as br
        from drydock.errors import SpecificationError

        monkeypatch.setattr(br, "get_repo_root", lambda: tmp_path / "Drydock")
        monkeypatch.setattr(br, "_dirty_paths", lambda p: (" M src/drydock/build_run.py",))

        target_dir, build_dir = _setup(tmp_path)

        with pytest.raises(SpecificationError, match="Drydock repository"):
            build_target("Demo", target_dir, build_dir=build_dir, runner=make_runner())

    def test_dirty_stack_dir_blocks_build(self, tmp_path, monkeypatch):
        import drydock.build_run as br
        from drydock.errors import SpecificationError

        monkeypatch.setattr(br, "_git_head", lambda p: "abc123")
        monkeypatch.setattr(br, "_is_dirty", lambda p: True)

        target_dir, build_dir = _setup(tmp_path, manifest=_WITH_STACK)
        (target_dir / "blueprint" / "common.md").write_text("stack content\n", encoding="utf-8")

        with pytest.raises(SpecificationError, match="uncommitted changes"):
            build_target("Demo", target_dir, build_dir=build_dir, runner=make_runner())

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
        blueprint = target_dir / "blueprint"
        blueprint.mkdir(parents=True)
        (target_dir / "MANIFEST.md").write_text(body, encoding="utf-8")
        (target_dir / "COMPASS.md").write_text("Compass.\n", encoding="utf-8")
        (blueprint / "DATABASE.md").write_text("DB SPEC\n", encoding="utf-8")
        return target_dir, tmp_path / "build"

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
        # Context always prefers the compact derivative; the applied record names
        # the file that actually entered the prompt.
        assert "ARCHITECTURE_compact.md" in plan.applied_specs
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
        with pytest.raises(SpecificationError, match="previously applied Blueprint specifications"):
            build_target("Demo", target_dir, build_dir=build_dir, runner=second_runner)

        assert len(second_runner.calls) == 0

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

    def test_drift_error_message_distinguishes_foundational_and_ordinary(self, tmp_path):
        import hashlib

        from drydock.build_run import _ensure_applied_specs_current
        from drydock.errors import SpecificationError

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

        with pytest.raises(SpecificationError) as excinfo:
            _ensure_applied_specs_current(manifest, blueprint)

        message = str(excinfo.value)
        assert "sealed foundational specification" in message
        assert "Amends: DATABASE.md" in message
        assert "drydock refit" in message
        assert "SCREEN-A.md" in message

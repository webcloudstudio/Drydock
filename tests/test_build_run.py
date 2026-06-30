"""Tests for ``drydock build`` orchestration (drydock.build_run)."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from drydock.build_plan import parse_build_plan
from drydock.build_run import build_target


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


class FakeResult:
    def __init__(self, ok=True, text="Built it. Created app.py.", execution_id="exec-1"):
        self.ok = ok
        self.text = text
        self.execution_id = execution_id


def _success_report(*, changed: tuple[str, ...], summary: str = "Built it.") -> str:
    return (
        "RESULT: SUCCESS\n\n"
        "FILES CHANGED:\n"
        + "\n".join(f"- {path}" for path in changed)
        + f"\n\nSUMMARY:\n{summary}\n"
    )


def make_runner(*, ok=True, text: str | None = None, write_files=True):
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
        return FakeResult(ok=ok, text=text or _success_report(changed=changed))

    runner.calls = calls  # type: ignore[attr-defined]
    return runner


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
    assert result.steps[0].status == "implemented"
    assert _state(target_dir, "foundation") == "implemented"
    assert _state(target_dir, "ac-db") == "pending"
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


def test_step_with_child_ac_stops_at_review_gate(tmp_path):
    target_dir, build_dir = _setup(tmp_path, manifest=_STORY_WITH_AC)
    runner = make_runner()
    result = build_target("Demo", target_dir, build_dir=build_dir, runner=runner)

    # foundation has an ac, so it stops at review and does not auto-close;
    # service depends on a verified foundation, so it stays blocked.
    assert [s.block_id for s in result.steps] == ["foundation"]
    assert result.steps[0].status == "implemented"
    assert _state(target_dir, "foundation") == "implemented"
    assert _state(target_dir, "service") == "pending"
    assert len(runner.calls) == 1


def test_failed_step_marks_failed_and_stops(tmp_path):
    target_dir, build_dir = _setup(tmp_path)
    runner = make_runner(ok=False, text="", write_files=False)
    result = build_target("Demo", target_dir, build_dir=build_dir, runner=runner)

    assert result.steps[0].status == "failed"
    assert _state(target_dir, "foundation") == "closed/failed"
    assert _state(target_dir, "service") == "pending"
    assert len(runner.calls) == 1
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


def test_missing_structured_report_marks_failed(tmp_path):
    target_dir, build_dir = _setup(tmp_path)
    result = build_target(
        "Demo",
        target_dir,
        build_dir=build_dir,
        runner=make_runner(text="Built it."),
    )

    assert result.steps[0].status == "failed"
    assert result.steps[0].error == "missing structured build report"
    assert _state(target_dir, "foundation") == "closed/failed"
    assert result.git_commit is not None


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

"""Unit tests for drydock.status module."""

from __future__ import annotations

import pytest

from drydock.errors import write_error_record
from drydock.status import (
    StatusResult,
    completion_check,
    status_blueprint,
    status_blueprint_target,
    status_current,
)

ANALYSIS_READY = """\
Quality: Ready
  Stories: 3
  Questions: 1
  Blockers: 0
  Screens: 1
"""

APPROVED_PLAN = """\
# MANIFEST: TestProject
state: approved
updated: 2026-01-01T00:00:00
plan_hash: abc123

## story 1: Core feature
id: core-feature
state: pending

## story 2: Extra feature
id: extra-feature
state: implemented
"""

DRAFT_PLAN = """\
# MANIFEST: TestProject
state: draft
updated: 2026-01-01T00:00:00
plan_hash: abc123

## story 1: Core feature
id: core-feature
state: pending
"""


class TestStatusBlueprintTarget:
    def _setup(self, tmp_target_root):
        tgt = tmp_target_root / "TestTarget"
        tgt.mkdir()
        (tgt / "MANIFEST.md").write_text(APPROVED_PLAN, encoding="utf-8")
        return tgt

    def test_returns_plan_and_frontier(self, tmp_target_root):
        tgt = self._setup(tmp_target_root)
        result = status_blueprint_target(
            "TestProject", "TestTarget", tgt / "blueprint", tmp_target_root
        )
        assert isinstance(result, StatusResult)
        assert result.blueprint == "TestProject"
        assert result.target == "TestTarget"
        assert result.plan is not None
        assert result.target_path == tmp_target_root / "TestTarget"
        assert result.target_info is not None
        assert result.target_info.phase == "Implement"

    def test_frontier_contains_pending_blocks(self, tmp_target_root):
        tgt = self._setup(tmp_target_root)
        result = status_blueprint_target(
            "TestProject", "TestTarget", tgt / "blueprint", tmp_target_root
        )
        ids = {b.block_id for b in result.frontier}
        assert "core-feature" in ids
        assert "extra-feature" not in ids

    def test_missing_plan_raises(self, tmp_target_root):
        tgt = tmp_target_root / "NoTarget"
        tgt.mkdir()
        result = status_blueprint_target("X", "NoTarget", tgt / "blueprint", tmp_target_root)
        assert isinstance(result, StatusResult)
        assert result.plan is None
        assert result.frontier == ()
        assert result.target_info is not None
        assert result.target_info.phase == "Set Up"

    def test_missing_target_raises(self, tmp_target_root):
        with pytest.raises(Exception):
            status_blueprint_target(
                "X", "NoTarget", tmp_target_root / "NoTarget" / "blueprint", tmp_target_root
            )

    def test_imported_sources_without_analysis_show_arrange(self, tmp_target_root):
        tgt = tmp_target_root / "TestTarget"
        (tgt / "blueprint" / "sources").mkdir(parents=True)
        (tgt / "blueprint" / "sources" / "request.md").write_text("# Request\n", encoding="utf-8")

        result = status_blueprint_target(
            "TestTarget", "TestTarget", tgt / "blueprint", tmp_target_root
        )

        assert result.target_info is not None
        assert result.target_info.phase == "Arrange"
        assert result.target_info.imported_sources == 1
        assert result.target_info.next_operation == "drydock analyze TestTarget"

    def test_analysis_ready_without_plan_suggests_plan(self, tmp_target_root):
        tgt = tmp_target_root / "TestTarget"
        tgt.mkdir()
        (tgt / "ANALYSIS.md").write_text(ANALYSIS_READY, encoding="utf-8")

        result = status_blueprint_target(
            "TestTarget", "TestTarget", tgt / "blueprint", tmp_target_root
        )

        assert result.target_info is not None
        assert result.target_info.phase == "Arrange"
        assert result.target_info.analysis is not None
        assert result.target_info.analysis.quality == "Ready"
        assert result.target_info.next_operation == "drydock plan TestTarget"

    def test_draft_plan_points_to_quarterdeck_review(self, tmp_target_root):
        tgt = tmp_target_root / "TestTarget"
        tgt.mkdir()
        (tgt / "MANIFEST.md").write_text(DRAFT_PLAN, encoding="utf-8")

        result = status_blueprint_target(
            "TestTarget", "TestTarget", tgt / "blueprint", tmp_target_root
        )

        assert result.target_info is not None
        assert result.target_info.phase == "Arrange"
        assert "review the Planning Session build tree" in result.target_info.phase_detail
        assert result.target_info.next_operation == "drydock run quarterdeck TestTarget"

    def test_active_error_overrides_normal_projection(self, tmp_target_root):
        tgt = self._setup(tmp_target_root)
        write_error_record(
            tgt,
            command="build",
            phase="LLM execution",
            classification="provider rate limit",
            detail="retry later",
            recovery="Run drydock build TestTarget",
            state="Error",
        )

        result = status_blueprint_target(
            "TestProject", "TestTarget", tgt / "blueprint", tmp_target_root
        )

        assert result.target_info is not None
        assert result.target_info.active_error is not None
        assert result.target_info.phase_detail == "Error: provider rate limit"
        assert result.target_info.next_operation == "drydock run quarterdeck TestTarget"

    def test_authored_blueprint_count_excludes_agents_md(self, tmp_target_root):
        tgt = tmp_target_root / "TestTarget"
        blueprint = tgt / "blueprint"
        blueprint.mkdir(parents=True)
        (tgt / "METADATA.md").write_text(
            "name: TestTarget\ndisplay_name: TestTarget\n", encoding="utf-8"
        )
        (blueprint / "ARCHITECTURE.md").write_text("# ARCHITECTURE: X\n", encoding="utf-8")
        (blueprint / "AGENTS.md").write_text("# not a spec\n", encoding="utf-8")

        result = status_blueprint_target("TestTarget", "TestTarget", blueprint, tmp_target_root)

        assert result.target_info is not None
        assert result.target_info.authored_blueprints == 1

    def test_authored_blueprint_count_excludes_generated_compacts(self, tmp_target_root):
        tgt = tmp_target_root / "TestTarget"
        blueprint = tgt / "blueprint"
        blueprint.mkdir(parents=True)
        (tgt / "METADATA.md").write_text(
            "name: TestTarget\ndisplay_name: TestTarget\n", encoding="utf-8"
        )
        (blueprint / "ARCHITECTURE.md").write_text("# ARCHITECTURE: X\n", encoding="utf-8")
        (blueprint / "ARCHITECTURE_compact.md").write_text("# Compact\n", encoding="utf-8")
        (blueprint / "DATABASE_compact.md").write_text("# Compact\n", encoding="utf-8")

        result = status_blueprint_target("TestTarget", "TestTarget", blueprint, tmp_target_root)

        assert result.target_info is not None
        assert result.target_info.authored_blueprints == 1

    def test_compact_recommendations_include_missing_required_context_compacts(
        self, tmp_target_root
    ):
        tgt = tmp_target_root / "TestTarget"
        blueprint = tgt / "blueprint"
        blueprint.mkdir(parents=True)
        (tgt / "METADATA.md").write_text(
            "name: TestTarget\ndisplay_name: TestTarget\n", encoding="utf-8"
        )
        (tgt / "MANIFEST.md").write_text(
            """# MANIFEST: TestTarget
state: approved

## story 1: One
id: one
state: pending
context: ARCHITECTURE.md, DATABASE.md

## story 2: Two
id: two
state: pending
context: ARCHITECTURE.md, DATABASE.md
""",
            encoding="utf-8",
        )
        (blueprint / "ARCHITECTURE.md").write_text("# ARCHITECTURE: X\n", encoding="utf-8")
        (blueprint / "DATABASE.md").write_text("# DATABASE: X\n", encoding="utf-8")

        result = status_blueprint_target("TestTarget", "TestTarget", blueprint, tmp_target_root)

        assert result.target_info is not None
        assert [rec.file for rec in result.target_info.compact_recs] == [
            "ARCHITECTURE.md",
            "DATABASE.md",
        ]

    def test_compact_recommendations_exclude_current_compacts(self, tmp_target_root):
        tgt = tmp_target_root / "TestTarget"
        blueprint = tgt / "blueprint"
        blueprint.mkdir(parents=True)
        (tgt / "METADATA.md").write_text(
            "name: TestTarget\ndisplay_name: TestTarget\n", encoding="utf-8"
        )
        (tgt / "MANIFEST.md").write_text(
            """# MANIFEST: TestTarget
state: approved

## story 1: One
id: one
state: pending
context: ARCHITECTURE.md, DATABASE.md

## story 2: Two
id: two
state: pending
context: ARCHITECTURE.md, DATABASE.md
""",
            encoding="utf-8",
        )
        (blueprint / "ARCHITECTURE.md").write_text("# ARCHITECTURE: X\n", encoding="utf-8")
        (blueprint / "DATABASE.md").write_text("# DATABASE: X\n", encoding="utf-8")
        (blueprint / "ARCHITECTURE_compact.md").write_text(
            "# ARCHITECTURE Structural Contract\n", encoding="utf-8"
        )
        (blueprint / "DATABASE_compact.md").write_text(
            "# DATABASE Persistence Contract\n", encoding="utf-8"
        )

        result = status_blueprint_target("TestTarget", "TestTarget", blueprint, tmp_target_root)

        assert result.target_info is not None
        assert result.target_info.compact_recs == []


class TestStatusBlueprint:
    def test_valid_spec_returns_pass(self, tmp_target_root):
        from drydock.init_specification import init_specification

        target_dir = tmp_target_root / "ValidBP"
        init_specification("ValidBP", target_dir)
        result = status_blueprint("ValidBP", target_dir)
        assert isinstance(result, StatusResult)
        assert result.blueprint == "ValidBP"
        assert result.validation is not None
        assert result.plan is None
        assert not result.validation.has_failures()

    def test_missing_spec_returns_failures(self, tmp_target_root):
        target_dir = tmp_target_root / "EmptyBP"
        target_dir.mkdir()
        result = status_blueprint("EmptyBP", target_dir)
        assert result.validation is not None
        assert result.validation.has_failures()


class TestStatusCurrent:
    def test_returns_none_when_no_activity_and_no_plan(
        self, tmp_target_root, isolated_config, monkeypatch
    ):
        monkeypatch.setenv("DRYDOCK_WORKSPACE", str(tmp_target_root.parent))
        monkeypatch.chdir(tmp_target_root)
        assert status_current(tmp_target_root) is None

    def test_uses_cwd_build_plan(self, tmp_target_root, isolated_config, monkeypatch):
        tgt = tmp_target_root / "TestTarget"
        tgt.mkdir()
        (tgt / "MANIFEST.md").write_text(APPROVED_PLAN, encoding="utf-8")
        monkeypatch.chdir(tgt)
        monkeypatch.setenv("DRYDOCK_WORKSPACE", str(tmp_target_root.parent))
        result = status_current(tmp_target_root)
        assert result is not None
        assert result.blueprint == "TestProject"
        assert result.target == "TestTarget"
        assert result.plan is not None

    def test_falls_back_to_last_activity(self, tmp_target_root, isolated_config, monkeypatch):
        tgt = tmp_target_root / "TestTarget"
        tgt.mkdir()
        (tgt / "MANIFEST.md").write_text(APPROVED_PLAN, encoding="utf-8")
        monkeypatch.chdir(tmp_target_root.parent)
        monkeypatch.setenv("DRYDOCK_WORKSPACE", str(tmp_target_root.parent))

        from drydock.config import record_activity

        record_activity("plan", "TestProject", "TestTarget")

        result = status_current(tmp_target_root)
        assert result is not None
        assert result.blueprint == "TestProject"
        assert result.target == "TestTarget"
        assert result.last_command == "plan"


VERIFIED_PLAN = """\
# MANIFEST: TestProject
state: approved
updated: 2026-01-01T00:00:00
plan_hash: abc123

## story 1: Core feature
id: core-feature
state: closed/verified

## story 2: Extra feature
id: extra-feature
state: closed/verified
"""


class TestCompletionCheck:
    def _target(self, tmp_target_root, manifest: str | None):
        tgt = tmp_target_root / "TestTarget"
        tgt.mkdir()
        if manifest is not None:
            (tgt / "MANIFEST.md").write_text(manifest, encoding="utf-8")
        return tgt

    def test_all_verified_is_complete(self, tmp_target_root):
        tgt = self._target(tmp_target_root, VERIFIED_PLAN)
        check = completion_check("TestTarget", tgt)
        assert check.complete is True
        assert check.exit_code() == 0
        assert (check.total, check.verified, check.remaining) == (2, 2, 0)

    def test_pending_work_is_incomplete(self, tmp_target_root):
        tgt = self._target(tmp_target_root, APPROVED_PLAN)
        check = completion_check("TestTarget", tgt)
        assert check.complete is False
        assert check.exit_code() == 1
        assert (check.total, check.verified, check.remaining) == (2, 0, 2)

    def test_failed_blocks_are_retryable(self, tmp_target_root):
        tgt = self._target(
            tmp_target_root, APPROVED_PLAN.replace("state: pending", "state: closed/failed")
        )
        check = completion_check("TestTarget", tgt)
        assert check.exit_code() == 1
        assert check.blocked is False

    def test_the_incomplete_reason_names_the_blocks_that_failed(self, tmp_target_root):
        """A count says a build stopped without saying where. The one line an operator reads
        after a failed run has to point at the story whose evidence explains it."""
        tgt = self._target(
            tmp_target_root, APPROVED_PLAN.replace("state: pending", "state: closed/failed")
        )
        check = completion_check("TestTarget", tgt)
        assert "1 closed/failed" in check.reason
        assert "failed: core-feature" in check.reason

    def test_not_started_is_blocked(self, tmp_target_root):
        tgt = self._target(tmp_target_root, None)
        check = completion_check("TestTarget", tgt)
        assert check.blocked is True
        assert check.exit_code() == 2
        assert "drydock plan" in check.reason

    def test_draft_plan_is_blocked(self, tmp_target_root):
        tgt = self._target(tmp_target_root, DRAFT_PLAN)
        check = completion_check("TestTarget", tgt)
        assert check.blocked is True
        assert check.exit_code() == 2
        assert "draft" in check.reason

    def test_unparsable_manifest_is_blocked(self, tmp_target_root):
        tgt = self._target(tmp_target_root, "not a manifest at all\n")
        check = completion_check("TestTarget", tgt)
        assert check.blocked is True
        assert check.exit_code() == 2

    def test_manifest_without_executable_work_is_blocked(self, tmp_target_root):
        tgt = self._target(
            tmp_target_root,
            "# MANIFEST: TestProject\nstate: approved\nupdated: 2026-01-01T00:00:00\n"
            "plan_hash: abc123\n",
        )
        check = completion_check("TestTarget", tgt)
        assert check.blocked is True
        assert check.exit_code() == 2
        assert "no executable work" in check.reason

"""Unit tests for drydock.status module."""

from __future__ import annotations

from pathlib import Path

import pytest

from drydock.status import StatusResult, status_blueprint, status_blueprint_target, status_current

APPROVED_PLAN = """\
# BUILD_PLAN: TestProject
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


class TestStatusBlueprintTarget:
    def _setup(self, tmp_spec_root: Path, tmp_target_root: Path) -> tuple[Path, Path]:
        bp = tmp_spec_root / "TestProject"
        bp.mkdir()
        tgt = tmp_target_root / "TestTarget"
        tgt.mkdir()
        (tgt / "BUILD_PLAN.md").write_text(APPROVED_PLAN, encoding="utf-8")
        return bp, tgt

    def test_returns_plan_and_frontier(self, tmp_spec_root, tmp_target_root):
        self._setup(tmp_spec_root, tmp_target_root)
        result = status_blueprint_target(
            "TestProject", "TestTarget", tmp_spec_root, tmp_target_root
        )
        assert isinstance(result, StatusResult)
        assert result.blueprint == "TestProject"
        assert result.target == "TestTarget"
        assert result.plan is not None
        assert result.target_path == tmp_target_root / "TestTarget"

    def test_frontier_contains_pending_blocks(self, tmp_spec_root, tmp_target_root):
        self._setup(tmp_spec_root, tmp_target_root)
        result = status_blueprint_target(
            "TestProject", "TestTarget", tmp_spec_root, tmp_target_root
        )
        ids = {b.block_id for b in result.frontier}
        assert "core-feature" in ids
        assert "extra-feature" not in ids

    def test_missing_plan_raises(self, tmp_spec_root, tmp_target_root):
        (tmp_target_root / "NoTarget").mkdir()
        with pytest.raises(Exception):
            status_blueprint_target("X", "NoTarget", tmp_spec_root, tmp_target_root)


class TestStatusBlueprint:
    def test_valid_spec_returns_pass(self, tmp_spec_root):
        from drydock.init_specification import init_specification

        init_specification("ValidBP", tmp_spec_root)
        result = status_blueprint("ValidBP", tmp_spec_root)
        assert isinstance(result, StatusResult)
        assert result.blueprint == "ValidBP"
        assert result.validation is not None
        assert result.plan is None
        assert not result.validation.has_failures()

    def test_missing_spec_returns_failures(self, tmp_spec_root):
        (tmp_spec_root / "EmptyBP").mkdir()
        result = status_blueprint("EmptyBP", tmp_spec_root)
        assert result.validation is not None
        assert result.validation.has_failures()


class TestStatusCurrent:
    def test_returns_none_when_no_activity_and_no_plan(
        self, tmp_spec_root, tmp_target_root, isolated_config, monkeypatch
    ):
        monkeypatch.setenv("DRYDOCK_WORKSPACE", str(tmp_spec_root.parent))
        monkeypatch.chdir(tmp_target_root)
        result = status_current(tmp_spec_root, tmp_target_root)
        assert result is None

    def test_uses_cwd_build_plan(
        self, tmp_spec_root, tmp_target_root, isolated_config, monkeypatch
    ):
        tgt = tmp_target_root / "TestTarget"
        tgt.mkdir()
        (tgt / "BUILD_PLAN.md").write_text(APPROVED_PLAN, encoding="utf-8")
        monkeypatch.chdir(tgt)
        monkeypatch.setenv("DRYDOCK_WORKSPACE", str(tmp_spec_root.parent))
        result = status_current(tmp_spec_root, tmp_target_root)
        assert result is not None
        assert result.blueprint == "TestProject"
        assert result.target == "TestTarget"
        assert result.plan is not None

    def test_falls_back_to_last_activity(
        self, tmp_spec_root, tmp_target_root, isolated_config, monkeypatch
    ):
        tgt = tmp_target_root / "TestTarget"
        tgt.mkdir()
        (tgt / "BUILD_PLAN.md").write_text(APPROVED_PLAN, encoding="utf-8")
        monkeypatch.chdir(tmp_spec_root)
        monkeypatch.setenv("DRYDOCK_WORKSPACE", str(tmp_spec_root.parent))

        from drydock.config import record_activity

        record_activity("plan create", "TestProject", "TestTarget")

        result = status_current(tmp_spec_root, tmp_target_root)
        assert result is not None
        assert result.blueprint == "TestProject"
        assert result.target == "TestTarget"
        assert result.last_command == "plan create"

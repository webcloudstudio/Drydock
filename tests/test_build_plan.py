"""Tests for canonical MANIFEST.md parsing and frontier calculation."""

from __future__ import annotations

from pathlib import Path

import pytest

from drydock.build_plan import (
    _format_applied_registry,
    _parse_applied_registry,
    parse_build_plan,
    set_applied_registry,
    set_plan_state,
)
from drydock.errors import SpecificationError


def write_plan(path: Path, body: str) -> Path:
    path.write_text(body, encoding="utf-8")
    return path


@pytest.fixture()
def plan_path(tmp_path: Path) -> Path:
    return write_plan(
        tmp_path / "MANIFEST.md",
        """# MANIFEST: Example
updated:     2026-06-11T12:00:00
plan_hash:   abc123

## story 1: Foundation
id:           foundation
summary:      Build the foundation.
state:        closed/verified

## story 2: Import documents
id:           import-documents
depends:      foundation
state:        pending

## story 3: Unknown dependency
id:           blocked-story
depends:      missing-block
state:        pending

## story 4: Awaiting checks
id:           awaiting-checks
state:        implemented

## ac 1: System starts
id:           system-starts
parent:       awaiting-checks
state:        pending

## ac 2: Foundation check
id:           foundation-check
parent:       foundation
state:        pending
""",
    )


def test_parse_build_plan(plan_path: Path):
    plan = parse_build_plan(plan_path)

    assert plan.project == "Example"
    assert plan.updated == "2026-06-11T12:00:00"
    assert plan.plan_hash == "abc123"
    assert len(plan.blocks) == 6
    assert plan.blocks[1].depends == ("foundation",)


def test_parse_build_plan_accepts_whitespace_separated_depends(tmp_path: Path):
    path = write_plan(
        tmp_path / "MANIFEST.md",
        """# MANIFEST: Example
state: draft

## story 1: First
id: first
state: closed/verified

## story 2: Second
id: second
depends: first third
state: pending

## story 3: Third
id: third
state: closed/verified

## ac 1: Second accepted
id: second-accepted
parent: second
state: pending
""",
    )

    plan = parse_build_plan(path)

    assert plan.by_id()["second"].depends == ("first", "third")


def test_parse_build_plan_captures_block_scalar_instructions(tmp_path: Path):
    path = write_plan(
        tmp_path / "MANIFEST.md",
        """# MANIFEST: Example
state: draft

## story 1: First
id: first
implements: A.md
instructions: |
  Build the first thing.
  Keep it small.
depends:
state: pending
""",
    )

    plan = parse_build_plan(path)

    block = plan.by_id()["first"]
    assert block.fields["instructions"] == "Build the first thing.\nKeep it small."
    # Fields after a block scalar are still parsed.
    assert block.depends == ()
    assert block.state == "pending"
    assert block.fields["implements"] == ("A.md",)


def test_runnable_frontier_applies_dependency_and_ac_parent_rules(plan_path: Path):
    plan = parse_build_plan(plan_path)

    assert [block.block_id for block in plan.runnable_frontier()] == [
        "import-documents",
        "system-starts",
    ]


def test_state_counts(plan_path: Path):
    counts = parse_build_plan(plan_path).state_counts()

    assert counts["pending"] == 4
    assert counts["implemented"] == 1
    assert counts["closed/verified"] == 1
    assert counts["closed/failed"] == 0


def test_missing_plan_raises(tmp_path: Path):
    with pytest.raises(SpecificationError, match="MANIFEST.md not found"):
        parse_build_plan(tmp_path / "MANIFEST.md")


def test_missing_id_raises(tmp_path: Path):
    path = write_plan(
        tmp_path / "MANIFEST.md",
        "# MANIFEST: Example\n\n## story 1: No id\nstate: pending\n",
    )

    with pytest.raises(SpecificationError, match="Missing id"):
        parse_build_plan(path)


def test_duplicate_id_raises(tmp_path: Path):
    path = write_plan(
        tmp_path / "MANIFEST.md",
        """# MANIFEST: Example

## story 1: First
id: duplicate
state: pending

## spike 1: Second
id: duplicate
state: pending
""",
    )

    with pytest.raises(SpecificationError, match="Duplicate block id"):
        parse_build_plan(path)


def test_ac_requires_parent(tmp_path: Path):
    path = write_plan(
        tmp_path / "MANIFEST.md",
        "# MANIFEST: Example\n\n## ac 1: Check\nid: check\nstate: pending\n",
    )

    with pytest.raises(SpecificationError, match="Missing parent"):
        parse_build_plan(path)


def test_invalid_state_raises(tmp_path: Path):
    path = write_plan(
        tmp_path / "MANIFEST.md",
        "# MANIFEST: Example\n\n## story 1: Bad\nid: bad\nstate: running\n",
    )

    with pytest.raises(SpecificationError, match="Invalid state"):
        parse_build_plan(path)


def test_draft_plan_has_no_runnable_frontier(tmp_path: Path):
    path = write_plan(
        tmp_path / "MANIFEST.md",
        """# MANIFEST: Example
state: draft

## story 1: Work
id: work
scope: target
state: pending
""",
    )

    plan = parse_build_plan(path)

    assert plan.state == "draft"
    assert plan.blocks[0].scope == "target"
    assert plan.runnable_frontier() == ()


def test_plan_approval_exposes_frontier(tmp_path: Path):
    path = write_plan(
        tmp_path / "MANIFEST.md",
        """# MANIFEST: Example
state: draft

## feature 1: Workflow
id: workflow
state: pending

## story 1: Work
id: work
parent: workflow
state: pending
""",
    )

    plan = set_plan_state(path, "approved")

    assert plan.state == "approved"
    assert [block.block_id for block in plan.runnable_frontier()] == ["work"]


def test_non_executable_feature_closes_after_all_children(tmp_path: Path):
    path = write_plan(
        tmp_path / "MANIFEST.md",
        """# MANIFEST: Example
state: approved

## feature 1: Workflow
id: workflow
state: pending

## story 1: Work
id: work
parent: workflow
state: closed/verified

## ac 1: Workflow accepted
id: workflow-accepted
parent: workflow
state: closed/verified
""",
    )

    plan = parse_build_plan(path)

    assert [block.block_id for block in plan.closable_features()] == ["workflow"]


def test_feature_acceptance_runs_after_feature_work_closes(tmp_path: Path):
    path = write_plan(
        tmp_path / "MANIFEST.md",
        """# MANIFEST: Example
state: approved

## feature 1: Workflow
id: workflow
state: pending

## story 1: Work
id: work
parent: workflow
state: closed/verified

## ac 1: Workflow accepted
id: workflow-accepted
parent: workflow
state: pending
""",
    )

    plan = parse_build_plan(path)

    assert [block.block_id for block in plan.runnable_frontier()] == ["workflow-accepted"]


class TestAppliedRegistry:
    _MANIFEST = "# MANIFEST: Test\nstate: approved\n\n## story 1: S\nid: s\nstate: pending\n"

    def test_empty_registry_by_default(self, tmp_path):
        path = tmp_path / "MANIFEST.md"
        path.write_text(self._MANIFEST, encoding="utf-8")
        plan = parse_build_plan(path)
        assert plan.applied_registry == {}

    def test_parse_applied_from_preamble(self, tmp_path):
        manifest = "# MANIFEST: Test\nstate: approved\napplied: common.md=abc123,python.md=def456\n\n## story 1: S\nid: s\nstate: pending\n"
        path = tmp_path / "MANIFEST.md"
        path.write_text(manifest, encoding="utf-8")
        plan = parse_build_plan(path)
        assert plan.applied_registry == {"common.md": "abc123", "python.md": "def456"}

    def test_set_applied_registry_writes_field(self, tmp_path):
        path = tmp_path / "MANIFEST.md"
        path.write_text(self._MANIFEST, encoding="utf-8")
        set_applied_registry(path, {"common.md": "abc123"})
        plan = parse_build_plan(path)
        assert plan.applied_registry == {"common.md": "abc123"}

    def test_set_applied_registry_updates_existing(self, tmp_path):
        manifest = "# MANIFEST: Test\nstate: approved\napplied: common.md=old123\n\n## story 1: S\nid: s\nstate: pending\n"
        path = tmp_path / "MANIFEST.md"
        path.write_text(manifest, encoding="utf-8")
        set_applied_registry(path, {"common.md": "new456", "python.md": "xyz789"})
        plan = parse_build_plan(path)
        assert plan.applied_registry == {"common.md": "new456", "python.md": "xyz789"}

    def test_parse_applied_registry_helper(self):
        assert _parse_applied_registry("a.md=abc,b.md=def") == {"a.md": "abc", "b.md": "def"}
        assert _parse_applied_registry("") == {}
        assert _parse_applied_registry("bad-entry") == {}

    def test_format_applied_registry_helper(self):
        result = _format_applied_registry({"b.md": "222", "a.md": "111"})
        assert result == "a.md=111,b.md=222"  # sorted

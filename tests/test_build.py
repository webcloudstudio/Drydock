"""Unit tests for build-step assembly and cost."""

from __future__ import annotations

from pathlib import Path

from drydock.build import (
    PROMPT_WARN_KB,
    StepRoots,
    assemble_step,
    assemble_steps,
    group_steps,
)
from drydock.build_plan import parse_build_plan

_MANIFEST = """# MANIFEST: Demo
state: approved

## feature 1: Foundation
id: feat-foundation
summary: Group.
state: pending

## story 2: Core
id: core
parent: feat-foundation
implements: ARCHITECTURE.md, DATABASE.md
context: README.md, missing-context.md
stack: common.md, python.md
rules: CLAUDE_RULES.md
instructions: |
  Build the core.
state: pending

## ac 3: Core Works
id: ac-core
parent: core
kind: smoke
check: true
state: pending

## spike 4: Open Question
id: spike-q
parent: feat-foundation
context: ARCHITECTURE.md
state: pending
"""


def _roots(tmp_path: Path) -> StepRoots:
    target = tmp_path / "target"
    blueprint = target / "blueprint"
    stack = tmp_path / "rigging" / "stack"
    rigging = tmp_path / "rigging"
    for d in (blueprint, stack, rigging):
        d.mkdir(parents=True, exist_ok=True)
    (blueprint / "ARCHITECTURE.md").write_text("a" * 400, encoding="utf-8")
    (blueprint / "DATABASE.md").write_text("b" * 800, encoding="utf-8")
    (target / "README.md").write_text("c" * 40, encoding="utf-8")
    (target / "COMPASS.md").write_text("d" * 200, encoding="utf-8")
    (stack / "common.md").write_text("e" * 120, encoding="utf-8")
    (stack / "python.md").write_text("f" * 160, encoding="utf-8")
    (rigging / "CLAUDE_RULES.md").write_text("g" * 80, encoding="utf-8")
    return StepRoots(
        target_dir=target, blueprint_dir=blueprint, stack_dir=stack, rigging_dir=rigging
    )


def _plan(tmp_path: Path):
    path = tmp_path / "MANIFEST.md"
    path.write_text(_MANIFEST, encoding="utf-8")
    return parse_build_plan(path)


class TestAssembleStep:
    def test_resolves_all_roles(self, tmp_path):
        plan = _plan(tmp_path)
        roots = _roots(tmp_path)
        step = assemble_step(plan.by_id()["core"], roots)
        names = {f.name: f for f in step.files}
        assert names["COMPASS.md"].role == "compass"
        assert names["ARCHITECTURE.md"].role == "implements"
        assert names["README.md"].role == "context"
        assert names["common.md"].role == "stack"
        assert names["CLAUDE_RULES.md"].role == "rules"

    def test_missing_file_flagged_zero_cost(self, tmp_path):
        plan = _plan(tmp_path)
        step = assemble_step(plan.by_id()["core"], _roots(tmp_path))
        miss = {f.name for f in step.missing_files()}
        assert miss == {"missing-context.md"}
        bad = next(f for f in step.files if f.name == "missing-context.md")
        assert bad.byte_count == 0 and bad.story_points == 0

    def test_total_story_points_sum_of_parts(self, tmp_path):
        plan = _plan(tmp_path)
        step = assemble_step(plan.by_id()["core"], _roots(tmp_path))
        # bytes: compass 200 + arch 400 + db 800 + readme 40 + common 120
        #        + python 160 + rules 80 = 1800; instructions "Build the core.\n"
        file_bytes = 200 + 400 + 800 + 40 + 120 + 160 + 80
        assert step.total_byte_count == file_bytes + len(step.instructions.encode())
        # story points = ceil(bytes/4) per file, summed
        assert step.total_story_points == sum(f.story_points for f in step.files) + (
            step.instructions_story_points
        )

    def test_instructions_counted(self, tmp_path):
        plan = _plan(tmp_path)
        step = assemble_step(plan.by_id()["core"], _roots(tmp_path))
        assert "Build the core." in step.instructions
        assert step.instructions_story_points > 0

    def test_over_warn_flag(self, tmp_path):
        plan = _plan(tmp_path)
        roots = _roots(tmp_path)
        # Inflate one implements file past the warn ceiling.
        (roots.blueprint_dir / "DATABASE.md").write_text(
            "x" * (PROMPT_WARN_KB * 1024 + 10), encoding="utf-8"
        )
        step = assemble_step(plan.by_id()["core"], roots)
        assert step.over_warn is True

    def test_under_warn_default(self, tmp_path):
        plan = _plan(tmp_path)
        step = assemble_step(plan.by_id()["core"], _roots(tmp_path))
        assert step.over_warn is False


class TestAssembleSteps:
    def test_only_story_and_spike_are_steps(self, tmp_path):
        plan = _plan(tmp_path)
        steps = assemble_steps(plan, _roots(tmp_path))
        ids = {s.block_id for s in steps}
        assert ids == {"core", "spike-q"}  # feature and ac excluded

    def test_manifest_order_preserved(self, tmp_path):
        plan = _plan(tmp_path)
        steps = assemble_steps(plan, _roots(tmp_path))
        assert [s.block_id for s in steps] == ["core", "spike-q"]


class TestGroupSteps:
    def test_groups_under_feature(self, tmp_path):
        plan = _plan(tmp_path)
        steps = assemble_steps(plan, _roots(tmp_path))
        groups = group_steps(plan, steps)
        assert len(groups) == 1
        assert groups[0].name == "Foundation"
        assert groups[0].feature_id == "feat-foundation"
        assert {s.block_id for s in groups[0].steps} == {"core", "spike-q"}

    def test_rollup_sums_step_points(self, tmp_path):
        plan = _plan(tmp_path)
        steps = assemble_steps(plan, _roots(tmp_path))
        groups = group_steps(plan, steps)
        assert groups[0].total_story_points == sum(s.total_story_points for s in steps)

    def test_orphan_steps_go_ungrouped(self, tmp_path):
        path = tmp_path / "MANIFEST.md"
        path.write_text(
            "# MANIFEST: D\nstate: approved\n\n"
            "## story 1: Solo\nid: solo\nimplements: A.md\nstate: pending\n",
            encoding="utf-8",
        )
        plan = parse_build_plan(path)
        steps = assemble_steps(plan, _roots(tmp_path))
        groups = group_steps(plan, steps)
        assert groups[0].name == "Ungrouped"
        assert groups[0].feature_id is None


_TWO_STORY_MANIFEST = """# MANIFEST: Demo
state: approved

## story 1: Foundation
id: s1
implements: ARCHITECTURE.md
stack: common.md, python.md
state: pending

## story 2: Feature
id: s2
implements: ARCHITECTURE.md
stack: common.md, python.md
state: pending
"""


class TestCompactSubstitution:
    def _roots_with_compacts(self, tmp_path: Path) -> StepRoots:
        target = tmp_path / "target"
        blueprint = target / "blueprint"
        stack = tmp_path / "rigging" / "stack"
        rigging = tmp_path / "rigging"
        for d in (blueprint, stack, rigging):
            d.mkdir(parents=True, exist_ok=True)
        (blueprint / "ARCHITECTURE.md").write_text("arch" * 100, encoding="utf-8")
        (target / "COMPASS.md").write_text("compass" * 10, encoding="utf-8")
        (stack / "common.md").write_text("common_full" * 100, encoding="utf-8")
        (stack / "common_compact.md").write_text("common_compact" * 20, encoding="utf-8")
        (stack / "python.md").write_text("python_full" * 80, encoding="utf-8")
        # no python_compact.md — compact falls through to full
        return StepRoots(
            target_dir=target, blueprint_dir=blueprint, stack_dir=stack, rigging_dir=rigging
        )

    def test_assemble_step_no_compact_by_default(self, tmp_path):
        roots = self._roots_with_compacts(tmp_path)
        path = tmp_path / "MANIFEST.md"
        path.write_text(_TWO_STORY_MANIFEST, encoding="utf-8")
        plan = parse_build_plan(path)
        step = assemble_step(plan.by_id()["s1"], roots)
        names = {f.name for f in step.files if f.role == "stack"}
        assert names == {"common.md", "python.md"}
        assert all(not f.compact_substituted for f in step.files)

    def test_assemble_step_compact_when_in_compact_stack(self, tmp_path):
        roots = self._roots_with_compacts(tmp_path)
        path = tmp_path / "MANIFEST.md"
        path.write_text(_TWO_STORY_MANIFEST, encoding="utf-8")
        plan = parse_build_plan(path)
        step = assemble_step(
            plan.by_id()["s1"], roots, compact_stack=frozenset({"common.md"})
        )
        common_file = next(f for f in step.files if "common" in f.name)
        assert common_file.name == "common_compact.md"
        assert common_file.compact_substituted is True
        # python has no compact sibling — falls through to full
        python_file = next(f for f in step.files if "python" in f.name)
        assert python_file.name == "python.md"
        assert python_file.compact_substituted is False

    def test_assemble_steps_first_use_full_subsequent_compact(self, tmp_path):
        roots = self._roots_with_compacts(tmp_path)
        path = tmp_path / "MANIFEST.md"
        path.write_text(_TWO_STORY_MANIFEST, encoding="utf-8")
        plan = parse_build_plan(path)
        steps = assemble_steps(plan, roots)
        assert len(steps) == 2
        # first step: canonical names, no compact substitution
        s1_common = next(f for f in steps[0].files if "common" in f.name)
        assert s1_common.name == "common.md"
        assert s1_common.compact_substituted is False
        # second step: common.md already seen → compact substituted
        s2_common = next(f for f in steps[1].files if "common" in f.name)
        assert s2_common.name == "common_compact.md"
        assert s2_common.compact_substituted is True
        # compact file is smaller → second step has lower total cost
        assert steps[1].total_story_points < steps[0].total_story_points

    def test_compact_fallthrough_when_no_sibling(self, tmp_path):
        roots = self._roots_with_compacts(tmp_path)
        path = tmp_path / "MANIFEST.md"
        path.write_text(_TWO_STORY_MANIFEST, encoding="utf-8")
        plan = parse_build_plan(path)
        steps = assemble_steps(plan, roots)
        # python.md has no compact sibling; second step still uses full python.md
        s2_python = next(f for f in steps[1].files if "python" in f.name)
        assert s2_python.name == "python.md"
        assert s2_python.compact_substituted is False

    def test_compact_applies_to_rules_role(self, tmp_path):
        roots = self._roots_with_compacts(tmp_path)
        # Add a rules file with a compact sibling to the rigging dir
        (roots.rigging_dir / "CLAUDE_RULES.md").write_text("rules" * 100, encoding="utf-8")
        (roots.rigging_dir / "CLAUDE_RULES_compact.md").write_text("rules_compact" * 10, encoding="utf-8")
        manifest = """# MANIFEST: Demo
state: approved

## story 1: Foundation
id: s1
implements: ARCHITECTURE.md
rules: CLAUDE_RULES.md
state: pending

## story 2: Feature
id: s2
implements: ARCHITECTURE.md
rules: CLAUDE_RULES.md
state: pending
"""
        path = tmp_path / "MANIFEST.md"
        path.write_text(manifest, encoding="utf-8")
        plan = parse_build_plan(path)
        steps = assemble_steps(plan, roots)
        # first step: full rules file
        s1_rules = next(f for f in steps[0].files if "CLAUDE_RULES" in f.name)
        assert s1_rules.name == "CLAUDE_RULES.md"
        assert s1_rules.compact_substituted is False
        # second step: compact sibling
        s2_rules = next(f for f in steps[1].files if "CLAUDE_RULES" in f.name)
        assert s2_rules.name == "CLAUDE_RULES_compact.md"
        assert s2_rules.compact_substituted is True

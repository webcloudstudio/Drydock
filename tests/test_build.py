"""Unit tests for build-step assembly and cost."""

from __future__ import annotations

from pathlib import Path

from drydock.build import (
    BAND_DATA,
    BAND_FEATURES,
    BAND_FOUNDATION,
    PROMPT_WARN_TOKENS,
    StepRoots,
    assemble_step,
    assemble_steps,
    band_for,
    band_of,
    group_duplicate_flags,
    group_steps,
    make_step_group,
    render_build_group_prompt_assembly,
    required_auto_compact_sources,
    step_incremental_story_points,
)
from drydock.build_plan import parse_build_plan


class TestBands:
    def test_spike_is_foundation(self):
        assert band_for("spike", ()) == BAND_FOUNDATION

    def test_architecture_is_foundation(self):
        assert band_for("story", ("ARCHITECTURE.md",)) == BAND_FOUNDATION

    def test_database_is_data(self):
        assert band_for("story", ("DATABASE.md",)) == BAND_DATA

    def test_feature_and_default_are_features_band(self):
        assert band_for("story", ("FEATURE-X.md",)) == BAND_FEATURES
        assert band_for("story", ()) == BAND_FEATURES

    def test_architecture_wins_over_database(self):
        assert band_for("story", ("DATABASE.md", "ARCHITECTURE.md")) == BAND_FOUNDATION

    def test_band_of_reads_block_implements(self, tmp_path):
        plan = _plan(tmp_path)
        # core implements ARCHITECTURE.md + DATABASE.md -> Foundation.
        assert band_of(plan.by_id()["core"]) == BAND_FOUNDATION
        assert band_of(plan.by_id()["spike-q"]) == BAND_FOUNDATION


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

    def test_overhead_excludes_implements_and_instructions(self, tmp_path):
        plan = _plan(tmp_path)
        step = assemble_step(plan.by_id()["core"], _roots(tmp_path))
        expected_overhead = sum(f.story_points for f in step.files if f.role != "implements")
        implements_sp = sum(f.story_points for f in step.files if f.role == "implements")
        assert step.overhead_story_points == expected_overhead
        assert step.own_story_points == implements_sp + step.instructions_story_points
        assert step.total_story_points == step.own_story_points + step.overhead_story_points

    def test_over_warn_flag(self, tmp_path):
        plan = _plan(tmp_path)
        roots = _roots(tmp_path)
        # Inflate one implements file past the token warn ceiling. Story points
        # are ceil(bytes / 4), so exceeding PROMPT_WARN_TOKENS needs > 4x bytes.
        (roots.blueprint_dir / "DATABASE.md").write_text(
            "x" * (PROMPT_WARN_TOKENS * 4 + 40), encoding="utf-8"
        )
        step = assemble_step(plan.by_id()["core"], roots)
        assert step.over_warn is True

    def test_under_warn_default(self, tmp_path):
        plan = _plan(tmp_path)
        step = assemble_step(plan.by_id()["core"], _roots(tmp_path))
        assert step.over_warn is False

    def test_feature_steps_receive_architecture_and_database_compacts(self, tmp_path):
        manifest = """# MANIFEST: Demo
state: approved

## story 1: Feature
id: feature
implements: FEATURE-Status.md
context: README.md
state: pending
"""
        path = tmp_path / "MANIFEST.md"
        path.write_text(manifest, encoding="utf-8")
        plan = parse_build_plan(path)
        roots = _roots(tmp_path)
        (roots.blueprint_dir / "FEATURE-Status.md").write_text("feature\n", encoding="utf-8")
        (roots.blueprint_dir / "ARCHITECTURE_compact.md").write_text(
            "arch-compact\n", encoding="utf-8"
        )
        (roots.blueprint_dir / "DATABASE_compact.md").write_text("db-compact\n", encoding="utf-8")

        step = assemble_step(plan.by_id()["feature"], roots)
        context_names = {f.name for f in step.files if f.role == "context"}
        assert context_names == {"README.md", "ARCHITECTURE_compact.md", "DATABASE_compact.md"}

    def test_screen_steps_do_not_receive_managed_compact_context(self, tmp_path):
        manifest = """# MANIFEST: Demo
state: approved

## story 1: Screen
id: screen
implements: SCREEN-Home.md
context: README.md, ARCHITECTURE.md, DATABASE.md
state: pending
"""
        path = tmp_path / "MANIFEST.md"
        path.write_text(manifest, encoding="utf-8")
        plan = parse_build_plan(path)
        roots = _roots(tmp_path)
        (roots.blueprint_dir / "SCREEN-Home.md").write_text("screen\n", encoding="utf-8")

        step = assemble_step(plan.by_id()["screen"], roots)
        context_names = {f.name for f in step.files if f.role == "context"}
        assert context_names == {"README.md"}


class TestAssembleSteps:
    def test_group_prompt_suppresses_compact_when_full_source_is_present(self, tmp_path):
        manifest = """# MANIFEST: Demo
state: approved

## feature 1: Foundation
id: foundation
state: pending

## story 2: Architecture
id: architecture
parent: foundation
implements: ARCHITECTURE.md
state: pending

## story 3: Consumer
id: consumer
parent: foundation
implements: FEATURE-Consumer.md
context: ARCHITECTURE_compact.md
state: pending
"""
        path = tmp_path / "MANIFEST.md"
        path.write_text(manifest, encoding="utf-8")
        roots = _roots(tmp_path)
        (roots.blueprint_dir / "ARCHITECTURE_compact.md").write_text("compact", encoding="utf-8")
        (roots.blueprint_dir / "FEATURE-Consumer.md").write_text("feature", encoding="utf-8")
        plan = parse_build_plan(path)
        steps = tuple(
            assemble_step(plan.by_id()[block_id], roots)
            for block_id in ("architecture", "consumer")
        )
        prompt = render_build_group_prompt_assembly(
            "Build.",
            make_step_group(feature_id="foundation", name="Foundation", steps=steps),
            target="Demo",
            build_dir=tmp_path / "build",
            today="2026-07-20",
        )
        assert 'filename="ARCHITECTURE.md"' in prompt.rendered_text
        assert 'filename="ARCHITECTURE_compact.md"' not in prompt.rendered_text

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

    def test_group_cost_counts_duplicate_files_once(self, tmp_path):
        plan = _plan(tmp_path)
        steps = assemble_steps(plan, _roots(tmp_path))
        groups = group_steps(plan, steps)
        summed = sum(s.total_story_points for s in steps)
        duplicate_points = 150  # COMPASS.md 50 SP + ARCHITECTURE.md 100 SP.
        assert groups[0].summed_story_points == summed
        assert groups[0].story_point_savings == duplicate_points
        assert groups[0].total_story_points == summed - duplicate_points

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
        step = assemble_step(plan.by_id()["s1"], roots, compact_stack=frozenset({"common.md"}))
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
        (roots.rigging_dir / "CLAUDE_RULES_compact.md").write_text(
            "rules_compact" * 10, encoding="utf-8"
        )
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


_CONTEXT_COMPACT_MANIFEST = """# MANIFEST: Demo
state: approved

## story 1: One
id: s1
implements: FEATURE-A.md
context: FEATURE-B.md, FEATURE-C.md
state: pending

## story 2: Two
id: s2
implements: FEATURE-B.md
context: FEATURE-B.md, FEATURE-B_compact.md, FEATURE-A.md
state: pending

## story 3: Three
id: s3
implements: FEATURE-C.md
context: FEATURE-B_compact.md, README.md
state: pending
"""


class TestContextCompactSubstitution:
    def _roots(self, tmp_path: Path) -> StepRoots:
        target = tmp_path / "target"
        blueprint = target / "blueprint"
        stack = tmp_path / "rigging" / "stack"
        rigging = tmp_path / "rigging"
        for d in (blueprint, stack, rigging):
            d.mkdir(parents=True, exist_ok=True)
        (target / "COMPASS.md").write_text("compass" * 10, encoding="utf-8")
        (target / "README.md").write_text("readme" * 10, encoding="utf-8")
        (blueprint / "FEATURE-A.md").write_text("feature-a" * 100, encoding="utf-8")
        (blueprint / "FEATURE-B.md").write_text("feature-b" * 100, encoding="utf-8")
        (blueprint / "FEATURE-B_compact.md").write_text("b-compact" * 10, encoding="utf-8")
        (blueprint / "FEATURE-C.md").write_text("feature-c" * 100, encoding="utf-8")
        # no FEATURE-C_compact.md — context falls through to the full file
        return StepRoots(
            target_dir=target, blueprint_dir=blueprint, stack_dir=stack, rigging_dir=rigging
        )

    def _plan(self, tmp_path: Path):
        path = tmp_path / "MANIFEST.md"
        path.write_text(_CONTEXT_COMPACT_MANIFEST, encoding="utf-8")
        return parse_build_plan(path)

    def test_context_prefers_compact_sibling_without_compact_stack(self, tmp_path):
        step = assemble_step(self._plan(tmp_path).by_id()["s1"], self._roots(tmp_path))
        b_file = next(f for f in step.files if f.role == "context" and "FEATURE-B" in f.name)
        assert b_file.name == "FEATURE-B_compact.md"
        assert b_file.compact_substituted is True

    def test_context_falls_through_to_full_file_when_no_sibling(self, tmp_path):
        step = assemble_step(self._plan(tmp_path).by_id()["s1"], self._roots(tmp_path))
        c_file = next(f for f in step.files if f.role == "context" and "FEATURE-C" in f.name)
        assert c_file.name == "FEATURE-C.md"
        assert c_file.compact_substituted is False

    def test_context_entry_dropped_when_source_is_in_implements(self, tmp_path):
        # s2 implements FEATURE-B.md; both FEATURE-B.md and FEATURE-B_compact.md
        # context entries collapse away, and the duplicate pair dedups to nothing.
        step = assemble_step(self._plan(tmp_path).by_id()["s2"], self._roots(tmp_path))
        context_names = [f.name for f in step.files if f.role == "context"]
        assert context_names == ["FEATURE-A.md"]
        implements_names = [f.name for f in step.files if f.role == "implements"]
        assert implements_names == ["FEATURE-B.md"]

    def test_authored_compact_context_name_resolves_compact(self, tmp_path):
        step = assemble_step(self._plan(tmp_path).by_id()["s3"], self._roots(tmp_path))
        b_file = next(f for f in step.files if f.role == "context" and "FEATURE-B" in f.name)
        assert b_file.name == "FEATURE-B_compact.md"
        # target-dir context files resolve normally
        readme = next(f for f in step.files if f.role == "context" and f.name == "README.md")
        assert readme.missing is False

    def test_required_auto_compact_sources_include_context_specs(self, tmp_path):
        plan = self._plan(tmp_path)
        roots = self._roots(tmp_path)
        s1 = required_auto_compact_sources(plan.by_id()["s1"], roots.blueprint_dir)
        assert [p.name for p in s1] == ["FEATURE-B.md", "FEATURE-C.md"]
        # s2: FEATURE-B is in implements → excluded; FEATURE-A remains
        s2 = required_auto_compact_sources(plan.by_id()["s2"], roots.blueprint_dir)
        assert [p.name for p in s2] == ["FEATURE-A.md"]
        # s3: README.md is not a Blueprint file → excluded
        s3 = required_auto_compact_sources(plan.by_id()["s3"], roots.blueprint_dir)
        assert [p.name for p in s3] == ["FEATURE-B.md"]

    def test_group_duplicate_flags_first_seen_wins(self, tmp_path):
        plan = self._plan(tmp_path)
        roots = self._roots(tmp_path)
        # s1 carries FEATURE-B_compact.md (context of s1); s3 names it again.
        steps = (
            assemble_step(plan.by_id()["s1"], roots),
            assemble_step(plan.by_id()["s3"], roots),
        )
        flags = group_duplicate_flags(steps)
        s1_flags = dict(zip([f.name for f in steps[0].files], flags[0], strict=True))
        s3_flags = dict(zip([f.name for f in steps[1].files], flags[1], strict=True))
        # first occurrence goes through
        assert s1_flags["FEATURE-B_compact.md"] is False
        # second occurrence is a duplicate; COMPASS.md repeats in every step
        assert s3_flags["FEATURE-B_compact.md"] is True
        assert s3_flags["COMPASS.md"] is True
        # s3 implements FEATURE-C.md — s1 already carried the full FEATURE-C.md
        # as context, which collapses to the same canonical key
        assert s3_flags["FEATURE-C.md"] is True
        # missing files are never duplicates
        assert all(not flag for f, flag in zip(steps[1].files, flags[1], strict=True) if f.missing)

    def test_step_incremental_story_points_excludes_duplicates(self, tmp_path):
        plan = self._plan(tmp_path)
        roots = self._roots(tmp_path)
        steps = (
            assemble_step(plan.by_id()["s1"], roots),
            assemble_step(plan.by_id()["s3"], roots),
        )
        flags = group_duplicate_flags(steps)
        # first step: nothing seen before it, incremental == total
        assert step_incremental_story_points(steps[0], flags[0]) == steps[0].total_story_points
        # later step: duplicates contribute zero
        duplicate_sp = sum(
            f.story_points for f, dup in zip(steps[1].files, flags[1], strict=True) if dup
        )
        assert duplicate_sp > 0
        expected = steps[1].total_story_points - duplicate_sp
        assert step_incremental_story_points(steps[1], flags[1]) == expected
        # incremental sums reconcile with the group combined cost
        combined = sum(
            step_incremental_story_points(step, step_flags)
            for step, step_flags in zip(steps, flags, strict=True)
        )
        from drydock.build import make_step_group

        group = make_step_group(feature_id="f", name="F", steps=steps)
        assert combined == group.total_story_points

    def test_required_auto_compact_sources_canonicalize_architecture_context(self, tmp_path):
        manifest = """# MANIFEST: Demo
state: approved

## spike 1: Question
id: spike-q
context: ARCHITECTURE.md
state: pending
"""
        path = tmp_path / "MANIFEST.md"
        path.write_text(manifest, encoding="utf-8")
        plan = parse_build_plan(path)
        roots = self._roots(tmp_path)
        (roots.blueprint_dir / "ARCHITECTURE.md").write_text("arch" * 50, encoding="utf-8")
        sources = required_auto_compact_sources(plan.by_id()["spike-q"], roots.blueprint_dir)
        assert [p.name for p in sources] == ["ARCHITECTURE.md"]


_COMPASS_CONTEXT_MANIFEST = """# MANIFEST: Demo
state: approved

## story 1: One
id: s1
implements: FEATURE-A.md
context: COMPASS.md, FEATURE-B.md
state: pending

## spike 1: Question
id: spike-q
context: COMPASS.md, PLAN_COMPASS.md, ANALYZE_COMPASS.md
state: pending
"""


class TestCompassNeverContextOrCompacted:
    """COMPASS files are injected whole by the compass role and are never compacted."""

    def _roots(self, tmp_path: Path) -> StepRoots:
        target = tmp_path / "target"
        blueprint = target / "blueprint"
        stack = tmp_path / "rigging" / "stack"
        rigging = tmp_path / "rigging"
        for d in (blueprint, stack, rigging):
            d.mkdir(parents=True, exist_ok=True)
        for name in ("COMPASS.md", "PLAN_COMPASS.md", "ANALYZE_COMPASS.md"):
            (target / name).write_text("compass" * 50, encoding="utf-8")
        (blueprint / "COMPASS_compact.md").write_text("stale derivative", encoding="utf-8")
        (blueprint / "FEATURE-A.md").write_text("feature-a" * 100, encoding="utf-8")
        (blueprint / "FEATURE-B.md").write_text("feature-b" * 100, encoding="utf-8")
        return StepRoots(
            target_dir=target, blueprint_dir=blueprint, stack_dir=stack, rigging_dir=rigging
        )

    def _plan(self, tmp_path: Path):
        path = tmp_path / "MANIFEST.md"
        path.write_text(_COMPASS_CONTEXT_MANIFEST, encoding="utf-8")
        return parse_build_plan(path)

    def test_compass_context_entry_is_dropped_not_duplicated(self, tmp_path):
        step = assemble_step(self._plan(tmp_path).by_id()["s1"], self._roots(tmp_path))
        assert [f.name for f in step.files if f.role == "context"] == ["FEATURE-B.md"]
        assert [f.name for f in step.files if f.role == "compass"] == ["COMPASS.md"]

    def test_compass_is_never_a_compaction_source(self, tmp_path):
        plan = self._plan(tmp_path)
        roots = self._roots(tmp_path)
        for block_id in ("s1", "spike-q"):
            sources = required_auto_compact_sources(plan.by_id()[block_id], roots.blueprint_dir)
            assert not any("COMPASS" in p.name for p in sources)

    def test_compass_never_substitutes_a_compact_sibling(self, tmp_path):
        roots = self._roots(tmp_path)
        step = assemble_step(self._plan(tmp_path).by_id()["s1"], roots)
        compass = next(f for f in step.files if f.role == "compass")
        assert compass.name == "COMPASS.md"
        assert compass.compact_substituted is False

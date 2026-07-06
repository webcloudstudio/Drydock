"""Tests for the QuarterDeck ``compass`` type — the unified Build Compass: the live
MANIFEST.md work graph with feature groups, assembled per-step prompt cost, folded
acceptance checks, the context warn flag, per-step lifecycle state chips (buildable
now / review / done / failed with reason), a rollup header, and editing controls."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


def _load_quarterdeck():
    path = Path(__file__).parents[1] / "QuarterDeck" / "app.py"
    spec = importlib.util.spec_from_file_location("quarterdeck_compass_test", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


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
context: missing-ctx.md
stack: common.md
instructions: |
  Build the core.
state: pending

## ac 3: Core Works
id: ac-core
parent: core
kind: smoke
check: true
state: pending
"""

_MANIFEST_TWO_STORIES = _MANIFEST.replace(
    """## ac 3: Core Works""",
    """## story 4: Extra
id: extra
parent: feat-foundation
implements: ARCHITECTURE.md
stack: common.md
instructions: |
  Build the extra.
state: pending

## ac 3: Core Works""",
)

_ITEM = {
    "id": "build_compass",
    "type": "compass",
    "path": "../MANIFEST.md",
    "label": "MANIFEST",
}


def _setup(quarterdeck, tmp_path, monkeypatch, *, manifest=_MANIFEST):
    target = tmp_path / "target"
    blueprint = target / "blueprint"
    stack = tmp_path / "rigging" / "stack"
    rigging = tmp_path / "rigging"
    for d in (blueprint, stack, rigging):
        d.mkdir(parents=True, exist_ok=True)
    (target / "MANIFEST.md").write_text(manifest, encoding="utf-8")
    (target / "COMPASS.md").write_bytes(b"c" * 200)
    (blueprint / "ARCHITECTURE.md").write_bytes(b"a" * 4000)  # 1000 SP
    (blueprint / "DATABASE.md").write_bytes(b"b" * 400)  # 100 SP
    (stack / "common.md").write_bytes(b"e" * 40)

    from drydock.build import StepRoots

    monkeypatch.setattr(quarterdeck, "PROJECT_ROOT", target)
    monkeypatch.setattr(
        quarterdeck,
        "_step_roots",
        lambda: StepRoots(
            target_dir=target, blueprint_dir=blueprint, stack_dir=stack, rigging_dir=rigging
        ),
    )
    return target


class TestRender:
    def test_shows_feature_group_and_step(self, tmp_path, monkeypatch):
        quarterdeck = _load_quarterdeck()
        _setup(quarterdeck, tmp_path, monkeypatch)
        out = quarterdeck.render_compass(_ITEM)
        assert "# Foundation" in out
        assert "Core" in out
        assert "STORY" in out
        assert "cmp-stype-story" in out
        assert "STEP " not in out

    def test_step_cost_includes_full_stack(self, tmp_path, monkeypatch):
        quarterdeck = _load_quarterdeck()
        _setup(quarterdeck, tmp_path, monkeypatch)
        out = quarterdeck.render_compass(_ITEM)
        # compass 200 + arch 4000 + db 400 + common 40 = 4640 bytes -> 1160 SP,
        # plus instructions text. Cost must exceed the bare spec-file total (1100).
        assert "Total SP " in out
        import re

        total = int(re.search(r"Total SP ([\d,]+)", out).group(1).replace(",", ""))
        assert total > 1100

    def test_missing_context_file_flagged(self, tmp_path, monkeypatch):
        quarterdeck = _load_quarterdeck()
        _setup(quarterdeck, tmp_path, monkeypatch)
        out = quarterdeck.render_compass(_ITEM)
        assert "missing-ctx.md" in out
        assert "missing" in out

    def test_acceptance_rendered_as_definition_of_done(self, tmp_path, monkeypatch):
        quarterdeck = _load_quarterdeck()
        _setup(quarterdeck, tmp_path, monkeypatch)
        out = quarterdeck.render_compass(_ITEM)
        assert "definition of done" in out
        assert "Core Works" in out
        # The ac is folded under its step, not rendered as its own step.
        assert "STEP " not in out

    def test_over_warn_flagged(self, tmp_path, monkeypatch):
        quarterdeck = _load_quarterdeck()
        _setup(quarterdeck, tmp_path, monkeypatch)
        from drydock.build import PROMPT_WARN_TOKENS

        big = quarterdeck._step_roots().blueprint_dir / "ARCHITECTURE.md"
        # Story points are ceil(bytes / 4); exceed the token ceiling with > 4x bytes.
        big.write_bytes(b"x" * (PROMPT_WARN_TOKENS * 4 + 40))
        out = quarterdeck.render_compass(_ITEM)
        assert "over" in out and "SP" in out

    def test_no_manifest_prompts_plan(self, tmp_path, monkeypatch):
        quarterdeck = _load_quarterdeck()
        monkeypatch.setattr(quarterdeck, "PROJECT_ROOT", tmp_path / "empty")
        out = quarterdeck.render_compass(_ITEM)
        assert "drydock plan" in out

    def test_move_controls_always_available(self, tmp_path, monkeypatch):
        # Reorder is not gated by plan state; running the next step is the approval.
        quarterdeck = _load_quarterdeck()
        _setup(quarterdeck, tmp_path, monkeypatch)
        out = quarterdeck.render_compass(_ITEM)
        assert "compassMove(" in out
        assert "compassRegroup(" in out
        assert "move_feature" in out
        assert "reorder is locked" not in out

    def test_group_rollup_labelled_combined(self, tmp_path, monkeypatch):
        # The group figure is a rollup of per-step assembled cost (shared context
        # re-injected per step), so it is not the arithmetic sum of its stories.
        quarterdeck = _load_quarterdeck()
        _setup(quarterdeck, tmp_path, monkeypatch)
        out = quarterdeck.render_compass(_ITEM)
        assert "Combined Story Points =" in out

    def test_story_has_no_up_down_reorder(self, tmp_path, monkeypatch):
        # Order within a group is meaningless; a story keeps only its change-group
        # control. move_step (per-story up/down) is gone; move_feature remains.
        quarterdeck = _load_quarterdeck()
        _setup(quarterdeck, tmp_path, monkeypatch)
        out = quarterdeck.render_compass(_ITEM)
        assert "move_step" not in out
        assert "move_feature" in out

    def test_toolbar_has_new_group_button(self, tmp_path, monkeypatch):
        quarterdeck = _load_quarterdeck()
        _setup(quarterdeck, tmp_path, monkeypatch)
        out = quarterdeck.render_compass(_ITEM)
        assert "compassAddFeature(" in out
        assert "New group" in out

    def test_story_and_feature_have_rename_buttons(self, tmp_path, monkeypatch):
        quarterdeck = _load_quarterdeck()
        _setup(quarterdeck, tmp_path, monkeypatch)
        out = quarterdeck.render_compass(_ITEM)
        assert "compassRename(" in out

    def test_single_story_group_has_no_split(self, tmp_path, monkeypatch):
        # The one-story Foundation group cannot be split.
        quarterdeck = _load_quarterdeck()
        _setup(quarterdeck, tmp_path, monkeypatch)
        out = quarterdeck.render_compass(_ITEM)
        assert "compassSplit(" not in out
        assert "compassSplitStep(" not in out

    def test_multi_story_group_shows_split_group_and_split_step(self, tmp_path, monkeypatch):
        quarterdeck = _load_quarterdeck()
        _setup(quarterdeck, tmp_path, monkeypatch, manifest=_MANIFEST_TWO_STORIES)
        out = quarterdeck.render_compass(_ITEM)
        assert "compassSplit(" in out
        assert "compassSplitStep(" in out
        assert "cmp-split-step" in out


_MANIFEST_VERIFIED = _MANIFEST.replace(
    """id: core
parent: feat-foundation
implements: ARCHITECTURE.md, DATABASE.md
context: missing-ctx.md
stack: common.md
instructions: |
  Build the core.
state: pending""",
    """id: core
parent: feat-foundation
implements: ARCHITECTURE.md, DATABASE.md
context: missing-ctx.md
stack: common.md
instructions: |
  Build the core.
state: closed/verified""",
)


_MANIFEST_FAILED = _MANIFEST.replace(
    """  Build the core.
state: pending""",
    """  Build the core.
state: closed/failed
finding: acceptance failed ac-core: assertion returned non-zero""",
)


# `extra` depends on the still-unbuilt `core`, so `extra` is Blocked while
# `core` is Ready To Build. Both share one feature group.
_MANIFEST_BLOCKED = _MANIFEST_TWO_STORIES.replace(
    """## story 4: Extra
id: extra
parent: feat-foundation""",
    """## story 4: Extra
id: extra
parent: feat-foundation
depends: core""",
)


class TestState:
    def test_header_rollup_present(self, tmp_path, monkeypatch):
        quarterdeck = _load_quarterdeck()
        _setup(quarterdeck, tmp_path, monkeypatch)
        out = quarterdeck.render_compass(_ITEM)
        # The header rolls up one count per story state plus total cost.
        assert "1 group</span>" in out
        assert "1 story</span>" in out
        assert "built</span>" in out
        assert "ready to build</span>" in out
        assert "blocked</span>" in out
        assert "failed</span>" in out
        assert "Total SP " in out
        assert "Total Savings " in out
        assert "Buildable now:" in out
        assert "steps</span>" not in out

    def test_toolbar_omits_step_count(self, tmp_path, monkeypatch):
        quarterdeck = _load_quarterdeck()
        _setup(quarterdeck, tmp_path, monkeypatch, manifest=_MANIFEST_TWO_STORIES)
        out = quarterdeck.render_compass(_ITEM)
        toolbar = out.split("<div class='cmp-toolbar'>", 1)[1].split("</div>", 1)[0]
        assert "steps" not in toolbar
        assert "Normalize order" in toolbar
        assert "New group" in toolbar

    def test_buildable_step_shows_chip(self, tmp_path, monkeypatch):
        # `core` is pending with no unmet depends, so it is ready to build.
        quarterdeck = _load_quarterdeck()
        _setup(quarterdeck, tmp_path, monkeypatch)
        out = quarterdeck.render_compass(_ITEM)
        assert "cmp-buildable" in out
        assert "Ready To Build" in out

    def test_step_shows_story_points_with_overhead(self, tmp_path, monkeypatch):
        quarterdeck = _load_quarterdeck()
        _setup(quarterdeck, tmp_path, monkeypatch)
        out = quarterdeck.render_compass(_ITEM)
        assert "Story Points =" in out
        assert "(overhead " in out

    def test_verified_step_shows_built_and_group_check(self, tmp_path, monkeypatch):
        quarterdeck = _load_quarterdeck()
        _setup(quarterdeck, tmp_path, monkeypatch, manifest=_MANIFEST_VERIFIED)
        out = quarterdeck.render_compass(_ITEM)
        assert "bp-done" in out  # Built chip on the verified step
        assert "Built" in out
        assert "bp-check" in out  # loud green check on the built step and group
        assert "Combined Story Points =" in out
        assert "move_step" not in out

    def test_group_shows_story_point_savings(self, tmp_path, monkeypatch):
        quarterdeck = _load_quarterdeck()
        _setup(quarterdeck, tmp_path, monkeypatch, manifest=_MANIFEST_TWO_STORIES)
        out = quarterdeck.render_compass(_ITEM)
        assert "Combined Story Points =" in out
        assert "Story Point Savings = 1,060" in out

    def test_failed_step_shows_failed_chip_and_reason(self, tmp_path, monkeypatch):
        quarterdeck = _load_quarterdeck()
        _setup(quarterdeck, tmp_path, monkeypatch, manifest=_MANIFEST_FAILED)
        out = quarterdeck.render_compass(_ITEM)
        assert "bp-failed" in out
        assert "cmp-fail-reason" in out
        assert "assertion returned non-zero" in out
        assert "cmp-fail-action" in out
        assert "rerun drydock build with --force to override errors" in out
        # A failed frontier blocks the graph: nothing is buildable.
        assert "blocked by" in out

    def test_blocked_step_names_its_blocker_and_colors_group(self, tmp_path, monkeypatch):
        quarterdeck = _load_quarterdeck()
        _setup(quarterdeck, tmp_path, monkeypatch, manifest=_MANIFEST_BLOCKED)
        out = quarterdeck.render_compass(_ITEM)
        # `extra` is Blocked; `core` is Ready To Build.
        assert "bp-blocked" in out
        assert "cmp-step-blocked" in out
        assert "Ready To Build" in out
        # The blocker is named as a story.
        assert "Blocked by story <strong>Core</strong>" in out
        # The group takes its worst story's color (blocked) and header label.
        assert "cmp-group-blocked" in out
        # Header rolls the blocked story into the blocked count.
        assert "blocked</span>" in out

    def test_group_title_is_click_to_rename(self, tmp_path, monkeypatch):
        quarterdeck = _load_quarterdeck()
        _setup(quarterdeck, tmp_path, monkeypatch)
        out = quarterdeck.render_compass(_ITEM)
        assert "cmp-gname-edit" in out
        assert "compassRename(" in out

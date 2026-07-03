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
    "label": "Build Compass",
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
        assert "story" in out
        assert "STEP " not in out

    def test_step_cost_includes_full_stack(self, tmp_path, monkeypatch):
        quarterdeck = _load_quarterdeck()
        _setup(quarterdeck, tmp_path, monkeypatch)
        out = quarterdeck.render_compass(_ITEM)
        # compass 200 + arch 4000 + db 400 + common 40 = 4640 bytes -> 1160 SP,
        # plus instructions text. Cost must exceed the bare spec-file total (1100).
        assert "Total SP " in out
        import re

        total = int(re.search(r"Total SP (\d+)", out).group(1))
        assert total > 1100

    def test_missing_context_file_flagged(self, tmp_path, monkeypatch):
        quarterdeck = _load_quarterdeck()
        _setup(quarterdeck, tmp_path, monkeypatch)
        out = quarterdeck.render_compass(_ITEM)
        assert "missing-ctx.md" in out
        assert "missing" in out

    def test_acceptance_folded_as_post_action(self, tmp_path, monkeypatch):
        quarterdeck = _load_quarterdeck()
        _setup(quarterdeck, tmp_path, monkeypatch)
        out = quarterdeck.render_compass(_ITEM)
        assert "post: Core Works" in out
        # The ac is folded, not rendered as its own step.
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

    def test_multi_story_group_shows_split(self, tmp_path, monkeypatch):
        quarterdeck = _load_quarterdeck()
        _setup(quarterdeck, tmp_path, monkeypatch, manifest=_MANIFEST_TWO_STORIES)
        out = quarterdeck.render_compass(_ITEM)
        assert "compassSplit(" in out


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


class TestState:
    def test_header_rollup_present(self, tmp_path, monkeypatch):
        quarterdeck = _load_quarterdeck()
        _setup(quarterdeck, tmp_path, monkeypatch)
        out = quarterdeck.render_compass(_ITEM)
        assert "Build Compass — " in out
        assert "Plan:" in out
        assert "Buildable now:" in out
        assert "steps ·" in out and "verified" in out

    def test_buildable_step_shows_chip(self, tmp_path, monkeypatch):
        # `core` is pending with no unmet depends, so it is buildable now.
        quarterdeck = _load_quarterdeck()
        _setup(quarterdeck, tmp_path, monkeypatch)
        out = quarterdeck.render_compass(_ITEM)
        assert "cmp-buildable" in out
        assert "buildable now" in out

    def test_verified_step_shows_done_and_group_check(self, tmp_path, monkeypatch):
        quarterdeck = _load_quarterdeck()
        _setup(quarterdeck, tmp_path, monkeypatch, manifest=_MANIFEST_VERIFIED)
        out = quarterdeck.render_compass(_ITEM)
        assert "bp-done" in out  # ✓ done chip on the verified step
        assert "bp-check" in out  # loud green check on the fully-verified group
        assert "Combined Story Points =" in out
        assert "move_step" not in out

    def test_failed_step_shows_failed_chip_and_reason(self, tmp_path, monkeypatch):
        quarterdeck = _load_quarterdeck()
        _setup(quarterdeck, tmp_path, monkeypatch, manifest=_MANIFEST_FAILED)
        out = quarterdeck.render_compass(_ITEM)
        assert "bp-failed" in out
        assert "cmp-fail-reason" in out
        assert "assertion returned non-zero" in out
        # A failed frontier blocks the graph: nothing is buildable.
        assert "blocked by" in out

    def test_group_title_is_click_to_rename(self, tmp_path, monkeypatch):
        quarterdeck = _load_quarterdeck()
        _setup(quarterdeck, tmp_path, monkeypatch)
        out = quarterdeck.render_compass(_ITEM)
        assert "cmp-gname-edit" in out
        assert "compassRename(" in out

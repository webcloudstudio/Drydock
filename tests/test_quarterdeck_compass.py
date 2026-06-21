"""Tests for the QuarterDeck ``compass`` type — the read-only MANIFEST.md build
view: feature groups, assembled per-step prompt cost, folded acceptance checks,
and the context warn flag."""

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
        assert "STEP 1" in out
        assert "Core" in out
        assert "story" in out

    def test_step_cost_includes_full_stack(self, tmp_path, monkeypatch):
        quarterdeck = _load_quarterdeck()
        _setup(quarterdeck, tmp_path, monkeypatch)
        out = quarterdeck.render_compass(_ITEM)
        # compass 200 + arch 4000 + db 400 + common 40 = 4640 bytes -> 1160 SP,
        # plus instructions text. Cost must exceed the bare spec-file total (1100).
        assert "Total Story Points = <strong>" in out
        import re

        total = int(re.search(r"Total Story Points = <strong>(\d+)</strong>", out).group(1))
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
        assert "STEP 2" not in out

    def test_over_warn_flagged(self, tmp_path, monkeypatch):
        quarterdeck = _load_quarterdeck()
        _setup(quarterdeck, tmp_path, monkeypatch)
        from drydock.build import PROMPT_WARN_KB

        big = quarterdeck._step_roots().blueprint_dir / "ARCHITECTURE.md"
        big.write_bytes(b"x" * (PROMPT_WARN_KB * 1024 + 10))
        out = quarterdeck.render_compass(_ITEM)
        assert "over" in out and "KB" in out

    def test_no_manifest_prompts_plan_create(self, tmp_path, monkeypatch):
        quarterdeck = _load_quarterdeck()
        monkeypatch.setattr(quarterdeck, "PROJECT_ROOT", tmp_path / "empty")
        out = quarterdeck.render_compass(_ITEM)
        assert "drydock plan create" in out

    def test_approved_plan_locks_reorder(self, tmp_path, monkeypatch):
        quarterdeck = _load_quarterdeck()
        _setup(quarterdeck, tmp_path, monkeypatch)
        out = quarterdeck.render_compass(_ITEM)
        assert "reorder is locked" in out
        assert "compassMove(" not in out

    def test_draft_plan_shows_move_controls(self, tmp_path, monkeypatch):
        quarterdeck = _load_quarterdeck()
        _setup(
            quarterdeck,
            tmp_path,
            monkeypatch,
            manifest=_MANIFEST.replace("state: approved", "state: draft", 1),
        )
        out = quarterdeck.render_compass(_ITEM)
        assert "compassMove(" in out
        assert "compassRegroup(" in out
        assert "move_feature" in out

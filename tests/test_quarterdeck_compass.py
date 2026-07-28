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

_CURRENT_MANIFEST = """# MANIFEST: Demo
state: approved

## feature 1: Program Surface
id: feature-program
summary: Establish the executable filter.
state: pending

## story 1: Program Interface
id: prog-001
parent: feature-program
summary: Implement the stdin-to-stdout filter.
implements: FEATURE-Program-Interface.md
covers: PROG-001
accepts: st-003
stack: common.md
instructions: Implement convert(md) and the stdin/stdout entry point.
state: pending
evidence: evidence/prog-001.md
scope: target
"""

_CURRENT_BLUEPRINT = """# FEATURE: Program Interface

## Programmatic Acceptance

### filter-function
The conversion function returns CommonMark HTML.
```python
from mycommonmark import convert
assert convert("hello") == "<p>hello</p>\\n"
```

### subprocess-filter
```python
assert run_filter("hello") == "<p>hello</p>\\n"
```

## User Acceptance

- Commander confirms the command behaves as a Unix filter.

## Guardrails

- Standard error remains empty on success.

## Open Questions

- Confirm whether Windows newline normalization is required.
"""

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
        assert "Foundation" in out
        assert "Core" in out
        assert "STORY" in out
        assert "BLOCK" in out
        assert "cmp-stype-story" in out
        assert "cmp-stype-block" in out
        assert "STEP " not in out

    def test_step_cost_includes_full_stack(self, tmp_path, monkeypatch):
        quarterdeck = _load_quarterdeck()
        _setup(quarterdeck, tmp_path, monkeypatch)
        out = quarterdeck.render_compass(_ITEM)
        # compass 200 + arch 4000 + db 400 + common 40 = 4640 bytes -> 1160 SP,
        # plus instructions text. Cost must exceed the bare spec-file total (1100).
        assert "Used SP " in out
        import re

        total = int(re.search(r"Used SP ([\d,]+)", out).group(1).replace(",", ""))
        assert total > 1100

    def test_step_cost_includes_non_markdown_tokens(self, tmp_path, monkeypatch):
        import re

        quarterdeck = _load_quarterdeck()
        manifest = _MANIFEST.replace("missing-ctx.md", "examples.txt")
        target = _setup(quarterdeck, tmp_path, monkeypatch, manifest=manifest)

        missing_out = quarterdeck.render_compass(_ITEM)
        missing_total = int(re.search(r"Used SP ([\d,]+)", missing_out).group(1).replace(",", ""))

        (target / "blueprint" / "examples.txt").write_bytes(b"x" * 4000)
        present_out = quarterdeck.render_compass(_ITEM)
        present_total = int(re.search(r"Used SP ([\d,]+)", present_out).group(1).replace(",", ""))

        assert present_total == missing_total + 1000
        assert "examples.txt" in present_out
        assert "<span class='cmp-fsp'>SP 1,000</span>" in present_out

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

    def test_current_blueprint_acceptance_and_plan_details_are_rendered(
        self, tmp_path, monkeypatch
    ):
        quarterdeck = _load_quarterdeck()
        target = _setup(quarterdeck, tmp_path, monkeypatch, manifest=_CURRENT_MANIFEST)
        (target / "blueprint" / "FEATURE-Program-Interface.md").write_text(
            _CURRENT_BLUEPRINT,
            encoding="utf-8",
        )

        out = quarterdeck.render_compass(_ITEM)

        # Preserve the existing card, controls, cost, and stack presentation.
        assert "cmp-stype-story" in out
        assert "compassRegroup(" in out
        assert "Story Points =" in out
        assert "stack breakdown" in out

        # Current plans carry routine acceptance in the implemented Blueprint,
        # without child Manifest ac blocks.
        assert "definition of done — 2 programmatic checks" in out
        assert "filter-function" in out
        assert "subprocess-filter" in out
        assert "The conversion function returns CommonMark HTML." in out
        assert "executable assertion" in out
        assert "assert convert(&quot;hello&quot;)" in out
        assert "UNVERIFIED" in out
        assert "orchestration gate" not in out

        # Human review and Manifest traceability remain collapsed, read-only views.
        assert "<summary>user acceptance</summary>" in out
        assert "Commander confirms the command behaves as a Unix filter." in out
        assert "plan and traceability" in out
        assert "PROG-001" in out
        assert "st-003" in out
        assert "evidence/prog-001.md" in out
        assert "Standard error remains empty on success." in out
        assert "Confirm whether Windows newline normalization is required." in out

        assert out.index("definition of done") < out.index("user acceptance")
        assert out.index("user acceptance") < out.index("plan and traceability")
        assert out.index("plan and traceability") < out.index("stack breakdown")

    def test_verified_story_labels_blueprint_acceptance_passed(self, tmp_path, monkeypatch):
        quarterdeck = _load_quarterdeck()
        target = _setup(
            quarterdeck,
            tmp_path,
            monkeypatch,
            manifest=_CURRENT_MANIFEST.replace(
                "state: pending\nevidence:",
                "state: closed/verified\nevidence:",
            ),
        )
        (target / "blueprint" / "FEATURE-Program-Interface.md").write_text(
            _CURRENT_BLUEPRINT,
            encoding="utf-8",
        )

        out = quarterdeck.render_compass(_ITEM)

        assert out.count("cmp-ac-pass") == 2
        assert out.count(">PASS</span>") == 2

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
# `extra` sits in its own group and depends on `core` in another group. Only an
# unverified dependency outside the story's group blocks it; a depends between
# stories in the same group is internal sequencing.
_MANIFEST_BLOCKED = _MANIFEST_TWO_STORIES.replace(
    """## story 4: Extra
id: extra
parent: feat-foundation""",
    """## feature 5: Later
id: feat-later
summary: Group.
state: pending

## story 4: Extra
id: extra
parent: feat-later
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
        assert "Blueprint SP " in out
        assert "Context SP " in out
        assert "Used SP " in out
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
        assert "rerun drydock build to continue this step" in out
        # A failed frontier step is resumable (continue is the default), so its group is
        # listed as buildable rather than blocking the graph.
        assert "Buildable now: <strong>feat-foundation</strong>" in out
        assert "blocked by" not in out

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

    def test_later_independent_group_is_not_ready_before_blocked_frontier(
        self, tmp_path, monkeypatch
    ):
        manifest = """# MANIFEST: Demo
state: approved

## feature 1: Blocked First
id: feat-blocked
summary: Group.
state: pending

## story 2: Blocked Core
id: blocked-core
parent: feat-blocked
implements: ARCHITECTURE.md
depends: missing-foundation
stack: common.md
instructions: |
  Build the blocked core.
state: pending

## feature 3: Later
id: feat-later
summary: Group.
state: pending

## story 4: Later Work
id: later-work
parent: feat-later
implements: DATABASE.md
stack: common.md
instructions: |
  Build later work.
state: pending
"""
        quarterdeck = _load_quarterdeck()
        _setup(quarterdeck, tmp_path, monkeypatch, manifest=manifest)
        out = quarterdeck.render_compass(_ITEM)

        assert "Buildable now: <strong>(none)</strong>" in out
        assert "Ready To Build" not in out
        assert "cmp-step-blocked" in out

    def test_same_group_depends_is_internal_and_never_blocks(self, tmp_path, monkeypatch):
        # `extra` depends on `core` inside the same group: the group builds as a
        # unit, so the dependency is internal sequencing and both stories are
        # Ready To Build. The first group can never block itself.
        manifest = _MANIFEST_TWO_STORIES.replace(
            """id: extra
parent: feat-foundation""",
            """id: extra
parent: feat-foundation
depends: core""",
        )
        quarterdeck = _load_quarterdeck()
        _setup(quarterdeck, tmp_path, monkeypatch, manifest=manifest)
        out = quarterdeck.render_compass(_ITEM)
        assert "cmp-step-blocked" not in out
        assert "cmp-group-blocked" not in out
        assert "Blocked by story" not in out
        assert "0 blocked</span>" in out

    def test_group_title_is_click_to_rename(self, tmp_path, monkeypatch):
        quarterdeck = _load_quarterdeck()
        _setup(quarterdeck, tmp_path, monkeypatch)
        out = quarterdeck.render_compass(_ITEM)
        assert "cmp-gname-edit" in out
        assert "compassRename(" in out

    def test_group_header_orders_state_block_name(self, tmp_path, monkeypatch):
        quarterdeck = _load_quarterdeck()
        _setup(quarterdeck, tmp_path, monkeypatch, manifest=_MANIFEST_FAILED)
        out = quarterdeck.render_compass(_ITEM)
        assert (
            out.index("bp-state bp-failed")
            < out.index("cmp-stype cmp-stype-block")
            < out.index("cmp-gname cmp-gname-edit")
        )

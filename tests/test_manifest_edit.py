"""Tests for constrained MANIFEST.md reorder/regroup editing."""

from __future__ import annotations

import pytest

from drydock.errors import SpecificationError
from drydock.manifest_edit import (
    add_feature,
    apply_edit,
    apply_move,
    batch_set_block_fields,
    move_feature,
    move_step,
    regroup_step,
    rename_block,
    render_manifest,
    split_group,
    split_manifest,
    validate_order,
)

MANIFEST = """# MANIFEST: Demo
state: approved

## feature 1: Core
id: feature-core
summary: Core feature.
state: pending

## story 1: Foundation
id: foundation
parent: feature-core
summary: Persistence.
implements: DATABASE.md
instructions: |
  Build the database.
state: pending

## ac 1: DB starts
id: db-starts
parent: foundation
summary: DB boots.
kind: smoke
check: test -f db
state: pending

## story 2: Service
id: service
parent: feature-core
summary: Service layer.
implements: FEATURE.md
depends: foundation
instructions: |
  Build the service.
state: pending

## feature 2: Screens
id: feature-screens
summary: UI feature.
state: pending

## story 3: Welcome
id: welcome
parent: feature-screens
summary: Welcome screen.
implements: UI-WELCOME.md
depends: service
instructions: |
  Build the welcome screen.
state: pending
"""


def _write(tmp_path):
    path = tmp_path / "MANIFEST.md"
    path.write_text(MANIFEST, encoding="utf-8")
    return path


def _ids(doc):
    return [b.block_id for b in doc.blocks]


def test_split_preserves_blocks_and_block_scalars(tmp_path):
    doc = split_manifest(_write(tmp_path))
    assert _ids(doc) == [
        "feature-core",
        "foundation",
        "db-starts",
        "service",
        "feature-screens",
        "welcome",
    ]
    foundation = doc.by_id()["foundation"]
    assert "  Build the database." in foundation.lines
    assert doc.by_id()["service"].depends == ("foundation",)


def test_validate_order_flags_dependency_before_provider(tmp_path):
    doc = split_manifest(_write(tmp_path))
    # Force service ahead of foundation.
    blocks = list(doc.blocks)
    fi = next(i for i, b in enumerate(blocks) if b.block_id == "foundation")
    si = next(i for i, b in enumerate(blocks) if b.block_id == "service")
    blocks[fi], blocks[si] = blocks[si], blocks[fi]
    errors = validate_order(blocks)
    assert any("service" in e and "foundation" in e for e in errors)


def test_move_step_down_within_feature(tmp_path):
    doc = split_manifest(_write(tmp_path))
    # foundation and service are both under feature-core; depends blocks the swap.
    with pytest.raises(SpecificationError, match="break the build topology"):
        move_step(doc, "service", "up")


def test_move_step_rejects_at_edge(tmp_path):
    doc = split_manifest(_write(tmp_path))
    with pytest.raises(SpecificationError, match="already at the edge"):
        move_step(doc, "foundation", "up")


def test_regroup_step_moves_into_other_feature(tmp_path):
    doc = split_manifest(_write(tmp_path))
    regroup_step(doc, "service", "feature-screens")
    moved = doc.by_id()["service"]
    assert moved.parent == "feature-screens"
    # service must still follow foundation in the flattened order.
    ids = _ids(doc)
    assert ids.index("foundation") < ids.index("service")
    # parent line rewritten in the raw block.
    assert any(line.strip() == "parent:       feature-screens" for line in moved.lines)


def test_regroup_step_rejects_when_it_breaks_topology(tmp_path):
    # welcome depends on service; if welcome leaves screens to come before service
    # via grouping, the order would break. Build a case: regroup foundation under
    # screens (after service) so service (depends foundation) precedes it.
    doc = split_manifest(_write(tmp_path))
    with pytest.raises(SpecificationError, match="break the build topology"):
        regroup_step(doc, "foundation", "feature-screens")


def test_move_feature_reorders_groups(tmp_path):
    # Screens depends (transitively) on Core, so moving Screens up breaks order.
    doc = split_manifest(_write(tmp_path))
    with pytest.raises(SpecificationError, match="break the build topology"):
        move_feature(doc, "feature-screens", "up")


def test_render_roundtrip_is_stable(tmp_path):
    doc = split_manifest(_write(tmp_path))
    once = render_manifest(doc)
    doc2 = split_manifest(_write(tmp_path))
    doc2.path = doc.path
    assert render_manifest(doc2) == once
    # re-parse of rendered output preserves ids and order.
    (tmp_path / "OUT.md").write_text(once, encoding="utf-8")
    again = split_manifest(tmp_path / "OUT.md")
    assert _ids(again) == _ids(doc)


def test_apply_move_writes_only_on_success(tmp_path):
    path = _write(tmp_path)
    before = path.read_text(encoding="utf-8")
    with pytest.raises(SpecificationError):
        apply_move(path, "move_step", "service", direction="up")
    assert path.read_text(encoding="utf-8") == before


def test_apply_move_regroup_persists(tmp_path):
    path = _write(tmp_path)
    apply_move(path, "regroup_step", "welcome", feature="feature-core")
    doc = split_manifest(path)
    assert doc.by_id()["welcome"].parent == "feature-core"


def test_batch_set_block_fields_updates_multiple_blocks(tmp_path):
    path = _write(tmp_path)
    batch_set_block_fields(
        path,
        {
            "foundation": {"state": "closed/verified"},
            "service": {"state": "implemented"},
        },
    )
    doc = split_manifest(path)
    assert doc.by_id()["foundation"].lines[1].strip().startswith("id:")
    text = path.read_text(encoding="utf-8")
    assert "state: closed/verified" in text
    assert "state: implemented" in text


def test_batch_set_block_fields_skips_unknown_ids(tmp_path):
    path = _write(tmp_path)
    before = path.read_text(encoding="utf-8")
    batch_set_block_fields(path, {"nonexistent-id": {"state": "closed/verified"}})
    assert path.read_text(encoding="utf-8") == before


def test_batch_set_block_fields_no_op_when_empty(tmp_path):
    path = _write(tmp_path)
    before = path.read_text(encoding="utf-8")
    batch_set_block_fields(path, {})
    assert path.read_text(encoding="utf-8") == before


# ── Structure edits ──────────────────────────────────────────────────────────


def test_rename_feature_changes_label_only(tmp_path):
    doc = split_manifest(_write(tmp_path))
    rename_block(doc, "feature-core", "Platform Core")
    core = doc.by_id()["feature-core"]
    assert core.lines[0] == "## feature 1: Platform Core"
    assert core.block_id == "feature-core"  # id untouched
    # Child steps still reference the unchanged id.
    assert doc.by_id()["foundation"].parent == "feature-core"


def test_rename_step_changes_label_only(tmp_path):
    doc = split_manifest(_write(tmp_path))
    rename_block(doc, "foundation", "Persistence Layer")
    assert doc.by_id()["foundation"].lines[0] == "## story 1: Persistence Layer"


def test_rename_rejects_empty_name(tmp_path):
    doc = split_manifest(_write(tmp_path))
    with pytest.raises(SpecificationError, match="non-empty"):
        rename_block(doc, "feature-core", "   ")


def test_add_feature_appends_empty_group(tmp_path):
    doc = split_manifest(_write(tmp_path))
    new_id = add_feature(doc, "Reporting")
    assert new_id == "feat-reporting"
    block = doc.by_id()[new_id]
    assert block.block_type == "feature"
    assert block.lines[0].endswith(": Reporting")
    # No steps parented to it yet.
    assert not any(b.parent == new_id for b in doc.blocks)


def test_add_feature_ids_are_unique(tmp_path):
    doc = split_manifest(_write(tmp_path))
    first = add_feature(doc, "Reporting")
    second = add_feature(doc, "Reporting")
    assert first != second
    assert second == "feat-reporting-2"


def test_split_group_makes_one_feature_per_story(tmp_path):
    doc = split_manifest(_write(tmp_path))
    features = split_group(doc, "feature-core")
    # feature-core had two stories: foundation, service.
    assert len(features) == 2
    assert features[0] == "feature-core"  # reused for the first story
    # First story stays under the (renamed) original feature.
    assert doc.by_id()["feature-core"].lines[0] == "## feature 1: Foundation"
    assert doc.by_id()["foundation"].parent == "feature-core"
    # Second story is reparented to its own new feature.
    assert doc.by_id()["service"].parent == features[1]
    assert doc.by_id()[features[1]].block_type == "feature"


def test_split_group_rejects_single_story(tmp_path):
    doc = split_manifest(_write(tmp_path))
    with pytest.raises(SpecificationError, match="at least two"):
        split_group(doc, "feature-screens")


def test_split_group_rejects_non_feature(tmp_path):
    doc = split_manifest(_write(tmp_path))
    with pytest.raises(SpecificationError, match="not a feature"):
        split_group(doc, "foundation")


def test_apply_edit_rename_persists(tmp_path):
    path = _write(tmp_path)
    apply_edit(path, "rename", block_id="feature-core", name="Platform Core")
    doc = split_manifest(path)
    assert doc.by_id()["feature-core"].lines[0] == "## feature 1: Platform Core"


def test_apply_edit_add_feature_persists_and_returns_id(tmp_path):
    path = _write(tmp_path)
    result = apply_edit(path, "add_feature", name="Reporting")
    assert result["feature_id"] == "feat-reporting"
    doc = split_manifest(path)
    assert "feat-reporting" in doc.by_id()


def test_apply_edit_split_group_persists(tmp_path):
    path = _write(tmp_path)
    result = apply_edit(path, "split_group", block_id="feature-core")
    assert len(result["features"]) == 2
    doc = split_manifest(path)
    assert doc.by_id()["service"].parent != "feature-core"


def test_apply_edit_does_not_write_on_failure(tmp_path):
    path = _write(tmp_path)
    before = path.read_text(encoding="utf-8")
    with pytest.raises(SpecificationError):
        apply_edit(path, "split_group", block_id="feature-screens")
    assert path.read_text(encoding="utf-8") == before


def test_apply_edit_unknown_kind_raises(tmp_path):
    path = _write(tmp_path)
    with pytest.raises(SpecificationError, match="Unknown edit kind"):
        apply_edit(path, "frobnicate", block_id="feature-core")

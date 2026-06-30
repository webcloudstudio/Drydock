"""Tests for constrained MANIFEST.md reorder/regroup editing."""

from __future__ import annotations

import pytest

from drydock.errors import SpecificationError
from drydock.manifest_edit import (
    apply_move,
    batch_set_block_fields,
    move_feature,
    move_step,
    regroup_step,
    render_manifest,
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

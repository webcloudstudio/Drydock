"""Tests for the QuarterDeck ``compass`` type — render, live recompute, and the
persist-on-mutation navigation ops (move / combine / split / rename / seed)."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest


def _load_quarterdeck():
    path = Path(__file__).parents[1] / "QuarterDeck" / "app.py"
    spec = importlib.util.spec_from_file_location("quarterdeck_compass_test", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


_COMPASS = "# Foundational\nFEATURE-Schema.md\n\n# Screens\nSCREEN-Dashboard.md\n"


def _blueprint(tmp_path: Path) -> Path:
    bp = tmp_path / "blueprint"
    bp.mkdir()
    (bp / "FEATURE-Schema.md").write_bytes(b"x" * 4000)  # 1000 SP
    (bp / "SCREEN-Dashboard.md").write_bytes(b"x" * 400)  # 100 SP
    return bp


_ITEM = {
    "id": "build_compass",
    "type": "compass",
    "path": "../BUILD_COMPASS.md",
    "label": "Build Compass",
}


def _setup_render(quarterdeck, tmp_path, monkeypatch, *, compass_text=_COMPASS):
    bp = _blueprint(tmp_path)
    compass_file = tmp_path / "BUILD_COMPASS.md"
    compass_file.write_text(compass_text, encoding="utf-8")
    monkeypatch.setattr(quarterdeck, "_BLUEPRINT_DIR", bp)
    monkeypatch.setattr(quarterdeck, "resolve_path", lambda _p: compass_file)
    return compass_file


class TestRender:
    def test_shows_groups_story_points_and_total(self, tmp_path, monkeypatch):
        quarterdeck = _load_quarterdeck()
        _setup_render(quarterdeck, tmp_path, monkeypatch)

        out = quarterdeck.render_compass(_ITEM)

        assert "# Foundational" in out
        assert "# Screens" in out
        assert "Story Points = 1000" in out  # FEATURE-Schema.md
        assert "Story Points = 100" in out  # SCREEN-Dashboard.md
        assert "Total Story Points = <strong>1100</strong>" in out
        # Navigation affordances present.
        assert "compassSplit('build_compass',0,0)" in out
        assert "compassOp('build_compass','combine',1)" in out

    def test_missing_spec_file_flagged(self, tmp_path, monkeypatch):
        quarterdeck = _load_quarterdeck()
        _setup_render(quarterdeck, tmp_path, monkeypatch, compass_text="# G\nGHOST.md\n")
        out = quarterdeck.render_compass(_ITEM)
        assert "missing" in out
        assert "Total Story Points = <strong>0</strong>" in out

    def test_absent_file_offers_seed_when_manifest_has_specs(self, tmp_path, monkeypatch):
        quarterdeck = _load_quarterdeck()
        monkeypatch.setattr(quarterdeck, "PROJECT_ROOT", tmp_path)
        (tmp_path / "MANIFEST.md").write_text(
            "# MANIFEST: Demo\nstate: draft\n\n"
            "## story 1: Build A\nid: build-a\nimplements: FEATURE-A.md\nstate: pending\n",
            encoding="utf-8",
        )

        def _missing(_p):
            raise quarterdeck.HTTPException(status_code=404, detail="missing")

        monkeypatch.setattr(quarterdeck, "resolve_path", _missing)
        out = quarterdeck.render_compass(_ITEM)
        assert "Seed from Manifest" in out
        assert "compassSeed('build_compass')" in out


def _setup_op(quarterdeck, tmp_path, monkeypatch, *, compass_text=_COMPASS):
    compass_file = tmp_path / "BUILD_COMPASS.md"
    compass_file.write_text(compass_text, encoding="utf-8")
    monkeypatch.setattr(quarterdeck, "find_item", lambda _id: _ITEM)
    monkeypatch.setattr(quarterdeck, "resolve_write_path", lambda _p: compass_file)
    return compass_file


def _parse(quarterdeck, compass_file):
    from drydock.build_compass import parse_build_compass

    return parse_build_compass(compass_file.read_text(encoding="utf-8"))


class TestOps:
    def test_move_down_persists_clean_file(self, tmp_path, monkeypatch):
        quarterdeck = _load_quarterdeck()
        compass_file = _setup_op(quarterdeck, tmp_path, monkeypatch)

        result = quarterdeck.api_compass_op(
            "build_compass", quarterdeck.CompassOp(op="move_down", group=0)
        )

        assert result["ok"] is True
        compass = _parse(quarterdeck, compass_file)
        assert [g.name for g in compass.groups] == ["Screens", "Foundational"]
        # Authored file carries no numbers.
        assert "Story Points" not in compass_file.read_text(encoding="utf-8")

    def test_combine_merges_into_previous(self, tmp_path, monkeypatch):
        quarterdeck = _load_quarterdeck()
        compass_file = _setup_op(quarterdeck, tmp_path, monkeypatch)

        quarterdeck.api_compass_op("build_compass", quarterdeck.CompassOp(op="combine", group=1))

        compass = _parse(quarterdeck, compass_file)
        assert len(compass.groups) == 1
        assert compass.groups[0].files == ["FEATURE-Schema.md", "SCREEN-Dashboard.md"]

    def test_split_moves_file_into_new_group(self, tmp_path, monkeypatch):
        quarterdeck = _load_quarterdeck()
        compass_file = _setup_op(quarterdeck, tmp_path, monkeypatch)

        quarterdeck.api_compass_op(
            "build_compass", quarterdeck.CompassOp(op="split", group=0, file=0)
        )

        compass = _parse(quarterdeck, compass_file)
        assert [g.name for g in compass.groups] == ["Foundational", "New Group", "Screens"]
        assert compass.groups[1].files == ["FEATURE-Schema.md"]
        assert compass.groups[0].files == []

    def test_rename_sets_group_name(self, tmp_path, monkeypatch):
        quarterdeck = _load_quarterdeck()
        compass_file = _setup_op(quarterdeck, tmp_path, monkeypatch)

        quarterdeck.api_compass_op(
            "build_compass", quarterdeck.CompassOp(op="rename", group=0, name="Core")
        )

        compass = _parse(quarterdeck, compass_file)
        assert compass.groups[0].name == "Core"

    def test_out_of_range_group_rejected(self, tmp_path, monkeypatch):
        quarterdeck = _load_quarterdeck()
        _setup_op(quarterdeck, tmp_path, monkeypatch)
        with pytest.raises(quarterdeck.HTTPException, match="out of range"):
            quarterdeck.api_compass_op(
                "build_compass", quarterdeck.CompassOp(op="move_up", group=9)
            )

    def test_unknown_op_rejected(self, tmp_path, monkeypatch):
        quarterdeck = _load_quarterdeck()
        _setup_op(quarterdeck, tmp_path, monkeypatch)
        with pytest.raises(quarterdeck.HTTPException, match="Unknown compass op"):
            quarterdeck.api_compass_op("build_compass", quarterdeck.CompassOp(op="bogus", group=0))


class TestSeed:
    def test_seed_writes_flat_group_from_manifest(self, tmp_path, monkeypatch):
        quarterdeck = _load_quarterdeck()
        compass_file = tmp_path / "BUILD_COMPASS.md"
        monkeypatch.setattr(quarterdeck, "PROJECT_ROOT", tmp_path)
        monkeypatch.setattr(quarterdeck, "find_item", lambda _id: _ITEM)
        monkeypatch.setattr(quarterdeck, "resolve_write_path", lambda _p: compass_file)
        (tmp_path / "MANIFEST.md").write_text(
            "# MANIFEST: Demo\nstate: draft\n\n"
            "## story 1: Build A\nid: build-a\nimplements: FEATURE-A.md\nstate: pending\n\n"
            "## story 2: Build B\nid: build-b\nimplements: FEATURE-B.md\nstate: pending\n",
            encoding="utf-8",
        )

        result = quarterdeck.api_compass_seed("build_compass")

        assert result == {"ok": True, "count": 2}
        compass = _parse(quarterdeck, compass_file)
        assert len(compass.groups) == 1
        assert compass.groups[0].files == ["FEATURE-A.md", "FEATURE-B.md"]

    def test_seed_without_manifest_specs_rejected(self, tmp_path, monkeypatch):
        quarterdeck = _load_quarterdeck()
        monkeypatch.setattr(quarterdeck, "PROJECT_ROOT", tmp_path)
        monkeypatch.setattr(quarterdeck, "find_item", lambda _id: _ITEM)
        with pytest.raises(quarterdeck.HTTPException, match="No MANIFEST.md stories"):
            quarterdeck.api_compass_seed("build_compass")

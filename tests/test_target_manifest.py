"""Tests for the per-target manifest (target.yaml)."""

from __future__ import annotations

import pytest

from drydock.errors import DrydockError
from drydock.target_manifest import (
    DEFAULT_CODE_ROOT,
    TargetManifest,
    parse_manifest,
    read_manifest,
    resolve_code_root,
    write_manifest,
)


def test_default_manifest_targets_workspace(tmp_path):
    path = write_manifest(tmp_path, TargetManifest())
    text = path.read_text(encoding="utf-8")
    assert "blueprint:" in text
    assert f"code_root: {DEFAULT_CODE_ROOT}" in text


def test_round_trip_preserves_fields(tmp_path):
    write_manifest(tmp_path, TargetManifest(blueprint="drydock", code_root="code"))
    manifest = read_manifest(tmp_path)
    assert manifest.blueprint == "drydock"
    assert manifest.code_root == "code"


def test_parse_ignores_comments_and_blank_lines():
    manifest = parse_manifest("# comment\n\nblueprint: app\ncode_root: ../..\n")
    assert manifest.blueprint == "app"
    assert manifest.code_root == "../.."


def test_read_missing_manifest_raises(tmp_path):
    with pytest.raises(DrydockError, match="Target manifest not found"):
        read_manifest(tmp_path)


def test_resolve_default_code_root_is_workspace(tmp_path):
    # target_dir = <ws>/targets/<Target>; ../.. resolves to <ws>.
    workspace = tmp_path
    target_dir = workspace / "targets" / "Example"
    target_dir.mkdir(parents=True)
    resolved = resolve_code_root(target_dir, TargetManifest())
    assert resolved == workspace.resolve()


def test_resolve_greenfield_code_root_is_container(tmp_path):
    target_dir = tmp_path / "targets" / "Example"
    target_dir.mkdir(parents=True)
    resolved = resolve_code_root(target_dir, TargetManifest(code_root="code"))
    assert resolved == (target_dir / "code").resolve()


def test_resolve_absolute_code_root(tmp_path):
    target_dir = tmp_path / "targets" / "Example"
    target_dir.mkdir(parents=True)
    absolute = tmp_path / "elsewhere"
    resolved = resolve_code_root(target_dir, TargetManifest(code_root=str(absolute)))
    assert resolved == absolute

"""Tests for the METADATA.md manifest (blueprint name + code_root)."""

from __future__ import annotations

from drydock.metadata import (
    METADATA_NAME,
    get_code_root,
    parse_metadata,
    render_metadata,
)


def test_render_and_parse_round_trip(tmp_path):
    path = tmp_path / METADATA_NAME
    path.write_text(render_metadata("Example", code_root="../.."), encoding="utf-8")
    fields = parse_metadata(path)
    assert fields["name"] == "Example"
    assert fields["blueprint"] == "Example"
    assert fields["code_root"] == "../.."


def test_get_code_root_default_is_workspace(tmp_path):
    target_dir = tmp_path / "targets" / "Example"
    target_dir.mkdir(parents=True)
    (target_dir / METADATA_NAME).write_text(render_metadata("Example"), encoding="utf-8")
    # ../.. from targets/Example resolves to the workspace root.
    assert get_code_root(target_dir) == tmp_path.resolve()


def test_get_code_root_absent_metadata_defaults(tmp_path):
    target_dir = tmp_path / "targets" / "Example"
    target_dir.mkdir(parents=True)
    assert get_code_root(target_dir) == tmp_path.resolve()


def test_get_code_root_greenfield_container(tmp_path):
    target_dir = tmp_path / "targets" / "Example"
    target_dir.mkdir(parents=True)
    (target_dir / METADATA_NAME).write_text(
        render_metadata("Example", code_root="code"), encoding="utf-8"
    )
    assert get_code_root(target_dir) == (target_dir / "code").resolve()

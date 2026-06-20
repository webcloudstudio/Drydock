"""Tests for the METADATA.md manifest (project identity, build_dir, lifecycle state)."""

from __future__ import annotations

from pathlib import Path

import pytest

from drydock.metadata import (
    BUILD_STATE_LADDER,
    METADATA_NAME,
    get_build_dir,
    get_build_state,
    load_metadata_vars,
    parse_metadata,
    render_metadata,
    set_build_state,
)


def test_render_contains_required_fields():
    md = render_metadata("Example", display_name="Example App", short_description="A test.")
    assert "name: Example" in md
    assert "display_name: Example App" in md
    assert "short_description: A test." in md


def test_render_defaults_display_name_to_target():
    md = render_metadata("Example")
    assert "display_name: Example" in md


def test_render_no_legacy_fields():
    md = render_metadata("Example")
    assert "blueprint:" not in md
    assert "code_root:" not in md
    assert "status: IDEA" not in md
    assert "type: oneshot" not in md
    assert "Agent Instructions" not in md


def test_render_and_parse_round_trip():
    import tempfile

    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / METADATA_NAME
        path.write_text(render_metadata("Example", stack="Python", version="1.0"), encoding="utf-8")
        fields = parse_metadata(path)
    assert fields["name"] == "Example"
    assert fields["stack"] == "Python"
    assert fields["version"] == "1.0"


def test_load_metadata_vars_returns_all_fields(tmp_path):
    (tmp_path / METADATA_NAME).write_text(
        render_metadata("T", short_description="desc"), encoding="utf-8"
    )
    fields = load_metadata_vars(tmp_path)
    assert fields["name"] == "T"
    assert fields["short_description"] == "desc"


def test_load_metadata_vars_empty_when_no_file(tmp_path):
    assert load_metadata_vars(tmp_path) == {}


# ---------------------------------------------------------------------------
# build_dir resolution
# ---------------------------------------------------------------------------


def test_get_build_dir_cli_override_wins(tmp_path, monkeypatch):
    target_dir = tmp_path / "targets" / "T"
    target_dir.mkdir(parents=True)
    (target_dir / METADATA_NAME).write_text(
        render_metadata("T") + "build_dir: /some/other/path\n", encoding="utf-8"
    )
    override = tmp_path / "override"
    override.mkdir()
    result = get_build_dir("T", target_dir, cli_override=str(override))
    assert result == override.resolve()


def test_get_build_dir_metadata_field_used(tmp_path, monkeypatch):
    build_out = tmp_path / "mybuilds" / "T"
    build_out.mkdir(parents=True)
    target_dir = tmp_path / "targets" / "T"
    target_dir.mkdir(parents=True)
    (target_dir / METADATA_NAME).write_text(
        render_metadata("T") + f"build_dir: {build_out}\n", encoding="utf-8"
    )
    result = get_build_dir("T", target_dir)
    assert result == build_out.resolve()


def test_get_build_dir_falls_back_to_config(tmp_path, monkeypatch):
    build_root = tmp_path / "builds"
    build_root.mkdir()
    monkeypatch.setenv("DRYDOCK_BUILD_DIRECTORY", str(build_root))
    target_dir = tmp_path / "targets" / "T"
    target_dir.mkdir(parents=True)
    (target_dir / METADATA_NAME).write_text(render_metadata("T"), encoding="utf-8")
    result = get_build_dir("T", target_dir)
    assert result == build_root / "T"


# ---------------------------------------------------------------------------
# Lifecycle state
# ---------------------------------------------------------------------------


def test_build_state_ladder_order():
    assert BUILD_STATE_LADDER == ("init", "analyzed", "planned", "building", "built")


def test_get_build_state_defaults_to_init(tmp_path):
    target_dir = tmp_path / "T"
    target_dir.mkdir()
    (target_dir / METADATA_NAME).write_text(render_metadata("T"), encoding="utf-8")
    assert get_build_state(target_dir) == "init"


def test_get_build_state_no_metadata_returns_init(tmp_path):
    target_dir = tmp_path / "T"
    target_dir.mkdir()
    assert get_build_state(target_dir) == "init"


def test_set_build_state_advances_forward(tmp_path):
    target_dir = tmp_path / "T"
    target_dir.mkdir()
    (target_dir / METADATA_NAME).write_text(render_metadata("T"), encoding="utf-8")
    changed = set_build_state(target_dir, "analyzed")
    assert changed is True
    assert get_build_state(target_dir) == "analyzed"


def test_set_build_state_persists_to_file(tmp_path):
    target_dir = tmp_path / "T"
    target_dir.mkdir()
    (target_dir / METADATA_NAME).write_text(render_metadata("T"), encoding="utf-8")
    set_build_state(target_dir, "planned")
    fields = parse_metadata(target_dir / METADATA_NAME)
    assert fields["drydock_build_state"] == "planned"


def test_set_build_state_forward_only(tmp_path):
    target_dir = tmp_path / "T"
    target_dir.mkdir()
    (target_dir / METADATA_NAME).write_text(render_metadata("T"), encoding="utf-8")
    set_build_state(target_dir, "built")
    changed = set_build_state(target_dir, "init")
    assert changed is False
    assert get_build_state(target_dir) == "built"


def test_set_build_state_same_state_is_noop(tmp_path):
    target_dir = tmp_path / "T"
    target_dir.mkdir()
    (target_dir / METADATA_NAME).write_text(render_metadata("T"), encoding="utf-8")
    set_build_state(target_dir, "analyzed")
    changed = set_build_state(target_dir, "analyzed")
    assert changed is False


def test_set_build_state_updates_existing_field(tmp_path):
    target_dir = tmp_path / "T"
    target_dir.mkdir()
    md = render_metadata("T") + "drydock_build_state: init\n"
    (target_dir / METADATA_NAME).write_text(md, encoding="utf-8")
    set_build_state(target_dir, "analyzed")
    fields = parse_metadata(target_dir / METADATA_NAME)
    assert fields["drydock_build_state"] == "analyzed"


def test_set_build_state_no_metadata_returns_false(tmp_path):
    target_dir = tmp_path / "T"
    target_dir.mkdir()
    changed = set_build_state(target_dir, "analyzed")
    assert changed is False


def test_set_build_state_invalid_state_raises(tmp_path):
    target_dir = tmp_path / "T"
    target_dir.mkdir()
    (target_dir / METADATA_NAME).write_text(render_metadata("T"), encoding="utf-8")
    with pytest.raises(ValueError, match="Unknown build state"):
        set_build_state(target_dir, "bogus")

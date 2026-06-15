"""Tests for the METADATA.md manifest (blueprint name + code_root + lifecycle state)."""

from __future__ import annotations

from drydock.metadata import (
    BUILD_STATE_LADDER,
    METADATA_NAME,
    get_build_state,
    get_code_root,
    parse_metadata,
    render_metadata,
    set_build_state,
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
    # Place the field before the ## section so parse_metadata can find it
    base = render_metadata("T")
    md = base.replace("## Agent Instructions", "drydock_build_state: init\n\n## Agent Instructions")
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
    import pytest

    target_dir = tmp_path / "T"
    target_dir.mkdir()
    (target_dir / METADATA_NAME).write_text(render_metadata("T"), encoding="utf-8")
    with pytest.raises(ValueError, match="Unknown build state"):
        set_build_state(target_dir, "bogus")

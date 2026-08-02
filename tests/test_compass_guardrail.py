import pytest

from drydock.compass_guardrail import apply_guardrail, validate_guardrail
from drydock.errors import SpecificationError


def test_apply_guardrail_is_idempotent_and_uses_absolute_paths(tmp_path):
    target_dir = tmp_path / "targets" / "Marina"
    build_dir = tmp_path / "Marina"
    once = apply_guardrail("# Compass", "Marina", target_dir, build_dir=build_dir)
    twice = apply_guardrail(once, "Marina", target_dir, build_dir=build_dir)

    assert once == twice
    assert once.count("## Build Write Guardrail") == 1
    assert f"`{build_dir.resolve()}`" in once
    assert f"`{target_dir.resolve()}`" in once


@pytest.mark.parametrize("content", ["# Compass\n", ""])
def test_validate_rejects_missing_guardrail_before_build(tmp_path, content):
    target_dir = tmp_path / "targets" / "Marina"
    target_dir.mkdir(parents=True)
    compass = target_dir / "COMPASS.md"
    if content:
        compass.write_text(content, encoding="utf-8")

    with pytest.raises(SpecificationError, match="drydock analyze Marina"):
        validate_guardrail(compass, "Marina", target_dir, build_dir=tmp_path / "Marina")


def test_validate_rejects_stale_build_path(tmp_path):
    target_dir = tmp_path / "targets" / "Marina"
    target_dir.mkdir(parents=True)
    compass = target_dir / "COMPASS.md"
    compass.write_text(
        apply_guardrail("# Compass", "Marina", target_dir, build_dir=tmp_path / "old"),
        encoding="utf-8",
    )

    with pytest.raises(SpecificationError, match="missing or stale"):
        validate_guardrail(compass, "Marina", target_dir, build_dir=tmp_path / "new")

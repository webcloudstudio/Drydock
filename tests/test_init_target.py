"""Tests for target workspace initialization."""

from __future__ import annotations

import pytest

from drydock.errors import DrydockError
from drydock.init_target import _validate_target, init_target


def test_init_target_creates_specification_independent_baseline(tmp_target_root):
    result = init_target("Example", tmp_target_root)

    assert result.target_dir == tmp_target_root / "Example"
    assert (result.target_dir / "QuarterDeck" / "console.yaml").is_file()
    assert (result.target_dir / "QuarterDeck" / "app.py").is_file()
    assert "Captain's Chair" in (result.target_dir / "QuarterDeck" / "console.yaml").read_text(
        encoding="utf-8"
    )
    assert (result.target_dir / "docs" / "SEA_TRIALS.md").is_file()
    assert (result.target_dir / "docs" / "SOUNDINGS.md").is_file()
    assert (result.target_dir / "QuarterDeck" / "tickets.json").read_text(encoding="utf-8") == (
        '{\n  "tickets": []\n}\n'
    )
    assert not (result.target_dir / "METADATA.md").exists()


def test_init_target_preserves_existing_baseline_files(tmp_target_root):
    first = init_target("Example", tmp_target_root)
    config = first.target_dir / "QuarterDeck" / "console.yaml"
    soundings = first.target_dir / "docs" / "SOUNDINGS.md"
    config.write_text("CUSTOM\n", encoding="utf-8")
    soundings.write_text("# Custom Soundings\n", encoding="utf-8")

    second = init_target("Example", tmp_target_root)

    assert config.read_text(encoding="utf-8") == "CUSTOM\n"
    assert soundings.read_text(encoding="utf-8") == "# Custom Soundings\n"
    assert config in second.skipped


@pytest.mark.parametrize("target", ["", "../bad", "nested/bad", "bad\\name"])
def test_validate_target_rejects_invalid_names(target):
    with pytest.raises(DrydockError):
        _validate_target(target)

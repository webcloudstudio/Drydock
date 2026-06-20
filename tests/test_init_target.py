"""Tests for target workspace initialization."""

from __future__ import annotations

import pytest

from drydock.errors import DrydockError
from drydock.init_target import _validate_target, init_target


def test_init_target_creates_specification_independent_baseline(tmp_target_root):
    result = init_target("Example", tmp_target_root)

    assert result.target_dir == tmp_target_root / "Example"
    assert (result.target_dir / "QuarterDeck" / "console.yaml").is_file()
    # The console runtime is served from the package; only state lives in-tree.
    assert not (result.target_dir / "QuarterDeck" / "app.py").exists()
    assert not (result.target_dir / "QuarterDeck" / "requirements.txt").exists()
    # Manifest lives in METADATA.md; there is no target.yaml or docs/.
    assert not (result.target_dir / "target.yaml").exists()
    assert not (result.target_dir / "docs").exists()
    metadata = (result.target_dir / "METADATA.md").read_text(encoding="utf-8")
    assert "name: Example" in metadata
    assert "display_name: Example" in metadata
    assert (result.target_dir / "blueprint" / "sources").is_dir()
    assert "Captain's Chair" in (result.target_dir / "QuarterDeck" / "console.yaml").read_text(
        encoding="utf-8"
    )
    assert not (result.target_dir / "SEA_TRIALS.md").is_file()
    assert not (result.target_dir / "SOUNDINGS.md").is_file()
    assert not (result.target_dir / "QuarterDeck" / "tickets.json").exists()


def test_init_target_preserves_existing_baseline_files(tmp_target_root):
    first = init_target("Example", tmp_target_root)
    config = first.target_dir / "QuarterDeck" / "console.yaml"
    soundings = first.target_dir / "SOUNDINGS.md"
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

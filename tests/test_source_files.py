"""Every command that reads imported sources skips hidden entries."""

from __future__ import annotations

from pathlib import Path

from drydock.source_files import is_hidden, iter_source_files


def _tree(root: Path) -> Path:
    sources = root / "sources"
    (sources / "sub").mkdir(parents=True)
    (sources / ".hidden-dir").mkdir()
    (sources / "SPEC.md").write_text("# Specification\n", encoding="utf-8")
    (sources / "sub" / "NOTES.md").write_text("# Notes\n", encoding="utf-8")
    (sources / ".gitkeep").write_text("", encoding="utf-8")
    (sources / ".drydock-import").write_text("source: x\n", encoding="utf-8")
    (sources / "sub" / ".env").write_text("SECRET=1\n", encoding="utf-8")
    (sources / ".hidden-dir" / "BURIED.md").write_text("# Buried\n", encoding="utf-8")
    return sources


def test_iteration_yields_visible_files_only(tmp_path: Path) -> None:
    sources = _tree(tmp_path)

    found = {path.relative_to(sources).as_posix() for path in iter_source_files(sources)}

    assert found == {"SPEC.md", "sub/NOTES.md"}


def test_missing_directory_yields_nothing(tmp_path: Path) -> None:
    assert list(iter_source_files(tmp_path / "absent")) == []


def test_hidden_test_covers_a_hidden_parent(tmp_path: Path) -> None:
    sources = _tree(tmp_path)

    assert is_hidden(sources / ".hidden-dir" / "BURIED.md", sources)
    assert not is_hidden(sources / "sub" / "NOTES.md", sources)


def test_score_spec_inventory_excludes_hidden_files(tmp_path: Path) -> None:
    from drydock.score_spec import inventory_sources

    sources = _tree(tmp_path)
    inventory, markdown = inventory_sources(sources)

    assert [record.path for record in inventory] == ["SPEC.md", "sub/NOTES.md"]
    assert set(markdown) == {"SPEC.md", "sub/NOTES.md"}


def test_source_material_excludes_hidden_files(tmp_path: Path) -> None:
    from drydock.source_material import discover_source_material

    blueprint = tmp_path / "blueprint"
    blueprint.mkdir()
    _tree(blueprint)

    relatives = {item.relative_path for item in discover_source_material(blueprint)}

    assert relatives == {"sources/SPEC.md", "sources/sub/NOTES.md"}


def test_status_counts_only_visible_imported_sources(tmp_path: Path) -> None:
    from drydock.status import _count_imported_sources

    blueprint = tmp_path / "blueprint"
    blueprint.mkdir()
    _tree(blueprint)

    assert _count_imported_sources(blueprint) == 2

"""Unit tests for import_markdown.import_markdown()."""

from __future__ import annotations

import pytest

from drydock.errors import SpecificationError
from drydock.import_markdown import import_markdown


class TestImportMarkdownFile:
    def test_single_md_file_copied_to_sources(self, tmp_path):
        source = tmp_path / "source" / "spec.md"
        source.parent.mkdir()
        source.write_text("# Spec\n\nContent.\n", encoding="utf-8")
        td = tmp_path / "targets"
        td.mkdir()

        result = import_markdown("MyProject", "MyTarget", source, td)

        dest = td / "MyTarget" / "blueprint" / "sources" / "spec.md"
        assert dest.is_file()
        assert dest.read_text(encoding="utf-8") == "# Spec\n\nContent.\n"
        assert "sources/spec.md" in [
            str(p.relative_to(result.blueprint_dir)) for p in result.imported
        ]

    def test_drydock_import_marker_written(self, tmp_path):
        source = tmp_path / "req.md"
        source.write_text("# Req\n", encoding="utf-8")
        td = tmp_path / "targets"
        td.mkdir()

        result = import_markdown("Proj", "Tgt", source, td)

        marker = result.blueprint_dir / "sources" / ".drydock-import"
        assert marker.is_file()
        text = marker.read_text(encoding="utf-8")
        assert "format: markdown" in text
        assert str(source) in text

    def test_non_md_file_raises(self, tmp_path):
        source = tmp_path / "spec.txt"
        source.write_text("not markdown", encoding="utf-8")
        td = tmp_path / "targets"
        td.mkdir()

        with pytest.raises(SpecificationError, match="Markdown import requires a .md file"):
            import_markdown("Proj", "Tgt", source, td)

    def test_missing_source_raises(self, tmp_path):
        td = tmp_path / "targets"
        td.mkdir()

        with pytest.raises(SpecificationError, match="Import source not found"):
            import_markdown("Proj", "Tgt", tmp_path / "nonexistent.md", td)


class TestImportMarkdownDirectory:
    def test_directory_recursion_copies_all_md_files(self, tmp_path):
        src = tmp_path / "docs"
        src.mkdir()
        (src / "a.md").write_text("# A\n", encoding="utf-8")
        subdir = src / "sub"
        subdir.mkdir()
        (subdir / "b.md").write_text("# B\n", encoding="utf-8")
        td = tmp_path / "targets"
        td.mkdir()

        result = import_markdown("Proj", "Tgt", src, td)

        bp = result.blueprint_dir / "sources"
        assert (bp / "a.md").is_file()
        assert (bp / "sub" / "b.md").is_file()
        assert len(result.imported) == 2

    def test_non_md_files_in_directory_skipped(self, tmp_path):
        src = tmp_path / "docs"
        src.mkdir()
        (src / "spec.md").write_text("# S\n", encoding="utf-8")
        (src / "ignore.txt").write_text("skip\n", encoding="utf-8")
        td = tmp_path / "targets"
        td.mkdir()

        result = import_markdown("Proj", "Tgt", src, td)

        assert len(result.imported) == 1

    def test_empty_directory_raises(self, tmp_path):
        src = tmp_path / "empty"
        src.mkdir()
        td = tmp_path / "targets"
        td.mkdir()

        with pytest.raises(SpecificationError, match="No Markdown files found"):
            import_markdown("Proj", "Tgt", src, td)


class TestImportMarkdownInitialization:
    def test_root_identity_seeded_blueprint_holds_only_sources(self, tmp_path):
        source = tmp_path / "s.md"
        source.write_text("# S\n", encoding="utf-8")
        td = tmp_path / "targets"
        td.mkdir()

        result = import_markdown("Proj", "Tgt", source, td)
        target_dir = td / "Tgt"

        assert result.initialized is True
        # Root identity anchor for lifecycle state.
        assert (target_dir / "METADATA.md").is_file()
        # No typed-spec corpus seeded into blueprint/; COMPASS.md is an analyze output.
        assert not (result.blueprint_dir / "ARCHITECTURE.md").exists()
        assert not (result.blueprint_dir / "DATABASE.md").exists()
        assert not (target_dir / "COMPASS.md").exists()
        # blueprint/ contains only the sources subtree.
        assert {p.name for p in result.blueprint_dir.iterdir()} == {"sources"}

    def test_initialized_false_on_reimport(self, tmp_path):
        source = tmp_path / "s.md"
        source.write_text("# S\n", encoding="utf-8")
        td = tmp_path / "targets"
        td.mkdir()

        import_markdown("Proj", "Tgt", source, td)
        result2 = import_markdown("Proj", "Tgt", source, td)

        assert result2.initialized is False

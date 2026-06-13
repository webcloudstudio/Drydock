"""Unit tests for import_source — file copy, no LLM calls."""

from __future__ import annotations

from pathlib import Path

import pytest

from drydock.errors import SpecificationError
from drydock.import_source import _is_excluded, detect_stack, import_source

# ---------------------------------------------------------------------------
# Stack detection
# ---------------------------------------------------------------------------


class TestDetectStack:
    def test_python_from_requirements(self, tmp_path):
        (tmp_path / "requirements.txt").write_text("flask\n", encoding="utf-8")
        assert "Python" in detect_stack(tmp_path)

    def test_node_from_package_json(self, tmp_path):
        (tmp_path / "package.json").write_text("{}", encoding="utf-8")
        assert "Node.js" in detect_stack(tmp_path)

    def test_rust_from_cargo(self, tmp_path):
        (tmp_path / "Cargo.toml").write_text("[package]", encoding="utf-8")
        assert "Rust" in detect_stack(tmp_path)

    def test_go_from_go_mod(self, tmp_path):
        (tmp_path / "go.mod").write_text("module example.com/m", encoding="utf-8")
        assert "Go" in detect_stack(tmp_path)

    def test_flask_detected_from_requirements_content(self, tmp_path):
        (tmp_path / "requirements.txt").write_text("Flask==3.0\n", encoding="utf-8")
        assert "Flask" in detect_stack(tmp_path)

    def test_empty_directory_returns_empty_list(self, tmp_path):
        assert detect_stack(tmp_path) == []

    def test_no_duplicate_labels(self, tmp_path):
        (tmp_path / "requirements.txt").write_text("flask\n", encoding="utf-8")
        assert detect_stack(tmp_path).count("Python") == 1


# ---------------------------------------------------------------------------
# Exclusion helper
# ---------------------------------------------------------------------------


class TestIsExcluded:
    def test_venv_excluded(self):
        assert _is_excluded(Path("venv/lib/site-packages/foo.py"))

    def test_node_modules_excluded(self):
        assert _is_excluded(Path("node_modules/lodash/index.js"))

    def test_pycache_excluded(self):
        assert _is_excluded(Path("src/__pycache__/mod.cpython-311.pyc"))

    def test_normal_file_not_excluded(self):
        assert not _is_excluded(Path("src/app.py"))

    def test_nested_normal_file_not_excluded(self):
        assert not _is_excluded(Path("src/utils/helpers.py"))


# ---------------------------------------------------------------------------
# import_source
# ---------------------------------------------------------------------------


class TestImportSource:
    def _make_source(self, tmp_path: Path) -> Path:
        src = tmp_path / "myapp"
        src.mkdir()
        (src / "app.py").write_text("x = 1\n", encoding="utf-8")
        (src / "requirements.txt").write_text("flask\n", encoding="utf-8")
        sub = src / "utils"
        sub.mkdir()
        (sub / "helpers.py").write_text("def f(): pass\n", encoding="utf-8")
        return src

    def test_copies_files_to_sources(self, tmp_path):
        src = self._make_source(tmp_path)
        td = tmp_path / "targets"
        td.mkdir()

        result = import_source("Proj", "Tgt", src, td)

        sources = result.blueprint_dir / "sources"
        assert (sources / "app.py").is_file()
        assert (sources / "requirements.txt").is_file()
        assert (sources / "utils" / "helpers.py").is_file()

    def test_preserves_directory_structure(self, tmp_path):
        src = self._make_source(tmp_path)
        td = tmp_path / "targets"
        td.mkdir()

        result = import_source("Proj", "Tgt", src, td)

        assert (result.blueprint_dir / "sources" / "utils" / "helpers.py").is_file()

    def test_drydock_import_marker_written(self, tmp_path):
        src = self._make_source(tmp_path)
        td = tmp_path / "targets"
        td.mkdir()

        result = import_source("Proj", "Tgt", src, td)

        marker = result.blueprint_dir / "sources" / ".drydock-import"
        assert marker.is_file()
        text = marker.read_text(encoding="utf-8")
        assert "format: source" in text

    def test_excluded_dirs_skipped(self, tmp_path):
        src = self._make_source(tmp_path)
        venv = src / "venv"
        venv.mkdir()
        (venv / "lib.py").write_text("x\n", encoding="utf-8")
        td = tmp_path / "targets"
        td.mkdir()

        result = import_source("Proj", "Tgt", src, td)

        sources = result.blueprint_dir / "sources"
        assert not (sources / "venv").exists()

    def test_imported_tuple_contains_all_copied_files(self, tmp_path):
        src = self._make_source(tmp_path)
        td = tmp_path / "targets"
        td.mkdir()

        result = import_source("Proj", "Tgt", src, td)

        assert len(result.imported) >= 3  # app.py, requirements.txt, utils/helpers.py

    def test_blueprint_templates_seeded(self, tmp_path):
        src = self._make_source(tmp_path)
        td = tmp_path / "targets"
        td.mkdir()

        result = import_source("Proj", "Tgt", src, td)

        assert (result.blueprint_dir / "ARCHITECTURE.md").is_file()

    def test_initialized_true_on_first_import(self, tmp_path):
        src = self._make_source(tmp_path)
        td = tmp_path / "targets"
        td.mkdir()

        result = import_source("Proj", "Tgt", src, td)

        assert result.initialized is True

    def test_initialized_false_on_reimport(self, tmp_path):
        src = self._make_source(tmp_path)
        td = tmp_path / "targets"
        td.mkdir()

        import_source("Proj", "Tgt", src, td)
        result2 = import_source("Proj", "Tgt", src, td)

        assert result2.initialized is False

    def test_non_directory_raises(self, tmp_path):
        f = tmp_path / "app.py"
        f.write_text("x = 1\n", encoding="utf-8")
        td = tmp_path / "targets"
        td.mkdir()

        with pytest.raises(SpecificationError, match="must be a directory"):
            import_source("Proj", "Tgt", f, td)

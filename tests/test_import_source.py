"""Unit tests for import_source — fake runner, no API credits spent."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest

from drydock.errors import LlmError, SpecificationError
from drydock.import_source import (
    _collect_source_files,
    _detect_stack,
    _directory_tree,
    import_source,
    parse_file_blocks,
)


@dataclass
class FakeRun:
    ok: bool = True
    text: str = '<file path="ARCHITECTURE.md"># ARCHITECTURE: Test\n</file>'
    execution_id: str = "exec-fake"


def fake_runner(response: FakeRun | None = None):
    run = response or FakeRun()
    seen: list[str] = []

    def _run(prompt, working_directory, **kwargs):
        seen.append(prompt)
        return run

    _run.seen = seen  # type: ignore[attr-defined]
    return _run


# ---------------------------------------------------------------------------
# Stack detection
# ---------------------------------------------------------------------------


class TestDetectStack:
    def test_python_from_requirements(self, tmp_path):
        (tmp_path / "requirements.txt").write_text("flask\n", encoding="utf-8")
        assert "Python" in _detect_stack(tmp_path)

    def test_node_from_package_json(self, tmp_path):
        (tmp_path / "package.json").write_text("{}", encoding="utf-8")
        assert "Node.js" in _detect_stack(tmp_path)

    def test_rust_from_cargo(self, tmp_path):
        (tmp_path / "Cargo.toml").write_text("[package]", encoding="utf-8")
        assert "Rust" in _detect_stack(tmp_path)

    def test_go_from_go_mod(self, tmp_path):
        (tmp_path / "go.mod").write_text("module example.com/m", encoding="utf-8")
        assert "Go" in _detect_stack(tmp_path)

    def test_flask_detected_from_requirements_content(self, tmp_path):
        (tmp_path / "requirements.txt").write_text("Flask==3.0\n", encoding="utf-8")
        hints = _detect_stack(tmp_path)
        assert "Flask" in hints

    def test_empty_directory_returns_empty_list(self, tmp_path):
        assert _detect_stack(tmp_path) == []

    def test_no_duplicate_labels(self, tmp_path):
        (tmp_path / "requirements.txt").write_text("flask\n", encoding="utf-8")
        hints = _detect_stack(tmp_path)
        assert hints.count("Python") == 1


# ---------------------------------------------------------------------------
# Source file collection
# ---------------------------------------------------------------------------


class TestCollectSourceFiles:
    def test_python_files_included(self, tmp_path):
        (tmp_path / "app.py").write_text("x = 1\n", encoding="utf-8")
        items = _collect_source_files(tmp_path)
        labels = [label for label, _ in items]
        assert "app.py" in labels

    def test_venv_excluded(self, tmp_path):
        venv = tmp_path / "venv"
        venv.mkdir()
        (venv / "lib.py").write_text("x = 1\n", encoding="utf-8")
        items = _collect_source_files(tmp_path)
        labels = [label for label, _ in items]
        assert all("venv" not in label for label in labels)

    def test_node_modules_excluded(self, tmp_path):
        nm = tmp_path / "node_modules"
        nm.mkdir()
        (nm / "index.js").write_text("module.exports = {}", encoding="utf-8")
        items = _collect_source_files(tmp_path)
        labels = [label for label, _ in items]
        assert all("node_modules" not in label for label in labels)

    def test_config_files_collected(self, tmp_path):
        (tmp_path / "requirements.txt").write_text("flask\n", encoding="utf-8")
        items = _collect_source_files(tmp_path)
        labels = [label for label, _ in items]
        assert "requirements.txt" in labels

    def test_long_files_capped(self, tmp_path):
        content = "\n".join(f"line {i}" for i in range(300))
        (tmp_path / "big.py").write_text(content, encoding="utf-8")
        items = _collect_source_files(tmp_path)
        _, text = next((label, t) for label, t in items if label == "big.py")
        assert "300 lines total" in text
        assert "showing first 200" in text


# ---------------------------------------------------------------------------
# Directory tree
# ---------------------------------------------------------------------------


class TestDirectoryTree:
    def test_basic_tree(self, tmp_path):
        (tmp_path / "app.py").write_text("x", encoding="utf-8")
        sub = tmp_path / "sub"
        sub.mkdir()
        (sub / "mod.py").write_text("y", encoding="utf-8")
        tree = _directory_tree(tmp_path)
        assert "app.py" in tree
        assert "sub/" in tree

    def test_excluded_dirs_omitted(self, tmp_path):
        (tmp_path / "__pycache__").mkdir()
        tree = _directory_tree(tmp_path)
        assert "__pycache__" not in tree


# ---------------------------------------------------------------------------
# File block parsing
# ---------------------------------------------------------------------------


class TestParseFileBlocks:
    def test_single_block(self):
        text = '<file path="ARCHITECTURE.md"># ARCH\n</file>'
        result = parse_file_blocks(text)
        assert "ARCHITECTURE.md" in result
        assert result["ARCHITECTURE.md"] == "# ARCH"

    def test_multiple_blocks(self):
        text = (
            '<file path="METADATA.md">name: Proj\n</file>\n'
            '<file path="ARCHITECTURE.md"># ARCH\n</file>'
        )
        result = parse_file_blocks(text)
        assert set(result.keys()) == {"METADATA.md", "ARCHITECTURE.md"}

    def test_path_traversal_rejected(self):
        text = '<file path="../../../etc/passwd">evil</file>'
        result = parse_file_blocks(text)
        assert result == {}

    def test_absolute_path_rejected(self):
        text = '<file path="/etc/passwd">evil</file>'
        result = parse_file_blocks(text)
        assert result == {}

    def test_lowercase_filename_rejected(self):
        text = '<file path="architecture.md">content</file>'
        result = parse_file_blocks(text)
        assert result == {}

    def test_valid_feature_filename(self):
        text = '<file path="FEATURE-Auth.md">content</file>'
        result = parse_file_blocks(text)
        assert "FEATURE-Auth.md" in result

    def test_no_blocks_returns_empty(self):
        assert parse_file_blocks("No blocks here.") == {}


# ---------------------------------------------------------------------------
# import_source integration
# ---------------------------------------------------------------------------


class TestImportSource:
    def _make_source(self, tmp_path: Path) -> Path:
        src = tmp_path / "myapp"
        src.mkdir()
        (src / "app.py").write_text("x = 1\n", encoding="utf-8")
        return src

    def test_writes_files_from_llm_output(self, tmp_path):
        src = self._make_source(tmp_path)
        td = tmp_path / "targets"
        td.mkdir()
        response = FakeRun(
            text='<file path="ARCHITECTURE.md"># ARCHITECTURE: Test\n</file>'
        )
        runner = fake_runner(response)

        result = import_source("Proj", "Tgt", src, td, runner=runner)

        assert "ARCHITECTURE.md" in result.files_written
        assert (result.blueprint_dir / "ARCHITECTURE.md").is_file()

    def test_root_template_written_to_target_dir(self, tmp_path):
        src = self._make_source(tmp_path)
        td = tmp_path / "targets"
        td.mkdir()
        response = FakeRun(
            text='<file path="METADATA.md">name: Proj\n</file>'
        )

        result = import_source("Proj", "Tgt", src, td, runner=fake_runner(response))

        # METADATA.md is a root template — goes to target_dir, not blueprint_dir
        target_dir = td / "Tgt"
        assert (target_dir / "METADATA.md").is_file()
        assert "METADATA.md" in result.files_written

    def test_runner_failure_raises_llm_error(self, tmp_path):
        src = self._make_source(tmp_path)
        td = tmp_path / "targets"
        td.mkdir()
        response = FakeRun(ok=False, text="", execution_id="bad-exec")

        with pytest.raises(LlmError, match="import_source"):
            import_source("Proj", "Tgt", src, td, runner=fake_runner(response))

    def test_empty_output_raises_specification_error(self, tmp_path):
        src = self._make_source(tmp_path)
        td = tmp_path / "targets"
        td.mkdir()
        response = FakeRun(text="No blocks produced.")

        with pytest.raises(SpecificationError, match="no <file"):
            import_source("Proj", "Tgt", src, td, runner=fake_runner(response))

    def test_non_directory_source_raises(self, tmp_path):
        file_src = tmp_path / "app.py"
        file_src.write_text("x = 1\n", encoding="utf-8")
        td = tmp_path / "targets"
        td.mkdir()

        with pytest.raises(SpecificationError, match="must be a directory"):
            import_source("Proj", "Tgt", file_src, td)

    def test_prompt_contains_project_name(self, tmp_path):
        src = self._make_source(tmp_path)
        td = tmp_path / "targets"
        td.mkdir()
        runner = fake_runner()

        import_source("UniqueProjectXYZ", "Tgt", src, td, runner=runner)

        assert runner.seen
        assert "UniqueProjectXYZ" in runner.seen[0]

    def test_blueprint_templates_seeded(self, tmp_path):
        src = self._make_source(tmp_path)
        td = tmp_path / "targets"
        td.mkdir()
        response = FakeRun(
            text='<file path="ARCHITECTURE.md"># ARCH\n</file>'
        )

        result = import_source("Proj", "Tgt", src, td, runner=fake_runner(response))

        # init_specification should have run
        assert result.blueprint_dir.is_dir()

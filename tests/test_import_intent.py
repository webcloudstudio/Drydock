"""Tests for drydock import --format intent (COMPASS.md seeding)."""

from __future__ import annotations

import subprocess
import sys

import pytest

from drydock.compass_sources import compass_import_pending
from drydock.errors import SpecificationError
from drydock.import_markdown import import_intent


class TestImportIntent:
    def test_copies_source_to_compass_md(self, tmp_path):
        source = tmp_path / "brief.md"
        source.write_text("# My Project\nThis is the intent.", encoding="utf-8")
        target_dir = tmp_path / "targets"

        result = import_intent("MyTarget", source, target_dir)

        dest = result.blueprint_dir / "COMPASS.md"
        assert dest.exists()
        assert dest.read_text(encoding="utf-8") == "# My Project\nThis is the intent."
        assert compass_import_pending(result.blueprint_dir)

    def test_result_has_correct_fields(self, tmp_path):
        source = tmp_path / "brief.md"
        source.write_text("content", encoding="utf-8")
        target_dir = tmp_path / "targets"

        result = import_intent("Tgt", source, target_dir)

        assert result.target == "Tgt"
        assert result.blueprint_dir == target_dir / "Tgt"
        assert len(result.imported) == 1
        assert result.imported[0].name == "COMPASS.md"

    def test_creates_blueprint_dir_if_absent(self, tmp_path):
        source = tmp_path / "brief.md"
        source.write_text("content", encoding="utf-8")
        target_dir = tmp_path / "targets"

        result = import_intent("NewTarget", source, target_dir)

        assert result.blueprint_dir.is_dir()

    def test_overwrites_existing_compass(self, tmp_path):
        source = tmp_path / "brief.md"
        source.write_text("new content", encoding="utf-8")
        target_dir = tmp_path / "targets"
        bp = target_dir / "MyTarget"
        bp.mkdir(parents=True)
        (bp / "COMPASS.md").write_text("old content", encoding="utf-8")

        result = import_intent("MyTarget", source, target_dir)

        assert (result.blueprint_dir / "COMPASS.md").read_text(encoding="utf-8") == "new content"

    def test_missing_source_raises(self, tmp_path):
        target_dir = tmp_path / "targets"
        with pytest.raises(SpecificationError, match="not found"):
            import_intent("MyTarget", tmp_path / "nonexistent.md", target_dir)

    def test_directory_source_raises(self, tmp_path):
        target_dir = tmp_path / "targets"
        source = tmp_path / "compass"
        source.mkdir()

        with pytest.raises(SpecificationError, match="Compass import requires a file"):
            import_intent("MyTarget", source, target_dir)

    def test_accepts_txt_source(self, tmp_path):
        source = tmp_path / "brief.txt"
        source.write_text("plain text brief", encoding="utf-8")
        target_dir = tmp_path / "targets"

        result = import_intent("MyTarget", source, target_dir)

        assert (result.blueprint_dir / "COMPASS.md").exists()


class TestImportIntentCli:
    def test_intent_format_accepted(self, tmp_path):
        source = tmp_path / "brief.md"
        source.write_text("# COMPASS: Test\n\n## Compass\nTest project.", encoding="utf-8")

        import os

        env = os.environ.copy()
        env["DRYDOCK_WORKSPACE"] = str(tmp_path / "ws")
        env["XDG_CONFIG_HOME"] = str(tmp_path / "config")

        r = subprocess.run(
            [
                sys.executable,
                "-m",
                "drydock",
                "import",
                "MyTarget",
                str(source),
                "--format",
                "intent",
            ],
            capture_output=True,
            text=True,
            env=env,
        )
        assert r.returncode == 0
        assert "COMPASS.md" in r.stdout
        assert "Edit it to match the required format" not in r.stdout

    def test_compass_format_accepted(self, tmp_path):
        source = tmp_path / "brief.md"
        source.write_text("# COMPASS\n", encoding="utf-8")

        import os

        env = os.environ.copy()
        env["DRYDOCK_WORKSPACE"] = str(tmp_path / "ws")
        env["XDG_CONFIG_HOME"] = str(tmp_path / "config")

        r = subprocess.run(
            [
                sys.executable,
                "-m",
                "drydock",
                "import",
                "MyTarget",
                str(source),
                "--format",
                "compass",
            ],
            capture_output=True,
            text=True,
            env=env,
        )
        assert r.returncode == 0
        assert "COMPASS.md" in r.stdout

    def test_compass_format_accepts_force(self, tmp_path):
        source = tmp_path / "brief.md"
        source.write_text("# COMPASS\n", encoding="utf-8")

        import os

        env = os.environ.copy()
        env["DRYDOCK_WORKSPACE"] = str(tmp_path / "ws")
        env["XDG_CONFIG_HOME"] = str(tmp_path / "config")

        r = subprocess.run(
            [
                sys.executable,
                "-m",
                "drydock",
                "import",
                "MyTarget",
                str(source),
                "--format",
                "compass",
                "--force",
            ],
            capture_output=True,
            text=True,
            env=env,
        )
        assert r.returncode == 0
        assert "COMPASS.md" in r.stdout

    def test_intent_in_help(self):
        r = subprocess.run(
            [sys.executable, "-m", "drydock", "import", "--help"],
            capture_output=True,
            text=True,
        )
        assert "intent" in r.stdout or "intent" in r.stderr

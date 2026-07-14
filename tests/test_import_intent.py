"""Tests for drydock import --format compass/intent (LLM-normalized COMPASS.md)."""

from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass

import pytest

from drydock.compass_sources import compass_import_pending, mark_compass_imported
from drydock.errors import DrydockError, SpecificationError
from drydock.import_markdown import import_intent

_NORMALIZED = (
    "=== COMPASS.md ===\n"
    "# COMPASS: MyTarget\n"
    "\n"
    "## Compass\n"
    "A trust and interoperability platform for software projects.\n"
    "\n"
    "## Constraints\n"
    "- None stated.\n"
    "\n"
    "## Guardrails\n"
    "- None stated.\n"
    "=== END COMPASS.md ===\n"
)


@dataclass
class FakeRun:
    ok: bool = True
    text: str = _NORMALIZED
    execution_id: str = "exec-fake"


class TestImportIntent:
    def test_writes_normalized_compass_md(self, tmp_path):
        source = tmp_path / "brief.md"
        source.write_text("# My Project\nThis is the intent.", encoding="utf-8")
        target_dir = tmp_path / "targets"

        result = import_intent("MyTarget", source, target_dir, runner=lambda *a, **k: FakeRun())

        dest = result.blueprint_dir / "COMPASS.md"
        assert dest.exists()
        text = dest.read_text(encoding="utf-8")
        assert text.startswith("# COMPASS: MyTarget")
        assert "trust and interoperability platform" in text
        assert not compass_import_pending(result.blueprint_dir)

    def test_prompt_contains_intent_and_target(self, tmp_path):
        source = tmp_path / "brief.md"
        source.write_text("the commander's exact wording", encoding="utf-8")
        target_dir = tmp_path / "targets"
        prompts: list[str] = []

        def runner(prompt, *a, **k):
            prompts.append(prompt)
            return FakeRun()

        import_intent("MyTarget", source, target_dir, runner=runner)

        assert len(prompts) == 1
        assert "the commander's exact wording" in prompts[0]
        assert "TARGET_NAME: MyTarget" in prompts[0]

    def test_result_has_correct_fields(self, tmp_path):
        source = tmp_path / "brief.md"
        source.write_text("content", encoding="utf-8")
        target_dir = tmp_path / "targets"

        result = import_intent("Tgt", source, target_dir, runner=lambda *a, **k: FakeRun())

        assert result.target == "Tgt"
        assert result.blueprint_dir == target_dir / "Tgt"
        assert len(result.imported) == 1
        assert result.imported[0].name == "COMPASS.md"

    def test_creates_blueprint_dir_if_absent(self, tmp_path):
        source = tmp_path / "brief.md"
        source.write_text("content", encoding="utf-8")
        target_dir = tmp_path / "targets"

        result = import_intent("NewTarget", source, target_dir, runner=lambda *a, **k: FakeRun())

        assert result.blueprint_dir.is_dir()

    def test_existing_compass_requires_force(self, tmp_path):
        source = tmp_path / "brief.md"
        source.write_text("new content", encoding="utf-8")
        target_dir = tmp_path / "targets"
        bp = target_dir / "MyTarget"
        bp.mkdir(parents=True)
        (bp / "COMPASS.md").write_text("old content", encoding="utf-8")

        with pytest.raises(SpecificationError, match="--force"):
            import_intent("MyTarget", source, target_dir, runner=lambda *a, **k: FakeRun())

    def test_force_overwrites_existing_compass(self, tmp_path):
        source = tmp_path / "brief.md"
        source.write_text("new content", encoding="utf-8")
        target_dir = tmp_path / "targets"
        bp = target_dir / "MyTarget"
        bp.mkdir(parents=True)
        (bp / "COMPASS.md").write_text("old content", encoding="utf-8")

        result = import_intent(
            "MyTarget", source, target_dir, force=True, runner=lambda *a, **k: FakeRun()
        )

        text = (result.blueprint_dir / "COMPASS.md").read_text(encoding="utf-8")
        assert "old content" not in text
        assert text.startswith("# COMPASS: MyTarget")

    def test_force_clears_stale_pending_marker(self, tmp_path):
        source = tmp_path / "brief.md"
        source.write_text("new content", encoding="utf-8")
        target_dir = tmp_path / "targets"
        bp = target_dir / "MyTarget"
        bp.mkdir(parents=True)
        (bp / "COMPASS.md").write_text("old content", encoding="utf-8")
        mark_compass_imported(bp, source)

        import_intent("MyTarget", source, target_dir, force=True, runner=lambda *a, **k: FakeRun())

        assert not compass_import_pending(bp)

    def test_llm_failure_raises_and_preserves_existing_compass(self, tmp_path):
        source = tmp_path / "brief.md"
        source.write_text("new content", encoding="utf-8")
        target_dir = tmp_path / "targets"
        bp = target_dir / "MyTarget"
        bp.mkdir(parents=True)
        (bp / "COMPASS.md").write_text("old content", encoding="utf-8")

        with pytest.raises(SpecificationError, match="LLM execution failed"):
            import_intent(
                "MyTarget",
                source,
                target_dir,
                force=True,
                runner=lambda *a, **k: FakeRun(ok=False, text=""),
            )

        assert (bp / "COMPASS.md").read_text(encoding="utf-8") == "old content"

    def test_missing_compass_block_raises(self, tmp_path):
        source = tmp_path / "brief.md"
        source.write_text("content", encoding="utf-8")
        target_dir = tmp_path / "targets"

        with pytest.raises(DrydockError):
            import_intent(
                "MyTarget",
                source,
                target_dir,
                runner=lambda *a, **k: FakeRun(text="I could not produce a compass."),
            )

        assert not (target_dir / "MyTarget" / "COMPASS.md").exists()

    def test_missing_source_raises(self, tmp_path):
        target_dir = tmp_path / "targets"
        with pytest.raises(SpecificationError, match="not found"):
            import_intent(
                "MyTarget",
                tmp_path / "nonexistent.md",
                target_dir,
                runner=lambda *a, **k: FakeRun(),
            )

    def test_directory_source_raises(self, tmp_path):
        target_dir = tmp_path / "targets"
        source = tmp_path / "compass"
        source.mkdir()

        with pytest.raises(SpecificationError, match="Compass import requires a file"):
            import_intent("MyTarget", source, target_dir, runner=lambda *a, **k: FakeRun())

    def test_empty_source_raises(self, tmp_path):
        source = tmp_path / "brief.md"
        source.write_text("   \n", encoding="utf-8")
        target_dir = tmp_path / "targets"

        with pytest.raises(SpecificationError, match="empty"):
            import_intent("MyTarget", source, target_dir, runner=lambda *a, **k: FakeRun())

    def test_accepts_txt_source(self, tmp_path):
        source = tmp_path / "brief.txt"
        source.write_text("plain text brief", encoding="utf-8")
        target_dir = tmp_path / "targets"

        result = import_intent("MyTarget", source, target_dir, runner=lambda *a, **k: FakeRun())

        assert (result.blueprint_dir / "COMPASS.md").exists()


class TestImportIntentCli:
    def _run_main(self, monkeypatch, tmp_path, fmt, extra_args=()):
        import drydock.import_markdown as im
        from drydock.cli import main

        source = tmp_path / "brief.md"
        source.write_text("# My Project\nThis is the intent.", encoding="utf-8")
        monkeypatch.setenv("DRYDOCK_WORKSPACE", str(tmp_path / "ws"))
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
        monkeypatch.setattr(im, "run_prompt", lambda *a, **k: FakeRun())

        argv = ["import", "MyTarget", str(source), "--format", fmt, *extra_args]
        try:
            main(argv)
        except SystemExit as exc:
            return exc.code or 0
        return 0

    def test_intent_format_accepted(self, monkeypatch, tmp_path, capsys):
        rc = self._run_main(monkeypatch, tmp_path, "intent")
        assert rc == 0
        assert "COMPASS.md" in capsys.readouterr().out

    def test_compass_format_accepted(self, monkeypatch, tmp_path, capsys):
        rc = self._run_main(monkeypatch, tmp_path, "compass")
        assert rc == 0
        out = capsys.readouterr().out
        assert "COMPASS.md" in out
        assert "normalized" in out

    def test_compass_format_accepts_force(self, monkeypatch, tmp_path, capsys):
        rc = self._run_main(monkeypatch, tmp_path, "compass", extra_args=("--force",))
        assert rc == 0
        assert "COMPASS.md" in capsys.readouterr().out

    def test_intent_in_help(self):
        r = subprocess.run(
            [sys.executable, "-m", "drydock", "import", "--help"],
            capture_output=True,
            text=True,
        )
        assert "intent" in r.stdout or "intent" in r.stderr

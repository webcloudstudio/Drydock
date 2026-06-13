"""Unit tests for import_speckit — fake runner, no API credits spent."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest

from drydock.errors import LlmError, SpecificationError
from drydock.import_speckit import (
    _discover_speckit,
    import_speckit,
)


@dataclass
class FakeRun:
    ok: bool = True
    text: str = (
        '<file path="COMPASS.md"># COMPASS: Test\n</file>\n'
        '<file path="FEATURE-Auth.md"># FEATURE: Auth\n</file>\n'
        "<conversion-report>\n# Spec Kit Conversion Report\n\n## Mapped\n- All mapped.\n</conversion-report>"
    )
    execution_id: str = "exec-fake"


def fake_runner(response: FakeRun | None = None):
    run = response or FakeRun()
    seen: list[str] = []

    def _run(prompt, working_directory, **kwargs):
        seen.append(prompt)
        return run

    _run.seen = seen  # type: ignore[attr-defined]
    return _run


def _make_speckit(root: Path, features: dict[str, dict[str, str]] | None = None) -> Path:
    """Create a minimal Spec Kit project directory."""
    specify = root / ".specify" / "memory"
    specify.mkdir(parents=True)
    (specify / "constitution.md").write_text("# Constitution\n\nProject intent.\n", encoding="utf-8")
    if features:
        for name, files in features.items():
            fdir = root / "specs" / name
            fdir.mkdir(parents=True)
            for fname, content in files.items():
                (fdir / fname).write_text(content, encoding="utf-8")
    return root


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------


class TestDiscoverSpecKit:
    def test_finds_constitution(self, tmp_path):
        src = _make_speckit(tmp_path / "sk")
        constitution, features = _discover_speckit(src)
        assert constitution is not None
        assert "Project intent." in constitution

    def test_finds_features(self, tmp_path):
        src = _make_speckit(
            tmp_path / "sk",
            features={
                "auth": {"spec.md": "# Auth spec\n"},
                "billing": {"spec.md": "# Billing spec\n"},
            },
        )
        _, features = _discover_speckit(src)
        names = [f.name for f in features]
        assert "auth" in names
        assert "billing" in names

    def test_feature_files_read_correctly(self, tmp_path):
        src = _make_speckit(
            tmp_path / "sk",
            features={
                "auth": {
                    "spec.md": "# Auth\n",
                    "plan.md": "# Plan\n",
                    "research.md": "# Research\n",
                    "data-model.md": "# Data\n",
                    "quickstart.md": "# Quick\n",
                }
            },
        )
        _, features = _discover_speckit(src)
        auth = next(f for f in features if f.name == "auth")
        assert auth.spec == "# Auth"
        assert auth.plan == "# Plan"
        assert auth.research == "# Research"
        assert auth.data_model == "# Data"
        assert auth.quickstart == "# Quick"

    def test_contracts_discovered(self, tmp_path):
        src = _make_speckit(
            tmp_path / "sk",
            features={"auth": {}},
        )
        contracts_dir = src / "specs" / "auth" / "contracts"
        contracts_dir.mkdir()
        (contracts_dir / "auth.yaml").write_text("paths: /login\n", encoding="utf-8")

        _, features = _discover_speckit(src)
        auth = next(f for f in features if f.name == "auth")
        assert "auth.yaml" in auth.contracts

    def test_missing_specify_dir_raises(self, tmp_path):
        with pytest.raises(SpecificationError, match="Not a Spec Kit project"):
            _discover_speckit(tmp_path / "notsk")

    def test_no_constitution_returns_none(self, tmp_path):
        src = tmp_path / "sk"
        (src / ".specify" / "memory").mkdir(parents=True)
        # No constitution.md written
        constitution, _ = _discover_speckit(src)
        assert constitution is None


# ---------------------------------------------------------------------------
# import_speckit integration
# ---------------------------------------------------------------------------


class TestImportSpecKit:
    def _make_src(self, tmp_path: Path) -> Path:
        return _make_speckit(
            tmp_path / "sk",
            features={"auth": {"spec.md": "# Auth\n\nLogin and logout.\n"}},
        )

    def test_writes_blueprint_files_from_llm_output(self, tmp_path):
        src = self._make_src(tmp_path)
        td = tmp_path / "targets"
        td.mkdir()

        result = import_speckit("Proj", "Tgt", src, td, runner=fake_runner())

        assert "COMPASS.md" in result.files_written
        assert "FEATURE-Auth.md" in result.files_written
        # COMPASS.md is a root template — goes to target_dir, not blueprint_dir
        target_dir = result.blueprint_dir.parent
        assert (target_dir / "COMPASS.md").is_file()
        assert (result.blueprint_dir / "FEATURE-Auth.md").is_file()

    def test_conversion_report_always_written(self, tmp_path):
        src = self._make_src(tmp_path)
        td = tmp_path / "targets"
        td.mkdir()

        result = import_speckit("Proj", "Tgt", src, td, runner=fake_runner())

        assert result.conversion_report.is_file()
        text = result.conversion_report.read_text(encoding="utf-8")
        assert "Spec Kit Conversion Report" in text

    def test_conversion_report_written_even_on_empty_files(self, tmp_path):
        src = self._make_src(tmp_path)
        td = tmp_path / "targets"
        td.mkdir()
        response = FakeRun(
            text="<conversion-report>\n# Report\n\n## Mapped\n- nothing\n</conversion-report>",
            ok=True,
        )

        with pytest.raises(SpecificationError, match="no <file"):
            import_speckit("Proj", "Tgt", src, td, runner=fake_runner(response))

        # Report was still written
        report = td / "Tgt" / "blueprint" / "sources" / "speckit_conversion_report.md"
        assert report.is_file()

    def test_runner_failure_raises_llm_error(self, tmp_path):
        src = self._make_src(tmp_path)
        td = tmp_path / "targets"
        td.mkdir()
        response = FakeRun(ok=False, text="", execution_id="bad-exec")

        with pytest.raises(LlmError, match="import_speckit"):
            import_speckit("Proj", "Tgt", src, td, runner=fake_runner(response))

    def test_non_speckit_source_raises(self, tmp_path):
        src = tmp_path / "notsk"
        src.mkdir()
        td = tmp_path / "targets"
        td.mkdir()

        with pytest.raises(SpecificationError, match="Not a Spec Kit project"):
            import_speckit("Proj", "Tgt", src, td)

    def test_features_found_reported(self, tmp_path):
        src = _make_speckit(
            tmp_path / "sk",
            features={"auth": {"spec.md": "# Auth\n"}, "billing": {}},
        )
        td = tmp_path / "targets"
        td.mkdir()

        result = import_speckit("Proj", "Tgt", src, td, runner=fake_runner())

        assert "auth" in result.features_found
        assert "billing" in result.features_found

    def test_prompt_contains_constitution(self, tmp_path):
        src = self._make_src(tmp_path)
        td = tmp_path / "targets"
        td.mkdir()
        runner = fake_runner()

        import_speckit("Proj", "Tgt", src, td, runner=runner)

        assert runner.seen
        assert "constitution.md" in runner.seen[0]

    def test_blueprint_templates_seeded(self, tmp_path):
        src = self._make_src(tmp_path)
        td = tmp_path / "targets"
        td.mkdir()

        result = import_speckit("Proj", "Tgt", src, td, runner=fake_runner())

        assert result.blueprint_dir.is_dir()

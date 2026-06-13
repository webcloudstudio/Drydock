"""Unit tests for import_speckit — file copy, no LLM calls."""

from __future__ import annotations

import pytest

from drydock.errors import SpecificationError
from drydock.import_speckit import discover_speckit, import_speckit


def _make_speckit(root, features=None):
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
        constitution, _ = discover_speckit(src)
        assert constitution is not None
        assert "Project intent." in constitution

    def test_finds_features(self, tmp_path):
        src = _make_speckit(
            tmp_path / "sk",
            features={"auth": {"spec.md": "# Auth\n"}, "billing": {"spec.md": "# Billing\n"}},
        )
        _, features = discover_speckit(src)
        assert {f.name for f in features} == {"auth", "billing"}

    def test_feature_fields_populated(self, tmp_path):
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
        _, features = discover_speckit(src)
        auth = next(f for f in features if f.name == "auth")
        assert auth.spec == "# Auth"
        assert auth.plan == "# Plan"
        assert auth.research == "# Research"
        assert auth.data_model == "# Data"
        assert auth.quickstart == "# Quick"

    def test_contracts_discovered(self, tmp_path):
        src = _make_speckit(tmp_path / "sk", features={"auth": {}})
        contracts_dir = src / "specs" / "auth" / "contracts"
        contracts_dir.mkdir()
        (contracts_dir / "auth.yaml").write_text("paths: /login\n", encoding="utf-8")

        _, features = discover_speckit(src)
        auth = next(f for f in features if f.name == "auth")
        assert "auth.yaml" in auth.contracts

    def test_missing_specify_dir_raises(self, tmp_path):
        with pytest.raises(SpecificationError, match="Not a Spec Kit project"):
            discover_speckit(tmp_path / "notsk")

    def test_no_constitution_returns_none(self, tmp_path):
        src = tmp_path / "sk"
        (src / ".specify" / "memory").mkdir(parents=True)
        constitution, _ = discover_speckit(src)
        assert constitution is None


# ---------------------------------------------------------------------------
# import_speckit
# ---------------------------------------------------------------------------


class TestImportSpecKit:
    def _make_src(self, tmp_path):
        return _make_speckit(
            tmp_path / "sk",
            features={"auth": {"spec.md": "# Auth\n\nLogin and logout.\n"}},
        )

    def test_copies_specify_dir_to_sources(self, tmp_path):
        src = self._make_src(tmp_path)
        td = tmp_path / "targets"
        td.mkdir()

        result = import_speckit("Proj", "Tgt", src, td)

        sources = result.blueprint_dir / "sources"
        assert (sources / ".specify" / "memory" / "constitution.md").is_file()

    def test_copies_specs_dir_to_sources(self, tmp_path):
        src = self._make_src(tmp_path)
        td = tmp_path / "targets"
        td.mkdir()

        result = import_speckit("Proj", "Tgt", src, td)

        sources = result.blueprint_dir / "sources"
        assert (sources / "specs" / "auth" / "spec.md").is_file()

    def test_drydock_import_marker_written(self, tmp_path):
        src = self._make_src(tmp_path)
        td = tmp_path / "targets"
        td.mkdir()

        result = import_speckit("Proj", "Tgt", src, td)

        marker = result.blueprint_dir / "sources" / ".drydock-import"
        assert marker.is_file()
        text = marker.read_text(encoding="utf-8")
        assert "format: speckit" in text

    def test_features_found_reported(self, tmp_path):
        src = _make_speckit(
            tmp_path / "sk",
            features={"auth": {"spec.md": "# A\n"}, "billing": {}},
        )
        td = tmp_path / "targets"
        td.mkdir()

        result = import_speckit("Proj", "Tgt", src, td)

        assert "auth" in result.features_found
        assert "billing" in result.features_found

    def test_blueprint_templates_seeded(self, tmp_path):
        src = self._make_src(tmp_path)
        td = tmp_path / "targets"
        td.mkdir()

        result = import_speckit("Proj", "Tgt", src, td)

        assert (result.blueprint_dir / "ARCHITECTURE.md").is_file()

    def test_initialized_true_on_first_import(self, tmp_path):
        src = self._make_src(tmp_path)
        td = tmp_path / "targets"
        td.mkdir()

        result = import_speckit("Proj", "Tgt", src, td)

        assert result.initialized is True

    def test_non_speckit_source_raises(self, tmp_path):
        src = tmp_path / "notsk"
        src.mkdir()
        td = tmp_path / "targets"
        td.mkdir()

        with pytest.raises(SpecificationError, match="Not a Spec Kit project"):
            import_speckit("Proj", "Tgt", src, td)

"""Tests for drydock.init_specification."""

from __future__ import annotations

import pytest

from drydock.errors import SpecificationError
from drydock.init_specification import (
    FileOutcome,
    InitResult,
    _derive_display_name,
    _validate_spec_name,
    init_specification,
)


class TestValidateSpecName:
    def test_valid_name(self):
        _validate_spec_name("MyProject")

    def test_valid_hyphen_name(self):
        _validate_spec_name("my-cool-project")

    def test_valid_underscore_name(self):
        _validate_spec_name("my_project")

    def test_empty_name_raises(self):
        with pytest.raises(SpecificationError):
            _validate_spec_name("")

    def test_slash_raises(self):
        with pytest.raises(SpecificationError):
            _validate_spec_name("foo/bar")

    def test_backslash_raises(self):
        with pytest.raises(SpecificationError):
            _validate_spec_name("foo\\bar")

    def test_dotdot_raises(self):
        with pytest.raises(SpecificationError):
            _validate_spec_name("../evil")

    def test_dotdot_embedded_raises(self):
        with pytest.raises(SpecificationError):
            _validate_spec_name("foo/../bar")

    def test_too_long_raises(self):
        with pytest.raises(SpecificationError):
            _validate_spec_name("a" * 201)


class TestDeriveDisplayName:
    def test_simple(self):
        assert _derive_display_name("myproject") == "Myproject"

    def test_hyphen(self):
        assert _derive_display_name("my-project") == "My Project"

    def test_underscore(self):
        assert _derive_display_name("my_project") == "My Project"

    def test_mixed(self):
        assert _derive_display_name("my-cool_project") == "My Cool Project"

    def test_consecutive_separators(self):
        assert _derive_display_name("my--project") == "My Project"


class TestInitSpecification:
    def test_creates_directory(self, tmp_spec_root):
        init_specification("NewSpec", tmp_spec_root)
        assert (tmp_spec_root / "NewSpec").is_dir()

    def test_creates_metadata(self, tmp_spec_root):
        init_specification("NewSpec", tmp_spec_root)
        assert (tmp_spec_root / "NewSpec" / "METADATA.md").exists()

    def test_returns_init_result(self, tmp_spec_root):
        result = init_specification("NewSpec", tmp_spec_root)
        assert isinstance(result, InitResult)
        assert result.spec_name == "NewSpec"

    def test_created_outcomes(self, tmp_spec_root):
        result = init_specification("NewSpec", tmp_spec_root)
        assert len(result.created()) > 0
        assert len(result.skipped()) == 0

    def test_token_replacement(self, tmp_spec_root):
        init_specification("TestProject", tmp_spec_root)
        metadata = (tmp_spec_root / "TestProject" / "METADATA.md").read_text()
        assert "__PROJECT_NAME__" not in metadata
        assert "__PROJECT_SLUG__" not in metadata
        assert "TestProject" in metadata

    def test_display_name_token(self, tmp_spec_root):
        init_specification("my-project", tmp_spec_root)
        metadata = (tmp_spec_root / "my-project" / "METADATA.md").read_text()
        assert "My Project" in metadata

    def test_metadata_does_not_store_configured_root_paths(self, tmp_spec_root):
        init_specification("Spec", tmp_spec_root)
        metadata = (tmp_spec_root / "Spec" / "METADATA.md").read_text()
        assert "specification_directory:" not in metadata
        assert "blueprint_directory:" not in metadata

    def test_existing_dir_raises_by_default(self, tmp_spec_root):
        init_specification("Spec", tmp_spec_root)
        with pytest.raises(SpecificationError, match="already exists"):
            init_specification("Spec", tmp_spec_root)

    def test_update_skips_existing(self, tmp_spec_root):
        init_specification("Spec", tmp_spec_root)
        meta = tmp_spec_root / "Spec" / "METADATA.md"
        meta.read_text()  # read before modification
        meta.write_text("MODIFIED")
        result = init_specification("Spec", tmp_spec_root, update=True)
        assert meta.read_text() == "MODIFIED"
        assert FileOutcome.SKIPPED in [o for _, o in result.outcomes]

    def test_force_overwrites(self, tmp_spec_root):
        init_specification("Spec", tmp_spec_root)
        meta = tmp_spec_root / "Spec" / "METADATA.md"
        meta.write_text("MODIFIED")
        result = init_specification("Spec", tmp_spec_root, force=True)
        assert meta.read_text() != "MODIFIED"
        assert FileOutcome.UPDATED in [o for _, o in result.outcomes]

    def test_invalid_name_raises(self, tmp_spec_root):
        with pytest.raises(SpecificationError):
            init_specification("../evil", tmp_spec_root)

    def test_utf8_output(self, tmp_spec_root):
        init_specification("Spec", tmp_spec_root)
        for f in (tmp_spec_root / "Spec").glob("*.md"):
            text = f.read_text(encoding="utf-8")
            assert isinstance(text, str)

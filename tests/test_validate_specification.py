"""Tests for drydock.validate_specification."""

from __future__ import annotations

from pathlib import Path

from drydock.init_specification import init_specification
from drydock.validate_specification import Severity, validate_specification


def _init(spec_root: Path, name: str = "TestProject") -> Path:
    init_specification(name, spec_root)
    return spec_root / name


class TestPostInitValidation:
    """After a fresh init, validate must pass (warnings allowed, no failures)."""

    def test_no_failures_after_init(self, tmp_spec_root):
        _init(tmp_spec_root)
        result = validate_specification("TestProject", tmp_spec_root)
        assert not result.has_failures(), [f.message for f in result.failures()]

    def test_exit_code_zero_after_init(self, tmp_spec_root):
        _init(tmp_spec_root)
        result = validate_specification("TestProject", tmp_spec_root)
        assert result.exit_code() == 0

    def test_result_has_findings(self, tmp_spec_root):
        _init(tmp_spec_root)
        result = validate_specification("TestProject", tmp_spec_root)
        assert len(result.findings) > 0


class TestMissingFiles:
    def test_missing_metadata_is_failure(self, tmp_spec_root):
        spec_dir = _init(tmp_spec_root)
        (spec_dir / "METADATA.md").unlink()
        result = validate_specification("TestProject", tmp_spec_root)
        assert result.has_failures()

    def test_missing_architecture_is_failure(self, tmp_spec_root):
        spec_dir = _init(tmp_spec_root)
        (spec_dir / "ARCHITECTURE.md").unlink()
        result = validate_specification("TestProject", tmp_spec_root)
        assert result.has_failures()

    def test_missing_readme_is_failure(self, tmp_spec_root):
        spec_dir = _init(tmp_spec_root)
        (spec_dir / "README.md").unlink()
        result = validate_specification("TestProject", tmp_spec_root)
        assert result.has_failures()


class TestNonExistentSpec:
    def test_nonexistent_dir_is_failure(self, tmp_spec_root):
        result = validate_specification("DoesNotExist", tmp_spec_root)
        assert result.has_failures()
        assert result.exit_code() == 1


class TestVerbose:
    def test_verbose_includes_passes(self, tmp_spec_root):
        _init(tmp_spec_root)
        result = validate_specification("TestProject", tmp_spec_root, verbose=True)
        passes = result.passes()
        assert len(passes) > 0

    def test_non_verbose_result_still_has_passes(self, tmp_spec_root):
        # verbose controls display only; the result object always collects all findings
        _init(tmp_spec_root)
        result_nv = validate_specification("TestProject", tmp_spec_root, verbose=False)
        result_vb = validate_specification("TestProject", tmp_spec_root, verbose=True)
        # Both collect the same set of findings
        assert len(result_nv.passes()) == len(result_vb.passes())
        assert len(result_nv.passes()) > 0


class TestMetadataFields:
    def test_name_mismatch_is_failure(self, tmp_spec_root):
        _init(tmp_spec_root, "TestProject")
        meta = tmp_spec_root / "TestProject" / "METADATA.md"
        content = meta.read_text()
        meta.write_text(content.replace("name: TestProject", "name: WrongName"))
        result = validate_specification("TestProject", tmp_spec_root)
        assert result.has_failures()

    def test_invalid_status_is_failure(self, tmp_spec_root):
        _init(tmp_spec_root)
        meta = tmp_spec_root / "TestProject" / "METADATA.md"
        content = meta.read_text()
        meta.write_text(content.replace("status: IDEA", "status: BADVALUE"))
        result = validate_specification("TestProject", tmp_spec_root)
        assert result.has_failures()


class TestExampleFileWarnings:
    def test_screen_example_warns(self, tmp_spec_root):
        _init(tmp_spec_root)
        result = validate_specification("TestProject", tmp_spec_root)
        warn_msgs = [f.message for f in result.warnings()]
        example_warns = [m for m in warn_msgs if "Example" in m]
        assert len(example_warns) > 0

    def test_no_example_files_no_warn(self, tmp_spec_root):
        spec_dir = _init(tmp_spec_root)
        for ex in ("SCREEN-Example.md", "FEATURE-Example.md", "UI-Component-Example.md"):
            fp = spec_dir / ex
            if fp.exists():
                fp.unlink()
        result = validate_specification("TestProject", tmp_spec_root)
        warn_msgs = [f.message for f in result.findings if f.severity == Severity.WARN]
        example_warns = [m for m in warn_msgs if "Example" in m and "template" in m.lower()]
        assert len(example_warns) == 0


class TestResultStructure:
    def test_result_has_spec_name(self, tmp_spec_root):
        _init(tmp_spec_root)
        result = validate_specification("TestProject", tmp_spec_root)
        assert result.spec_name == "TestProject"

    def test_result_has_spec_dir(self, tmp_spec_root):
        _init(tmp_spec_root)
        result = validate_specification("TestProject", tmp_spec_root)
        assert result.spec_dir == tmp_spec_root / "TestProject"

    def test_findings_have_sections(self, tmp_spec_root):
        _init(tmp_spec_root)
        result = validate_specification("TestProject", tmp_spec_root, verbose=True)
        assert all(f.section for f in result.findings)

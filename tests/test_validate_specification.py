"""Tests for drydock.validate_specification."""

from __future__ import annotations

from pathlib import Path

from drydock.init_specification import init_specification
from drydock.validate_specification import Severity, validate_specification


def _init(target_root: Path, name: str = "TestProject") -> Path:
    target_dir = target_root / name
    init_specification(name, target_dir)
    return target_dir


class TestPostInitValidation:
    """After a fresh init, validate must pass (warnings allowed, no failures)."""

    def test_no_failures_after_init(self, tmp_target_root):
        target_dir = _init(tmp_target_root)
        result = validate_specification("TestProject", target_dir)
        assert not result.has_failures(), [f.message for f in result.failures()]

    def test_exit_code_zero_after_init(self, tmp_target_root):
        target_dir = _init(tmp_target_root)
        result = validate_specification("TestProject", target_dir)
        assert result.exit_code() == 0

    def test_result_has_findings(self, tmp_target_root):
        target_dir = _init(tmp_target_root)
        result = validate_specification("TestProject", target_dir)
        assert len(result.findings) > 0


class TestMissingFiles:
    def test_missing_metadata_is_failure(self, tmp_target_root):
        target_dir = _init(tmp_target_root)
        (target_dir / "METADATA.md").unlink()
        result = validate_specification("TestProject", target_dir)
        assert result.has_failures()

    def test_missing_architecture_is_failure_at_implement_phase(self, tmp_target_root):
        target_dir = _init(tmp_target_root)
        # Simulate Implement phase (MANIFEST.md present) so ARCHITECTURE.md is required
        (target_dir / "MANIFEST.md").write_text("# MANIFEST: Example\n", encoding="utf-8")
        (target_dir / "blueprint" / "ARCHITECTURE.md").unlink()
        result = validate_specification("TestProject", target_dir)
        assert result.has_failures()

    def test_missing_readme_is_failure_at_implement_phase(self, tmp_target_root):
        target_dir = _init(tmp_target_root)
        # Simulate Implement phase so README.md is required
        (target_dir / "MANIFEST.md").write_text("# MANIFEST: Example\n", encoding="utf-8")
        (target_dir / "README.md").unlink()
        result = validate_specification("TestProject", target_dir)
        assert result.has_failures()

    def test_missing_architecture_not_required_at_setup_phase(self, tmp_target_root):
        target_dir = _init(tmp_target_root)
        (target_dir / "blueprint" / "ARCHITECTURE.md").unlink()
        result = validate_specification("TestProject", target_dir)
        assert not result.has_failures()

    def test_missing_readme_not_required_at_setup_phase(self, tmp_target_root):
        target_dir = _init(tmp_target_root)
        (target_dir / "README.md").unlink()
        result = validate_specification("TestProject", target_dir)
        assert not result.has_failures()


class TestNonExistentSpec:
    def test_nonexistent_dir_is_failure(self, tmp_target_root):
        result = validate_specification("DoesNotExist", tmp_target_root / "DoesNotExist")
        assert result.has_failures()
        assert result.exit_code() == 1


class TestVerbose:
    def test_verbose_includes_passes(self, tmp_target_root):
        target_dir = _init(tmp_target_root)
        result = validate_specification("TestProject", target_dir, verbose=True)
        assert len(result.passes()) > 0

    def test_non_verbose_result_still_has_passes(self, tmp_target_root):
        target_dir = _init(tmp_target_root)
        result_nv = validate_specification("TestProject", target_dir, verbose=False)
        result_vb = validate_specification("TestProject", target_dir, verbose=True)
        assert len(result_nv.passes()) == len(result_vb.passes())
        assert len(result_nv.passes()) > 0


class TestMetadataFields:
    def test_name_mismatch_is_failure(self, tmp_target_root):
        target_dir = _init(tmp_target_root, "TestProject")
        meta = target_dir / "METADATA.md"
        meta.write_text(meta.read_text().replace("name: TestProject", "name: WrongName"))
        result = validate_specification("TestProject", target_dir)
        assert result.has_failures()

    def test_missing_legacy_status_is_not_a_failure(self, tmp_target_root):
        target_dir = _init(tmp_target_root)
        result = validate_specification("TestProject", target_dir)
        assert "status not set in METADATA.md" not in [f.message for f in result.findings]

    def test_invalid_status_is_failure(self, tmp_target_root):
        target_dir = _init(tmp_target_root)
        meta = target_dir / "METADATA.md"
        meta.write_text(meta.read_text().replace("status: IDEA", "status: BADVALUE"))
        result = validate_specification("TestProject", target_dir)
        assert result.has_failures()


class TestNonSpecBlueprintFiles:
    def test_agents_md_is_forbidden_in_blueprint(self, tmp_target_root):
        target_dir = _init(tmp_target_root)
        agents = target_dir / "blueprint" / "AGENTS.md"
        agents.write_text("# Not a typed spec\n", encoding="utf-8")

        result = validate_specification("TestProject", target_dir)
        messages = [f.message for f in result.findings]

        assert result.has_failures()
        assert any("AGENTS.md is forbidden in blueprint/" in message for message in messages)

    def test_generated_compacts_are_allowed(self, tmp_target_root):
        target_dir = _init(tmp_target_root)
        blueprint = target_dir / "blueprint"
        (blueprint / "ARCHITECTURE_compact.md").write_text("# Compact\n", encoding="utf-8")
        (blueprint / "DATABASE_compact.md").write_text("# Compact\n", encoding="utf-8")

        result = validate_specification("TestProject", target_dir)
        messages = [f.message for f in result.findings]
        assert "Unexpected file name: ARCHITECTURE_compact.md" not in messages
        assert "Unexpected file name: DATABASE_compact.md" not in messages

    def test_generated_compacts_do_not_require_terminal_sections(self, tmp_target_root):
        target_dir = _init(tmp_target_root)
        blueprint = target_dir / "blueprint"
        (blueprint / "ARCHITECTURE_compact.md").write_text("# Compact\n", encoding="utf-8")
        (blueprint / "DATABASE_compact.md").write_text("# Compact\n", encoding="utf-8")

        result = validate_specification("TestProject", target_dir)
        messages = [f.message for f in result.findings]

        assert "ARCHITECTURE_compact.md missing ## Programmatic Acceptance" not in messages
        assert "ARCHITECTURE_compact.md missing ## User Acceptance" not in messages
        assert "ARCHITECTURE_compact.md missing ## Guardrails" not in messages
        assert "ARCHITECTURE_compact.md missing ## Open Questions" not in messages
        assert "DATABASE_compact.md missing ## Programmatic Acceptance" not in messages
        assert "DATABASE_compact.md missing ## User Acceptance" not in messages
        assert "DATABASE_compact.md missing ## Guardrails" not in messages
        assert "DATABASE_compact.md missing ## Open Questions" not in messages


class TestExampleFileWarnings:
    def test_screen_example_warns(self, tmp_target_root):
        target_dir = _init(tmp_target_root)
        result = validate_specification("TestProject", target_dir)
        warn_msgs = [f.message for f in result.warnings()]
        assert any("Example" in m for m in warn_msgs)

    def test_no_example_files_no_warn(self, tmp_target_root):
        target_dir = _init(tmp_target_root)
        for ex in ("SCREEN-Example.md", "FEATURE-Example.md", "UI-Component-Example.md"):
            fp = target_dir / "blueprint" / ex
            if fp.exists():
                fp.unlink()
        result = validate_specification("TestProject", target_dir)
        warn_msgs = [f.message for f in result.findings if f.severity == Severity.WARN]
        example_warns = [m for m in warn_msgs if "Example" in m and "template" in m.lower()]
        assert len(example_warns) == 0


class TestResultStructure:
    def test_result_has_spec_name(self, tmp_target_root):
        target_dir = _init(tmp_target_root)
        result = validate_specification("TestProject", target_dir)
        assert result.spec_name == "TestProject"

    def test_result_has_spec_dir(self, tmp_target_root):
        target_dir = _init(tmp_target_root)
        result = validate_specification("TestProject", target_dir)
        assert result.spec_dir == target_dir / "blueprint"

    def test_findings_have_sections(self, tmp_target_root):
        target_dir = _init(tmp_target_root)
        result = validate_specification("TestProject", target_dir, verbose=True)
        assert all(f.section for f in result.findings)

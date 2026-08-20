"""CLI contract tests for workflow-state recording side effects.

Recording is a side effect only: it must never alter a command's exit code, and a usage
error must never be recorded as a lifecycle attempt.
"""

from __future__ import annotations

import pytest

from drydock.project_status import latest_per_label, read_status
from tests.test_cli import run_cli


@pytest.fixture()
def workspace(tmp_target_root, isolated_config, monkeypatch):
    monkeypatch.setenv("DRYDOCK_WORKSPACE", str(tmp_target_root.parent))
    return tmp_target_root


class TestInitRecordsStatus:
    def test_init_records_initialized(self, workspace):
        rc, _out, _err = run_cli("init", "Tgt")

        assert rc == 0
        latest = latest_per_label(read_status(workspace / "Tgt"))
        assert latest["INITIALIZED"].passed is True
        assert latest["INITIALIZED"].command == "drydock init Tgt"

    def test_status_file_lives_beside_metadata(self, workspace):
        run_cli("init", "Tgt")

        assert (workspace / "Tgt" / "PROJECT_STATUS.md").is_file()


class TestImportRecordsStatus:
    def test_import_records_imported(self, tmp_path, workspace):
        run_cli("init", "Tgt")
        source = tmp_path / "spec.md"
        source.write_text("# Spec\n", encoding="utf-8")

        rc, _out, _err = run_cli("import", "Tgt", str(source), "--format", "markdown")

        assert rc == 0
        latest = latest_per_label(read_status(workspace / "Tgt"))
        assert latest["IMPORTED"].passed is True

    def test_usage_error_keeps_exit_code_two_and_records_nothing(self, workspace):
        run_cli("init", "Tgt")

        rc, _out, _err = run_cli("import", "Tgt")

        assert rc == 2
        assert "IMPORTED" not in latest_per_label(read_status(workspace / "Tgt"))

    def test_usage_error_against_uninitialized_target_writes_no_status_file(self, workspace):
        rc, _out, _err = run_cli("import", "Missing")

        assert rc == 2
        assert not (workspace / "Missing").exists()

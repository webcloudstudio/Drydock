"""Tests for drydock rigging update and drydock rigging verify."""

from __future__ import annotations

from pathlib import Path

from drydock.rigging_update import (
    MARKER_END,
    MARKER_START,
    _inject_block,
    _strip_rigging_block,
    update,
)
from drydock.rigging_verify import verify

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_rigging(tmp_path: Path, compact_content: str = "# Rule A\nDo this.") -> Path:
    """Write a minimal BUSINESS_RULES_compact.md into a fake Rigging dir."""
    rigging = tmp_path / "Rigging"
    rigging.mkdir()
    (rigging / "BUSINESS_RULES_compact.md").write_text(compact_content, encoding="utf-8")
    return rigging


def _make_build_dir(tmp_path: Path, target: str, *, with_metadata: bool = True) -> Path:
    build_dir = tmp_path / "builds" / target
    build_dir.mkdir(parents=True)
    (build_dir / "AGENTS.md").write_text(
        "# Agent instructions\n\nDo the thing.\n", encoding="utf-8"
    )
    if with_metadata:
        (build_dir / "METADATA.md").write_text(
            "name: MyApp\nshort_description: A test app\nbuild_state: built\n",
            encoding="utf-8",
        )
    return build_dir


# ---------------------------------------------------------------------------
# Unit: _strip_rigging_block / _inject_block
# ---------------------------------------------------------------------------


class TestStripInject:
    def test_strip_removes_existing_block(self):
        text = f"Before\n{MARKER_START}\nold content\n{MARKER_END}\nAfter\n"
        result = _strip_rigging_block(text)
        assert MARKER_START not in result
        assert MARKER_END not in result
        assert "old content" not in result
        assert "Before" in result
        assert "After" in result

    def test_strip_noop_when_no_block(self):
        text = "No markers here\n"
        assert _strip_rigging_block(text) == text

    def test_inject_adds_markers(self):
        original = "# AGENTS\nContent\n"
        result = _inject_block(original, "Rule A\nRule B")
        assert MARKER_START in result
        assert MARKER_END in result
        assert "Rule A" in result

    def test_inject_replaces_existing_block(self):
        original = f"Before\n{MARKER_START}\nold\n{MARKER_END}\nAfter\n"
        result = _inject_block(original, "new content")
        assert "old" not in result
        assert "new content" in result
        assert result.count(MARKER_START) == 1

    def test_inject_appends_after_existing_content(self):
        original = "Line 1\nLine 2\n"
        result = _inject_block(original, "rules")
        assert result.startswith("Line 1")
        idx_start = result.index(MARKER_START)
        assert result.index("Line 2") < idx_start


# ---------------------------------------------------------------------------
# Unit: update()
# ---------------------------------------------------------------------------


class TestUpdate:
    def test_update_injects_compact_into_agents(self, tmp_path, monkeypatch):
        rigging = _make_rigging(tmp_path, "# Business Rule\nUse it.")
        build_dir = _make_build_dir(tmp_path, "MyTarget")
        monkeypatch.setattr("drydock.rigging_update.get_rigging_root", lambda: rigging)
        monkeypatch.setattr("drydock.rigging_update.build_dir_for", lambda t: build_dir)

        rc, log = update("MyTarget")

        assert rc == 0
        agents = (build_dir / "AGENTS.md").read_text()
        assert MARKER_START in agents
        assert MARKER_END in agents
        assert "Business Rule" in agents

    def test_update_stamps_metadata_fields(self, tmp_path, monkeypatch):
        rigging = _make_rigging(tmp_path)
        build_dir = _make_build_dir(tmp_path, "MyTarget")
        monkeypatch.setattr("drydock.rigging_update.get_rigging_root", lambda: rigging)
        monkeypatch.setattr("drydock.rigging_update.build_dir_for", lambda t: build_dir)

        update("MyTarget")

        from drydock.metadata import parse_metadata

        meta = parse_metadata(build_dir / "METADATA.md")
        assert meta["drydock_target"] == "MyTarget"
        assert meta["drydock_build_directory"] == str(build_dir)
        assert meta["drydock_project_state"] == "built"
        assert "drydock_rigging_updated" in meta

    def test_update_dry_run_writes_nothing(self, tmp_path, monkeypatch):
        rigging = _make_rigging(tmp_path)
        build_dir = _make_build_dir(tmp_path, "MyTarget")
        original_agents = (build_dir / "AGENTS.md").read_text()
        original_meta = (build_dir / "METADATA.md").read_text()
        monkeypatch.setattr("drydock.rigging_update.get_rigging_root", lambda: rigging)
        monkeypatch.setattr("drydock.rigging_update.build_dir_for", lambda t: build_dir)

        rc, log = update("MyTarget", dry_run=True)

        assert rc == 0
        assert (build_dir / "AGENTS.md").read_text() == original_agents
        assert (build_dir / "METADATA.md").read_text() == original_meta

    def test_update_errors_when_compact_missing(self, tmp_path, monkeypatch):
        rigging = tmp_path / "Rigging"
        rigging.mkdir()
        build_dir = _make_build_dir(tmp_path, "MyTarget")
        monkeypatch.setattr("drydock.rigging_update.get_rigging_root", lambda: rigging)
        monkeypatch.setattr("drydock.rigging_update.build_dir_for", lambda t: build_dir)

        rc, log = update("MyTarget")

        assert rc == 1
        assert any("BUSINESS_RULES_compact.md" in line for line in log)

    def test_update_errors_when_agents_missing(self, tmp_path, monkeypatch):
        rigging = _make_rigging(tmp_path)
        build_dir = tmp_path / "builds" / "MyTarget"
        build_dir.mkdir(parents=True)
        monkeypatch.setattr("drydock.rigging_update.get_rigging_root", lambda: rigging)
        monkeypatch.setattr("drydock.rigging_update.build_dir_for", lambda t: build_dir)

        rc, log = update("MyTarget")

        assert rc == 1
        assert any("AGENTS.md" in line for line in log)

    def test_update_replaces_stale_block(self, tmp_path, monkeypatch):
        rigging = _make_rigging(tmp_path, "New rules")
        build_dir = _make_build_dir(tmp_path, "MyTarget")
        old_agents = f"# AGENTS\n{MARKER_START}\nOld rules\n{MARKER_END}\n"
        (build_dir / "AGENTS.md").write_text(old_agents)
        monkeypatch.setattr("drydock.rigging_update.get_rigging_root", lambda: rigging)
        monkeypatch.setattr("drydock.rigging_update.build_dir_for", lambda t: build_dir)

        update("MyTarget")

        agents = (build_dir / "AGENTS.md").read_text()
        assert "Old rules" not in agents
        assert "New rules" in agents
        assert agents.count(MARKER_START) == 1


# ---------------------------------------------------------------------------
# Unit: verify()
# ---------------------------------------------------------------------------


class TestVerify:
    def test_verify_passes_when_current(self, tmp_path, monkeypatch):
        compact_content = "# Rule\nFollow it."
        rigging = _make_rigging(tmp_path, compact_content)
        build_dir = _make_build_dir(tmp_path, "MyTarget")
        # Pre-inject the block so it matches
        agents = (build_dir / "AGENTS.md").read_text()
        injected = f"{agents.rstrip()}\n{MARKER_START}\n{compact_content.strip()}\n{MARKER_END}\n"
        (build_dir / "AGENTS.md").write_text(injected)
        # Add stamp fields
        meta = (build_dir / "METADATA.md").read_text()
        meta += (
            "drydock_target: MyTarget\n"
            f"drydock_build_directory: {build_dir}\n"
            "drydock_project_state: built\n"
            "drydock_rigging_updated: 2026-01-01T00:00:00Z\n"
        )
        (build_dir / "METADATA.md").write_text(meta)
        monkeypatch.setattr("drydock.rigging_verify.get_rigging_root", lambda: rigging)
        monkeypatch.setattr("drydock.rigging_verify.build_dir_for", lambda t: build_dir)

        rc, checks = verify("MyTarget")

        assert rc == 0
        assert all(c.passed for c in checks)

    def test_verify_fails_when_block_stale(self, tmp_path, monkeypatch):
        rigging = _make_rigging(tmp_path, "New rules")
        build_dir = _make_build_dir(tmp_path, "MyTarget")
        agents = (build_dir / "AGENTS.md").read_text()
        stale = f"{agents.rstrip()}\n{MARKER_START}\nOld rules\n{MARKER_END}\n"
        (build_dir / "AGENTS.md").write_text(stale)
        meta = (build_dir / "METADATA.md").read_text()
        meta += (
            "drydock_target: MyTarget\n"
            f"drydock_build_directory: {build_dir}\n"
            "drydock_project_state: built\n"
            "drydock_rigging_updated: 2026-01-01T00:00:00Z\n"
        )
        (build_dir / "METADATA.md").write_text(meta)
        monkeypatch.setattr("drydock.rigging_verify.get_rigging_root", lambda: rigging)
        monkeypatch.setattr("drydock.rigging_verify.build_dir_for", lambda t: build_dir)

        rc, checks = verify("MyTarget")

        assert rc == 1
        failed = [c for c in checks if not c.passed]
        assert any("stale" in c.message for c in failed)

    def test_verify_fails_when_block_absent(self, tmp_path, monkeypatch):
        rigging = _make_rigging(tmp_path)
        build_dir = _make_build_dir(tmp_path, "MyTarget")
        monkeypatch.setattr("drydock.rigging_verify.get_rigging_root", lambda: rigging)
        monkeypatch.setattr("drydock.rigging_verify.build_dir_for", lambda t: build_dir)

        rc, checks = verify("MyTarget")

        assert rc == 1
        failed = [c for c in checks if not c.passed]
        assert any("no" in c.message.lower() and MARKER_START in c.message for c in failed)

    def test_verify_flags_missing_name(self, tmp_path, monkeypatch):
        compact_content = "# Rule"
        rigging = _make_rigging(tmp_path, compact_content)
        build_dir = _make_build_dir(tmp_path, "MyTarget")
        # Inject current block
        agents = (build_dir / "AGENTS.md").read_text()
        (build_dir / "AGENTS.md").write_text(
            f"{agents.rstrip()}\n{MARKER_START}\n{compact_content.strip()}\n{MARKER_END}\n"
        )
        # METADATA.md missing name
        (build_dir / "METADATA.md").write_text(
            "short_description: A test\n"
            "drydock_target: MyTarget\n"
            f"drydock_build_directory: {build_dir}\n"
            "drydock_project_state: built\n"
            "drydock_rigging_updated: 2026-01-01T00:00:00Z\n"
        )
        monkeypatch.setattr("drydock.rigging_verify.get_rigging_root", lambda: rigging)
        monkeypatch.setattr("drydock.rigging_verify.build_dir_for", lambda t: build_dir)

        rc, checks = verify("MyTarget")

        assert rc == 1
        failed = [c for c in checks if not c.passed]
        assert any(c.name == "name" for c in failed)

    def test_verify_flags_missing_short_description(self, tmp_path, monkeypatch):
        compact_content = "# Rule"
        rigging = _make_rigging(tmp_path, compact_content)
        build_dir = _make_build_dir(tmp_path, "MyTarget")
        (build_dir / "AGENTS.md").write_text(
            f"# AGENTS\n{MARKER_START}\n{compact_content.strip()}\n{MARKER_END}\n"
        )
        (build_dir / "METADATA.md").write_text(
            "name: MyApp\n"
            "drydock_target: MyTarget\n"
            f"drydock_build_directory: {build_dir}\n"
            "drydock_project_state: built\n"
            "drydock_rigging_updated: 2026-01-01T00:00:00Z\n"
        )
        monkeypatch.setattr("drydock.rigging_verify.get_rigging_root", lambda: rigging)
        monkeypatch.setattr("drydock.rigging_verify.build_dir_for", lambda t: build_dir)

        rc, checks = verify("MyTarget")

        assert rc == 1
        failed = [c for c in checks if not c.passed]
        assert any(c.name == "short_description" for c in failed)


# ---------------------------------------------------------------------------
# CLI contract
# ---------------------------------------------------------------------------


class TestRiggingUpdateCLI:
    def test_update_help(self):
        from tests.test_cli import run_cli

        rc, out, _ = run_cli("rigging", "update", "--help")
        assert rc == 0
        assert "Target" in out or "target" in out

    def test_update_dry_run_flag_accepted(self, tmp_path, monkeypatch):
        from tests.test_cli import run_cli

        monkeypatch.setattr(
            "drydock.rigging_update.update",
            lambda target, dry_run=False: (0, ["  ✓  AGENTS.md  rigging block injected"]),
        )
        rc, out, err = run_cli("rigging", "update", "--dry-run", "MyTarget")
        assert rc == 0

    def test_update_exits_1_on_failure(self, tmp_path, monkeypatch):
        from tests.test_cli import run_cli

        monkeypatch.setattr(
            "drydock.rigging_update.update",
            lambda target, dry_run=False: (1, ["ERROR: compact missing"]),
        )
        rc, out, err = run_cli("rigging", "update", "MyTarget")
        assert rc == 1


class TestRiggingVerifyCLI:
    def test_verify_help(self):
        from tests.test_cli import run_cli

        rc, out, _ = run_cli("rigging", "verify", "--help")
        assert rc == 0

    def test_verify_pass_output(self, monkeypatch):
        from drydock.rigging_verify import CheckResult
        from tests.test_cli import run_cli

        monkeypatch.setattr(
            "drydock.rigging_verify.verify",
            lambda target: (0, [CheckResult("rigging_block_current", True)]),
        )
        rc, out, err = run_cli("rigging", "verify", "MyTarget")
        assert rc == 0
        assert "PASS" in out

    def test_verify_fail_output(self, monkeypatch):
        from drydock.rigging_verify import CheckResult
        from tests.test_cli import run_cli

        monkeypatch.setattr(
            "drydock.rigging_verify.verify",
            lambda target: (
                1,
                [CheckResult("rigging_block_current", False, "stale — run update")],
            ),
        )
        rc, out, err = run_cli("rigging", "verify", "MyTarget")
        assert rc == 1
        assert "FAIL" in out

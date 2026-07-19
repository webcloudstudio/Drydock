"""Tests for ``drydock rigging --add`` catalog registration."""

from __future__ import annotations

from pathlib import Path

import pytest

from drydock.errors import UsageError
from drydock.rigging_manifest import add_to_manifest


def _rigging(tmp_path: Path) -> Path:
    root = tmp_path / "Rigging"
    root.mkdir()
    (root / "MANIFEST.md").write_text(
        "# Rigging Manifest\n\n"
        "| File | Category | Purpose | Prerequisites |\n"
        "|---|---|---|---|\n"
        "| `common.md` | Technologies | Common rules. | — |\n",
        encoding="utf-8",
    )
    return root


def test_add_file_persists_rigging_relative_path(tmp_path):
    root = _rigging(tmp_path)
    path = root / "rules" / "deployment.md"
    path.parent.mkdir()
    path.write_text("# Deployment\n", encoding="utf-8")

    result = add_to_manifest(files=[path], rigging_root=root)

    assert result.added == (Path("rules/deployment.md"),)
    manifest = (root / "MANIFEST.md").read_text(encoding="utf-8")
    assert "| `rules/deployment.md` | Uncategorized | — | — |" in manifest


def test_add_directory_registers_all_regular_files_in_path_order(tmp_path):
    root = _rigging(tmp_path)
    directory = root / "stack" / "aws"
    directory.mkdir(parents=True)
    (directory / "z.md").write_text("z", encoding="utf-8")
    nested = directory / "nested"
    nested.mkdir()
    (nested / "a.txt").write_text("a", encoding="utf-8")

    result = add_to_manifest(directories=[directory], rigging_root=root)

    assert result.added == (Path("stack/aws/nested/a.txt"), Path("stack/aws/z.md"))
    manifest = (root / "MANIFEST.md").read_text(encoding="utf-8")
    assert "`stack/aws/nested/a.txt`" in manifest
    assert "`stack/aws/z.md`" in manifest


def test_add_is_idempotent(tmp_path):
    root = _rigging(tmp_path)
    path = root / "rules.md"
    path.write_text("# Rules\n", encoding="utf-8")

    add_to_manifest(files=[path], rigging_root=root)
    result = add_to_manifest(files=[path], rigging_root=root)

    assert result.added == ()
    assert result.existing == (Path("rules.md"),)
    assert (root / "MANIFEST.md").read_text(encoding="utf-8").count("`rules.md`") == 1


def test_add_rejects_file_outside_rigging(tmp_path):
    root = _rigging(tmp_path)
    outside = tmp_path / "outside.md"
    outside.write_text("# Outside\n", encoding="utf-8")

    with pytest.raises(UsageError, match="must be inside"):
        add_to_manifest(files=[outside], rigging_root=root)


class TestRiggingAddCLI:
    def test_add_file_registers_path(self, tmp_path, monkeypatch):
        from tests.test_cli import run_cli

        root = _rigging(tmp_path)
        path = root / "custom.md"
        path.write_text("# Custom\n", encoding="utf-8")
        monkeypatch.setattr("drydock.paths.get_rigging_root", lambda: root)

        rc, out, err = run_cli("rigging", "--add", "--file", str(path))

        assert rc == 0, err
        assert "ADDED     custom.md" in out
        assert "`custom.md`" in (root / "MANIFEST.md").read_text(encoding="utf-8")

    def test_add_requires_a_path(self):
        from tests.test_cli import run_cli

        rc, _out, err = run_cli("rigging", "--add")

        assert rc == 2
        assert "--add requires exactly one of --file or --dir" in err

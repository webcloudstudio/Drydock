from __future__ import annotations

import subprocess
from pathlib import Path

from drydock.uat_git import checkpoint_kit_repository, ensure_kit_repository


def _git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=root, check=True, capture_output=True, text=True
    ).stdout.strip()


def _identity(monkeypatch) -> None:
    monkeypatch.setenv("GIT_AUTHOR_NAME", "Drydock Test")
    monkeypatch.setenv("GIT_AUTHOR_EMAIL", "drydock@example.test")
    monkeypatch.setenv("GIT_COMMITTER_NAME", "Drydock Test")
    monkeypatch.setenv("GIT_COMMITTER_EMAIL", "drydock@example.test")


def test_ensure_initializes_only_the_direct_kit_repository(tmp_path):
    kit = tmp_path / "ReadingList"
    kit.mkdir()

    assert ensure_kit_repository(kit) is True
    assert ensure_kit_repository(kit) is False
    assert (kit / ".git").is_dir()


def test_checkpoint_replaces_nested_run_repository_with_tracked_files(tmp_path, monkeypatch):
    _identity(monkeypatch)
    kit = tmp_path / "ReadingList"
    target = kit / "runs" / "run-1" / "workspace" / "targets" / "ReadingList"
    target.mkdir(parents=True)
    (kit / "uat.json").write_text("{}\n", encoding="utf-8")
    (target / "METADATA.md").write_text("# Target\n", encoding="utf-8")
    _git(target, "init", "-q")
    _git(target, "add", "--all")
    _git(target, "commit", "-q", "-m", "target checkpoint")
    _git(kit, "init", "-q")
    _git(kit, "add", "--all")
    assert _git(kit, "ls-files", "--stage").startswith("160000 ")

    commit = checkpoint_kit_repository(kit)

    assert commit
    assert not (target / ".git").exists()
    assert _git(kit, "status", "--short") == ""
    modes = [line.split()[0] for line in _git(kit, "ls-files", "--stage").splitlines()]
    assert "160000" not in modes
    assert (
        _git(kit, "show", "HEAD:runs/run-1/workspace/targets/ReadingList/METADATA.md") == "# Target"
    )


def test_checkpoint_commits_every_later_write(tmp_path, monkeypatch):
    _identity(monkeypatch)
    kit = tmp_path / "Toml"
    kit.mkdir()
    artifact = kit / "index.html"
    artifact.write_text("first\n", encoding="utf-8")
    checkpoint_kit_repository(kit)
    first = _git(kit, "rev-parse", "HEAD")

    artifact.write_text("second\n", encoding="utf-8")
    checkpoint_kit_repository(kit)

    assert _git(kit, "rev-parse", "HEAD") != first
    assert _git(kit, "show", "HEAD:index.html") == "second"

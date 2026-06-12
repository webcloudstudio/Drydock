"""Regression tests for canonical specification worktree protection."""

from __future__ import annotations

import subprocess
from pathlib import Path

GUARD = Path(__file__).parents[1] / "bin" / "pre_commit_guard.sh"
SPECIFICATION = Path("docs/Drydock_Specification.md")


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )


def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    specification = repo / SPECIFICATION
    specification.parent.mkdir(parents=True)
    specification.write_text("authoritative\n", encoding="utf-8")
    _git(repo.parent, "init", str(repo))
    _git(repo, "add", str(SPECIFICATION))
    return repo


def _guard(repo: Path, *command: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(GUARD), *command],
        cwd=repo,
        check=False,
        capture_output=True,
        text=True,
    )


def test_guard_blocks_before_pre_commit_can_stash_unstaged_specification(tmp_path: Path):
    repo = _repo(tmp_path)
    specification = repo / SPECIFICATION
    specification.write_text("approved working copy\n", encoding="utf-8")

    result = _guard(repo, "true")

    assert result.returncode == 1
    assert "has unstaged edits" in result.stderr
    assert specification.read_text(encoding="utf-8") == "approved working copy\n"
    backup = repo / ".git" / "canonical-backups" / "Drydock_Specification.md"
    assert backup.read_text(encoding="utf-8") == "approved working copy\n"


def test_guard_restores_specification_removed_by_commit_tooling(tmp_path: Path):
    repo = _repo(tmp_path)
    specification = repo / SPECIFICATION

    result = _guard(repo, "rm", str(SPECIFICATION))

    assert result.returncode == 1
    assert "removed the canonical specification" in result.stderr
    assert specification.read_text(encoding="utf-8") == "authoritative\n"


def test_guard_restores_missing_specification_from_snapshot(tmp_path: Path):
    repo = _repo(tmp_path)
    specification = repo / SPECIFICATION
    backup = repo / ".git" / "canonical-backups" / "Drydock_Specification.md"
    backup.parent.mkdir(parents=True)
    backup.write_text("latest snapshot\n", encoding="utf-8")
    specification.unlink()

    result = _guard(repo, "true")

    assert result.returncode == 1
    assert "was missing" in result.stderr
    assert specification.read_text(encoding="utf-8") == "latest snapshot\n"

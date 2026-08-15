from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from drydock import source_refit
from drydock.errors import SpecificationError
from drydock.target_git import (
    commit_paths,
    commit_target,
    diff,
    file_versions,
    head_commit,
    is_repo,
    setup_target,
    show,
    tracked_sources,
)


def _git(target: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=target, check=True, capture_output=True)


def _repo(tmp_path: Path, name: str = "Demo") -> Path:
    target = tmp_path / name
    target.mkdir()
    _git(target, "init", "-q")
    _git(target, "config", "user.email", "test@example.com")
    _git(target, "config", "user.name", "Test")
    return target


def _write(target: Path, rel: str, text: str) -> None:
    path = target / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _commit(target: Path, message: str) -> None:
    _git(target, "add", "-A")
    _git(target, "commit", "-q", "-m", message)


def test_is_repo_and_head_commit_on_a_bare_directory(tmp_path):
    plain = tmp_path / "NoRepo"
    plain.mkdir()

    assert is_repo(plain) is False
    assert head_commit(plain) is None


def test_setup_target_initializes_quietly_and_reports_one_summary(tmp_path, capsys):
    target = tmp_path / "Demo"
    target.mkdir()

    assert setup_target(target) is True
    assert setup_target(target) is False
    assert capsys.readouterr().out.splitlines() == ["Target - setup project workspace git store"]
    assert is_repo(target)


def test_commit_target_reports_one_line_checkpoint(tmp_path, capsys):
    target = _repo(tmp_path)
    _write(target, "a.md", "a\n")
    _write(target, "b.md", "b\n")

    sha = commit_target(target, "Refresh imported source snapshot")

    lines = capsys.readouterr().out.splitlines()
    assert lines == ["Target - committed project workspace git store"]
    assert sha == head_commit(target)


def test_commit_target_raises_when_git_commit_fails(tmp_path, monkeypatch):
    target = _repo(tmp_path)
    _write(target, "a.md", "a\n")
    real_run = __import__("drydock.target_git", fromlist=["_run"])._run

    def failing_run(target_dir, *args, timeout=30):
        if args and args[0] == "commit":
            return 1, "simulated commit failure"
        return real_run(target_dir, *args, timeout=timeout)

    monkeypatch.setattr("drydock.target_git._run", failing_run)

    with pytest.raises(SpecificationError, match="simulated commit failure"):
        commit_target(target, "Refresh imported source snapshot")


def test_commit_target_is_silent_without_changes(tmp_path, capsys):
    target = _repo(tmp_path, "Clean")

    assert commit_target(target, "Nothing to do") is None
    assert capsys.readouterr().out == ""


def test_commit_target_is_silent_without_a_repository(tmp_path, capsys):
    target = tmp_path / "NoRepo"
    target.mkdir()
    _write(target, "a.md", "a\n")

    assert commit_target(target, "Nothing to do") is None
    assert capsys.readouterr().out == ""


def test_source_refit_still_exports_commit_target():
    assert source_refit.commit_target is commit_target


def test_commit_paths_leaves_the_prior_commit_reachable(tmp_path):
    target = _repo(tmp_path)
    _write(target, "a.md", "a\n")
    _commit(target, "first")
    first = head_commit(target)
    _write(target, "LINEAGE.json", "{}\n")
    _write(target, "unrelated.md", "keep me out\n")

    sha = commit_paths(target, ["LINEAGE.json"], "Record source lineage")

    assert sha not in (None, first)
    # The sha a lineage record points at must survive the stamp; amending would orphan it.
    assert show(target, first, "a.md") == "a\n"
    files = subprocess.run(
        ["git", "show", "--name-only", "--format=", "HEAD"],
        cwd=target,
        capture_output=True,
        text=True,
        check=True,
    )
    assert files.stdout.split() == ["LINEAGE.json"]


def test_commit_paths_is_a_noop_when_the_path_is_unchanged(tmp_path):
    target = _repo(tmp_path)
    _write(target, "LINEAGE.json", "{}\n")
    _commit(target, "first")

    assert commit_paths(target, ["LINEAGE.json"], "Record source lineage") is None


def test_commit_paths_without_a_repository_is_a_noop(tmp_path):
    plain = tmp_path / "NoRepo"
    plain.mkdir()

    assert commit_paths(plain, ["LINEAGE.json"], "Record source lineage") is None


def test_file_versions_returns_every_version_oldest_first(tmp_path):
    target = _repo(tmp_path)
    _write(target, "blueprint/sources/spec.md", "one\n")
    _commit(target, "import")
    _write(target, "blueprint/sources/spec.md", "one\ntwo\n")
    _commit(target, "update")

    versions = file_versions(target, "blueprint/sources/spec.md")

    assert [v.subject for v in versions] == ["import", "update"]
    assert all(v.commit and v.date for v in versions)


def test_show_returns_content_at_a_commit_and_none_when_absent(tmp_path):
    target = _repo(tmp_path)
    _write(target, "blueprint/sources/spec.md", "one\n")
    _commit(target, "import")
    first = head_commit(target)
    _write(target, "blueprint/sources/spec.md", "one\ntwo\n")
    _commit(target, "update")

    assert show(target, first, "blueprint/sources/spec.md") == "one\n"
    assert show(target, first, "blueprint/sources/missing.md") is None


def test_diff_reports_the_working_tree_change_since_a_base(tmp_path):
    target = _repo(tmp_path)
    _write(target, "blueprint/sources/spec.md", "one\n")
    _commit(target, "import")
    base = head_commit(target)
    _write(target, "blueprint/sources/spec.md", "one\ntwo\n")

    text = diff(target, base, "blueprint/sources/spec.md")

    assert "+two" in text


def test_diff_without_a_base_renders_the_whole_file_as_additions(tmp_path):
    target = _repo(tmp_path)
    _write(target, "blueprint/sources/spec.md", "one\ntwo\n")

    text = diff(target, None, "blueprint/sources/spec.md")

    assert "+one" in text
    assert "+two" in text


def test_tracked_sources_includes_a_withdrawn_source(tmp_path):
    target = _repo(tmp_path)
    _write(target, "blueprint/sources/kept.md", "a\n")
    _write(target, "blueprint/sources/gone.md", "b\n")
    _write(target, "blueprint/sources/.drydock-import", "source: x\n")
    _commit(target, "import")
    (target / "blueprint" / "sources" / "gone.md").unlink()
    _commit(target, "withdraw")

    assert tracked_sources(target) == ("gone.md", "kept.md")


def test_tracked_sources_without_a_repository_is_empty(tmp_path):
    plain = tmp_path / "NoRepo"
    plain.mkdir()

    assert tracked_sources(plain) == ()

from __future__ import annotations

import subprocess
from pathlib import Path

from drydock import source_refit
from drydock.target_git import (
    amend_head,
    commit_target,
    diff,
    file_versions,
    head_commit,
    is_repo,
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


def test_commit_target_announces_the_git_commit(tmp_path, capsys):
    target = _repo(tmp_path)
    _write(target, "a.md", "a\n")
    _write(target, "b.md", "b\n")

    sha = commit_target(target, "Refresh imported source snapshot")

    out = capsys.readouterr().out
    assert f"Git commit: {target}" in out
    assert 'git add -A && git commit -m "Refresh imported source snapshot"' in out
    assert "staging 2 pending Target file(s)" in out
    assert "Refresh imported source snapshot" in out.splitlines()[-1]
    assert sha == head_commit(target)


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


def test_amend_head_folds_a_file_into_the_tip_commit(tmp_path):
    target = _repo(tmp_path)
    _write(target, "a.md", "a\n")
    _commit(target, "first")
    before = head_commit(target)
    _write(target, "LINEAGE.json", "{}\n")

    assert amend_head(target, ["LINEAGE.json"]) is True

    assert head_commit(target) != before
    log = subprocess.run(
        ["git", "log", "--format=%s"], cwd=target, capture_output=True, text=True, check=True
    )
    assert log.stdout.split() == ["first"]
    files = subprocess.run(
        ["git", "show", "--name-only", "--format=", "HEAD"],
        cwd=target,
        capture_output=True,
        text=True,
        check=True,
    )
    assert "LINEAGE.json" in files.stdout


def test_amend_head_without_a_repository_is_a_noop(tmp_path):
    plain = tmp_path / "NoRepo"
    plain.mkdir()

    assert amend_head(plain, ["LINEAGE.json"]) is False


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

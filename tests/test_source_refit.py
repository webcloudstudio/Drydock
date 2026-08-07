from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

from drydock.source_refit import (
    commit_target,
    record_import_root,
    source_refit_target,
    update_import,
)


@dataclass
class FakeRun:
    ok: bool = True
    text: str = ""
    execution_id: str = "fake"


def _manifest(source: str) -> str:
    return f'''# MANIFEST: Demo
state: approved
source_lineage: |
  {{"version": 1, "files": {{"{source}": {{"hash": "old", "blueprints": ["FEATURE-Demo.md"]}}}}}}

## story 1: Demo
id: demo
summary: Demo
implements: FEATURE-Demo.md
state: closed/verified
'''


def _target(tmp_path: Path, source_root: Path) -> Path:
    target = tmp_path / "Demo"
    sources = target / "blueprint" / "sources"
    sources.mkdir(parents=True)
    (sources / ".drydock-import").write_text(
        f"source: {source_root}\nformat: markdown\n", encoding="utf-8"
    )
    (target / "MANIFEST.md").write_text(_manifest("change.md"), encoding="utf-8")
    (target / "blueprint" / "FEATURE-Demo.md").write_text("# FEATURE: Demo\n", encoding="utf-8")
    return target


def test_update_import_copies_changed_files_and_records_pending_change(tmp_path):
    source = tmp_path / "authoring"
    source.mkdir()
    (source / "change.md").write_text("new\n", encoding="utf-8")
    target = _target(tmp_path, source)
    (target / "blueprint" / "sources" / "change.md").write_text("old\n", encoding="utf-8")

    result = update_import(target)

    assert result.changed == ("change.md",)
    assert (target / "blueprint" / "sources" / "change.md").read_text() == "new\n"
    assert '"pending_change":true' in (target / "MANIFEST.md").read_text()


def test_update_import_marks_deleted_files_and_keeps_the_local_copy(tmp_path):
    source = tmp_path / "authoring"
    source.mkdir()
    target = _target(tmp_path, source)
    removed = target / "blueprint" / "sources" / "removed.md"
    removed.write_text("old\n", encoding="utf-8")

    result = update_import(target)

    assert result.deleted == ("removed.md",)
    assert removed.is_file()
    assert '"pending_delete":true' in (target / "MANIFEST.md").read_text()


def test_record_import_root_keeps_wider_directory_root(tmp_path):
    root = tmp_path / "authoring"
    root.mkdir()
    member = root / "one.md"
    member.write_text("x\n", encoding="utf-8")
    sources = tmp_path / "sources"
    sources.mkdir()

    record_import_root(sources, root, "markdown")
    record_import_root(sources, member, "markdown")

    assert (sources / ".drydock-import").read_text(encoding="utf-8") == (
        f"source: {root}\nformat: markdown\n"
    )


def test_record_import_root_replaces_unrelated_root(tmp_path):
    first = tmp_path / "a"
    second = tmp_path / "b"
    first.mkdir()
    second.mkdir()
    sources = tmp_path / "sources"
    sources.mkdir()

    record_import_root(sources, first, "markdown")
    record_import_root(sources, second, "source")

    assert (sources / ".drydock-import").read_text(encoding="utf-8") == (
        f"source: {second}\nformat: source\n"
    )


def test_source_refit_writes_ordered_ticket_and_manifest_story(tmp_path):
    source = tmp_path / "authoring"
    source.mkdir()
    (source / "change.md").write_text("new\n", encoding="utf-8")
    target = _target(tmp_path, source)
    sources = target / "blueprint" / "sources"
    (sources / "change.md").write_text("old\n", encoding="utf-8")
    update_import(target)

    def runner(prompt, working_directory, **kwargs):
        return FakeRun(text="exact change specification\n")

    result = source_refit_target(target, runner=runner)

    ticket = target / "blueprint" / "FEATURE-Demo_refit_1.md"
    assert result.items[0].ticket == ticket
    ticket_text = ticket.read_text()
    assert "| Blueprint | FEATURE-Demo.md |" in ticket_text
    assert "exact change specification" in ticket_text
    manifest = (target / "MANIFEST.md").read_text()
    assert "implements: FEATURE-Demo_refit_1.md" in manifest
    assert '"pending_change"' not in manifest


def _git(target: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=target, check=True, capture_output=True)


def test_commit_target_announces_the_git_commit(tmp_path, capsys):
    target = tmp_path / "Demo"
    target.mkdir()
    _git(target, "init", "-q")
    _git(target, "config", "user.email", "test@example.com")
    _git(target, "config", "user.name", "Test")
    (target / "a.md").write_text("a\n", encoding="utf-8")
    (target / "b.md").write_text("b\n", encoding="utf-8")

    commit_target(target, "Refresh imported source snapshot")

    out = capsys.readouterr().out
    assert f"Git commit: {target}" in out
    assert 'git add -A && git commit -m "Refresh imported source snapshot"' in out
    assert "staging 2 pending Target file(s)" in out
    assert "Refresh imported source snapshot" in out.splitlines()[-1]


def test_commit_target_is_silent_without_changes(tmp_path, capsys):
    target = tmp_path / "Clean"
    target.mkdir()
    _git(target, "init", "-q")

    commit_target(target, "Nothing to do")

    assert capsys.readouterr().out == ""


def test_commit_target_is_silent_without_a_repository(tmp_path, capsys):
    target = tmp_path / "NoRepo"
    target.mkdir()
    (target / "a.md").write_text("a\n", encoding="utf-8")

    commit_target(target, "Nothing to do")

    assert capsys.readouterr().out == ""

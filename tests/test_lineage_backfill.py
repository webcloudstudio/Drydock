from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

import pytest

from drydock.errors import SpecificationError
from drydock.lineage import load_lineage
from drydock.lineage_backfill import relineage_target, replay_source, require_target_repo
from drydock.target_git import SourceVersion

_MANIFEST = """# MANIFEST: Demo
state: approved

## story 1: Establish the application.
id: architecture
summary: Establish the application.
type: foundational
implements: ARCHITECTURE.md
state: closed/verified

## story 2: Add a book.
id: add-book
summary: Add a book.
type: feature
implements: FEATURE-Add-Book.md
state: closed/verified
"""

_ATTRIBUTION = """<requirement name="add-books" stories="add-book">
The reader can add a book.
</requirement>
<unattached story="architecture"/>
"""


@dataclass
class FakeRun:
    ok: bool = True
    text: str = ""
    execution_id: str = "fake"


def _runner(text: str = _ATTRIBUTION):
    def run(prompt, working_directory, **kwargs):
        return FakeRun(text=text)

    return run


def _git(target: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=target, check=True, capture_output=True)


def _target(tmp_path: Path, *, repo: bool = True) -> Path:
    target = tmp_path / "Demo"
    sources = target / "blueprint" / "sources"
    sources.mkdir(parents=True)
    (target / "MANIFEST.md").write_text(_MANIFEST, encoding="utf-8")
    if repo:
        _git(target, "init", "-q")
        _git(target, "config", "user.email", "test@example.com")
        _git(target, "config", "user.name", "Test")
    return target


def _commit(target: Path, message: str) -> None:
    _git(target, "add", "-A")
    _git(target, "commit", "-q", "-m", message)


def test_relineage_requires_a_target_git_repository(tmp_path):
    target = _target(tmp_path, repo=False)

    with pytest.raises(SpecificationError, match="No git repository"):
        require_target_repo(target)

    with pytest.raises(SpecificationError, match="No git repository"):
        relineage_target(target, runner=_runner())


def test_relineage_requires_a_manifest_to_attribute_against(tmp_path):
    target = _target(tmp_path)
    (target / "MANIFEST.md").unlink()

    with pytest.raises(SpecificationError, match="no stories to attribute"):
        relineage_target(target, runner=_runner())


def test_replay_source_folds_versions_chronologically():
    history = [
        (SourceVersion("aaaaaaa", "2026-08-01", "import"), "one\n"),
        (SourceVersion("bbbbbbb", "2026-08-02", "update"), "one\ntwo\n"),
    ]

    records = replay_source(history, release="0.01")

    assert [record.commit for record in records] == ["aaaaaaa", "bbbbbbb"]
    assert [record.date for record in records] == ["2026-08-01", "2026-08-02"]
    assert all(record.state == "consumed" and record.via == "relineage" for record in records)
    assert records[0].hash != records[1].hash
    assert records[0].release == "0.01"


def test_replay_source_collapses_commits_that_did_not_change_content():
    # git records a commit per touch; lineage records a version per distinct state.
    history = [
        (SourceVersion("aaaaaaa", "2026-08-01", "import"), "one\n"),
        (SourceVersion("bbbbbbb", "2026-08-02", "no-op"), "one\n"),
        (SourceVersion("ccccccc", "2026-08-03", "edit"), "two\n"),
    ]

    records = replay_source(history)

    assert [record.commit for record in records] == ["aaaaaaa", "ccccccc"]


def test_relineage_replays_git_history_into_versions(tmp_path):
    target = _target(tmp_path)
    spec = target / "blueprint" / "sources" / "spec.md"
    spec.write_text("The reader can add a book.\n", encoding="utf-8")
    _commit(target, "import")
    spec.write_text("The reader can add a book.\nAnd remove one.\n", encoding="utf-8")
    _commit(target, "update")

    result = relineage_target(target, runner=_runner())

    versions = load_lineage(target).sources["spec.md"].versions
    assert len(versions) == 2
    assert [version.via for version in versions] == ["relineage", "relineage"]
    assert all(version.commit for version in versions)
    assert result.sources[0].path == "spec.md"
    assert result.sources[0].versions == 2


def test_relineage_attributes_stories_and_leaves_foundational_work_unattached(tmp_path):
    target = _target(tmp_path)
    (target / "blueprint" / "sources" / "spec.md").write_text(
        "The reader can add a book.\n", encoding="utf-8"
    )
    _commit(target, "import")

    result = relineage_target(target, runner=_runner())

    versions = load_lineage(target).sources["spec.md"].versions
    assert versions[-1].requirements[0].name == "add-books"
    assert versions[-1].requirements[0].stories == ("add-book",)
    assert result.unattached == ("architecture",)
    manifest = (target / "MANIFEST.md").read_text(encoding="utf-8")
    assert "origin: plan" in manifest


def test_relineage_drops_an_unknown_story_id_with_a_warning_not_a_failure(tmp_path):
    target = _target(tmp_path)
    (target / "blueprint" / "sources" / "spec.md").write_text("Add a book.\n", encoding="utf-8")
    _commit(target, "import")
    output = (
        '<requirement name="add-books" stories="add-book,hallucinated">Add a book.</requirement>'
    )

    result = relineage_target(target, runner=_runner(output))

    assert any("hallucinated" in warning for warning in result.warnings)
    versions = load_lineage(target).sources["spec.md"].versions
    assert versions[-1].requirements[0].stories == ("add-book",)


def test_relineage_records_uncommitted_content_as_a_pending_version(tmp_path):
    target = _target(tmp_path)
    spec = target / "blueprint" / "sources" / "spec.md"
    spec.write_text("Add a book.\n", encoding="utf-8")
    _commit(target, "import")
    spec.write_text("Add a book.\nMark it read.\n", encoding="utf-8")

    relineage_target(target, runner=_runner())

    versions = load_lineage(target).sources["spec.md"].versions
    assert [version.state for version in versions] == ["consumed", "pending"]
    assert versions[-1].commit is None


def test_relineage_marks_a_withdrawn_source_deleted_but_keeps_its_history(tmp_path):
    target = _target(tmp_path)
    spec = target / "blueprint" / "sources" / "gone.md"
    spec.write_text("Old requirement.\n", encoding="utf-8")
    _commit(target, "import")
    spec.unlink()
    _commit(target, "withdraw")

    relineage_target(target, runner=_runner())

    record = load_lineage(target).sources["gone.md"]
    assert record.state == "deleted"
    assert len(record.versions) == 1


def test_relineage_is_idempotent(tmp_path):
    target = _target(tmp_path)
    (target / "blueprint" / "sources" / "spec.md").write_text("Add a book.\n", encoding="utf-8")
    _commit(target, "import")

    relineage_target(target, runner=_runner())
    first = (target / "LINEAGE.json").read_text(encoding="utf-8")
    relineage_target(target, runner=_runner())

    assert (target / "LINEAGE.json").read_text(encoding="utf-8") == first

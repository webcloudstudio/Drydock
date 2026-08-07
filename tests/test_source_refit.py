from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest

from drydock.errors import SpecificationError
from drydock.lineage import load_lineage, write_lineage
from drydock.lineage import record_import_root as record_lineage_root
from drydock.source_refit import update_import


@dataclass
class FakeRun:
    ok: bool = True
    text: str = ""
    execution_id: str = "fake"


_MANIFEST = """# MANIFEST: Demo
state: approved

## story 1: Demo
id: demo
summary: Demo
implements: FEATURE-Demo.md
state: closed/verified
"""


def _target(tmp_path: Path, source_root: Path | None = None) -> Path:
    target = tmp_path / "Demo"
    sources = target / "blueprint" / "sources"
    sources.mkdir(parents=True)
    (target / "MANIFEST.md").write_text(_MANIFEST, encoding="utf-8")
    (target / "blueprint" / "FEATURE-Demo.md").write_text("# FEATURE: Demo\n", encoding="utf-8")
    if source_root is not None:
        record_lineage_root(target, source_root, "markdown")
    return target


def test_update_import_copies_changed_files_and_records_a_pending_version(tmp_path):
    source = tmp_path / "authoring"
    source.mkdir()
    (source / "change.md").write_text("new\n", encoding="utf-8")
    target = _target(tmp_path, source)
    (target / "blueprint" / "sources" / "change.md").write_text("old\n", encoding="utf-8")

    result = update_import(target)

    assert result.changed == ("change.md",)
    assert result.pending_versions == 1
    assert (target / "blueprint" / "sources" / "change.md").read_text() == "new\n"
    version = load_lineage(target).sources["change.md"].versions[-1]
    assert version.pending is True


def test_update_import_does_not_open_the_manifest(tmp_path):
    source = tmp_path / "authoring"
    source.mkdir()
    (source / "change.md").write_text("new\n", encoding="utf-8")
    target = _target(tmp_path, source)
    before = (target / "MANIFEST.md").read_text(encoding="utf-8")

    update_import(target)

    assert (target / "MANIFEST.md").read_text(encoding="utf-8") == before


def test_update_import_works_before_the_target_is_planned(tmp_path):
    source = tmp_path / "authoring"
    source.mkdir()
    (source / "change.md").write_text("new\n", encoding="utf-8")
    target = _target(tmp_path, source)
    (target / "MANIFEST.md").unlink()

    result = update_import(target)

    assert result.added == ("change.md",)


def test_update_import_marks_deleted_sources_and_keeps_the_local_copy(tmp_path):
    source = tmp_path / "authoring"
    source.mkdir()
    (source / "kept.md").write_text("kept\n", encoding="utf-8")
    target = _target(tmp_path, source)
    removed = target / "blueprint" / "sources" / "removed.md"
    removed.write_text("old\n", encoding="utf-8")

    result = update_import(target)

    assert result.deleted == ("removed.md",)
    assert removed.is_file()
    assert load_lineage(target).sources["removed.md"].state == "deleted"


def test_update_import_records_one_version_per_distinct_content(tmp_path):
    source = tmp_path / "authoring"
    source.mkdir()
    (source / "change.md").write_text("one\n", encoding="utf-8")
    target = _target(tmp_path, source)

    update_import(target)
    update_import(target)
    (source / "change.md").write_text("two\n", encoding="utf-8")
    update_import(target)

    assert [v.hash[:6] for v in load_lineage(target).sources["change.md"].versions] != []
    assert len(load_lineage(target).sources["change.md"].versions) == 2


def test_update_import_refuses_a_changed_compass_source(tmp_path):
    source = tmp_path / "authoring"
    source.mkdir()
    (source / "COMPASS.md").write_text("# Compass\n\nnew intent\n", encoding="utf-8")
    target = _target(tmp_path, source)
    (target / "blueprint" / "sources" / "COMPASS.md").write_text(
        "# Compass\n\nold intent\n", encoding="utf-8"
    )

    with pytest.raises(SpecificationError, match="Compass-owned source changed"):
        update_import(target)


def test_update_import_without_a_recorded_root_names_the_import_command(tmp_path):
    target = _target(tmp_path)
    write_lineage(target, load_lineage(target))

    with pytest.raises(SpecificationError, match="No recorded import root"):
        update_import(target)


def test_update_import_reports_an_unavailable_root(tmp_path):
    source = tmp_path / "authoring"
    source.mkdir()
    target = _target(tmp_path, source)
    source.rmdir()

    with pytest.raises(SpecificationError, match="Imported source root is unavailable"):
        update_import(target)

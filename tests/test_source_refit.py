from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest

from drydock.errors import SpecificationError
from drydock.lineage import load_lineage, write_lineage
from drydock.lineage import record_import_root as record_lineage_root
from drydock.source_refit import source_refit_target, update_import


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


_ROUTE_OUTPUT = """<requirement name="mark-book-read">
The reader can mark a book as read.
</requirement>

<story id="mark-read-schema" implements="DATABASE.md" scope="amending" sections="Schema"
       requirement="mark-book-read" contract="changed">
Add persisted read state per book.
</story>

<story id="mark-read-view" implements="FEATURE-Demo.md" scope="additive"
       requirement="mark-book-read" depends="mark-read-schema">
Render read state per book.
</story>
"""

_PLANNED_MANIFEST = """# MANIFEST: Demo
state: approved

## story 1: Persist books.
id: database
summary: Persist books.
type: foundational
phase: 1
block: 1
implements: DATABASE.md
provides: books persistence interface
state: closed/verified

## story 2: Demo feature.
id: demo
summary: Demo feature.
type: feature
phase: 2
block: 2
implements: FEATURE-Demo.md
consumes: books persistence interface
state: closed/verified
"""


def _routable_target(tmp_path: Path, source_root: Path) -> Path:
    from drydock.lineage import record_initial_snapshot

    target = _target(tmp_path, source_root)
    blueprint = target / "blueprint"
    (target / "MANIFEST.md").write_text(_PLANNED_MANIFEST, encoding="utf-8")
    (blueprint / "DATABASE.md").write_text(
        "# DATABASE: Demo\n\n| Depends On | ARCHITECTURE.md |\n\n## Schema\n\nBooks.\n",
        encoding="utf-8",
    )
    (blueprint / "FEATURE-Demo.md").write_text("# FEATURE: Demo\n\n## Purpose\n\nDemo.\n", "utf-8")
    (blueprint / "sources" / "spec.md").write_text("Add a book.\n", encoding="utf-8")
    record_initial_snapshot(target, blueprint / "sources", date="2026-08-05")
    lineage = load_lineage(target)
    for version in lineage.sources["spec.md"].versions:
        version.state = "consumed"
        version.via = "plan"
    write_lineage(target, lineage)
    (source_root / "spec.md").write_text("Add a book.\nMark a book read.\n", encoding="utf-8")
    update_import(target)
    return target


def _runner(text: str = _ROUTE_OUTPUT):
    def run(prompt, working_directory, **kwargs):
        return FakeRun(text=text)

    return run


def test_source_refit_with_no_pending_versions_makes_no_llm_call(tmp_path):
    source = tmp_path / "authoring"
    source.mkdir()
    (source / "spec.md").write_text("Add a book.\n", encoding="utf-8")
    target = _routable_target(tmp_path, source)
    lineage = load_lineage(target)
    for record in lineage.sources.values():
        for version in record.versions:
            version.state = "consumed"
            version.via = "plan"
    write_lineage(target, lineage)

    def explode(prompt, working_directory, **kwargs):  # pragma: no cover - must not run
        raise AssertionError("no pending versions must not reach the model")

    result = source_refit_target(target, runner=explode)

    assert result.items == ()


def test_source_refit_writes_one_ticket_per_blueprint_with_stories(tmp_path):
    source = tmp_path / "authoring"
    source.mkdir()
    target = _routable_target(tmp_path, source)

    result = source_refit_target(target, runner=_runner())

    assert [item.blueprint for item in result.items] == ["DATABASE.md", "FEATURE-Demo.md"]
    database, feature = result.items
    assert database.scope == "amending"
    assert feature.scope == "additive"
    assert database.ticket.parent.name == "changes"
    assert database.ticket.name.startswith("TICKET-001-")
    assert feature.ticket.name.startswith("TICKET-002-")

    text = database.ticket.read_text(encoding="utf-8")
    assert "| Amends | DATABASE.md |" in text
    assert "| Scope | amending |" in text
    assert "| Created | " in text
    assert "| Stories | mark-read-schema |" in text
    assert "| Depends On | DATABASE.md, ARCHITECTURE.md |" in text
    assert "## Amended Sections" in text

    additive = feature.ticket.read_text(encoding="utf-8")
    assert "supersedes nothing" in additive


def test_source_refit_appends_ordered_stories_with_provenance(tmp_path):
    source = tmp_path / "authoring"
    source.mkdir()
    target = _routable_target(tmp_path, source)

    source_refit_target(target, runner=_runner())

    manifest = (target / "MANIFEST.md").read_text(encoding="utf-8")
    assert "id: mark-read-schema" in manifest
    assert "id: mark-read-view" in manifest
    assert "depends: mark-read-schema" in manifest
    assert "origin: spec.md" in manifest
    assert "created: " in manifest
    assert "implements: changes/TICKET-001-" in manifest


def test_source_refit_consumes_the_version_and_records_its_stories(tmp_path):
    source = tmp_path / "authoring"
    source.mkdir()
    target = _routable_target(tmp_path, source)

    source_refit_target(target, runner=_runner())

    versions = load_lineage(target).sources["spec.md"].versions
    assert [v.state for v in versions] == ["consumed", "consumed"]
    assert versions[0].via == "plan"
    assert versions[-1].via == "refit"
    assert versions[-1].requirements[0].name == "mark-book-read"
    assert versions[-1].requirements[0].stories == ("mark-read-schema", "mark-read-view")
    # The earlier version keeps its own provenance; nothing is overwritten.
    assert versions[0].hash != versions[-1].hash


def test_source_refit_reports_downstream_consumers_without_blocking(tmp_path):
    source = tmp_path / "authoring"
    source.mkdir()
    target = _routable_target(tmp_path, source)

    result = source_refit_target(target, runner=_runner())

    assert any("demo" in item for item in result.downstream)
    assert "## Downstream Impact" in result.items[0].ticket.read_text(encoding="utf-8")


def test_source_refit_blocks_a_deletion_a_live_story_consumes(tmp_path):
    source = tmp_path / "authoring"
    source.mkdir()
    target = _routable_target(tmp_path, source)
    output = _ROUTE_OUTPUT + '\n<deleted provides="books persistence interface"/>\n'

    with pytest.raises(SpecificationError, match="would break demo"):
        source_refit_target(target, runner=_runner(output))

    assert not list((target / "blueprint" / "changes").glob("TICKET-*.md"))


def test_source_refit_refuses_to_create_a_blueprint(tmp_path):
    source = tmp_path / "authoring"
    source.mkdir()
    target = _routable_target(tmp_path, source)
    output = _ROUTE_OUTPUT.replace("FEATURE-Demo.md", "FEATURE-Invented.md")

    with pytest.raises(SpecificationError, match="never creates a Blueprint"):
        source_refit_target(target, runner=_runner(output))


def test_source_refit_fails_with_replan_required_on_an_unseatable_requirement(tmp_path):
    source = tmp_path / "authoring"
    source.mkdir()
    target = _routable_target(tmp_path, source)
    output = '<unseatable requirement="user-accounts">No Blueprint owns identity.</unseatable>'

    with pytest.raises(SpecificationError, match="Replan required"):
        source_refit_target(target, runner=_runner(output))


def test_source_refit_rolls_back_the_manifest_and_lineage_on_failure(tmp_path):
    source = tmp_path / "authoring"
    source.mkdir()
    target = _routable_target(tmp_path, source)
    before_manifest = (target / "MANIFEST.md").read_text(encoding="utf-8")
    before_lineage = (target / "LINEAGE.json").read_text(encoding="utf-8")
    # A section the parent does not have fails during ticket rendering, after the first write.
    output = _ROUTE_OUTPUT.replace('sections="Schema"', 'sections="Nonexistent"')

    with pytest.raises(SpecificationError):
        source_refit_target(target, runner=_runner(output))

    assert (target / "MANIFEST.md").read_text(encoding="utf-8") == before_manifest
    assert (target / "LINEAGE.json").read_text(encoding="utf-8") == before_lineage
    assert not list((target / "blueprint" / "changes").glob("TICKET-*.md"))


def test_source_refit_refuses_a_non_text_source(tmp_path):
    source = tmp_path / "authoring"
    source.mkdir()
    target = _routable_target(tmp_path, source)
    (source / "app.py").write_text("print('x')\n", encoding="utf-8")
    update_import(target)

    with pytest.raises(SpecificationError, match="markdown and text sources"):
        source_refit_target(target, runner=_runner())


def test_source_refit_without_a_manifest_names_plan(tmp_path):
    source = tmp_path / "authoring"
    source.mkdir()
    target = _routable_target(tmp_path, source)
    (target / "MANIFEST.md").unlink()

    with pytest.raises(SpecificationError, match="plan the Target"):
        source_refit_target(target, runner=_runner())

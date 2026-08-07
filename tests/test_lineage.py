from __future__ import annotations

import json
from pathlib import Path

from drydock.lineage import (
    LINEAGE_FILENAME,
    Lineage,
    Requirement,
    append_version,
    attach_stories,
    consume_version,
    lineage_path,
    load_lineage,
    load_or_migrate,
    mark_source_deleted,
    record_import_root,
    seed_from_disk,
    stamp_pending_commits,
    write_lineage,
)

_MANIFEST = """# MANIFEST: Demo
state: approved
source_lineage: |
  {"version": 1, "files": {"spec.md": {"hash": "old", "blueprints": ["FEATURE-Demo.md"], \
"pending_change": true}}}
updated: 2026-08-06

## story 1: Demo
id: demo
summary: Demo
implements: FEATURE-Demo.md
state: closed/verified
"""


def _target(tmp_path: Path, *, sources: dict[str, str] | None = None) -> Path:
    target = tmp_path / "Demo"
    sources_dir = target / "blueprint" / "sources"
    sources_dir.mkdir(parents=True)
    for name, text in (sources or {}).items():
        path = sources_dir / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return target


def test_load_lineage_returns_empty_on_missing_file(tmp_path):
    assert load_lineage(tmp_path).is_empty()


def test_load_lineage_returns_empty_on_corrupt_json(tmp_path):
    lineage_path(tmp_path).write_text("{not json", encoding="utf-8")

    assert load_lineage(tmp_path).is_empty()


def test_write_lineage_uses_two_space_indent_lf_and_a_trailing_newline(tmp_path):
    lineage = Lineage()
    append_version(lineage, "spec.md", hash="abc", date="2026-08-06")

    path = write_lineage(tmp_path, lineage)

    raw = path.read_bytes().decode("utf-8")
    assert raw.endswith("}\n")
    assert "\r\n" not in raw
    assert '\n  "version": 1' in raw
    assert path.name == LINEAGE_FILENAME


def test_lineage_round_trips_through_json(tmp_path):
    lineage = Lineage()
    append_version(lineage, "spec.md", hash="abc", date="2026-08-06", release="0.01")
    consume_version(
        lineage,
        "spec.md",
        via="refit",
        ticket="TICKET-001-Demo.md",
        requirements=[Requirement("mark-read", "The reader can mark a book as read.", ("a", "b"))],
    )
    write_lineage(tmp_path, lineage)

    reloaded = load_lineage(tmp_path)

    version = reloaded.sources["spec.md"].versions[0]
    assert version.state == "consumed"
    assert version.via == "refit"
    assert version.ticket == "TICKET-001-Demo.md"
    assert version.requirements[0].name == "mark-read"
    assert version.requirements[0].stories == ("a", "b")


def test_append_version_ignores_unchanged_content(tmp_path):
    lineage = Lineage()

    assert append_version(lineage, "spec.md", hash="abc", date="2026-08-06") is not None
    assert append_version(lineage, "spec.md", hash="abc", date="2026-08-07") is None
    assert append_version(lineage, "spec.md", hash="def", date="2026-08-08") is not None
    assert len(lineage.sources["spec.md"].versions) == 2


def test_consume_version_does_not_rewrite_an_earlier_version(tmp_path):
    lineage = Lineage()
    append_version(lineage, "spec.md", hash="one", date="2026-08-06")
    consume_version(lineage, "spec.md", via="plan")
    append_version(lineage, "spec.md", hash="two", date="2026-08-07")

    consume_version(lineage, "spec.md", via="refit", ticket="TICKET-001-Demo.md")

    first, second = lineage.sources["spec.md"].versions
    assert (first.hash, first.via, first.ticket) == ("one", "plan", None)
    assert (second.hash, second.via, second.ticket) == ("two", "refit", "TICKET-001-Demo.md")


def test_pending_versions_reports_only_unconsumed_work(tmp_path):
    lineage = Lineage()
    append_version(lineage, "a.md", hash="one", date="2026-08-06")
    consume_version(lineage, "a.md", via="plan")
    append_version(lineage, "b.md", hash="two", date="2026-08-06")

    assert [path for path, _ in lineage.pending_versions()] == ["b.md"]


def test_stamp_pending_commits_fills_only_missing_shas(tmp_path):
    lineage = Lineage()
    append_version(lineage, "a.md", hash="one", date="2026-08-06", commit="aaaaaaa")
    append_version(lineage, "b.md", hash="two", date="2026-08-06")

    assert stamp_pending_commits(lineage, "bbbbbbb") == 1
    assert lineage.sources["a.md"].versions[0].commit == "aaaaaaa"
    assert lineage.sources["b.md"].versions[0].commit == "bbbbbbb"


def test_mark_source_deleted_retains_every_version(tmp_path):
    lineage = Lineage()
    append_version(lineage, "spec.md", hash="one", date="2026-08-06")

    record = mark_source_deleted(lineage, "spec.md")

    assert record.state == "deleted"
    assert len(record.versions) == 1


def test_attach_stories_merges_without_duplicating(tmp_path):
    lineage = Lineage()
    append_version(lineage, "spec.md", hash="one", date="2026-08-06")
    version = consume_version(
        lineage, "spec.md", via="plan", requirements=[Requirement("r", "text", ("a",))]
    )

    attach_stories(version, {"r": ["a", "b"]})

    assert version.requirements[0].stories == ("a", "b")


def test_record_import_root_keeps_a_wider_directory_root(tmp_path):
    target = _target(tmp_path)
    wide = tmp_path / "sources"
    (wide / "nested").mkdir(parents=True)
    narrow = wide / "nested" / "spec.md"
    narrow.write_text("spec\n", encoding="utf-8")

    record_import_root(target, wide, "markdown")
    lineage = record_import_root(target, narrow, "source")

    assert lineage.import_record.root == str(wide)
    assert lineage.import_record.format == "markdown"


def test_record_import_root_replaces_an_unrelated_root(tmp_path):
    target = _target(tmp_path)
    first = tmp_path / "one"
    first.mkdir()
    second = tmp_path / "two"
    second.mkdir()

    record_import_root(target, first, "markdown")
    lineage = record_import_root(target, second, "source")

    assert lineage.import_record.root == str(second)
    assert lineage.import_record.format == "source"


def test_seed_from_disk_skips_hidden_and_compass_sources(tmp_path):
    target = _target(
        tmp_path,
        sources={
            "spec.md": "# Spec\n\nBuild a thing.\n",
            "COMPASS.md": "# Compass\n\nThis is the author's intent.\n",
            ".drydock-import": "source: x\n",
        },
    )
    lineage = Lineage()

    seeded = seed_from_disk(lineage, target / "blueprint" / "sources", date="2026-08-06")

    assert seeded == ("spec.md",)


def test_seed_from_disk_leaves_versions_pending_by_default(tmp_path):
    target = _target(tmp_path, sources={"spec.md": "one\n"})
    lineage = Lineage()

    seed_from_disk(lineage, target / "blueprint" / "sources", date="2026-08-06")

    assert lineage.sources["spec.md"].versions[0].pending is True


def test_seed_from_disk_backdates_only_when_a_consumer_is_named(tmp_path):
    target = _target(tmp_path, sources={"spec.md": "one\n"})
    lineage = Lineage()

    seed_from_disk(lineage, target / "blueprint" / "sources", date="2026-08-06", consumed_by="plan")

    version = lineage.sources["spec.md"].versions[0]
    assert (version.state, version.via) == ("consumed", "plan")


def test_migration_absorbs_the_legacy_import_marker_and_deletes_it(tmp_path):
    target = _target(tmp_path, sources={"spec.md": "one\n"})
    marker = target / "blueprint" / "sources" / ".drydock-import"
    marker.write_text(f"source: {tmp_path / 'spec.md'}\nformat: markdown\n", encoding="utf-8")

    lineage = load_or_migrate(target, date="2026-08-06")

    assert lineage.import_record.root == str(tmp_path / "spec.md")
    assert lineage.import_record.format == "markdown"
    assert not marker.exists()
    assert lineage_path(target).is_file()


def test_migration_keeps_pending_work_and_discards_the_blueprint_mapping(tmp_path):
    target = _target(tmp_path, sources={"spec.md": "one\n"})
    (target / "MANIFEST.md").write_text(_MANIFEST, encoding="utf-8")

    lineage = load_or_migrate(target, date="2026-08-06")

    version = lineage.sources["spec.md"].versions[0]
    assert version.pending is True
    raw = json.loads(lineage_path(target).read_text(encoding="utf-8"))
    assert "blueprints" not in json.dumps(raw)
    assert "source_lineage" not in (target / "MANIFEST.md").read_text(encoding="utf-8")


def test_migration_on_a_target_with_no_legacy_state_is_still_valid(tmp_path):
    target = _target(tmp_path, sources={"spec.md": "one\n"})

    lineage = load_or_migrate(target, date="2026-08-06")

    assert lineage.import_record.root is None
    assert lineage.sources["spec.md"].versions[0].pending is True


def test_load_or_migrate_is_idempotent(tmp_path):
    target = _target(tmp_path, sources={"spec.md": "one\n"})

    first = load_or_migrate(target, date="2026-08-06")
    consume_version(first, "spec.md", via="plan")
    append_version(first, "spec.md", hash="two", date="2026-08-07")
    consume_version(first, "spec.md", via="refit", ticket="TICKET-001-Demo.md")
    write_lineage(target, first)
    second = load_or_migrate(target, date="2026-08-07")

    assert [v.ticket for v in second.sources["spec.md"].versions] == [
        None,
        "TICKET-001-Demo.md",
    ]


def test_consume_version_takes_the_oldest_pending_delta_first(tmp_path):
    lineage = Lineage()
    append_version(lineage, "spec.md", hash="one", date="2026-08-06")
    append_version(lineage, "spec.md", hash="two", date="2026-08-07")

    consumed = consume_version(lineage, "spec.md", via="refit", ticket="TICKET-001-Demo.md")

    assert consumed.hash == "one"
    assert lineage.sources["spec.md"].versions[1].pending is True


def test_migration_backdates_a_planned_target_to_plan(tmp_path):
    target = _target(tmp_path, sources={"spec.md": "one\n"})
    (target / "MANIFEST.md").write_text(
        "# MANIFEST: Demo\nstate: approved\n\n## story 1: Demo\nid: demo\nsummary: Demo\n"
        "implements: FEATURE-Demo.md\nstate: pending\n",
        encoding="utf-8",
    )

    lineage = load_or_migrate(target, date="2026-08-06")

    version = lineage.sources["spec.md"].versions[0]
    assert (version.state, version.via) == ("consumed", "plan")

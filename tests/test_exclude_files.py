from __future__ import annotations

from drydock.exclude_files import (
    append_suggested_exclusions,
    ensure_exclude_file,
    load_excluded_filenames,
)


def test_ensure_exclude_file_creates_template(tmp_path):
    text = ensure_exclude_file(tmp_path)

    assert "# Exclude Files" in text
    assert "## Excluded files" in text
    assert (tmp_path / "EXCLUDE_FILES.md").is_file()


def test_append_suggested_exclusions_adds_matching_source_names_once(tmp_path):
    ensure_exclude_file(tmp_path)
    source_dir = tmp_path / "blueprint" / "sources"
    source_dir.mkdir(parents=True)
    build_plan = source_dir / "BUILD_PLAN.md"
    build_plan.write_text("x", encoding="utf-8")

    append_suggested_exclusions(tmp_path, [build_plan])
    append_suggested_exclusions(tmp_path, [build_plan])

    assert load_excluded_filenames(tmp_path) == frozenset({"BUILD_PLAN.md"})
    text = (tmp_path / "EXCLUDE_FILES.md").read_text(encoding="utf-8")
    assert text.count("- BUILD_PLAN.md") == 1


def test_append_suggested_exclusions_does_not_exclude_intent_or_functionality(tmp_path):
    ensure_exclude_file(tmp_path)
    source_dir = tmp_path / "blueprint" / "sources"
    source_dir.mkdir(parents=True)
    intent = source_dir / "INTENT.md"
    functionality = source_dir / "FUNCTIONALITY.md"
    intent.write_text("intent", encoding="utf-8")
    functionality.write_text("features", encoding="utf-8")

    append_suggested_exclusions(tmp_path, [intent, functionality])

    assert load_excluded_filenames(tmp_path) == frozenset()


def test_append_suggested_exclusions_excludes_manifest_and_contract_sources(tmp_path):
    ensure_exclude_file(tmp_path)
    source_dir = tmp_path / "blueprint" / "sources"
    source_dir.mkdir(parents=True)
    manifest = source_dir / "MANIFEST.md"
    contract = source_dir / "API_CONTRACT.md"
    functionality = source_dir / "FUNCTIONALITY.md"
    for path in (manifest, contract, functionality):
        path.write_text("x", encoding="utf-8")

    append_suggested_exclusions(tmp_path, [manifest, contract, functionality])

    assert load_excluded_filenames(tmp_path) == frozenset({"API_CONTRACT.md", "MANIFEST.md"})

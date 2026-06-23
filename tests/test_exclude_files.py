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

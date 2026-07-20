from __future__ import annotations

from drydock.source_roles import parse_source_roles, promote_imported_sources, stage_context_file


def test_promotes_assets_and_routes_author_intent_to_compass(tmp_path):
    blueprint = tmp_path / "blueprint"
    sources = blueprint / "sources"
    sources.mkdir(parents=True)
    (sources / "spec.txt").write_text("corpus", encoding="utf-8")
    (sources / "ED_INSTRUCTIONS.md").write_text("# Author Intent\n\nBuild it.\n", encoding="utf-8")
    roles = parse_source_roles(
        """## Source Roles

| Path | Role | Plan disposition | Build disposition |
|---|---|---|---|
| sources/spec.txt | normative conformance corpus | context | stage |
| sources/ED_INSTRUCTIONS.md | author intent | compass | none |
"""
    )

    promote_imported_sources(blueprint, roles, tmp_path)

    assert (blueprint / "spec.txt").read_text(encoding="utf-8") == "corpus"
    assert (sources / "spec.txt").read_text(encoding="utf-8") == "corpus"
    assert not (blueprint / "ED_INSTRUCTIONS.md").exists()
    assert "Build it." in (tmp_path / "COMPASS.md").read_text(encoding="utf-8")


def test_stage_context_file_copies_non_markdown_asset(tmp_path):
    blueprint = tmp_path / "blueprint"
    source = blueprint / "test" / "spec.txt"
    source.parent.mkdir(parents=True)
    source.write_text("corpus", encoding="utf-8")
    build = tmp_path / "build"

    staged = stage_context_file(source, "test/spec.txt", blueprint_dir=blueprint, build_dir=build)

    assert staged == build / "test" / "spec.txt"
    assert staged.read_text(encoding="utf-8") == "corpus"

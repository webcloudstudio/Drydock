from pathlib import Path

from drydock.planning_session import _source_evidence_bundle
from drydock.source_material import (
    discover_source_material,
    inventory_markdown,
    withheld_content_warning,
)


def test_discover_source_material_accounts_for_heterogeneous_imports(tmp_path: Path) -> None:
    blueprint = tmp_path / "blueprint"
    sources = blueprint / "sources"
    sources.mkdir(parents=True)
    (sources / "request.md").write_text("# Request\n", encoding="utf-8")
    (sources / "parser.py").write_text("def parse(): pass\n", encoding="utf-8")
    (sources / "asset.bin").write_bytes(b"\0binary")
    (sources / "bundle.js").write_text("x" * 2_100, encoding="utf-8")

    source_material = discover_source_material(blueprint)

    assert [(entry.relative_path, entry.disposition) for entry in source_material] == [
        ("sources/asset.bin", "skipped"),
        ("sources/bundle.js", "summarized"),
        ("sources/parser.py", "analyzed"),
        ("sources/request.md", "analyzed"),
    ]
    assert "| `sources/asset.bin` | binary | skipped | binary content |" in inventory_markdown(
        source_material
    )
    assert source_material[2].fence == "python"


def test_plan_evidence_bundle_includes_every_readable_source(tmp_path: Path) -> None:
    blueprint = tmp_path / "blueprint"
    sources = blueprint / "sources"
    sources.mkdir(parents=True)
    (sources / "parser.py").write_text("def parse(): pass\n", encoding="utf-8")
    (sources / "normalizer.py").write_text("def normalize(): pass\n", encoding="utf-8")
    analysis = "## Planning Instructions\n\nParser scope: `sources/parser.py`.\n"

    bundle = _source_evidence_bundle(blueprint, analysis, excluded_filenames=frozenset())

    assert [entry.relative_path for entry in bundle or []] == [
        "sources/normalizer.py",
        "sources/parser.py",
    ]


def test_plan_evidence_bundle_does_not_require_analyze_citations(tmp_path: Path) -> None:
    blueprint = tmp_path / "blueprint"
    (blueprint / "sources").mkdir(parents=True)
    (blueprint / "sources" / "parser.py").write_text("pass\n", encoding="utf-8")

    bundle = _source_evidence_bundle(
        blueprint,
        "## Planning Instructions\n\nScope: `sources/absent.md`.\n",
        excluded_filenames=frozenset(),
    )

    assert [entry.relative_path for entry in bundle or []] == ["sources/parser.py"]


def test_wrapped_prose_is_not_classified_as_generated(tmp_path: Path) -> None:
    # Observed on the Marina target: nine hand-written specifications were classified `summarized`
    # and their text was withheld from every prompt. The old test was aggregate newline density,
    # which Markdown wrapped at ~120 columns fails by construction.
    blueprint = tmp_path / "blueprint"
    sources = blueprint / "sources"
    sources.mkdir(parents=True)
    paragraph = ("The scanner records repository identity and provenance evidence. " * 2).strip()
    prose = "# Feature\n\n" + "\n".join(f"- {paragraph}" for _ in range(60)) + "\n"
    assert len(prose) > 2_000
    (sources / "FEATURE.md").write_text(prose, encoding="utf-8")

    source_material = discover_source_material(blueprint)

    assert source_material[0].disposition == "analyzed"
    assert source_material[0].text == prose


def test_single_line_minified_asset_is_still_summarized(tmp_path: Path) -> None:
    blueprint = tmp_path / "blueprint"
    sources = blueprint / "sources"
    sources.mkdir(parents=True)
    (sources / "bundle.js").write_text("var a=1;" * 1_000, encoding="utf-8")

    source_material = discover_source_material(blueprint)

    assert source_material[0].disposition == "summarized"
    assert source_material[0].reason == "likely generated or minified"
    assert source_material[0].text is None


def test_machine_packed_prose_is_still_analyzed(tmp_path: Path) -> None:
    # An author imports a specification to have it read. Prose content is never withheld on
    # formatting grounds: a withheld specification is a missing story.
    blueprint = tmp_path / "blueprint"
    sources = blueprint / "sources"
    sources.mkdir(parents=True)
    one_line = "The scanner shall record repository provenance. " * 200
    (sources / "FEATURE.md").write_text(one_line, encoding="utf-8")
    (sources / "NOTES.txt").write_text(one_line, encoding="utf-8")

    source_material = discover_source_material(blueprint)

    assert [(entry.relative_path, entry.disposition) for entry in source_material] == [
        ("sources/FEATURE.md", "analyzed"),
        ("sources/NOTES.txt", "analyzed"),
    ]
    assert all(entry.text == one_line for entry in source_material)


def test_large_prose_is_chunked_rather_than_withheld(tmp_path: Path) -> None:
    blueprint = tmp_path / "blueprint"
    sources = blueprint / "sources"
    sources.mkdir(parents=True)
    huge = "The scanner shall record repository provenance evidence.\n" * 1_500
    assert len(huge) > 48_000
    (sources / "FEATURE.md").write_text(huge, encoding="utf-8")

    entry = discover_source_material(blueprint)[0]

    assert entry.disposition == "chunked"
    assert entry.text == huge
    assert "".join(entry.prompt_chunks) == huge


def test_withheld_content_warning_names_every_unread_file(tmp_path: Path) -> None:
    blueprint = tmp_path / "blueprint"
    sources = blueprint / "sources"
    sources.mkdir(parents=True)
    (sources / "bundle.js").write_text("var a=1;" * 1_000, encoding="utf-8")
    (sources / "logo.png").write_bytes(b"\0png")
    (sources / "FEATURE.md").write_text("# Feature\n", encoding="utf-8")

    warning = withheld_content_warning(discover_source_material(blueprint))

    assert warning is not None
    assert "sources/bundle.js (likely generated or minified)" in warning
    assert "sources/logo.png (binary content)" in warning
    assert "FEATURE.md" not in warning


def test_withheld_content_warning_is_absent_when_every_file_is_read(tmp_path: Path) -> None:
    blueprint = tmp_path / "blueprint"
    sources = blueprint / "sources"
    sources.mkdir(parents=True)
    (sources / "FEATURE.md").write_text("# Feature\n", encoding="utf-8")

    assert withheld_content_warning(discover_source_material(blueprint)) is None

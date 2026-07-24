from pathlib import Path

import pytest

from drydock.errors import SpecificationError
from drydock.planning_session import _source_evidence_bundle
from drydock.source_material import discover_source_material, inventory_markdown


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


def test_plan_evidence_bundle_selects_only_analyze_citations(tmp_path: Path) -> None:
    blueprint = tmp_path / "blueprint"
    sources = blueprint / "sources"
    sources.mkdir(parents=True)
    (sources / "parser.py").write_text("def parse(): pass\n", encoding="utf-8")
    (sources / "normalizer.py").write_text("def normalize(): pass\n", encoding="utf-8")
    analysis = "## Planning Instructions\n\nParser scope: `sources/parser.py`.\n"

    bundle = _source_evidence_bundle(blueprint, analysis, excluded_filenames=frozenset())

    assert [entry.relative_path for entry in bundle or []] == ["sources/parser.py"]


def test_plan_evidence_bundle_rejects_missing_analyze_citation(tmp_path: Path) -> None:
    blueprint = tmp_path / "blueprint"
    (blueprint / "sources").mkdir(parents=True)
    (blueprint / "sources" / "parser.py").write_text("pass\n", encoding="utf-8")

    with pytest.raises(SpecificationError, match="no `sources/...` evidence citations"):
        _source_evidence_bundle(
            blueprint,
            "## Planning Instructions\n\n### Delivery Shape\n\nCLI.\n",
            excluded_filenames=frozenset(),
        )

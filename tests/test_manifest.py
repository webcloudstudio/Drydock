"""Typed, lossless MANIFEST.md graph contract."""

from __future__ import annotations

from pathlib import Path

import pytest

from drydock.manifest import (
    AcceptanceNode,
    DrydockManifest,
    FeatureNode,
    ManifestError,
    StoryNode,
)

VALID = """# MANIFEST: Demo
state: approved
extension: retained

<!-- preamble comment -->

## feature 1: Core
id: feature-core
summary: Core work.
state: pending
x-owner: Ed

## story 1: Service
id: service
parent: feature-core
summary: Build service.
implements: FEATURE-SERVICE.md
instructions: |
  First line.
  Second line.
state: implemented

## ac 1: Release gate
id: release-gate
parent: service
summary: Gate the release.
kind: assertion
state: pending
"""


def test_parse_exposes_typed_metadata_nodes_and_queries():
    graph = DrydockManifest.parse(VALID, source="MANIFEST.md")

    assert graph.project == "Demo"
    assert graph.metadata.fields["extension"] == "retained"
    assert isinstance(graph.blocks[0], FeatureNode)
    assert isinstance(graph.blocks[1], StoryNode)
    assert isinstance(graph.blocks[2], AcceptanceNode)
    assert graph.parent_of("service").block_id == "feature-core"
    assert [node.block_id for node in graph.children("feature-core")] == ["service"]
    assert [node.block_id for node in graph.runnable_frontier()] == ["release-gate"]


def test_unrelated_mutation_preserves_comments_extensions_order_and_multiline():
    graph = DrydockManifest.parse(VALID, source="MANIFEST.md")
    graph.transition("release-gate", "closed/verified")
    rendered = graph.render()

    assert "<!-- preamble comment -->" in rendered
    assert "x-owner: Ed" in rendered
    assert "First line.\n  Second line." in rendered
    assert rendered.index("## feature") < rendered.index("## story") < rendered.index("## ac")


def test_legacy_compact_ac_becomes_explicit_on_mutation():
    text = """# MANIFEST: Demo
state: approved

## story 1: Service
id: service
state: implemented

## ac 1: Health works (smoke: test -f health)
"""
    graph = DrydockManifest.parse(text, source="MANIFEST.md")
    acceptance = graph.blocks[-1]
    assert acceptance.legacy_compact

    graph.transition(acceptance.block_id, "closed/verified")
    rendered = graph.render()

    assert "id: health-works" in rendered
    assert "parent: service" in rendered
    assert "summary: Health works" in rendered
    assert "kind: smoke" in rendered
    assert "check: test -f health" in rendered


@pytest.mark.parametrize(
    ("body", "message"),
    [
        ("# MANIFEST: Demo\n\n## story one: Bad\nid: bad\n", "malformed block header"),
        ("# MANIFEST: Demo\n\n## story 1: Bad\nstate: pending\n", "missing required `id`"),
        (
            "# MANIFEST: Demo\n\n## story 1: A\nid: duplicate\nstate: pending\n\n"
            "## spike 1: B\nid: duplicate\nstate: pending\n",
            "Duplicate block id",
        ),
        (
            "# MANIFEST: Demo\n\n## story 1: A\nid: a\ndepends: absent\nstate: pending\n",
            "unknown dependency",
        ),
        (
            "# MANIFEST: Demo\n\n## feature 1: F\nid: f\nstate: pending\n\n"
            "## story 1: A\nid: a\nparent: f\ndepends: b\nstate: pending\n\n"
            "## story 2: B\nid: b\nparent: f\ndepends: a\nstate: pending\n",
            "dependency cycle",
        ),
        (
            "# MANIFEST: Demo\n\n## story 1: A\nid: a\nstate: pending\n\n"
            "## ac 1: Bad\nid: bad\nparent: absent\nkind: nope\nstate: pending\n",
            "parent names unknown id",
        ),
    ],
)
def test_structured_defects_are_actionable(body: str, message: str):
    with pytest.raises(ManifestError) as excinfo:
        DrydockManifest.parse(body, source="/target/MANIFEST.md")

    rendered = str(excinfo.value)
    assert "/target/MANIFEST.md" in rendered
    assert message in rendered
    assert "No files were changed" in rendered
    assert excinfo.value.defects


def test_save_is_atomic_and_reloads(tmp_path: Path):
    path = tmp_path / "MANIFEST.md"
    graph = DrydockManifest.parse(VALID, source=path)
    graph.transition("service", "closed/verified")
    graph.save()

    loaded = DrydockManifest.load(path)
    assert loaded.node("service").state == "closed/verified"
    assert not tuple(tmp_path.glob("tmp*"))


def test_graph_add_move_regroup_remove_and_reset():
    graph = DrydockManifest.parse(VALID, source="MANIFEST.md")
    second = graph.create_node(
        "story",
        "consumer",
        "Consumer",
        number=2,
        parent="feature-core",
        depends=("service",),
        summary="Consume service.",
        implements=("FEATURE-CONSUMER.md",),
        state="closed/verified",
    )
    graph.add(second, before="release-gate")
    graph.move("consumer", after="release-gate")
    assert graph.reset(("service",)) == (
        "feature-core",
        "service",
        "release-gate",
        "consumer",
    )
    assert all(graph.node(node_id).state == "pending" for node_id in graph.ids())

    graph.remove("consumer")
    assert "consumer" not in graph.by_id()


def test_replay_20260727_context_manifest_parses_without_executing_acceptance():
    # Captured from the 2026-07-27 CommonMark plan run; logs/ is not committed, so the replayed
    # MANIFEST.md body lives with the tests.
    manifest = (Path(__file__).parent / "fixtures" / "replay_20260727_manifest.md").read_text(
        encoding="utf-8"
    )

    graph = DrydockManifest.parse(manifest, source="replay:20260727.214434.270Z-e71883e0")

    assert len(graph.blocks) == 67
    assert [node.block_id for node in graph.runnable_frontier()] == ["scaffold"]


_LINEAGE_MANIFEST = """# MANIFEST: Demo
state: approved
source_lineage: |
  {"version": 1, "files": {"spec.md": {"hash": "old"}}}
updated: 2026-08-06

## story 1: Demo
id: demo
summary: Demo
implements: FEATURE-Demo.md
state: pending
"""


def test_clear_source_lineage_removes_the_preamble_field_and_its_body():
    manifest = DrydockManifest.parse(_LINEAGE_MANIFEST, source="test")

    assert manifest.clear_source_lineage() is True

    rendered = manifest.render()
    assert "source_lineage" not in rendered
    assert '{"version": 1' not in rendered
    assert "updated: 2026-08-06" in rendered
    assert "## story 1: Demo" in rendered
    assert manifest.source_lineage == {}


def test_clear_source_lineage_survives_a_save_and_reload(tmp_path: Path):
    path = tmp_path / "MANIFEST.md"
    path.write_text(_LINEAGE_MANIFEST, encoding="utf-8")
    manifest = DrydockManifest.load(path, compatibility=True)

    manifest.clear_source_lineage()
    manifest.save()

    reloaded = DrydockManifest.load(path, compatibility=True)
    assert reloaded.source_lineage == {}
    assert "source_lineage" not in path.read_text(encoding="utf-8")
    assert reloaded.node("demo").block_id == "demo"


def test_remove_metadata_reports_a_missing_field():
    manifest = DrydockManifest.parse(_LINEAGE_MANIFEST, source="test")

    assert manifest.remove_metadata("nonexistent") is False

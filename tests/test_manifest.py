"""Tests for the manifest work graph — node model, parser, writer, frontier."""

from __future__ import annotations

from drydock.manifest import (
    ManifestGraph,
    ManifestNode,
    parse_manifest,
    render_manifest,
    render_node,
)

# ---------------------------------------------------------------------------
# Minimal MANIFEST.md fixtures
# ---------------------------------------------------------------------------

_MINIMAL_MANIFEST = """\
## SPIKE-001: Choose frontend validation library
- type: spike
- depends-on: ROOT
- state: not-started

Decision: native HTML5 or third-party library?

## STORY-001: Add login form validation
- type: story
- spec: FEATURE-Authentication.md
- parent: FEATURE-001
- depends-on: SPIKE-001
- state: not-started

Validate email format and password length.

## AC-001a: Login validation rejects invalid email
- type: ac
- depends-on: STORY-001
- state: not-started

pytest: tests/test_login.py::test_invalid_email_rejected
"""

_FEATURE_NODE = """\
## FEATURE-001: Authentication
- type: feature
- state: not-started
"""


# ---------------------------------------------------------------------------
# parse_manifest
# ---------------------------------------------------------------------------


class TestParseManifest:
    def test_parses_node_count(self):
        graph = parse_manifest(_MINIMAL_MANIFEST)
        assert len(graph.nodes) == 3

    def test_parses_node_ids(self):
        graph = parse_manifest(_MINIMAL_MANIFEST)
        ids = [n.node_id for n in graph.nodes]
        assert "SPIKE-001" in ids
        assert "STORY-001" in ids
        assert "AC-001a" in ids

    def test_parses_node_names(self):
        graph = parse_manifest(_MINIMAL_MANIFEST)
        nm = graph.node_map()
        assert nm["STORY-001"].name == "Add login form validation"

    def test_parses_node_type(self):
        graph = parse_manifest(_MINIMAL_MANIFEST)
        nm = graph.node_map()
        assert nm["SPIKE-001"].node_type == "spike"
        assert nm["STORY-001"].node_type == "story"
        assert nm["AC-001a"].node_type == "ac"

    def test_parses_spec(self):
        graph = parse_manifest(_MINIMAL_MANIFEST)
        nm = graph.node_map()
        assert nm["STORY-001"].spec == "FEATURE-Authentication.md"
        assert nm["SPIKE-001"].spec is None

    def test_parses_parent(self):
        graph = parse_manifest(_MINIMAL_MANIFEST)
        nm = graph.node_map()
        assert nm["STORY-001"].parent == ["FEATURE-001"]

    def test_parses_depends_on(self):
        graph = parse_manifest(_MINIMAL_MANIFEST)
        nm = graph.node_map()
        assert nm["STORY-001"].depends_on == ["SPIKE-001"]
        assert nm["SPIKE-001"].depends_on == ["ROOT"]

    def test_parses_state(self):
        graph = parse_manifest(_MINIMAL_MANIFEST)
        nm = graph.node_map()
        assert nm["STORY-001"].state == "not-started"

    def test_parses_body_text(self):
        graph = parse_manifest(_MINIMAL_MANIFEST)
        nm = graph.node_map()
        assert "Validate email format" in nm["STORY-001"].body

    def test_empty_text_returns_empty_graph(self):
        graph = parse_manifest("")
        assert graph.nodes == []

    def test_feature_node_no_spec(self):
        graph = parse_manifest(_FEATURE_NODE)
        nm = graph.node_map()
        assert nm["FEATURE-001"].spec is None
        assert nm["FEATURE-001"].node_type == "feature"

    def test_multi_value_depends_on(self):
        text = "## STORY-010: Depends on multiple\n- type: story\n- depends-on: SPIKE-001, STORY-001\n- state: not-started\n"
        graph = parse_manifest(text)
        node = graph.nodes[0]
        assert node.depends_on == ["SPIKE-001", "STORY-001"]

    def test_multi_value_parent(self):
        text = "## STORY-010: Multi-parent\n- type: story\n- parent: FEATURE-001, FEATURE-002\n- state: not-started\n"
        graph = parse_manifest(text)
        node = graph.nodes[0]
        assert node.parent == ["FEATURE-001", "FEATURE-002"]


# ---------------------------------------------------------------------------
# ManifestGraph helpers
# ---------------------------------------------------------------------------


class TestManifestGraph:
    def test_stories_returns_only_stories(self):
        graph = parse_manifest(_MINIMAL_MANIFEST)
        stories = graph.stories()
        assert all(n.node_type == "story" for n in stories)
        assert len(stories) == 1

    def test_story_count(self):
        graph = parse_manifest(_MINIMAL_MANIFEST)
        assert graph.story_count() == 1

    def test_over_cap_false_when_under(self):
        graph = parse_manifest(_MINIMAL_MANIFEST)
        assert not graph.over_cap(cap=100)

    def test_over_cap_true_when_over(self):
        graph = parse_manifest(_MINIMAL_MANIFEST)
        assert graph.over_cap(cap=0)

    def test_frontier_returns_nodes_with_no_unmet_deps(self):
        graph = parse_manifest(_MINIMAL_MANIFEST)
        front = graph.frontier()
        ids = [n.node_id for n in front]
        assert "SPIKE-001" in ids
        assert "STORY-001" not in ids

    def test_frontier_after_spike_done(self):
        graph = parse_manifest(_MINIMAL_MANIFEST)
        graph.node_map()["SPIKE-001"].state = "done"
        front = graph.frontier()
        ids = [n.node_id for n in front]
        assert "STORY-001" in ids
        assert "SPIKE-001" not in ids

    def test_validate_ids_clean_graph(self):
        graph = parse_manifest(_MINIMAL_MANIFEST)
        errors = graph.validate_ids()
        assert errors == []

    def test_validate_ids_catches_unknown_dep(self):
        text = "## STORY-001: Bad dep\n- type: story\n- depends-on: NONEXISTENT\n- state: not-started\n"
        graph = parse_manifest(text)
        errors = graph.validate_ids()
        assert any("NONEXISTENT" in e for e in errors)

    def test_node_map_keyed_by_id(self):
        graph = parse_manifest(_MINIMAL_MANIFEST)
        nm = graph.node_map()
        assert set(nm.keys()) == {"SPIKE-001", "STORY-001", "AC-001a"}


# ---------------------------------------------------------------------------
# render_node / render_manifest
# ---------------------------------------------------------------------------


class TestRenderNode:
    def test_header_format(self):
        node = ManifestNode(node_id="STORY-001", name="Do the thing", node_type="story")
        text = render_node(node)
        assert text.startswith("## STORY-001: Do the thing")

    def test_type_field_present(self):
        node = ManifestNode(node_id="SPIKE-001", name="A spike", node_type="spike")
        assert "- type: spike" in render_node(node)

    def test_spec_field_emitted(self):
        node = ManifestNode(node_id="STORY-001", name="Thing", node_type="story", spec="FEATURE-A.md")
        assert "- spec: FEATURE-A.md" in render_node(node)

    def test_spec_field_omitted_when_none(self):
        node = ManifestNode(node_id="SPIKE-001", name="Spike", node_type="spike")
        assert "spec:" not in render_node(node)

    def test_parent_emitted(self):
        node = ManifestNode(node_id="STORY-001", name="S", node_type="story", parent=["FEATURE-001"])
        assert "- parent: FEATURE-001" in render_node(node)

    def test_depends_on_multi_value(self):
        node = ManifestNode(node_id="STORY-001", name="S", node_type="story", depends_on=["SPIKE-001", "STORY-002"])
        assert "- depends-on: SPIKE-001, STORY-002" in render_node(node)

    def test_state_field_present(self):
        node = ManifestNode(node_id="STORY-001", name="S", node_type="story", state="in-progress")
        assert "- state: in-progress" in render_node(node)

    def test_body_emitted(self):
        node = ManifestNode(node_id="STORY-001", name="S", node_type="story", body="Build the thing.")
        assert "Build the thing." in render_node(node)


class TestRenderManifest:
    def test_round_trip(self):
        graph = parse_manifest(_MINIMAL_MANIFEST)
        rendered = render_manifest(graph)
        graph2 = parse_manifest(rendered)
        nm1 = graph.node_map()
        nm2 = graph2.node_map()
        assert set(nm1.keys()) == set(nm2.keys())
        for node_id in nm1:
            assert nm1[node_id].node_type == nm2[node_id].node_type
            assert nm1[node_id].state == nm2[node_id].state
            assert nm1[node_id].depends_on == nm2[node_id].depends_on

    def test_empty_graph_returns_empty(self):
        assert render_manifest(ManifestGraph()) == ""

    def test_nodes_separated_by_blank_lines(self):
        node1 = ManifestNode(node_id="STORY-001", name="First", node_type="story")
        node2 = ManifestNode(node_id="STORY-002", name="Second", node_type="story")
        graph = ManifestGraph(nodes=[node1, node2])
        rendered = render_manifest(graph)
        assert "\n\n" in rendered

"""MANIFEST.md work graph — node model, parser, writer, and frontier computation.

MANIFEST.md uses a headers-on-file format. Each node is a markdown H2 header
followed by ``- key: value`` field lines and an optional body paragraph:

    ## STORY-042: Add login form validation
    - type: story
    - spec: FEATURE-Authentication.md
    - parent: FEATURE-Auth
    - depends-on: SPIKE-001, STORY-039
    - state: not-started

    Validate email format and password length on the login form.

Node types: ``feature`` | ``story`` | ``spike`` | ``ac`` | ``root``
State values: ``not-started`` | ``in-progress`` | ``done`` | ``blocked``
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

STORY_CAP = 100

_VALID_TYPES = frozenset({"feature", "story", "spike", "ac", "root"})
_VALID_STATES = frozenset({"not-started", "in-progress", "done", "blocked"})

_HEADER_RE = re.compile(r"^## ([^\s:]+):\s+(.+)$", re.MULTILINE)
_FIELD_LINE_RE = re.compile(r"^- ([a-z][a-z0-9-]*):\s*(.*)$")


@dataclass
class ManifestNode:
    node_id: str
    name: str
    node_type: str = ""
    spec: str | None = None
    parent: list[str] = field(default_factory=list)
    depends_on: list[str] = field(default_factory=list)
    state: str = "not-started"
    body: str = ""

    def is_story(self) -> bool:
        return self.node_type == "story"

    def is_done(self) -> bool:
        return self.state == "done"

    def is_active(self) -> bool:
        return self.state in ("not-started",)


@dataclass
class ManifestGraph:
    nodes: list[ManifestNode] = field(default_factory=list)

    def node_map(self) -> dict[str, ManifestNode]:
        return {n.node_id: n for n in self.nodes}

    def stories(self) -> list[ManifestNode]:
        return [n for n in self.nodes if n.is_story()]

    def story_count(self) -> int:
        return len(self.stories())

    def over_cap(self, cap: int = STORY_CAP) -> bool:
        return self.story_count() > cap

    def frontier(self) -> list[ManifestNode]:
        """Return nodes whose ``depends-on`` are all ``done`` (or ROOT)."""
        done_ids = {n.node_id for n in self.nodes if n.is_done()}
        result = []
        for node in self.nodes:
            if not node.is_active():
                continue
            unmet = [
                dep
                for dep in node.depends_on
                if dep != "ROOT" and dep not in done_ids
            ]
            if not unmet:
                result.append(node)
        return result

    def validate_ids(self) -> list[str]:
        """Return error messages for unknown ``depends-on`` ids."""
        all_ids = {n.node_id for n in self.nodes} | {"ROOT"}
        errors = []
        for node in self.nodes:
            for dep in node.depends_on:
                if dep not in all_ids:
                    errors.append(f"{node.node_id}: unknown depends-on id {dep!r}")
        return errors


def _split_multi(value: str) -> list[str]:
    """Split a comma-separated field value into a stripped list."""
    return [v.strip() for v in value.split(",") if v.strip()]


def _parse_node(node_id: str, name: str, body_lines: list[str]) -> ManifestNode:
    """Parse field lines and body from a node section."""
    node = ManifestNode(node_id=node_id, name=name)
    field_end = 0
    for i, line in enumerate(body_lines):
        m = _FIELD_LINE_RE.match(line)
        if not m:
            field_end = i
            break
        key, value = m.group(1), m.group(2).strip()
        if key == "type":
            node.node_type = value
        elif key == "spec":
            node.spec = value or None
        elif key == "parent":
            node.parent = _split_multi(value)
        elif key == "depends-on":
            node.depends_on = _split_multi(value)
        elif key == "state":
            node.state = value
        field_end = i + 1
    else:
        field_end = len(body_lines)

    # Collect body text after the field lines
    body_text = "\n".join(body_lines[field_end:]).strip()
    node.body = body_text
    return node


def parse_manifest(text: str) -> ManifestGraph:
    """Parse MANIFEST.md text and return a ManifestGraph."""
    graph = ManifestGraph()
    positions = [(m.start(), m.group(1), m.group(2)) for m in _HEADER_RE.finditer(text)]
    for i, (start, node_id, name) in enumerate(positions):
        section_end = positions[i + 1][0] if i + 1 < len(positions) else len(text)
        section_text = text[start:section_end]
        # Strip the header line itself
        body_text = section_text[section_text.index("\n") + 1:].lstrip("\n")
        body_lines = body_text.splitlines()
        node = _parse_node(node_id, name.strip(), body_lines)
        graph.nodes.append(node)
    return graph


def render_node(node: ManifestNode) -> str:
    """Render a ManifestNode to MANIFEST.md format."""
    lines = [f"## {node.node_id}: {node.name}"]
    lines.append(f"- type: {node.node_type}")
    if node.spec:
        lines.append(f"- spec: {node.spec}")
    if node.parent:
        lines.append(f"- parent: {', '.join(node.parent)}")
    if node.depends_on:
        lines.append(f"- depends-on: {', '.join(node.depends_on)}")
    lines.append(f"- state: {node.state}")
    if node.body:
        lines.append("")
        lines.append(node.body)
    return "\n".join(lines)


def render_manifest(graph: ManifestGraph) -> str:
    """Render a ManifestGraph to MANIFEST.md text."""
    if not graph.nodes:
        return ""
    return "\n\n".join(render_node(n) for n in graph.nodes) + "\n"

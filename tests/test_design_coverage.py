"""Every top-level ``drydock`` command has a design file listed in the AGENTS.md manifest."""

from __future__ import annotations

import argparse
from pathlib import Path

import pytest

from drydock.cli import _build_parser

ROOT = Path(__file__).resolve().parent.parent
DESIGN = ROOT / "design"
SECTIONS = (
    "## Behavior",
    "### Rules",
    "## Decisions",
    "## Open Questions",
    "## Open Actions",
    "## Working Notes",
)


def _commands() -> list[str]:
    parser = _build_parser()
    sub = next(a for a in parser._actions if isinstance(a, argparse._SubParsersAction))
    return sorted(sub.choices)


def _manifest() -> str:
    agents = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
    return agents[agents.index("### Design Manifest") :]


@pytest.mark.parametrize("command", _commands())
def test_command_has_design_file(command: str) -> None:
    path = DESIGN / "commands" / f"{command}.md"
    assert path.is_file(), f"missing design file: design/commands/{command}.md"
    assert f"`design/commands/{command}.md`" in _manifest()


@pytest.mark.parametrize("path", sorted(DESIGN.glob("*/*.md")), ids=lambda p: p.name)
def test_design_file_layout(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    positions = [text.find(heading) for heading in SECTIONS]
    assert -1 not in positions, f"{path.name} lacks a required section"
    assert positions == sorted(positions), f"{path.name} sections are out of order"
    assert f"`design/{path.parent.name}/{path.name}`" in _manifest()

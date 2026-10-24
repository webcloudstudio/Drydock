"""Every top-level ``drydock`` command has a Memory File, and every Memory File is indexed and formatted."""

from __future__ import annotations

import argparse
import re
from pathlib import Path

import pytest

from drydock.cli import _build_parser

ROOT = Path(__file__).resolve().parent.parent
DESIGN = ROOT / "design"
SECTIONS = (
    "## Intent",
    "## Guardrails",
    "## Details",
    "## Decisions",
    "## Questions",
    "## Actions",
    "## Working Notes",
)


def _heading(text: str, heading: str) -> int:
    match = re.search(rf"^{re.escape(heading)}$", text, re.M)
    return match.start() if match else -1


def _commands() -> list[str]:
    parser = _build_parser()
    sub = next(a for a in parser._actions if isinstance(a, argparse._SubParsersAction))
    return sorted(sub.choices)


def _manifest() -> str:
    agents = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
    return agents[agents.index("### Memory File Index") :]


@pytest.mark.parametrize("command", _commands())
def test_command_has_design_file(command: str) -> None:
    path = DESIGN / "commands" / f"{command}.md"
    assert path.is_file(), f"missing Memory File: design/commands/{command}.md"
    assert f"`design/commands/{command}.md`" in _manifest()


@pytest.mark.parametrize("path", sorted(DESIGN.glob("*/*.md")), ids=lambda p: p.name)
def test_design_file_layout(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    assert text.startswith("# MEMORY: "), f"{path.name} lacks a # MEMORY: title"
    positions = [_heading(text, heading) for heading in SECTIONS]
    assert -1 not in positions, f"{path.name} lacks a required section"
    assert positions == sorted(positions), f"{path.name} sections are out of order"
    assert f"`design/{path.parent.name}/{path.name}`" in _manifest()

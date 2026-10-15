"""Every top-level ``drydock`` command has a design file indexed in ``design/README.md``."""

from __future__ import annotations

import argparse
from pathlib import Path

import pytest

from drydock.cli import _build_parser

DESIGN = Path(__file__).resolve().parent.parent / "design"


def _commands() -> list[str]:
    parser = _build_parser()
    sub = next(a for a in parser._actions if isinstance(a, argparse._SubParsersAction))
    return sorted(sub.choices)


@pytest.mark.parametrize("command", _commands())
def test_command_has_design_file(command: str) -> None:
    path = DESIGN / "commands" / f"{command}.md"
    assert path.is_file(), f"missing design file: design/commands/{command}.md"
    text = path.read_text(encoding="utf-8")
    for heading in ("## Behavior", "### Rules", "## Decisions", "## Open Questions"):
        assert heading in text, f"{path.name} lacks {heading}"
    assert f"(commands/{command}.md)" in (DESIGN / "README.md").read_text(encoding="utf-8")


def test_index_links_resolve() -> None:
    index = (DESIGN / "README.md").read_text(encoding="utf-8")
    for kind in ("commands", "topics"):
        for path in (DESIGN / kind).glob("*.md"):
            assert f"({kind}/{path.name})" in index, f"design/README.md omits {kind}/{path.name}"

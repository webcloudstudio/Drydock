"""REFIT ticket numbering, chaining, and Manifest story creation."""

from __future__ import annotations

from pathlib import Path

import pytest

from drydock.errors import SpecificationError
from drydock.manifest import DrydockManifest
from drydock.refit_ticket import add_ticket, parse_ticket_name, ticket_chain

_MANIFEST = """# MANIFEST: Demo
state: approved
blocks: 2

## story 1: Service
id: home-service
summary: Service
type: service
phase: 1
block: 1
implements: FEATURE-HOME.md
state: closed/verified

## story 2: Home screen
id: home-screen
summary: Home screen
type: feature
kind: capability
phase: 2
block: 2
implements: SCREEN-HOME.md
context: ARCHITECTURE_compact.md
stack: python.md
depends: home-service
state: closed/verified
"""


def _target(tmp_path: Path) -> Path:
    target = tmp_path / "Demo"
    blueprint = target / "blueprint"
    blueprint.mkdir(parents=True)
    (blueprint / "SCREEN-HOME.md").write_text("# Screen: Home\n", encoding="utf-8")
    (blueprint / "FEATURE-HOME.md").write_text("# Feature: Home\n", encoding="utf-8")
    (target / "MANIFEST.md").write_text(_MANIFEST, encoding="utf-8")
    return target


def test_first_ticket_depends_on_the_blueprint_stories_and_inherits_its_stack(tmp_path):
    target = _target(tmp_path)

    added = add_ticket(
        target, "SCREEN-HOME", "# Rename\n\n- The button reads Go.\n", today="2026-09-22"
    )

    assert added.path.name == "SCREEN-HOME_refit_001.md"
    assert added.depends == ("home-screen",)
    text = added.path.read_text(encoding="utf-8")
    assert text.startswith("# REFIT: SCREEN-HOME 001 — Rename\n")
    assert text.count("\n# ") == 0
    assert "| Blueprint | SCREEN-HOME.md |" in text
    assert "| Parent | SCREEN-HOME.md |" in text
    assert "- The button reads Go." in text
    node = DrydockManifest.load(target / "MANIFEST.md", compatibility=True).node(added.story_id)
    assert node.state == "pending"
    assert node.fields["implements"] == ("SCREEN-HOME_refit_001.md",)
    assert node.fields["context"] == ("ARCHITECTURE_compact.md", "SCREEN-HOME.md")
    assert node.fields["stack"] == ("python.md",)
    assert node.phase == 2
    assert node.block == 3
    assert "acceptance" not in node.fields


def test_ticket_with_ac_blocks_is_held_to_acceptance(tmp_path):
    target = _target(tmp_path)
    body = "# Rename\n\n=== AC x ===\nIntent: y\nassert True\n=== END AC x ===\n"

    added = add_ticket(target, "SCREEN-HOME", body)

    node = DrydockManifest.load(target / "MANIFEST.md", compatibility=True).node(added.story_id)
    assert node.has_acceptance_contract


def test_second_ticket_chains_on_the_first(tmp_path):
    target = _target(tmp_path)
    first = add_ticket(target, "SCREEN-HOME.md", "# One\n")

    second = add_ticket(target, "SCREEN-HOME.md", "# Two\n")

    assert second.path.name == "SCREEN-HOME_refit_002.md"
    assert second.depends == (first.story_id,)
    assert "| Parent | SCREEN-HOME_refit_001.md |" in second.path.read_text(encoding="utf-8")
    node = DrydockManifest.load(target / "MANIFEST.md", compatibility=True).node(second.story_id)
    assert node.fields["context"][-1] == "SCREEN-HOME_refit_001.md"
    assert [p.name for p in ticket_chain(target / "blueprint", "SCREEN-HOME")] == [
        "SCREEN-HOME_refit_001.md",
        "SCREEN-HOME_refit_002.md",
    ]


def test_chains_are_per_blueprint(tmp_path):
    target = _target(tmp_path)
    add_ticket(target, "SCREEN-HOME", "# One\n")

    other = add_ticket(target, "FEATURE-HOME", "# Other\n")

    assert other.path.name == "FEATURE-HOME_refit_001.md"
    assert other.depends == ("home-service",)


@pytest.mark.parametrize(
    ("blueprint", "message"),
    [
        ("SCREEN-MISSING", "Blueprint not found"),
        ("SCREEN-HOME_refit_001", "Not an authored Blueprint"),
        ("../SCREEN-HOME", "file name in blueprint/"),
    ],
)
def test_rejects_non_blueprints(tmp_path, blueprint, message):
    target = _target(tmp_path)
    with pytest.raises(SpecificationError, match=message):
        add_ticket(target, blueprint, "# X\n")


def test_rejects_empty_text_and_unowned_blueprint(tmp_path):
    target = _target(tmp_path)
    with pytest.raises(SpecificationError, match="empty"):
        add_ticket(target, "SCREEN-HOME", "  \n")
    (target / "blueprint" / "UI-GENERAL.md").write_text("# UI\n", encoding="utf-8")
    with pytest.raises(SpecificationError, match="No Manifest story implements UI-GENERAL.md"):
        add_ticket(target, "UI-GENERAL", "# X\n")
    assert not list((target / "blueprint").glob("*_refit_*.md"))


def test_parse_ticket_name():
    assert parse_ticket_name("SCREEN-A_refit_012.md") == ("SCREEN-A", 12)
    assert parse_ticket_name("SCREEN-A.md") is None

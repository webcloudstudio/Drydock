"""REFIT ticket numbering, chaining, and Manifest story creation."""

from __future__ import annotations

from pathlib import Path

import pytest

from drydock.errors import SpecificationError
from drydock.manifest import DrydockManifest
from drydock.manifest_edit import optimize_build_blocks
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


def test_successive_tickets_group_by_inherited_context_without_moving_built_work(
    tmp_path, isolated_config
):
    target = _target(tmp_path)
    manifest_path = target / "MANIFEST.md"
    # No stack savings: the inherited rules and context alone must justify this grouping.
    manifest_path.write_text(
        _MANIFEST.replace("stack: python.md", "rules: local-rules.md"), encoding="utf-8"
    )
    (target / "blueprint" / "ARCHITECTURE_compact.md").write_text("context " * 800)
    (target / "local-rules.md").write_text("rule " * 800)
    before = DrydockManifest.load(manifest_path, compatibility=True)
    original_nodes = {node.block_id: list(node.lines) for node in before.blocks}

    tickets = [add_ticket(target, "SCREEN-HOME", f"# Change {number}\n") for number in range(3)]

    plan = DrydockManifest.load(manifest_path, compatibility=True)
    nodes = [plan.node(ticket.story_id) for ticket in tickets]
    assert [node.block for node in nodes] == [3, 3, 3]
    assert [node.depends for node in nodes] == [
        ("home-screen",),
        (tickets[0].story_id,),
        (tickets[1].story_id,),
    ]
    assert all(node.fields["rules"] == ("local-rules.md",) for node in nodes)
    assert all("ARCHITECTURE_compact.md" in node.fields["context"] for node in nodes)
    for node_id, lines in original_nodes.items():
        assert plan.node(node_id).lines == lines
    # Another pass sees the same inputs and leaves the file byte-for-byte unchanged.
    assert optimize_build_blocks(manifest_path, pending_only=True) is False


def test_new_ticket_does_not_join_a_partially_built_block(tmp_path, isolated_config):
    target = _target(tmp_path)
    (target / "blueprint" / "ARCHITECTURE_compact.md").write_text("context " * 800)
    first = add_ticket(target, "SCREEN-HOME", "# First\n")
    second = add_ticket(target, "SCREEN-HOME", "# Second\n")
    path = target / "MANIFEST.md"
    plan = DrydockManifest.load(path, compatibility=True)
    assert plan.node(first.story_id).block == plan.node(second.story_id).block
    plan.set_fields(first.story_id, state="closed/implemented")
    plan.save()
    before = DrydockManifest.load(path, compatibility=True)
    original = {node.block_id: list(node.lines) for node in before.blocks}

    third = add_ticket(target, "SCREEN-HOME", "# Third\n")

    after = DrydockManifest.load(path, compatibility=True)
    assert after.node(third.story_id).block > after.node(second.story_id).block
    for node_id, lines in original.items():
        assert after.node(node_id).lines == lines


def test_optimizer_failure_restores_manifest_and_ticket_number(tmp_path, monkeypatch):
    target = _target(tmp_path)
    path = target / "MANIFEST.md"
    original = path.read_bytes()

    def fail(*args, **kwargs):
        raise SpecificationError("Cannot optimize build blocks: test limit")

    with monkeypatch.context() as patch:
        patch.setattr("drydock.manifest_edit.optimize_build_blocks", fail)
        with pytest.raises(SpecificationError, match="test limit"):
            add_ticket(target, "SCREEN-HOME", "# First\n")
    assert path.read_bytes() == original
    assert ticket_chain(target / "blueprint", "SCREEN-HOME") == []
    assert add_ticket(target, "SCREEN-HOME", "# First\n").path.name.endswith("_001.md")


def test_plain_refit_regroups_existing_unbuilt_tickets(tmp_path, isolated_config):
    from drydock.refit import refit_target

    target = _target(tmp_path)
    (target / "blueprint" / "ARCHITECTURE_compact.md").write_text("context " * 800)
    first = add_ticket(target, "SCREEN-HOME", "# First\n")
    second = add_ticket(target, "SCREEN-HOME", "# Second\n")
    path = target / "MANIFEST.md"
    plan = DrydockManifest.load(path, compatibility=True)
    plan.set_fields(second.story_id, block="4")
    plan.set_metadata(blocks="4")
    plan.save()

    def no_agent(*args, **kwargs):
        pytest.fail("Regrouping existing tickets must not invoke an agent")

    result = refit_target(target, runner=no_agent)

    assert result.exit_code() == 0
    after = DrydockManifest.load(path, compatibility=True)
    assert after.node(first.story_id).block == after.node(second.story_id).block == 3


def test_plain_refit_restores_manifest_on_optimization_failure(
    tmp_path, isolated_config, monkeypatch
):
    from drydock.refit import refit_target

    target = _target(tmp_path)
    path = target / "MANIFEST.md"
    original = path.read_bytes()

    def fail(*args, **kwargs):
        path.write_text("partial optimization\n")
        raise SpecificationError("Cannot optimize build blocks: test limit")

    monkeypatch.setattr("drydock.manifest_edit.optimize_build_blocks", fail)
    with pytest.raises(SpecificationError, match="test limit"):
        refit_target(target, runner=lambda *a, **k: pytest.fail("Unexpected agent invocation"))
    assert path.read_bytes() == original
    assert "test limit" in (target / "BLOCKERS.md").read_text()

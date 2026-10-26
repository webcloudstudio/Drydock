"""Stabilization S3/F12: imported source briefs reach the consumed build prompt with provenance."""

from __future__ import annotations

from hashlib import sha256

import pytest

from drydock.build import StepRoots, assemble_step
from drydock.build_plan import parse_build_plan
from drydock.build_run import build_target
from tests.test_build_run import _setup, make_runner

_MANIFEST = """# MANIFEST: Demo
state: approved

## story 1: Foundation
id: foundation
implements: DATABASE.md
context: {context}
instructions: |
  Build the database.
state: pending
"""


def _target(tmp_path, context: str):
    target_dir, build_dir = _setup(tmp_path, manifest=_MANIFEST.format(context=context))
    sources = target_dir / "blueprint" / "sources"
    sources.mkdir()
    (sources / "INSTRUCTIONS.md").write_text("SOURCE BRIEF: block before inline\n", "utf-8")
    return target_dir, build_dir


def _context_file(target_dir, name="INSTRUCTIONS.md"):
    plan = parse_build_plan(target_dir / "MANIFEST.md")
    roots = StepRoots(
        target_dir=target_dir,
        blueprint_dir=target_dir / "blueprint",
        stack_dir=target_dir,
        rigging_dir=target_dir,
    )
    step = assemble_step(plan.by_id()["foundation"], roots)
    return next(f for f in step.files if f.role == "context" and name in f.name)


@pytest.mark.parametrize("context", ["INSTRUCTIONS.md", "sources/INSTRUCTIONS.md"])
def test_bare_and_explicit_source_names_resolve_to_the_import(tmp_path, context):
    target_dir, _ = _target(tmp_path, context)
    found = _context_file(target_dir)
    assert not found.missing
    assert found.source == target_dir / "blueprint" / "sources" / "INSTRUCTIONS.md"


def test_an_authored_blueprint_file_wins_a_name_collision(tmp_path):
    target_dir, _ = _target(tmp_path, "INSTRUCTIONS.md")
    authored = target_dir / "blueprint" / "INSTRUCTIONS.md"
    authored.write_text("AUTHORED\n", encoding="utf-8")
    assert _context_file(target_dir).source == authored


def test_an_absent_source_is_still_reported_missing(tmp_path):
    target_dir, _ = _target(tmp_path, "ABSENT.md")
    assert _context_file(target_dir, "ABSENT.md").missing


def test_source_brief_reaches_the_build_prompt_and_stays_unchanged(tmp_path):
    """FxRates 20261026.011843: INSTRUCTIONS.md was reported missing context."""
    target_dir, build_dir = _target(tmp_path, "INSTRUCTIONS.md")
    source = target_dir / "blueprint" / "sources" / "INSTRUCTIONS.md"
    before = sha256(source.read_bytes()).hexdigest()
    runner = make_runner()

    build_target("Demo", target_dir, build_dir=build_dir, runner=runner)

    prompt = runner.calls[0]["prompt"]
    assert "SOURCE BRIEF: block before inline" in prompt
    assert f'filename="INSTRUCTIONS.md" role="context" path="{source}"' in prompt
    assert "Missing context" not in prompt
    assert sha256(source.read_bytes()).hexdigest() == before

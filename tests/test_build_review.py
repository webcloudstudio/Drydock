"""Tests for build review gate transitions."""

from __future__ import annotations

import pytest

from drydock.build_plan import parse_build_plan
from drydock.build_review import verify_build_step
from drydock.errors import SpecificationError

_MANIFEST = """# MANIFEST: Demo
state: approved

## story 1: Foundation
id: foundation
state: implemented

## ac 1: Starts
id: ac-starts
parent: foundation
state: pending

## ac 2: Persists
id: ac-persists
parent: foundation
state: pending

## story 2: Service
id: service
depends: foundation
state: pending
"""


def _write(tmp_path, text: str = _MANIFEST):
    path = tmp_path / "MANIFEST.md"
    path.write_text(text, encoding="utf-8")
    return path


def _state(path, block_id):
    return parse_build_plan(path).by_id()[block_id].state


def test_verify_build_step_closes_step_and_child_acs(tmp_path):
    path = _write(tmp_path)

    result = verify_build_step(path, "foundation")

    assert result.step_id == "foundation"
    assert result.ac_ids == ("ac-starts", "ac-persists")
    assert _state(path, "foundation") == "closed/verified"
    assert _state(path, "ac-starts") == "closed/verified"
    assert _state(path, "ac-persists") == "closed/verified"
    assert parse_build_plan(path).buildable_steps()[0].block_id == "service"


def test_verify_build_step_requires_implemented_state(tmp_path):
    path = _write(tmp_path, _MANIFEST.replace("state: implemented", "state: pending", 1))

    with pytest.raises(SpecificationError, match="only implemented"):
        verify_build_step(path, "foundation")


def test_verify_build_step_rejects_acceptance_block(tmp_path):
    path = _write(tmp_path)

    with pytest.raises(SpecificationError, match="not a build step"):
        verify_build_step(path, "ac-starts")

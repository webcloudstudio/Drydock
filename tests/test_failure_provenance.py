"""Grouped execution failures retain the criterion owner's provenance."""

from dataclasses import replace

from drydock.acceptance import AcceptanceRunResult
from drydock.build_run import BuildStepResult
from drydock.cli import _failure_representatives, _render_build_failures


def test_group_failure_reports_later_owner_and_keeps_unowned_process_failures():
    check = AcceptanceRunResult("convert", "FEATURE-Convert.md", "Convert", False, 1, "", "")
    first = BuildStepResult(
        "initialize",
        "Initialize",
        "story",
        "failed",
        "closed/failed",
        1,
        container_block_id="service",
        container_name="Service",
        execution_id="exec-1",
        acceptance=(check,),
        error="programmatic acceptance failed: convert",
    )
    owner = replace(first, block_id="convert", name="Convert", owned_acceptance=(check,))
    selected = _failure_representatives([first, owner])
    assert selected == [owner]
    banner = _render_build_failures("Demo", selected, hint="Inspect")
    assert "Story: Convert [convert]" in banner
    assert "Story: Initialize" not in banner
    assert _failure_representatives([first, replace(owner, owned_acceptance=())]) == [first]
    independent = replace(first, block_id="other", execution_id="exec-2")
    assert _failure_representatives([first, owner, independent]) == [owner, independent]

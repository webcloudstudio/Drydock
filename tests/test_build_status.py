"""Tests for the build-status report (drydock.build_status)."""

from __future__ import annotations

from drydock.build_plan import parse_build_plan
from drydock.build_status import build_status

_PLAN = """# MANIFEST: Demo
state: draft

## feature 1: Core
id: core

## story 2: Foundation
id: foundation
parent: core
state: closed/verified

## story 3: Service
id: service
parent: core
depends: foundation
state: pending

## ac 4: Service responds
id: ac-svc
parent: service
state: pending

## feature 5: Extras
id: extras

## story 6: Reports
id: reports
parent: extras
depends: service
state: pending

## spike 7: Loose end
id: loose
state: pending
"""


def _report(tmp_path, manifest=_PLAN):
    path = tmp_path / "MANIFEST.md"
    path.write_text(manifest, encoding="utf-8")
    return build_status(parse_build_plan(path))


def test_groups_steps_under_their_feature_in_order(tmp_path):
    report = _report(tmp_path)
    names = [g.name for g in report.groups]
    assert names == ["Core", "Extras", "Ungrouped"]
    core = report.groups[0]
    assert [s.block.block_id for s in core.steps] == ["foundation", "service"]


def test_acs_fold_under_their_parent_step(tmp_path):
    report = _report(tmp_path)
    service = report.groups[0].steps[1]
    assert service.block.block_id == "service"
    assert [a.block_id for a in service.acs] == ["ac-svc"]


def test_ungrouped_holds_steps_without_a_feature_parent(tmp_path):
    report = _report(tmp_path)
    ungrouped = report.groups[-1]
    assert ungrouped.feature is None
    assert [s.block.block_id for s in ungrouped.steps] == ["loose"]


def test_buildable_marks_pending_steps_with_verified_depends(tmp_path):
    report = _report(tmp_path)
    # The Core block is buildable even though service depends on foundation
    # inside the same block. Later blocks are not marked buildable until earlier
    # pending work is complete or reordered ahead of them.
    assert report.buildable_ids == ("core",)
    service = report.groups[0].steps[1]
    assert service.buildable is True
    loose = report.groups[-1].steps[0]
    assert loose.buildable is False


def test_blocked_frontier_hides_later_independent_work(tmp_path):
    manifest = """# MANIFEST: Demo
state: draft

## feature 1: Core
id: core

## story 2: Service
id: service
parent: core
depends: missing-foundation
state: pending

## spike 3: Later
id: later
state: pending
"""
    report = _report(tmp_path, manifest=manifest)

    assert report.buildable_ids == ()
    assert [step.buildable for group in report.groups for step in group.steps] == [False, False]


def test_self_dependent_group_is_buildable_as_one_block(tmp_path):
    manifest = """# MANIFEST: Demo
state: draft

## feature 1: Core
id: core

## story 2: Foundation
id: foundation
parent: core
state: pending

## story 3: Service
id: service
parent: core
depends: foundation
state: pending
"""
    report = _report(tmp_path, manifest=manifest)

    assert report.buildable_ids == ("core",)
    assert [step.buildable for step in report.groups[0].steps] == [True, True]


def test_rollup_counts_and_percent(tmp_path):
    report = _report(tmp_path)
    assert report.steps_total == 4
    assert report.steps_verified == 1
    assert report.steps_pending == 3
    assert report.steps_failed == 0
    assert report.percent_complete() == 25


def test_feature_rollup_counts_verified_over_total(tmp_path):
    report = _report(tmp_path)
    core = report.groups[0]
    assert (core.verified, core.total) == (1, 2)


def test_empty_plan_has_no_groups_and_zero_percent(tmp_path):
    report = _report(tmp_path, manifest="# MANIFEST: Empty\nstate: draft\n")
    assert report.groups == ()
    assert report.percent_complete() == 0

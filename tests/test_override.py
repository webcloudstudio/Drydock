"""Tests for the --override waiver record, summary, and Target stamp."""

from __future__ import annotations

from drydock.override import (
    ACCEPTANCE_AUTHORIZATION,
    PLAN_DECISION,
    WaivedGate,
    format_override_summary,
    stamp_override,
)

_METADATA = """# AUTHORITATIVE PROJECT METADATA — FIELDS SHOULD BE CURRENT

name: Demo
version: 0.01
build_state: planned
"""


def test_no_waivers_renders_no_summary():
    assert format_override_summary(()) == ""


def test_summary_counts_and_names_every_bypassed_gate():
    text = format_override_summary([
        WaivedGate(kind=PLAN_DECISION, subject="discovery-stack.json: Which framework?"),
        WaivedGate(
            kind=ACCEPTANCE_AUTHORIZATION,
            subject="DATABASE.md#health",
            detail="python-package=flask",
        ),
    ])

    assert "2 gates bypassed" in text
    assert "discovery-stack.json: Which framework?" in text
    assert "python-package=flask" in text
    assert "not governed" in text


def test_a_single_waiver_is_reported_in_the_singular():
    text = format_override_summary([WaivedGate(kind=PLAN_DECISION, subject="one")])

    assert "1 gate bypassed" in text


def test_stamp_marks_the_target_as_ungoverned(tmp_path):
    (tmp_path / "METADATA.md").write_text(_METADATA, encoding="utf-8")

    stamp_override(tmp_path, [WaivedGate(kind=PLAN_DECISION, subject="one")])

    text = (tmp_path / "METADATA.md").read_text(encoding="utf-8")
    assert "override: true" in text
    assert "override_waivers: 1" in text


def test_a_clean_run_leaves_no_stamp(tmp_path):
    (tmp_path / "METADATA.md").write_text(_METADATA, encoding="utf-8")

    stamp_override(tmp_path, [])

    assert "override:" not in (tmp_path / "METADATA.md").read_text(encoding="utf-8")

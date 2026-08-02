"""Tests for ``drydock.decisions`` — the DECISIONS.json parse/persist/reconcile contract."""

from __future__ import annotations

import json
from dataclasses import replace

from drydock.decisions import (
    Decision,
    DecisionOption,
    load_decisions,
    parse_plan_decisions,
    reconcile_decisions,
    validate_decision_blueprints,
    write_decisions,
)

_CHOICE_ITEM = {
    "id": "Q-001",
    "type": "choice",
    "severity": "material",
    "blueprint": "ARCHITECTURE.md",
    "story": None,
    "title": "Pick a queue backend",
    "description": "The Blueprint is silent on which queue technology to use.",
    "options": [{"value": "sqs", "label": "AWS SQS"}, {"value": "redis", "label": "Redis"}],
    "system_choice": "sqs",
}

_TEXT_ITEM = {
    "id": "Q-002",
    "type": "text",
    "severity": "low",
    "blueprint": "FEATURE-Status.md",
    "story": "story-status",
    "title": "Naming convention",
    "description": "No naming convention was specified for the status endpoint.",
    "options": [],
    "system_choice": "Use kebab-case route names.",
}


def test_parse_plan_decisions_accepts_choice_and_text_items():
    text = json.dumps([_CHOICE_ITEM, _TEXT_ITEM])
    decisions = parse_plan_decisions(text)
    assert len(decisions) == 2
    choice, text_item = decisions
    assert choice.id == "Q-001"
    assert choice.origin == "plan"
    assert choice.status == "recommended"
    assert choice.archived is False
    assert choice.options == (DecisionOption("sqs", "AWS SQS"), DecisionOption("redis", "Redis"))
    assert text_item.story == "story-status"
    assert text_item.options == ()


def test_parse_plan_decisions_returns_empty_for_malformed_json():
    assert parse_plan_decisions("not json") == ()
    assert parse_plan_decisions('{"not": "a list"}') == ()


def test_parse_plan_decisions_drops_invalid_items_without_failing():
    invalid_severity = {**_CHOICE_ITEM, "id": "Q-003", "severity": "urgent"}
    missing_title = {**_TEXT_ITEM, "id": "Q-004", "title": ""}
    choice_without_options = {**_CHOICE_ITEM, "id": "Q-005", "options": []}
    text = json.dumps([_CHOICE_ITEM, invalid_severity, missing_title, choice_without_options])
    decisions = parse_plan_decisions(text)
    assert [d.id for d in decisions] == ["Q-001"]


def test_parse_plan_decisions_drops_duplicate_ids():
    text = json.dumps([_CHOICE_ITEM, {**_CHOICE_ITEM}])
    decisions = parse_plan_decisions(text)
    assert len(decisions) == 1


def test_parse_plan_decisions_emits_empty_tuple_for_empty_list():
    assert parse_plan_decisions("[]") == ()


def test_validate_decision_blueprints_drops_unemitted_attachment():
    decisions = parse_plan_decisions(json.dumps([_CHOICE_ITEM, _TEXT_ITEM]))
    kept, warnings = validate_decision_blueprints(decisions, frozenset())
    assert [d.id for d in kept] == ["Q-001"]
    assert len(warnings) == 1
    assert "Q-002" in warnings[0]
    assert "FEATURE-Status.md" in warnings[0]


def test_validate_decision_blueprints_keeps_architecture_bucket():
    decisions = parse_plan_decisions(json.dumps([_CHOICE_ITEM]))
    kept, warnings = validate_decision_blueprints(decisions, frozenset())
    assert len(kept) == 1
    assert warnings == ()


def test_write_and_load_decisions_roundtrip(tmp_path):
    decisions = parse_plan_decisions(json.dumps([_CHOICE_ITEM, _TEXT_ITEM]))
    path = tmp_path / "DECISIONS.json"
    write_decisions(path, decisions)
    loaded = load_decisions(path)
    assert loaded == decisions


def test_load_decisions_tolerates_missing_or_malformed_file(tmp_path):
    assert load_decisions(tmp_path / "missing.json") == ()
    bad = tmp_path / "bad.json"
    bad.write_text("not json", encoding="utf-8")
    assert load_decisions(bad) == ()


def test_is_human_authored_requires_commander_touch():
    fresh = parse_plan_decisions(json.dumps([_CHOICE_ITEM]))[0]
    assert fresh.is_human_authored is False
    directed = replace(fresh, commander_direction="redis")
    assert directed.is_human_authored is True
    overridden = replace(fresh, override_text="use redis instead")
    assert overridden.is_human_authored is True


def test_reconcile_decisions_retains_only_human_authored_prior_items():
    fresh = parse_plan_decisions(json.dumps([_CHOICE_ITEM, _TEXT_ITEM]))
    prior_directed = Decision(
        id="Q-001",
        type="choice",
        severity="material",
        origin="plan",
        blueprint="ARCHITECTURE.md",
        story=None,
        status="answered",
        archived=False,
        title="Pick a queue backend",
        description="stale description",
        options=(DecisionOption("sqs", "AWS SQS"), DecisionOption("redis", "Redis")),
        system_choice="sqs",
        commander_direction="redis",
    )
    prior_untouched = Decision(
        id="Q-099",
        type="text",
        severity="low",
        origin="plan",
        blueprint="ARCHITECTURE.md",
        story=None,
        status="recommended",
        archived=False,
        title="Stale disclosure",
        description="No longer relevant.",
        options=(),
        system_choice="stale",
    )
    merged = reconcile_decisions(fresh, prior=(prior_directed, prior_untouched))
    ids = {d.id for d in merged}
    assert ids == {"Q-001", "Q-002"}
    kept_q001 = next(d for d in merged if d.id == "Q-001")
    # The retained Commander-directed item survives unchanged; a same-id fresh item never
    # overrides it.
    assert kept_q001.commander_direction == "redis"
    assert kept_q001.description == "stale description"


def test_reconcile_decisions_with_no_prior_returns_fresh_only():
    fresh = parse_plan_decisions(json.dumps([_CHOICE_ITEM]))
    assert reconcile_decisions(fresh, prior=()) == fresh

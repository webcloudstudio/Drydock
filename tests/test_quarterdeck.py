"""Focused tests for reusable QuarterDeck renderers."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import yaml


def _load_quarterdeck():
    path = Path(__file__).parents[1] / "QuarterDeck" / "app.py"
    spec = importlib.util.spec_from_file_location("quarterdeck_app_test", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _console_config():
    root = Path(__file__).parents[1]
    return yaml.safe_load((root / "QuarterDeck" / "console.yaml").read_text(encoding="utf-8"))


def test_jsonl_renderer_sorts_fields_and_isolates_invalid_lines(tmp_path, monkeypatch):
    quarterdeck = _load_quarterdeck()
    source = tmp_path / "events.jsonl"
    source.write_text(
        "\n".join(
            [
                json.dumps({"recorded_at": "2026-01-01T00:00:00Z", "title": "Older"}),
                "{broken",
                json.dumps({"recorded_at": "2026-02-01T00:00:00Z", "title": "Newer"}),
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(quarterdeck, "resolve_path", lambda _path: source)

    rendered = quarterdeck.render_jsonl_item(
        {
            "label": "Events",
            "path": "events.jsonl",
            "fields": ["recorded_at", "title"],
            "sort": "recorded_at",
            "sort_direction": "desc",
        }
    )

    assert rendered.index("Newer") < rendered.index("Older")
    assert "2 record(s)" in rendered
    assert "line 2" in rendered


def test_drydock_console_has_five_configured_sections():
    config = _console_config()
    section_ids = [s["id"] for s in config["sections"]]
    assert section_ids == ["core", "build_plan", "actions", "project_pages", "archive"]


def test_drydock_console_archive_section_is_collapsed():
    config = _console_config()
    archive = next(s for s in config["sections"] if s["id"] == "archive")
    assert archive.get("collapsed") is True


def test_drydock_console_core_has_master_blueprint():
    config = _console_config()
    items = {item["id"]: item for item in config["items"]}
    assert "master_blueprint" in items
    assert items["master_blueprint"]["section"] == "core"
    assert items["master_blueprint"]["label"] == "Master Blueprint"


def test_drydock_console_exposes_existing_owned_documents():
    root = Path(__file__).parents[1]
    config = _console_config()
    docs_items = {
        "soundings",
        "master_blueprint",
        "sea_trials",
        "rendered_docs",
        "sea_trials_poster",
        "sea_trials_pdf",
        "pypi_reservation",
        "pypi_reservation_pdf",
    }
    items = {item["id"]: item for item in config["items"]}

    assert docs_items <= items.keys()
    for item_id in docs_items:
        item = items[item_id]
        relative = item.get("path") or item.get("href")
        assert relative
        assert (root / "QuarterDeck" / relative).resolve().is_file(), item_id

    ships_log = items["ships_log"]
    assert ships_log["type"] == "jsonl"
    assert ships_log["path"] == "../logs/ships_log.jsonl"
    assert len(ships_log["fields"]) > 0
    assert ships_log.get("badge_field") == "event_type"


def test_drydock_console_pins_the_three_standard_artifacts_in_core():
    config = _console_config()
    items = {item["id"]: item for item in config["items"]}
    for standard in ("commanders_view", "soundings", "sea_trials"):
        assert items[standard]["section"] == "core", standard


# ── Command status (Core Docs only, read-only) ─────────────────────────────────


def _command_status_markdown(
    *,
    done_evidence: str = "`test_done`",
    stubbed_state: str = "STUBBED",
    done_summary: int = 1,
) -> str:
    return f"""# Soundings

## Command Acceptance

| Order | Command | Acceptance Criteria | State | Evidence / Notes |
|---:|---|---|---|---|
| 1 | `drydock done` | Works | DONE | {done_evidence} |
| 2 | `drydock later` | Deferred | {stubbed_state} | exits 2 |

## Summary

| Category | Count |
|---|---:|
| Total commands | 2 |
| DONE | {done_summary} |
| IMPLEMENTED | 0 |
| STUBBED | 1 |
| NOT STARTED | 0 |
"""


def _configure_command_status(quarterdeck, monkeypatch, sources):
    config_items = [
        {
            "id": item_id,
            "label": label,
            "section": section,
            "type": "markdown",
            "path": f"{item_id}.md",
        }
        for item_id, label, section, _text in sources
    ]
    monkeypatch.setattr(quarterdeck, "CONFIG", {"items": config_items})
    monkeypatch.setattr(quarterdeck, "CONFIG_ERROR", None)
    texts = {f"{item_id}.md": text for item_id, _label, _section, text in sources}

    class Source:
        def __init__(self, text):
            self.text = text

        def read_text(self, encoding="utf-8"):
            return self.text

    monkeypatch.setattr(quarterdeck, "resolve_path", lambda path: Source(texts[path]))


def test_command_status_derives_status_and_core_reference_coverage(monkeypatch):
    quarterdeck = _load_quarterdeck()
    _configure_command_status(
        quarterdeck,
        monkeypatch,
        [
            ("soundings", "Soundings", "core", _command_status_markdown()),
            ("spec", "Specification", "core", "Use `drydock done` and `drydock later`."),
            ("roadmap", "Roadmap", "plan", "Use `drydock ignored`."),
        ],
    )

    rendered = quarterdeck.render_command_status({"label": "Command Status"})

    assert "Derived from Core Doc: Soundings" in rendered
    assert "DONE (1)" in rendered
    assert "STUBBED (1)" in rendered
    assert "Specification" in rendered
    assert "Roadmap" not in rendered
    assert "no structured findings" in rendered


def test_command_status_reports_structured_findings(monkeypatch):
    quarterdeck = _load_quarterdeck()
    _configure_command_status(
        quarterdeck,
        monkeypatch,
        [
            (
                "soundings",
                "Soundings",
                "core",
                _command_status_markdown(done_evidence="", stubbed_state="UNKNOWN", done_summary=9),
            )
        ],
    )

    rendered = quarterdeck.render_command_status({"label": "Command Status"})

    assert "DONE row has no evidence" in rendered
    assert "Unknown state" in rendered
    assert "Summary mismatch for DONE" in rendered
    assert "Summary mismatch for STUBBED" in rendered


def test_command_status_requires_exactly_one_core_command_acceptance_table(monkeypatch):
    quarterdeck = _load_quarterdeck()
    _configure_command_status(
        quarterdeck,
        monkeypatch,
        [
            ("one", "One", "core", _command_status_markdown()),
            ("two", "Two", "core", _command_status_markdown()),
        ],
    )

    rendered = quarterdeck.render_command_status({"label": "Command Status"})

    assert "Expected exactly one Core Doc Command Acceptance table; found 2" in rendered


def test_drydock_command_status_renders_current_soundings():
    quarterdeck = _load_quarterdeck()

    rendered = quarterdeck.render_command_status({"label": "Command Status"})

    assert "Total commands</strong><br>28" in rendered
    assert "DONE (17)" in rendered
    assert "IMPLEMENTED (2)" in rendered
    assert "STUBBED (9)" in rendered
    assert "no structured findings" in rendered


def test_plan_decision_approves_authoritative_plan(tmp_path, monkeypatch):
    quarterdeck = _load_quarterdeck()
    plan_path = tmp_path / "BUILD_PLAN.md"
    plan_path.write_text(
        "# BUILD_PLAN: Example\nstate: draft\n\n## story 1: Work\nid: work\nstate: pending\n",
        encoding="utf-8",
    )
    item = {
        "id": "planning_session",
        "label": "Planning Session",
        "section": "core",
        "type": "plan_decision",
        "plan_path": str(plan_path),
    }
    monkeypatch.setattr(quarterdeck, "CONFIG", {"items": [item]})
    monkeypatch.setattr(quarterdeck, "CONFIG_ERROR", None)

    result = quarterdeck.api_plan_decision(
        "planning_session", quarterdeck.PlanDecision(decision="approve")
    )

    assert result["state"] == "approved"
    assert "state: approved" in plan_path.read_text(encoding="utf-8")

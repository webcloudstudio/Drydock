"""Focused tests for reusable QuarterDeck renderers."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest


def _load_quarterdeck():
    path = Path(__file__).parents[1] / "QuarterDeck" / "app.py"
    spec = importlib.util.spec_from_file_location("quarterdeck_app_test", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


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


def test_drydock_console_exposes_existing_owned_documents():
    root = Path(__file__).parents[1]
    config = json.loads((root / "QuarterDeck" / "console.json").read_text(encoding="utf-8"))
    docs_items = {
        "soundings",
        "specification",
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
    assert "tags" in ships_log["fields"]


def test_drydock_console_pins_the_three_standard_artifacts_in_core():
    root = Path(__file__).parents[1]
    config = json.loads((root / "QuarterDeck" / "console.json").read_text(encoding="utf-8"))
    items = {item["id"]: item for item in config["items"]}
    for standard in ("overview", "soundings", "sea_trials"):
        assert items[standard]["section"] == "core", standard


# ── Recategorize (section-only move; pin core, free elsewhere) ───────────────────


def _sample_config() -> dict:
    return {
        "console": {"name": "Test", "default_item": "spec"},
        "items": [
            {"id": "spec", "label": "Spec", "section": "core", "type": "markdown", "path": "a.md"},
            {
                "id": "review",
                "label": "Review",
                "section": "pages",
                "type": "markdown",
                "path": "b.md",
            },
        ],
    }


def test_legal_target_sections_pins_core_and_frees_others():
    quarterdeck = _load_quarterdeck()
    assert quarterdeck.legal_target_sections({"id": "spec", "section": "core"}) == []
    assert quarterdeck.legal_target_sections({"id": "review", "section": "pages"}) == [
        "pages",
        "plan",
        "actions",
        "archive",
    ]


def test_apply_section_change_moves_non_core_item():
    quarterdeck = _load_quarterdeck()
    config = _sample_config()
    item = quarterdeck.apply_section_change(config, "review", "archive")
    assert item["section"] == "archive"
    assert config["items"][1]["section"] == "archive"  # mutated in place


def test_apply_section_change_rejects_pinned_core():
    quarterdeck = _load_quarterdeck()
    config = _sample_config()
    with pytest.raises(quarterdeck.HTTPException) as exc:
        quarterdeck.apply_section_change(config, "spec", "archive")
    assert exc.value.status_code == 400
    assert config["items"][0]["section"] == "core"  # unchanged


def test_apply_section_change_rejects_illegal_target():
    quarterdeck = _load_quarterdeck()
    config = _sample_config()
    with pytest.raises(quarterdeck.HTTPException) as exc:
        quarterdeck.apply_section_change(config, "review", "core")
    assert exc.value.status_code == 400
    assert config["items"][1]["section"] == "pages"  # unchanged


def test_apply_section_change_rejects_unknown_item():
    quarterdeck = _load_quarterdeck()
    config = _sample_config()
    with pytest.raises(quarterdeck.HTTPException) as exc:
        quarterdeck.apply_section_change(config, "nope", "archive")
    assert exc.value.status_code == 404


def test_write_config_round_trips_and_preserves_order(tmp_path, monkeypatch):
    quarterdeck = _load_quarterdeck()
    target = tmp_path / "console.json"
    monkeypatch.setattr(quarterdeck, "CONFIG_PATH", target)
    config = _sample_config()
    quarterdeck.apply_section_change(config, "review", "archive")
    quarterdeck.write_config(config)
    reloaded = json.loads(target.read_text(encoding="utf-8"))
    assert [i["id"] for i in reloaded["items"]] == ["spec", "review"]
    assert reloaded["items"][1]["section"] == "archive"

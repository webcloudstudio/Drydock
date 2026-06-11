"""Focused tests for reusable QuarterDeck renderers."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


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

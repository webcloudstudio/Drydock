"""Focused tests for reusable QuarterDeck renderers."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest
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
    items = {item["id"]: item for item in config["items"]}

    # Simple items that resolve to a single file path
    simple_items = {"soundings", "master_blueprint", "rendered_docs"}
    assert simple_items <= items.keys()
    for item_id in simple_items:
        item = items[item_id]
        relative = item.get("path") or item.get("href")
        assert relative, item_id
        assert (root / "QuarterDeck" / relative).resolve().is_file(), item_id

    # Document items (multi-variant)
    sea_trials = items["sea_trials"]
    assert sea_trials["type"] == "document"
    assert sea_trials["section"] == "core"
    assert (root / "QuarterDeck" / sea_trials["path_md"]).resolve().is_file()
    assert (root / "QuarterDeck" / sea_trials["path_html"]).resolve().is_file()
    assert (root / "QuarterDeck" / sea_trials["path_pdf"]).resolve().is_file()

    pypi = items["pypi_reservation"]
    assert pypi["type"] == "document"
    assert (root / "QuarterDeck" / pypi["path_md"]).resolve().is_file()
    assert (root / "QuarterDeck" / pypi["path_pdf"]).resolve().is_file()

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

    assert "Total commands</strong><br>25" in rendered
    assert "DONE (15)" in rendered
    assert "IMPLEMENTED (2)" in rendered
    assert "STUBBED (8)" in rendered
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


def test_plan_decision_rejects_non_approval(tmp_path, monkeypatch):
    quarterdeck = _load_quarterdeck()
    plan_path = tmp_path / "BUILD_PLAN.md"
    plan_path.write_text(
        "# BUILD_PLAN: Example\nstate: draft\n\n## story 1: Work\nid: work\nstate: pending\n",
        encoding="utf-8",
    )
    item = {"type": "plan_decision", "plan_path": str(plan_path)}
    monkeypatch.setattr(quarterdeck, "find_item", lambda _item_id: item)

    with pytest.raises(quarterdeck.HTTPException, match="supports plan approval"):
        quarterdeck.api_plan_decision(
            "planning_session", quarterdeck.PlanDecision(decision="revise")
        )


# ── document type renderer ────────────────────────────────────────────────────


def test_document_renderer_tabs_md_html_pdf(tmp_path, monkeypatch):
    quarterdeck = _load_quarterdeck()
    md_file = tmp_path / "doc.md"
    html_file = tmp_path / "doc.html"
    pdf_file = tmp_path / "doc.pdf"
    md_file.write_text("# Hello\nworld", encoding="utf-8")
    html_file.write_text("<html><body>hello</body></html>", encoding="utf-8")
    pdf_file.write_bytes(b"%PDF-1.4")

    def fake_resolve(path_value: str):
        m = {"../doc.md": md_file, "../doc.html": html_file, "../doc.pdf": pdf_file}
        p = m.get(path_value)
        if p is None:
            raise quarterdeck.HTTPException(status_code=404, detail="not found")
        return p

    monkeypatch.setattr(quarterdeck, "resolve_path", fake_resolve)

    rendered = quarterdeck.render_document_item(
        {
            "id": "test_doc",
            "label": "Test Doc",
            "type": "document",
            "path_md": "../doc.md",
            "path_html": "../doc.html",
            "path_pdf": "../doc.pdf",
        }
    )

    assert "Read" in rendered
    assert "View HTML" in rendered
    assert "PDF" in rendered
    assert "md-tabs" in rendered


def test_document_renderer_single_md_no_tabs(tmp_path, monkeypatch):
    quarterdeck = _load_quarterdeck()
    md_file = tmp_path / "doc.md"
    md_file.write_text("# Solo\ncontent", encoding="utf-8")

    monkeypatch.setattr(quarterdeck, "resolve_path", lambda _: md_file)

    rendered = quarterdeck.render_document_item(
        {"id": "solo", "label": "Solo", "type": "document", "path_md": "../doc.md"}
    )

    assert "md-tabs" not in rendered
    assert "Solo" in rendered


def test_document_renderer_missing_all_paths():
    quarterdeck = _load_quarterdeck()

    rendered = quarterdeck.render_document_item(
        {"id": "empty", "label": "Empty", "type": "document"}
    )

    assert "No files found" in rendered


# ── sources expansion ────────────────────────────────────────────────────────


def test_expand_sources_adds_discovered_files(tmp_path):
    quarterdeck = _load_quarterdeck()
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "GUIDE.md").write_text("# Guide", encoding="utf-8")

    project_root_orig = quarterdeck.PROJECT_ROOT
    base_dir_orig = quarterdeck.BASE_DIR
    quarterdeck.PROJECT_ROOT = tmp_path
    quarterdeck.BASE_DIR = tmp_path / "QuarterDeck"

    try:
        config: dict = {
            "sources": [{"glob": "docs/*.md", "section": "project_pages", "type": "markdown"}],
            "items": [],
        }
        quarterdeck._expand_sources(config)
        ids = [item["id"] for item in config["items"]]
        assert "guide" in ids
        item = next(i for i in config["items"] if i["id"] == "guide")
        assert item["section"] == "project_pages"
        assert item["type"] == "markdown"
    finally:
        quarterdeck.PROJECT_ROOT = project_root_orig
        quarterdeck.BASE_DIR = base_dir_orig


def test_expand_sources_skips_files_covered_by_explicit_items(tmp_path):
    quarterdeck = _load_quarterdeck()
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "SPEC.md").write_text("# Spec", encoding="utf-8")

    base_dir = tmp_path / "QuarterDeck"
    quarterdeck.PROJECT_ROOT = tmp_path
    quarterdeck.BASE_DIR = base_dir

    try:
        config: dict = {
            "sources": [{"glob": "docs/*.md", "section": "project_pages", "type": "markdown"}],
            "items": [
                {
                    "id": "master_blueprint",
                    "label": "Master Blueprint",
                    "section": "core",
                    "type": "markdown",
                    "path": "../docs/SPEC.md",
                }
            ],
        }
        quarterdeck._expand_sources(config)
        ids = [item["id"] for item in config["items"]]
        assert ids == [
            "master_blueprint"
        ], "source must not duplicate a path covered by an explicit item"
    finally:
        quarterdeck.PROJECT_ROOT = tmp_path.parent
        quarterdeck.BASE_DIR = tmp_path.parent / "QuarterDeck"


# ── archive / unarchive ───────────────────────────────────────────────────────


def test_archive_and_unarchive_item(tmp_path, monkeypatch):
    quarterdeck = _load_quarterdeck()
    db_file = tmp_path / "state.sqlite"

    monkeypatch.setattr(quarterdeck, "db_path", lambda: db_file)
    monkeypatch.setattr(
        quarterdeck,
        "CONFIG",
        {
            "sections": [
                {"id": "project_pages", "label": "Project Pages"},
                {"id": "archive", "label": "Archive", "collapsed": True},
            ],
            "items": [
                {
                    "id": "my_doc",
                    "label": "My Doc",
                    "section": "project_pages",
                    "type": "markdown",
                    "path": "x.md",
                }
            ],
        },
    )
    monkeypatch.setattr(quarterdeck, "CONFIG_ERROR", None)

    result = quarterdeck.api_archive_item("my_doc")
    assert result["ok"] is True

    archived = quarterdeck._archived_item_ids()
    assert "my_doc" in archived

    result = quarterdeck.api_unarchive_item("my_doc")
    assert result["ok"] is True

    archived = quarterdeck._archived_item_ids()
    assert "my_doc" not in archived


def test_archive_blocked_for_pinned_section(monkeypatch):
    quarterdeck = _load_quarterdeck()
    monkeypatch.setattr(
        quarterdeck,
        "CONFIG",
        {
            "sections": [{"id": "core", "label": "Core", "pinned": True}],
            "items": [{"id": "spec", "section": "core", "type": "markdown", "path": "x.md"}],
        },
    )
    monkeypatch.setattr(quarterdeck, "CONFIG_ERROR", None)

    with pytest.raises(quarterdeck.HTTPException, match="pinned"):
        quarterdeck.api_archive_item("spec")

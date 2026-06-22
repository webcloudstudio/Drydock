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


def test_drydock_console_has_four_configured_sections():
    config = _console_config()
    section_ids = [s["id"] for s in config["sections"]]
    assert section_ids == ["core", "actions", "docs", "archive"]


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
    assert items["commanders_view"]["label"] == "Captain's Chair"


# ── Acceptance status (Core Docs only, read-only) ──────────────────────────────


def _soundings_markdown(
    *,
    done_evidence: str = "`test_done`",
    stubbed_state: str = "STUBBED",
) -> str:
    return f"""# Soundings

| ID | Acceptance Criterion | State | Evidence |
|---|---|---|---|
| AC-001 | `drydock done` works | DONE | {done_evidence} |
| AC-002 | `drydock later` is deferred | {stubbed_state} | exits 2 |
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


def test_command_status_calculates_acceptance_totals(monkeypatch):
    quarterdeck = _load_quarterdeck()
    _configure_command_status(
        quarterdeck,
        monkeypatch,
        [
            ("soundings", "Soundings", "core", _soundings_markdown()),
        ],
    )

    rendered = quarterdeck.render_command_status({"label": "Acceptance Status"})

    assert "Derived from Core Doc: Soundings" in rendered
    assert "Total criteria</strong><br>2" in rendered
    assert "DONE (1)" in rendered
    assert "STUBBED (1)" in rendered
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
                _soundings_markdown(done_evidence="", stubbed_state="UNKNOWN"),
            )
        ],
    )

    rendered = quarterdeck.render_command_status({"label": "Command Status"})

    assert "DONE row has no evidence" in rendered
    assert "Unknown state" in rendered


def test_command_status_requires_exactly_one_core_soundings_table(monkeypatch):
    quarterdeck = _load_quarterdeck()
    _configure_command_status(
        quarterdeck,
        monkeypatch,
        [
            ("one", "One", "core", _soundings_markdown()),
            ("two", "Two", "core", _soundings_markdown()),
        ],
    )

    rendered = quarterdeck.render_command_status({"label": "Command Status"})

    assert "Expected exactly one Core Doc Soundings table; found 2" in rendered


def test_drydock_command_status_renders_current_soundings():
    quarterdeck = _load_quarterdeck()

    rendered = quarterdeck.render_command_status({"label": "Command Status"})

    assert "Total criteria</strong><br>46" in rendered
    assert "DONE (34)" in rendered
    assert "IMPLEMENTED (6)" in rendered
    assert "STUBBED (6)" in rendered
    assert "NOT STARTED (0)" in rendered
    assert "no structured findings" in rendered


def test_drydock_console_core_artifact_order():
    config = _console_config()
    core = sorted(
        (item for item in config["items"] if item["section"] == "core" and item.get("order")),
        key=lambda item: item["order"],
    )

    assert [item["id"] for item in core] == [
        "commanders_view",
        "master_blueprint",
        "sea_trials",
        "soundings",
        "ships_log",
        "board",
    ]


def test_plan_decision_approves_authoritative_plan(tmp_path, monkeypatch):
    quarterdeck = _load_quarterdeck()
    plan_path = tmp_path / "MANIFEST.md"
    plan_path.write_text(
        "# MANIFEST: Example\nstate: draft\n\n## story 1: Work\nid: work\nstate: pending\n",
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
    plan_path = tmp_path / "MANIFEST.md"
    plan_path.write_text(
        "# MANIFEST: Example\nstate: draft\n\n## story 1: Work\nid: work\nstate: pending\n",
        encoding="utf-8",
    )
    item = {"type": "plan_decision", "plan_path": str(plan_path)}
    monkeypatch.setattr(quarterdeck, "find_item", lambda _item_id: item)

    with pytest.raises(quarterdeck.HTTPException, match="supports plan approval"):
        quarterdeck.api_plan_decision(
            "planning_session", quarterdeck.PlanDecision(decision="revise")
        )


# ── document type renderer ────────────────────────────────────────────────────


def test_document_renderer_html_takes_priority(tmp_path, monkeypatch):
    """With all three variants present, html is rendered (highest priority)."""
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

    assert "doc-frame" in rendered  # html iframe rendered
    assert "variant=html" in rendered
    assert "md-tabs" not in rendered  # no tabs


def test_document_renderer_pdf_fallback_when_no_html(tmp_path, monkeypatch):
    """Without html, pdf is rendered next."""
    quarterdeck = _load_quarterdeck()
    pdf_file = tmp_path / "doc.pdf"
    pdf_file.write_bytes(b"%PDF-1.4")

    def fake_resolve(path_value: str):
        m = {"../doc.pdf": pdf_file}
        p = m.get(path_value)
        if p is None:
            raise quarterdeck.HTTPException(status_code=404, detail="not found")
        return p

    monkeypatch.setattr(quarterdeck, "resolve_path", fake_resolve)

    rendered = quarterdeck.render_document_item(
        {"id": "test_doc", "label": "Test Doc", "type": "document", "path_pdf": "../doc.pdf"}
    )

    assert "pdf-open-btn" in rendered
    assert "variant=pdf" in rendered


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


def test_markdown_renderer_tabs_splits_h2_sections(tmp_path, monkeypatch):
    """A markdown item with tabs: true renders each ## section as a switchable tab."""
    quarterdeck = _load_quarterdeck()
    md_file = tmp_path / "ANALYSIS.md"
    md_file.write_text(
        "# Blueprint Analysis\n\nQuality: Ready\n\n## Open Questions\n- None.\n\n## Notes\nNone.\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(quarterdeck, "resolve_path", lambda _: md_file)

    rendered = quarterdeck.render_markdown_item(
        {
            "id": "analysis",
            "label": "Analysis",
            "type": "markdown",
            "tabs": True,
            "path": "../ANALYSIS.md",
        }
    )

    assert "md-tabs" in rendered
    # Overview tab (pre-## block) + Open Questions + Notes = 3 tab buttons.
    assert rendered.count("md-tab-btn") >= 3
    assert "Overview" in rendered
    assert "Open Questions" in rendered
    assert "Notes" in rendered


def test_markdown_renderer_without_tabs_flag_renders_plain(tmp_path, monkeypatch):
    quarterdeck = _load_quarterdeck()
    md_file = tmp_path / "doc.md"
    md_file.write_text("# Title\n\n## One\na\n\n## Two\nb\n", encoding="utf-8")
    monkeypatch.setattr(quarterdeck, "resolve_path", lambda _: md_file)

    rendered = quarterdeck.render_markdown_item(
        {"id": "plain", "label": "Plain", "type": "markdown", "path": "../doc.md"}
    )

    assert "md-tabs" not in rendered


# ── _item_file_exists ────────────────────────────────────────────────────────


def test_item_file_exists_document_hidden_until_path_html_present(tmp_path, monkeypatch):
    quarterdeck = _load_quarterdeck()
    monkeypatch.setattr(quarterdeck, "BASE_DIR", tmp_path / "QuarterDeck")

    item = {"id": "chair", "type": "document", "path_html": "captains_chair.html"}
    assert not quarterdeck._item_file_exists(item)

    (tmp_path / "QuarterDeck" / "captains_chair.html").parent.mkdir(parents=True, exist_ok=True)
    (tmp_path / "QuarterDeck" / "captains_chair.html").write_text("<html/>", encoding="utf-8")
    assert quarterdeck._item_file_exists(item)


def test_item_file_exists_document_visible_when_any_variant_exists(tmp_path, monkeypatch):
    quarterdeck = _load_quarterdeck()
    monkeypatch.setattr(quarterdeck, "BASE_DIR", tmp_path / "QuarterDeck")

    item = {
        "id": "doc",
        "type": "document",
        "path_md": "doc.md",
        "path_html": "doc.html",
        "path_pdf": "doc.pdf",
    }
    assert not quarterdeck._item_file_exists(item)

    (tmp_path / "QuarterDeck" / "doc.md").parent.mkdir(parents=True, exist_ok=True)
    (tmp_path / "QuarterDeck" / "doc.md").write_text("# Doc", encoding="utf-8")
    assert quarterdeck._item_file_exists(item)


def test_item_file_exists_document_no_paths_always_visible(tmp_path, monkeypatch):
    quarterdeck = _load_quarterdeck()
    monkeypatch.setattr(quarterdeck, "BASE_DIR", tmp_path / "QuarterDeck")

    item = {"id": "doc", "type": "document"}
    assert quarterdeck._item_file_exists(item)


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
        assert ids == ["master_blueprint"], (
            "source must not duplicate a path covered by an explicit item"
        )
    finally:
        quarterdeck.PROJECT_ROOT = tmp_path.parent
        quarterdeck.BASE_DIR = tmp_path.parent / "QuarterDeck"


# ── archive / unarchive ───────────────────────────────────────────────────────


def test_archive_and_unarchive_item(tmp_path, monkeypatch):
    quarterdeck = _load_quarterdeck()

    monkeypatch.setattr(quarterdeck, "_SESSION_ARCHIVED", set())
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
    assert quarterdeck._archive_key("my_doc") in quarterdeck._SESSION_ARCHIVED

    result = quarterdeck.api_unarchive_item("my_doc")
    assert result["ok"] is True
    assert quarterdeck._archive_key("my_doc") not in quarterdeck._SESSION_ARCHIVED


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


# ── Spike questionnaire template ──────────────────────────────────────────────


def _discovery_json(**overrides) -> str:
    data = {
        "id": "discovery-intent",
        "title": "Discovery: Intent",
        "purpose": "What does this product do?",
        "questions": [
            {
                "id": "primary_goal",
                "label": "Primary Goal",
                "prompt": "In one sentence, what must this product do?",
                "input": "textarea",
            }
        ],
    }
    data.update(overrides)
    return json.dumps(data, indent=2)


def _discovery_item() -> dict:
    return {
        "id": "discovery_intent",
        "label": "Discovery: Intent",
        "section": "actions",
        "type": "questionnaire",
        "template": "discovery",
        "path": "questionnaires/discovery-intent.json",
    }


def test_spike_questionnaire_is_buttonless_with_autosave(tmp_path, monkeypatch):
    quarterdeck = _load_quarterdeck()
    discovery_file = tmp_path / "discovery-intent.json"
    discovery_file.write_text(_discovery_json(), encoding="utf-8")
    monkeypatch.setattr(quarterdeck, "resolve_path", lambda _: discovery_file)

    rendered = quarterdeck.render_questionnaire(_discovery_item())

    # The two nonsensical resolution buttons are gone.
    assert "Implement as Story" not in rendered
    assert "Commander Implements" not in rendered
    assert "Save Answers" not in rendered
    assert "<button" not in rendered
    # A buttonless discovery form that autosaves remains.
    assert "data-template='discovery'" in rendered
    assert "save automatically" in rendered
    assert "q-save-status" in rendered


def test_spike_questionnaire_done_still_renders_editable_form(tmp_path, monkeypatch):
    quarterdeck = _load_quarterdeck()
    discovery_file = tmp_path / "discovery-intent.json"
    discovery_file.write_text(_discovery_json(state="answered"), encoding="utf-8")
    monkeypatch.setattr(quarterdeck, "resolve_path", lambda _: discovery_file)

    rendered = quarterdeck.render_questionnaire(_discovery_item())

    # No resolution label / buttons; a done discovery stays editable and shows the done mark.
    assert "Implement as Story" not in rendered
    assert "<form data-questionnaire=" in rendered
    assert "q-done-mark" in rendered


def test_non_spike_questionnaire_is_also_buttonless(tmp_path, monkeypatch):
    quarterdeck = _load_quarterdeck()
    q_file = tmp_path / "q.json"
    q_file.write_text(
        json.dumps({"id": "q1", "title": "Q", "purpose": "p", "questions": []}),
        encoding="utf-8",
    )
    monkeypatch.setattr(quarterdeck, "resolve_path", lambda _: q_file)

    item = {
        "id": "q1",
        "label": "Q",
        "section": "actions",
        "type": "questionnaire",
        "path": "q.json",
    }
    rendered = quarterdeck.render_questionnaire(item)

    assert "Save Answers" not in rendered
    assert "<button" not in rendered
    assert "q-save-status" in rendered


def test_writeback_questionnaire_writes_resolution(tmp_path, monkeypatch):
    quarterdeck = _load_quarterdeck()
    discovery_file = tmp_path / "discovery-intent.json"
    discovery_file.write_text(_discovery_json(), encoding="utf-8")

    item = {
        "id": "discovery_intent",
        "type": "questionnaire",
        "path": str(discovery_file.relative_to(tmp_path)),
    }
    monkeypatch.setattr(quarterdeck, "items", lambda: [item])
    monkeypatch.setattr(quarterdeck, "BASE_DIR", tmp_path)

    quarterdeck._writeback_questionnaire(
        "questionnaire.discovery-intent",
        "promoted",
        {"primary_goal": "Build a ship.", "resolution": "promoted"},
    )

    written = json.loads(discovery_file.read_text(encoding="utf-8"))
    assert written["state"] == "promoted"
    assert written["resolution"] == "promoted"
    assert written["questions"][0]["answer"] == "Build a ship."


def test_answered_discovery_stays_in_actions_section(tmp_path, monkeypatch):
    quarterdeck = _load_quarterdeck()
    q_dir = tmp_path / "QuarterDeck" / "questionnaires"
    q_dir.mkdir(parents=True)
    discovery_file = q_dir / "discovery-guardrails.json"
    discovery_file.write_text(
        _discovery_json(id="discovery-guardrails", title="Discovery: Guardrails"), encoding="utf-8"
    )
    item = {
        "id": "discovery_guardrails",
        "label": "Discovery: Guardrails",
        "section": "actions",
        "type": "questionnaire",
        "template": "discovery",
        "path": "questionnaires/discovery-guardrails.json",
    }
    monkeypatch.setattr(quarterdeck, "BASE_DIR", tmp_path / "QuarterDeck")
    monkeypatch.setattr(
        quarterdeck,
        "CONFIG",
        {
            "sections": [
                {"id": "actions", "label": "Actions", "dot": "#dc2626"},
                {"id": "archive", "label": "Archive", "dot": "#94a3b8", "collapsed": True},
            ],
            "items": [item],
        },
    )
    monkeypatch.setattr(quarterdeck, "CONFIG_ERROR", None)

    assert [section["id"] for section in quarterdeck.nav_model()] == ["actions"]

    quarterdeck.api_set_state(
        "questionnaire.discovery-guardrails",
        quarterdeck.StateUpdate(
            document_id="discovery-guardrails",
            state="answered",
            payload={"primary_goal": "Keep generated work inside the guardrails."},
        ),
    )

    # Answering does not archive — item stays in actions, shows as done.
    assert [section["id"] for section in quarterdeck.nav_model()] == ["actions"]
    rendered = quarterdeck.render_nav()
    assert "data-sec='actions'" in rendered
    assert "data-item='discovery_guardrails'" in rendered
    assert "ns-done" in rendered


def _write_target_console(target_dir: Path, name: str) -> None:
    quarterdeck_dir = target_dir / "QuarterDeck"
    (quarterdeck_dir / "pages").mkdir(parents=True, exist_ok=True)
    (quarterdeck_dir / "pages" / "help.html").write_text(
        f"<p>{name} help</p>",
        encoding="utf-8",
    )
    (quarterdeck_dir / "pages" / "overview.md").write_text(
        f"# {name} Captain's Chair\n\nStatus.\n",
        encoding="utf-8",
    )
    (quarterdeck_dir / "console.yaml").write_text(
        "\n".join(
            [
                "console:",
                f"  name: {name} QuarterDeck",
                "  default_item: commanders_view",
                "  app_help_file_location: pages/help.html",
                "project:",
                f"  id: {name.lower()}",
                f"  name: {name}",
                "  description: \"Workspace target\"",
                f"  copyright: Copyright (c) 2026 {name} Studio. All rights reserved.",
                "sections:",
                "  - { id: core, label: \"Core\", dot: \"#0d9488\", pinned: true }",
                "items:",
                "  - { id: commanders_view, label: \"Captain's Chair\", section: core, type: markdown, path: pages/overview.md }",
                "",
            ]
        ),
        encoding="utf-8",
    )


def _configure_quarterdeck_workspace(quarterdeck, monkeypatch, tmp_path: Path) -> Path:
    workspace = tmp_path / "workspace"
    alpha = workspace / "targets" / "Alpha"
    beta = workspace / "targets" / "Beta"
    _write_target_console(alpha, "Alpha")
    _write_target_console(beta, "Beta")

    monkeypatch.setattr(quarterdeck, "WORKSPACE_ROOT", workspace)
    monkeypatch.setattr(quarterdeck, "PROJECT_ROOT", alpha)
    monkeypatch.setattr(quarterdeck, "BASE_DIR", alpha / "QuarterDeck")
    monkeypatch.setattr(quarterdeck, "CONFIG_PATH", alpha / "QuarterDeck" / "console.yaml")
    quarterdeck.CONFIG, quarterdeck.CONFIG_ERROR = quarterdeck.load_config(
        base_dir=quarterdeck.BASE_DIR,
        project_root=quarterdeck.PROJECT_ROOT,
        config_path=quarterdeck.CONFIG_PATH,
    )
    return workspace


class _RequestStub:
    def __init__(self, cookies=None, query_params=None):
        self.cookies = cookies or {}
        self.query_params = query_params or {}


def test_nav_renders_bottom_target_switcher(tmp_path, monkeypatch):
    quarterdeck = _load_quarterdeck()
    _configure_quarterdeck_workspace(quarterdeck, monkeypatch, tmp_path)

    rendered = quarterdeck.api_nav(_RequestStub())["html"]
    assert "target-dock" in rendered
    assert "Targets" not in rendered
    assert "/switch-target/Alpha" in rendered
    assert "/switch-target/Beta" in rendered
    assert "target-btn active" in rendered
    assert "target-btn-id" not in rendered
    assert ">Alpha</span>" in rendered
    assert ">Beta</span>" in rendered
    assert "Workspace target" not in rendered
    assert "<span class='section-label'>Alpha</span>" in rendered
    assert "collapse-arrow" not in rendered


def test_render_nav_includes_build_plan_flag_and_static_sections(monkeypatch):
    quarterdeck = _load_quarterdeck()
    monkeypatch.setattr(
        quarterdeck,
        "CONFIG",
        {
            "sections": [
                {"id": "build_plan", "label": "Build Steps", "dot": "#d97706"},
                {"id": "archive", "label": "Archive", "dot": "#94a3b8", "collapsed": True},
            ],
            "items": [
                {"id": "plan", "label": "Plan", "section": "build_plan", "type": "markdown", "path": "plan.md"},
                {"id": "old", "label": "Old", "section": "archive", "type": "markdown", "path": "old.md"},
            ],
        },
    )
    monkeypatch.setattr(quarterdeck, "CONFIG_ERROR", None)
    monkeypatch.setattr(quarterdeck, "_item_file_exists", lambda _item: True)
    monkeypatch.setattr(quarterdeck, "_is_item_archived", lambda _item: False)

    rendered = quarterdeck.render_nav()

    assert "Build Steps" in rendered
    assert "sec-flag" in rendered
    assert "onclick='toggleSection" not in rendered
    assert "collapse-arrow" not in rendered
    assert "data-item='old'" in rendered


def test_switch_target_sets_cookie_and_changes_active_context(tmp_path, monkeypatch):
    quarterdeck = _load_quarterdeck()
    _configure_quarterdeck_workspace(quarterdeck, monkeypatch, tmp_path)

    response = quarterdeck.switch_target("Beta", _RequestStub())

    assert response.status_code == 303
    assert response.headers["location"] == "/?item=commanders_view"
    assert "quarterdeck_target=Beta" in response.headers["set-cookie"]

    config = quarterdeck.api_config(_RequestStub({"quarterdeck_target": "Beta"}))
    assert config["project"]["name"] == "Beta"


def test_captains_chair_uses_single_navigation_surface(tmp_path, monkeypatch):
    quarterdeck = _load_quarterdeck()
    _configure_quarterdeck_workspace(quarterdeck, monkeypatch, tmp_path)

    response = quarterdeck.api_document("commanders_view", _RequestStub({"quarterdeck_target": "Beta"}))
    html = response["html"]
    assert "Captain&#x27;s Chair" in html
    assert "Viewing Target" not in html
    assert "target-panel" not in html
    assert "/switch-target/Beta" not in html


def test_index_uses_project_title_copyright_and_help_button(tmp_path, monkeypatch):
    quarterdeck = _load_quarterdeck()
    _configure_quarterdeck_workspace(quarterdeck, monkeypatch, tmp_path)

    html = quarterdeck.index(_RequestStub({"quarterdeck_target": "Beta"}))

    assert "<title>Beta</title>" in html
    assert '<header><strong>The Drydock</strong><div class="header-actions">' in html
    assert "Workspace target" not in html
    assert "Copyright (c) 2026 Beta Studio. All rights reserved." in html
    assert 'Drydock <span class="flyout">↗</span>' in html
    assert 'Drydock Home <span class="flyout">↗</span>' in html
    assert 'href="https://webcloudstudio.com"' in html


def test_index_respects_requested_item_query_parameter(tmp_path, monkeypatch):
    quarterdeck = _load_quarterdeck()
    _configure_quarterdeck_workspace(quarterdeck, monkeypatch, tmp_path)

    request = _RequestStub({"quarterdeck_target": "Beta"})
    request.query_params = {"item": "commanders_view"}

    html = quarterdeck.index(request)

    assert 'loadDoc("commanders_view");' in html

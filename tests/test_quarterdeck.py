"""Focused tests for reusable QuarterDeck renderers."""

from __future__ import annotations

import importlib.util
import json
import re
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
        "\n".join([
            json.dumps({"recorded_at": "2026-01-01T00:00:00Z", "title": "Older"}),
            "{broken",
            json.dumps({"recorded_at": "2026-02-01T00:00:00Z", "title": "Newer"}),
        ]),
        encoding="utf-8",
    )
    monkeypatch.setattr(quarterdeck, "resolve_path", lambda _path: source)

    rendered = quarterdeck.render_jsonl_item({
        "label": "Events",
        "path": "events.jsonl",
        "fields": ["recorded_at", "title"],
        "sort": "recorded_at",
        "sort_direction": "desc",
    })

    assert rendered.index("Newer") < rendered.index("Older")
    assert "2 record(s)" in rendered
    assert "line 2" in rendered


def test_drydock_console_has_three_configured_sections():
    config = _console_config()
    section_ids = [s["id"] for s in config["sections"]]
    assert section_ids == ["core", "actions", "docs"]


def test_drydock_console_has_no_archive_section():
    config = _console_config()
    assert "archive" not in {s["id"] for s in config["sections"]}


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


def test_drydock_console_pins_the_three_standard_artifacts_in_core():
    config = _console_config()
    items = {item["id"]: item for item in config["items"]}
    for standard in ("commanders_chair", "soundings", "sea_trials"):
        assert items[standard]["section"] == "core", standard
    assert items["commanders_chair"]["label"] == "Commanders Chair"


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

    assert "Total criteria</strong><br>49" in rendered
    assert "DONE (33)" in rendered
    assert "IMPLEMENTED (16)" in rendered
    assert "STUBBED (0)" in rendered
    assert "NOT STARTED (0)" in rendered
    assert "no structured findings" in rendered


def test_drydock_console_core_artifact_order():
    config = _console_config()
    core = sorted(
        (item for item in config["items"] if item["section"] == "core" and item.get("order")),
        key=lambda item: item["order"],
    )

    assert [item["id"] for item in core] == [
        "commanders_chair",
        "master_blueprint",
        "sea_trials",
        "soundings",
        "board",
    ]


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

    rendered = quarterdeck.render_document_item({
        "id": "test_doc",
        "label": "Test Doc",
        "type": "document",
        "path_md": "../doc.md",
        "path_html": "../doc.html",
        "path_pdf": "../doc.pdf",
        "help_text": "Document help.",
    })

    assert "doc-frame" in rendered  # html iframe rendered
    assert "variant=html" in rendered
    assert "md-tabs" not in rendered  # no tabs
    assert "Document help." not in rendered
    assert "<h1>Test Doc</h1>" not in rendered


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

    rendered = quarterdeck.render_document_item({
        "id": "test_doc",
        "label": "Test Doc",
        "type": "document",
        "path_pdf": "../doc.pdf",
    })

    assert "pdf-open-btn" in rendered
    assert "variant=pdf" in rendered
    assert "<h1>Test Doc</h1>" not in rendered


def test_document_renderer_single_md_no_tabs(tmp_path, monkeypatch):
    quarterdeck = _load_quarterdeck()
    md_file = tmp_path / "doc.md"
    md_file.write_text("# Source Heading\ncontent", encoding="utf-8")

    monkeypatch.setattr(quarterdeck, "resolve_path", lambda _: md_file)

    rendered = quarterdeck.render_document_item({
        "id": "solo",
        "label": "Solo",
        "type": "document",
        "path_md": "../doc.md",
        "help_text": "Document help.",
    })

    assert "md-tabs" not in rendered
    assert "<h1>Solo</h1>" not in rendered
    assert "Source Heading" not in rendered
    assert "Document help." in rendered


def test_document_renderer_missing_all_paths():
    quarterdeck = _load_quarterdeck()

    rendered = quarterdeck.render_document_item({
        "id": "empty",
        "label": "Empty",
        "type": "document",
    })

    assert "No files found" in rendered


def test_markdown_renderer_tabs_splits_h2_sections(tmp_path, monkeypatch):
    """A markdown item with tabs: true renders each ## section as a switchable tab."""
    quarterdeck = _load_quarterdeck()
    md_file = tmp_path / "ANALYSIS.md"
    md_file.write_text(
        "# Blueprint Analysis\n\n## Story List\n- Story.\n\n## Analysis Notes\nQuality: Ready\n\nNone.\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(quarterdeck, "resolve_path", lambda _: md_file)

    rendered = quarterdeck.render_markdown_item({
        "id": "analysis",
        "label": "Analysis",
        "type": "markdown",
        "tabs": True,
        "path": "../ANALYSIS.md",
        "help_text": "Markdown help.",
    })

    assert "md-tabs" in rendered
    assert rendered.count("<button class='md-tab-btn") == 2
    assert "<h1>Analysis</h1>" not in rendered
    assert "Overview" not in rendered
    assert "Story List" in rendered
    assert "Analysis Notes" in rendered
    assert "Markdown help." in rendered


def test_sea_trials_renderer_boxes_documentation_blocks(tmp_path, monkeypatch):
    """Embedded h3 documentation renders as standout notes; criteria render outside them."""
    quarterdeck = _load_quarterdeck()
    md_file = tmp_path / "SEA_TRIALS.md"
    md_file.write_text(
        "# Sea Trials: Demo\n\n"
        "### About Sea Trials\nWhat they are.\n\n"
        "### Guardrails\nWhat they prohibit.\n\n"
        "## st-001: Catalog responds\n"
        "Type: behavioral\nPattern: event\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(quarterdeck, "resolve_path", lambda _: md_file)

    rendered = quarterdeck.render_markdown_item({
        "id": "sea_trials",
        "label": "Sea Trials",
        "type": "markdown",
        "path": "../SEA_TRIALS.md",
        "help_text": "Sea Trials help.",
    })

    assert "sea-trials-doc" in rendered
    assert rendered.count("<div class='doc-note'>") == 2
    assert "What they are." in rendered

    outside_notes = re.sub(r"(?s)<div class='doc-note'>.*?</div>", "", rendered)
    assert "st-001" in outside_notes
    assert "What they are." not in outside_notes


def test_ordinary_markdown_pages_do_not_box_h3_headings(tmp_path, monkeypatch):
    quarterdeck = _load_quarterdeck()
    md_file = tmp_path / "doc.md"
    md_file.write_text("# Title\n\n### Section\nBody.\n", encoding="utf-8")
    monkeypatch.setattr(quarterdeck, "resolve_path", lambda _: md_file)

    rendered = quarterdeck.render_markdown_item({
        "id": "plain",
        "label": "Plain",
        "type": "markdown",
        "path": "../doc.md",
    })

    assert "doc-note" not in rendered
    assert "<h3>Section</h3>" in rendered


def test_markdown_renderer_without_tabs_flag_renders_plain(tmp_path, monkeypatch):
    quarterdeck = _load_quarterdeck()
    md_file = tmp_path / "doc.md"
    md_file.write_text("# Title\n\n## One\na\n\n## Two\nb\n", encoding="utf-8")
    monkeypatch.setattr(quarterdeck, "resolve_path", lambda _: md_file)

    rendered = quarterdeck.render_markdown_item({
        "id": "plain",
        "label": "Plain",
        "type": "markdown",
        "path": "../doc.md",
        "help_text": "Markdown help.",
    })

    assert "md-tabs" not in rendered
    assert "Markdown help." in rendered
    assert "<h1>Title</h1>" not in rendered
    assert "Title" not in rendered


# ── _item_file_exists ────────────────────────────────────────────────────────


def test_item_file_exists_document_hidden_until_path_html_present(tmp_path, monkeypatch):
    quarterdeck = _load_quarterdeck()
    monkeypatch.setattr(quarterdeck, "BASE_DIR", tmp_path / "QuarterDeck")

    item = {"id": "chair", "type": "document", "path_html": "commanders_chair.html"}
    assert not quarterdeck._item_file_exists(item)

    (tmp_path / "QuarterDeck" / "commanders_chair.html").parent.mkdir(parents=True, exist_ok=True)
    (tmp_path / "QuarterDeck" / "commanders_chair.html").write_text("<html/>", encoding="utf-8")
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


def test_item_file_exists_refit_requires_manifest(tmp_path, monkeypatch):
    quarterdeck = _load_quarterdeck()
    target_dir = tmp_path / "Example"
    target_dir.mkdir()
    monkeypatch.setattr(quarterdeck, "PROJECT_ROOT", target_dir)

    item = {"id": "refit_status", "type": "refit"}
    assert not quarterdeck._item_file_exists(item)

    (target_dir / "MANIFEST.md").write_text("# MANIFEST: Example\n", encoding="utf-8")
    assert quarterdeck._item_file_exists(item)


def test_legacy_drydock_console_surfaces_blockers_on_refresh_without_rewrite(tmp_path, monkeypatch):
    quarterdeck = _load_quarterdeck()
    target_dir = tmp_path / "Example"
    base_dir = target_dir / "QuarterDeck"
    base_dir.mkdir(parents=True)
    (target_dir / "METADATA.md").write_text("name: Example\n", encoding="utf-8")
    console_path = base_dir / "console.yaml"
    console_text = "sections:\n  - { id: setup, label: Setup }\nitems: []\nsources: []\n"
    console_path.write_text(console_text, encoding="utf-8")

    config, error = quarterdeck.load_config(base_dir=base_dir, project_root=target_dir)

    assert error is None
    assert console_path.read_text(encoding="utf-8") == console_text
    monkeypatch.setattr(quarterdeck, "BASE_DIR", base_dir)
    monkeypatch.setattr(quarterdeck, "PROJECT_ROOT", target_dir)
    monkeypatch.setattr(quarterdeck, "CONFIG", config)
    monkeypatch.setattr(quarterdeck, "CONFIG_ERROR", None)
    assert all(
        item["id"] != "blockers_doc"
        for section in quarterdeck.nav_model()
        for item in section["items"]
    )

    blockers_path = target_dir / "BLOCKERS.md"
    blockers_path.write_text("# Blockers\n", encoding="utf-8")

    blocker_item = next(
        item
        for section in quarterdeck.nav_model()
        for item in section["items"]
        if item["id"] == "blockers_doc"
    )
    assert quarterdeck.item_nav_status(blocker_item) == "pending"
    rendered = quarterdeck.render_nav()
    assert "blockers-btn" in rendered
    assert "ns-pending" in rendered

    blockers_path.write_text(
        "## blocker-one: Confirm decision\n\n### Commander Resolution\n\nUse option A.\n",
        encoding="utf-8",
    )

    assert quarterdeck.item_nav_status(blocker_item) == "done"
    assert "ns-done" in quarterdeck.render_nav()


def test_legacy_drydock_console_blocker_uses_critical_error_marker(tmp_path):
    quarterdeck = _load_quarterdeck()
    target_dir = tmp_path / "Example"
    base_dir = target_dir / "QuarterDeck"
    base_dir.mkdir(parents=True)
    (target_dir / "METADATA.md").write_text("name: Example\n", encoding="utf-8")
    (target_dir / "BLOCKERS.md").write_text("# Blockers\n", encoding="utf-8")
    (base_dir / "console.yaml").write_text(
        "sections:\n  - { id: setup, label: Setup }\nitems: []\nsources: []\n",
        encoding="utf-8",
    )

    config, error = quarterdeck.load_config(base_dir=base_dir, project_root=target_dir)

    assert error is None
    blocker = next(item for item in config["items"] if item["id"] == "blockers_doc")
    assert blocker["label"] == "⛔ Blockers"


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


def test_expand_sources_keeps_discovery_items_last_when_rule_sets_order(tmp_path):
    quarterdeck = _load_quarterdeck()
    q_dir = tmp_path / "QuarterDeck" / "questionnaires"
    q_dir.mkdir(parents=True)
    (q_dir / "discovery-stack.json").write_text(_discovery_json(), encoding="utf-8")

    project_root_orig = quarterdeck.PROJECT_ROOT
    base_dir_orig = quarterdeck.BASE_DIR
    quarterdeck.PROJECT_ROOT = tmp_path
    quarterdeck.BASE_DIR = tmp_path / "QuarterDeck"

    try:
        config: dict = {
            "sources": [
                {
                    "glob": "QuarterDeck/questionnaires/discovery-*.json",
                    "section": "analyze",
                    "type": "questionnaire",
                    "template": "discovery",
                    "order": 99,
                }
            ],
            "items": [
                {
                    "id": "analysis",
                    "label": "Analysis",
                    "section": "analyze",
                    "type": "markdown",
                    "path": "../ANALYSIS.md",
                    "order": 4,
                }
            ],
        }
        quarterdeck._expand_sources(config)
        generated = next(item for item in config["items"] if item["id"] == "discovery_stack")
        assert generated["order"] == 99
    finally:
        quarterdeck.PROJECT_ROOT = project_root_orig
        quarterdeck.BASE_DIR = base_dir_orig


# ── navigation controls ───────────────────────────────────────────────────────


def test_nav_has_no_archive_controls(monkeypatch):
    quarterdeck = _load_quarterdeck()
    monkeypatch.setattr(
        quarterdeck,
        "CONFIG",
        {
            "sections": [{"id": "docs", "label": "Docs"}],
            "items": [{"id": "spec", "section": "docs", "type": "markdown", "path": "x.md"}],
        },
    )
    monkeypatch.setattr(quarterdeck, "CONFIG_ERROR", None)
    monkeypatch.setattr(quarterdeck, "_item_file_exists", lambda _item: True)

    rendered = quarterdeck.render_nav()

    assert "arc-btn" not in rendered
    assert "archiveToggle" not in rendered
    assert not hasattr(quarterdeck, "api_archive_item")
    assert not hasattr(quarterdeck, "api_unarchive_item")


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
        "section": "analyze",
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
        "section": "analyze",
        "type": "questionnaire",
        "path": "q.json",
    }
    rendered = quarterdeck.render_questionnaire(item)

    assert "Save Answers" not in rendered
    assert "<button" not in rendered


def test_editable_markdown_renders_configured_help_and_prompt_text(tmp_path, monkeypatch):
    quarterdeck = _load_quarterdeck()
    monkeypatch.setattr(quarterdeck, "BASE_DIR", tmp_path / "QuarterDeck")
    monkeypatch.setattr(quarterdeck, "PROJECT_ROOT", tmp_path)
    (tmp_path / "ANALYZE_COMPASS.md").write_text("# Analyze Compass\n", encoding="utf-8")

    rendered = quarterdeck.render_editable_markdown({
        "id": "analyze_compass",
        "type": "editable_markdown",
        "path": "../ANALYZE_COMPASS.md",
        "help_text": "Injected into every analyze run.",
        "prompt_text": "Short steering only.",
    })

    assert "Injected into every analyze run." in rendered
    assert "<h1>Analyze Compass</h1>" not in rendered
    assert "Prompt Text." not in rendered
    assert "Short steering only." not in rendered


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


def test_answered_discovery_stays_in_analyze_section(tmp_path, monkeypatch):
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
        "section": "analyze",
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
                {"id": "analyze", "label": "Analyze", "dot": "#0d9488"},
            ],
            "items": [item],
        },
    )
    monkeypatch.setattr(quarterdeck, "CONFIG_ERROR", None)

    assert [section["id"] for section in quarterdeck.nav_model()] == ["analyze"]

    quarterdeck.api_set_state(
        "questionnaire.discovery-guardrails",
        quarterdeck.StateUpdate(
            document_id="discovery-guardrails",
            state="answered",
            payload={"primary_goal": "Keep generated work inside the guardrails."},
        ),
    )

    # Answering does not archive; the item stays in Analyze and shows as done.
    assert [section["id"] for section in quarterdeck.nav_model()] == ["analyze"]
    rendered = quarterdeck.render_nav()
    assert "data-sec='analyze'" in rendered
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
        f"# {name} Commanders Chair\n\nStatus.\n",
        encoding="utf-8",
    )
    (quarterdeck_dir / "console.yaml").write_text(
        "\n".join([
            "console:",
            f"  name: {name} QuarterDeck",
            "  default_item: commanders_chair",
            "  app_help_file_location: pages/help.html",
            "project:",
            f"  id: {name.lower()}",
            f"  name: {name}",
            '  description: "Workspace target"',
            f"  copyright: Copyright (c) 2026 {name} Studio. All rights reserved.",
            "sections:",
            '  - { id: core, label: "Core", dot: "#0d9488", pinned: true }',
            "items:",
            '  - { id: commanders_chair, label: "Commanders Chair", section: core, type: markdown, path: pages/overview.md }',
            "",
        ]),
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
    assert "fleet-btn" in rendered
    assert "fleet-popout" in rendered
    assert "Targets" not in rendered
    assert "/switch-target/Alpha" in rendered
    assert "/switch-target/Beta" in rendered
    assert "fleet-card active" in rendered
    assert ">Alpha</span>" in rendered
    assert ">Beta</span>" in rendered
    assert "Workspace target" not in rendered
    assert "<span class='section-label'>Alpha</span>" in rendered
    assert "collapse-arrow" not in rendered


def test_render_nav_includes_implement_flag_and_static_sections(monkeypatch):
    quarterdeck = _load_quarterdeck()
    monkeypatch.setattr(
        quarterdeck,
        "CONFIG",
        {
            "sections": [
                {"id": "plan", "label": "Implement", "dot": "#2563eb"},
            ],
            "items": [
                {
                    "id": "plan",
                    "label": "Plan",
                    "section": "plan",
                    "type": "markdown",
                    "path": "plan.md",
                },
            ],
        },
    )
    monkeypatch.setattr(quarterdeck, "CONFIG_ERROR", None)
    monkeypatch.setattr(quarterdeck, "_item_file_exists", lambda _item: True)

    rendered = quarterdeck.render_nav()

    # The implement phase renders its label uppercased alongside the section flag.
    assert "IMPLEMENT" in rendered
    assert "sec-flag" in rendered
    assert "onclick='toggleSection" not in rendered
    assert "collapse-arrow" not in rendered


def test_render_nav_phase_headers_show_target_flag_and_right_phase(monkeypatch):
    quarterdeck = _load_quarterdeck()
    monkeypatch.setattr(quarterdeck, "PROJECT_ROOT", Path("/tmp/workspace/targets/stim"))
    monkeypatch.setattr(
        quarterdeck,
        "CONFIG",
        {
            "sections": [
                {"id": "setup", "label": "Setup", "dot": "#64748b", "pinned": True},
                {"id": "analyze", "label": "Analysis", "dot": "#0d9488", "pinned": True},
                {"id": "plan", "label": "Implement", "dot": "#2563eb"},
            ],
            "items": [
                {
                    "id": "commanders_chair",
                    "label": "Commanders Chair",
                    "section": "setup",
                    "type": "markdown",
                    "path": "overview.md",
                },
                {
                    "id": "analysis",
                    "label": "Analysis",
                    "section": "analyze",
                    "type": "markdown",
                    "path": "analysis.md",
                },
                {
                    "id": "board",
                    "label": "Kanban Board",
                    "section": "plan",
                    "type": "kanban",
                    "path": "../MANIFEST.md",
                },
            ],
        },
    )
    monkeypatch.setattr(quarterdeck, "CONFIG_ERROR", None)
    monkeypatch.setattr(quarterdeck, "_item_file_exists", lambda _item: True)

    rendered = quarterdeck.render_nav()

    assert "section-head-phase" in rendered
    assert "<span class='section-target-name'>STIM</span>" in rendered
    assert "<span class='section-phase-name'>SETUP</span>" in rendered
    assert "<span class='section-phase-name'>ANALYSIS</span>" in rendered
    assert "<span class='section-phase-name'>IMPLEMENT</span>" in rendered
    assert "data-sec='plan'" in rendered


def test_render_nav_includes_build_compass_item_flag(monkeypatch):
    quarterdeck = _load_quarterdeck()
    monkeypatch.setattr(
        quarterdeck,
        "CONFIG",
        {
            "sections": [
                {"id": "core", "label": "Core", "dot": "#0d9488", "pinned": True},
            ],
            "items": [
                {
                    "id": "build_compass",
                    "label": "Build Compass",
                    "section": "core",
                    "type": "compass",
                    "path": "../MANIFEST.md",
                }
            ],
        },
    )
    monkeypatch.setattr(quarterdeck, "CONFIG_ERROR", None)
    monkeypatch.setattr(quarterdeck, "_item_file_exists", lambda _item: True)

    rendered = quarterdeck.render_nav()

    assert "MANIFEST" in rendered
    assert "Build Compass" not in rendered
    assert 'class="item-flag"' in rendered or "class='item-flag'" in rendered


def test_switch_target_sets_cookie_and_changes_active_context(tmp_path, monkeypatch):
    quarterdeck = _load_quarterdeck()
    _configure_quarterdeck_workspace(quarterdeck, monkeypatch, tmp_path)

    response = quarterdeck.switch_target("Beta", _RequestStub())

    assert response.status_code == 303
    assert response.headers["location"] == "/?item=commanders_chair"
    assert "quarterdeck_target=Beta" in response.headers["set-cookie"]

    config = quarterdeck.api_config(_RequestStub({"quarterdeck_target": "Beta"}))
    assert config["project"]["name"] == "Beta"


def test_commanders_chair_uses_single_navigation_surface(tmp_path, monkeypatch):
    quarterdeck = _load_quarterdeck()
    _configure_quarterdeck_workspace(quarterdeck, monkeypatch, tmp_path)

    response = quarterdeck.api_document(
        "commanders_chair", _RequestStub({"quarterdeck_target": "Beta"})
    )
    html = response["html"]
    assert "commanders_chair.html" not in html
    assert "ph-title-row" not in html
    assert "Viewing Target" not in html
    assert "target-panel" not in html
    assert "/switch-target/Beta" not in html


def test_index_uses_project_title_copyright_and_help_button(tmp_path, monkeypatch):
    quarterdeck = _load_quarterdeck()
    _configure_quarterdeck_workspace(quarterdeck, monkeypatch, tmp_path)

    html = quarterdeck.index(_RequestStub({"quarterdeck_target": "Beta"}))

    assert "<title>Beta</title>" in html
    assert (
        '<a class="brand" href="/" title="Drydock"><img src="/logo.png" alt="Drydock"></a>' in html
        or "<header><strong>Drydock</strong>" in html
    )
    assert "Workspace target" not in html
    assert "Copyright (c) 2026 Beta Studio. All rights reserved." in html
    assert 'Web Cloud Studio <span class="flyout">↗</span>' in html
    assert 'Help <span class="flyout">↗</span>' in html
    assert 'href="https://webcloudstudio.net"' in html
    assert (
        'href="https://webcloudstudio.com/project-docs/drydock/Drydock_Specification.html"' in html
    )


def test_target_identity_uses_slug_not_project_name(tmp_path, monkeypatch):
    quarterdeck = _load_quarterdeck()
    workspace = _configure_quarterdeck_workspace(quarterdeck, monkeypatch, tmp_path)

    stim_console = workspace / "targets" / "stim" / "QuarterDeck"
    stim_console.mkdir(parents=True, exist_ok=True)
    (stim_console / "pages").mkdir(parents=True, exist_ok=True)
    (stim_console / "pages" / "help.html").write_text("<p>stim help</p>", encoding="utf-8")
    (stim_console / "commanders_chair.html").write_text("<h1>stim</h1>", encoding="utf-8")
    (stim_console / "console.yaml").write_text(
        "\n".join([
            "console:",
            "  name: Secure Team Inventory Matrix QuarterDeck",
            "  default_item: commanders_chair",
            "  app_help_file_location: pages/help.html",
            "project:",
            "  id: stim",
            "  name: Secure Team Inventory Matrix",
            '  description: "Target description"',
            "  copyright: Copyright (c) 2026 Stim Studio. All rights reserved.",
            "sections:",
            '  - { id: core, label: "Core", dot: "#0d9488", pinned: true }',
            "items:",
            '  - { id: commanders_chair, label: "Commanders Chair", section: core, type: document, path_html: commanders_chair.html }',
            "",
        ]),
        encoding="utf-8",
    )

    nav_html = quarterdeck.api_nav(_RequestStub({"quarterdeck_target": "stim"}))["html"]
    index_html = quarterdeck.index(_RequestStub({"quarterdeck_target": "stim"}))

    assert "/switch-target/stim" in nav_html
    assert ">stim</span>" in nav_html
    assert "Secure Team Inventory Matrix" not in nav_html
    assert "<title>stim</title>" in index_html
    assert "Secure Team Inventory Matrix" not in index_html


def test_index_respects_requested_item_query_parameter(tmp_path, monkeypatch):
    quarterdeck = _load_quarterdeck()
    _configure_quarterdeck_workspace(quarterdeck, monkeypatch, tmp_path)

    request = _RequestStub({"quarterdeck_target": "Beta"})
    request.query_params = {"item": "commanders_chair"}

    html = quarterdeck.index(request)

    assert "new URLSearchParams(window.location.search).get('item')" in html
    assert "localStorage.getItem(lastItemKey)" in html


def test_render_refit_reports_only_changed_not_never_applied(tmp_path, monkeypatch):
    quarterdeck = _load_quarterdeck()
    target = tmp_path / "targets" / "Alpha"
    blueprint = target / "blueprint"
    blueprint.mkdir(parents=True)
    (blueprint / "APPLIED.md").write_text("applied content\n", encoding="utf-8")
    (blueprint / "TOUCHED.md").write_text("edited after apply\n", encoding="utf-8")
    (blueprint / "NEW.md").write_text("never applied\n", encoding="utf-8")
    import hashlib

    applied_hash = hashlib.sha256(b"applied content\n").hexdigest()
    stale_hash = hashlib.sha256(b"original content\n").hexdigest()
    (target / "MANIFEST.md").write_text(
        "# MANIFEST: Alpha\n\n"
        "applied_specs: |\n"
        f"  APPLIED.md sha256={applied_hash} commit=- applied_by=x applied_at=now\n"
        f"  TOUCHED.md sha256={stale_hash} commit=- applied_by=x applied_at=now\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(quarterdeck, "PROJECT_ROOT", target)

    out = quarterdeck.render_refit({"id": "refit_status", "type": "refit"})

    assert "drydock refit" in out
    # Never-applied blueprints are build items, not refit items.
    assert "NEW.md" not in out
    # Only the drifted (previously applied, now changed) blueprint is reported.
    assert "TOUCHED.md" in out
    assert "APPLIED.md" not in out
    assert "1 item adrift" in out


def test_render_refit_reports_change_tickets(tmp_path, monkeypatch):
    quarterdeck = _load_quarterdeck()
    target = tmp_path / "targets" / "Alpha"
    blueprint = target / "blueprint"
    changes = blueprint / "changes"
    changes.mkdir(parents=True)
    (blueprint / "APPLIED.md").write_text("applied content\n", encoding="utf-8")
    (changes / "TICKET-001-Fix.md").write_text("Amends: APPLIED.md\n", encoding="utf-8")
    import hashlib

    applied_hash = hashlib.sha256(b"applied content\n").hexdigest()
    (target / "MANIFEST.md").write_text(
        f"applied_specs: |\n  APPLIED.md sha256={applied_hash} commit=-\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(quarterdeck, "PROJECT_ROOT", target)

    out = quarterdeck.render_refit({"id": "refit_status", "type": "refit"})

    assert "TICKET-001-Fix.md" in out
    assert "blueprint/changes/TICKET-001-Fix.md" in out
    assert "1 item adrift" in out
    assert "steady as she goes" not in out


def test_render_refit_all_applied_is_clear(tmp_path, monkeypatch):
    quarterdeck = _load_quarterdeck()
    target = tmp_path / "targets" / "Alpha"
    blueprint = target / "blueprint"
    blueprint.mkdir(parents=True)
    (blueprint / "APPLIED.md").write_text("applied content\n", encoding="utf-8")
    import hashlib

    applied_hash = hashlib.sha256(b"applied content\n").hexdigest()
    (target / "MANIFEST.md").write_text(
        f"applied_specs: |\n  APPLIED.md sha256={applied_hash} commit=-\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(quarterdeck, "PROJECT_ROOT", target)

    out = quarterdeck.render_refit({"id": "refit_status", "type": "refit"})

    assert "steady as she goes" in out
    assert "drydock refit" not in out


def test_render_refit_never_built_target_is_clear(tmp_path, monkeypatch):
    # A drafted-but-never-built target has an empty applied_specs registry and
    # many pending blueprints. Nothing has been applied, so nothing is adrift.
    quarterdeck = _load_quarterdeck()
    target = tmp_path / "targets" / "Alpha"
    blueprint = target / "blueprint"
    blueprint.mkdir(parents=True)
    for name in ("A.md", "B.md", "C.md"):
        (blueprint / name).write_text(f"{name} content\n", encoding="utf-8")
    (target / "MANIFEST.md").write_text(
        "# MANIFEST: Alpha\nstate: draft\napplied_specs: |\n\n## feature 1\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(quarterdeck, "PROJECT_ROOT", target)

    out = quarterdeck.render_refit({"id": "refit_status", "type": "refit"})

    assert "steady as she goes" in out
    assert "A.md" not in out
    assert "drydock refit" not in out


def test_render_step_files_badges_compact_and_duplicate(tmp_path):
    from drydock.build import StepRoots, assemble_step, group_duplicate_flags
    from drydock.build_plan import parse_build_plan

    quarterdeck = _load_quarterdeck()

    target = tmp_path / "target"
    blueprint = target / "blueprint"
    stack = tmp_path / "rigging" / "stack"
    rigging = tmp_path / "rigging"
    for d in (blueprint, stack, rigging):
        d.mkdir(parents=True, exist_ok=True)
    (target / "COMPASS.md").write_text("compass" * 10, encoding="utf-8")
    (blueprint / "FEATURE-A.md").write_text("feature-a" * 100, encoding="utf-8")
    (blueprint / "FEATURE-B.md").write_text("feature-b" * 100, encoding="utf-8")
    (blueprint / "FEATURE-B_compact.md").write_text("b-compact" * 10, encoding="utf-8")
    roots = StepRoots(
        target_dir=target, blueprint_dir=blueprint, stack_dir=stack, rigging_dir=rigging
    )
    manifest = tmp_path / "MANIFEST.md"
    manifest.write_text(
        """# MANIFEST: Demo
state: approved

## story 1: One
id: s1
implements: FEATURE-A.md
context: FEATURE-B.md
state: pending

## story 2: Two
id: s2
implements: FEATURE-A.md
context: FEATURE-B.md
state: pending
""",
        encoding="utf-8",
    )
    plan = parse_build_plan(manifest)
    steps = (
        assemble_step(plan.by_id()["s1"], roots),
        assemble_step(plan.by_id()["s2"], roots),
    )
    flags = group_duplicate_flags(steps)

    first = quarterdeck._render_step_files(steps[0], flags[0])
    second = quarterdeck._render_step_files(steps[1], flags[1])

    # context FEATURE-B substitutes its compact sibling in both steps
    assert "FEATURE-B_compact.md" in first
    assert "cmp-badge-compact" in first
    # first occurrence is not a duplicate
    assert "cmp-badge-dup" not in first
    # second step repeats every file — duplicate badges appear
    assert "cmp-badge-dup" in second

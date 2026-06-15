"""QuarterDeck — a YAML-driven viewer for LLM-assisted development.

The QuarterDeck is deliberately dumb. It owns no project state and makes no build
decisions. It reads one `console.yaml` — a sections list and a flat list of **items**
(things) — and renders each item by its `type`. A framework (and the user) append and
update the items; the QuarterDeck only navigates and renders them.

Each item carries navigation properties (`label`, `section`) and type properties
(`type` + type-specific fields). Sections are defined in the `sections:` block of
`console.yaml` (id / label / dot / collapsed / pinned); items reference a section id.

Five canonical sections: Drydock Core (pinned) · Build Plan · Action Items ·
Project Pages · Archive (collapsed by default).

Page types (one Python renderer each, in TYPES):
  - markdown      render a markdown file as HTML
  - document      render md/html/pdf variants as tabs (path_md / path_html / path_pdf)
  - jsonl         render append-only JSON records as a read-only table
  - kanban        render a tickets JSON file as a board (read-only work tracking)
  - questionnaire render a questionnaire JSON as a form; persist answers
  - link          a hyperlink (external URL or a local file served raw)
  - command_status derive acceptance readiness and consistency from configured Core Docs
  - plan_decision review and decide an authoritative Drydock BUILD_PLAN.md

console.yaml also accepts:
  sources:   list of {glob, section, type, ...} rules that auto-discover files as items.
             Items in the explicit `items:` list (matched by ID or by path) take priority.
  overrides: list of {match: <path-relative-to-project-root>, <field overrides>} applied
             to source-generated items before they are added.

Archive/unarchive (POST /api/item/{id}/archive|unarchive): SQLite-backed toggle that
moves items to the Archive section. Items in pinned sections cannot be archived.

Tickets (the kanban's work items) live in a separate JSON file the framework writes;
the QuarterDeck renders them read-only. Contract: QuarterDeck/README.md
"""

from __future__ import annotations

import html
import json
import os
import re
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import markdown
import yaml
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from pydantic import BaseModel

# The console runtime may live in the package while its state lives in a Target
# tree. ``QUARTERDECK_DIR`` overrides the state directory (holding console.yaml,
# data/, and item paths); ``QUARTERDECK_PROJECT_ROOT`` overrides the project root
# used by source globbing. Both default to a runtime that sits inside the Target.
_RUNTIME_DIR = Path(__file__).resolve().parent
BASE_DIR = (
    Path(os.environ["QUARTERDECK_DIR"]).resolve()
    if os.environ.get("QUARTERDECK_DIR")
    else _RUNTIME_DIR
)
PROJECT_ROOT = (
    Path(os.environ["QUARTERDECK_PROJECT_ROOT"]).resolve()
    if os.environ.get("QUARTERDECK_PROJECT_ROOT")
    else BASE_DIR.parent  # the project that contains QuarterDeck/
)
CONFIG_PATH = BASE_DIR / "console.yaml"

_DONE_STATES = {"done", "answered", "complete", "verified"}
_DEFAULT_DOT = "#94a3b8"

# Kanban status columns. A ticket's `status` selects its column (default backlog).
STATUSES = [
    ("backlog", "Backlog"),
    ("in_progress", "In Progress"),
    ("review", "Review"),
    ("done", "Done"),
]
_STATUS_LABEL = dict(STATUSES)


class ConsoleConfigError(RuntimeError):
    """Raised when the Console configuration is missing or invalid."""


def load_config() -> tuple[dict[str, Any], str | None]:
    if not CONFIG_PATH.exists():
        return {}, (
            f"QuarterDeck config not found at {CONFIG_PATH}. "
            "Create QuarterDeck/console.yaml for this project before starting the QuarterDeck."
        )
    try:
        config = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8")) or {}
        _expand_sources(config)
        return config, None
    except yaml.YAMLError as exc:
        return {}, f"QuarterDeck config at {CONFIG_PATH} is invalid YAML: {exc}"


def _expand_sources(config: dict[str, Any]) -> None:
    """Expand sources: rules into items. Explicit items (by ID or by path) take priority."""
    sources = config.get("sources", [])
    if not sources:
        return
    explicit_items = config.get("items", [])
    explicit_ids: set[str] = {item["id"] for item in explicit_items}

    # Paths already covered by explicit items — prevent generating duplicate content.
    explicit_paths: set[str] = set()
    for item in explicit_items:
        for key in ("path", "path_md", "path_html", "path_pdf", "href"):
            val = item.get(key)
            if val:
                try:
                    explicit_paths.add(str((BASE_DIR / val).resolve()))
                except Exception:
                    pass

    override_map: dict[str, dict[str, Any]] = {}
    for ov in config.get("overrides", []):
        match = ov.get("match")
        if match:
            override_map[match] = {k: v for k, v in ov.items() if k != "match"}

    generated: list[dict[str, Any]] = []
    seen_ids: set[str] = set(explicit_ids)

    for rule in sources:
        glob_pattern = rule.get("glob", "")
        rule_defaults = {k: v for k, v in rule.items() if k != "glob"}
        rule_defaults.setdefault("section", "project_pages")
        rule_defaults.setdefault("type", "markdown")

        for path in sorted(PROJECT_ROOT.glob(glob_pattern)):
            if not path.is_file():
                continue
            if str(path.resolve()) in explicit_paths:
                continue
            rel_from_root = path.relative_to(PROJECT_ROOT)
            rel_from_base = f"../{rel_from_root}"
            stem = path.stem
            auto_id = re.sub(r"[^a-z0-9]+", "_", stem.lower()).strip("_")
            auto_label = stem.replace("_", " ").replace("-", " ").title()

            item: dict[str, Any] = {
                **rule_defaults,
                "id": auto_id,
                "label": auto_label,
                "path": rel_from_base,
            }
            ov = override_map.get(str(rel_from_root), {})
            if ov:
                item.update(ov)
            if item.get("type") == "document" and "path" in item:
                item["path_md"] = item.pop("path")

            final_id = item["id"]
            if final_id in seen_ids:
                continue
            seen_ids.add(final_id)
            generated.append(item)

    config.setdefault("items", []).extend(generated)


CONFIG, CONFIG_ERROR = load_config()
app = FastAPI(title=CONFIG.get("console", {}).get("name", "Project Console"))


# ── Config access ──────────────────────────────────────────────────────────────


def require_config() -> dict[str, Any]:
    if CONFIG_ERROR:
        raise ConsoleConfigError(CONFIG_ERROR)
    return CONFIG


def config_error_payload() -> dict[str, Any]:
    return {
        "detail": CONFIG_ERROR,
        "config_path": str(CONFIG_PATH),
        "next_step": "Add QuarterDeck/console.yaml, then restart the QuarterDeck.",
    }


def items() -> list[dict[str, Any]]:
    return require_config().get("items", [])


# Item types that have no backing file — always visible regardless of file existence.
_UNTRACKED_TYPES = frozenset({"link"})


def _item_file_exists(item: dict[str, Any]) -> bool:
    """Return False when the item has a backing file path that does not exist."""
    item_type = item.get("type", "")
    if item_type in _UNTRACKED_TYPES:
        return True
    if item_type == "plan_decision":
        path_val = item.get("plan_path")
        if not path_val:
            return True
        try:
            return (BASE_DIR / path_val).resolve().exists()
        except Exception:
            return True
    if item_type == "document":
        for key in ("path_html", "path_md", "path_pdf"):
            path_val = item.get(key)
            if path_val:
                try:
                    if (BASE_DIR / path_val).resolve().exists():
                        return True
                except Exception:
                    pass
        return not any(item.get(k) for k in ("path_html", "path_md", "path_pdf"))
    path_val = item.get("path")
    if not path_val:
        return True
    try:
        return (BASE_DIR / path_val).resolve().exists()
    except Exception:
        return True


def find_item(item_id: str) -> dict[str, Any]:
    for item in items():
        if item.get("id") == item_id:
            return item
    raise HTTPException(status_code=404, detail=f"No item {item_id!r}")


def nav_model() -> list[dict[str, Any]]:
    """Group items into sidebar sections, config order first.

    Items whose backing file does not exist are hidden from the sidebar; they
    reappear automatically once the file is created — no console.yaml rewrite needed.

    Archived items (from non-pinned sections) are transparently moved to the
    archive section; pinned-section items are immune to archiving.
    """
    archived_ids = _archived_item_ids()
    config_sections = CONFIG.get("sections", [])
    config_map = {s["id"]: s for s in config_sections}
    pinned_sids = {s["id"] for s in config_sections if s.get("pinned")}

    by_section: dict[str, list[dict[str, Any]]] = {}
    order: list[str] = []
    for item in items():
        if not _item_file_exists(item):
            continue
        original_sid = item.get("section", "project_pages")
        if item.get("id") in archived_ids and original_sid not in pinned_sids:
            sid = "archive"
        else:
            sid = original_sid
        if sid not in by_section:
            by_section[sid] = []
            order.append(sid)
        by_section[sid].append(item)

    config_ids = [s["id"] for s in config_sections]
    ordered_ids = [sid for sid in config_ids if sid in by_section]
    ordered_ids += [sid for sid in order if sid not in config_ids]

    sections = []
    for sid in ordered_ids:
        docs = sorted(by_section[sid], key=lambda d: d.get("order", 0))
        sec_cfg = config_map.get(sid, {})
        sections.append(
            {
                "id": sid,
                "label": sec_cfg.get("label", sid.replace("_", " ").title()),
                "dot": sec_cfg.get("dot", _DEFAULT_DOT),
                "collapsed": sec_cfg.get("collapsed", False),
                "pinned": sec_cfg.get("pinned", False),
                "items": docs,
            }
        )
    return sections


# ── File resolution ─────────────────────────────────────────────────────────────


def resolve_path(path_value: str) -> Path:
    """Resolve a config path relative to Console/, confined to the project root
    (the directory containing Console/) so siblings like ../evidence are reachable."""
    path = (BASE_DIR / path_value).resolve()
    if PROJECT_ROOT not in path.parents and path != PROJECT_ROOT:
        raise HTTPException(status_code=400, detail=f"Path escapes the project: {path_value}")
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"Missing file: {path_value}")
    return path


def resolve_write_path(path_value: str) -> Path:
    """Resolve for write: confined within the project root; creates parent dirs; file need not exist."""
    path = (BASE_DIR / path_value).resolve()
    if PROJECT_ROOT not in path.parents and path != PROJECT_ROOT:
        raise HTTPException(status_code=400, detail=f"Path escapes the project: {path_value}")
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _md(text: str) -> str:
    return markdown.markdown(text, extensions=["tables", "fenced_code", "sane_lists"])


def _inline_md(text: str) -> str:
    rendered = _md(text).strip()
    if rendered.startswith("<p>") and rendered.endswith("</p>"):
        rendered = rendered[3:-4]
    return rendered


def _strip_frontmatter(text: str) -> str:
    """Remove YAML frontmatter (--- block) if present at the top of the text."""
    if text.startswith("---\n") or text.startswith("---\r\n"):
        end = text.find("\n---", 4)
        if end != -1:
            return text[end + 4 :].lstrip("\n")
    return text


def _split_h2_sections(text: str) -> list[tuple[str, str]]:
    """Split markdown at ## headings. Returns (tab_label, content) pairs."""
    parts = re.split(r"^## (.+)$", text, flags=re.MULTILINE)
    result: list[tuple[str, str]] = []
    intro = parts[0].strip()
    if intro:
        body = re.sub(r"^# [^\n]*\n", "", intro, count=1).strip()
        if body:
            result.append(("Overview", body))
    for i in range(1, len(parts) - 1, 2):
        label = parts[i].strip()
        content = parts[i + 1].strip() if i + 1 < len(parts) else ""
        if label or content:
            result.append((label, content))
    return result


def _render_markdown_tabbed(item: dict[str, Any], text: str) -> str:
    """Render markdown with ## sections as switchable tabs."""
    sections = _split_h2_sections(text)
    if not sections:
        return _md(text)
    tab_btns = "".join(
        f"<button class='md-tab-btn{' active' if i == 0 else ''}' onclick='mdTab(this,{i})'>"
        f"{html.escape(t)}</button>"
        for i, (t, _) in enumerate(sections)
    )
    tab_panes = "".join(
        f"<div class='md-tab-pane{' active' if i == 0 else ''}' data-tab='{i}'>{_md(c)}</div>"
        for i, (_, c) in enumerate(sections)
    )
    return (
        f"<h1>{html.escape(item.get('label', ''))}</h1>"
        f"<div class='md-tabs'><div class='md-tab-bar'>{tab_btns}</div>"
        f"<div class='md-tab-body'>{tab_panes}</div></div>"
    )


# ── Renderers (one per type; each takes the item dict) ──────────────────────────


def render_markdown_item(item: dict[str, Any]) -> str:
    text = _strip_frontmatter(resolve_path(item["path"]).read_text(encoding="utf-8"))
    if item.get("tabs"):
        return _render_markdown_tabbed(item, text)
    return _md(text)


def render_editable_markdown(item: dict[str, Any]) -> str:
    """Markdown that the human can edit in place. Renders the doc plus an Edit
    toggle; Save POSTs the raw source back to the file (creates the file if absent)."""
    item_id = html.escape(item["id"])
    label = html.escape(item.get("label", ""))
    filename = html.escape(Path(item["path"]).name)
    try:
        raw = resolve_path(item["path"]).read_text(encoding="utf-8")
        rendered = _md(raw)
    except HTTPException:
        raw = ""
        rendered = "<p><em>File not yet created — edit and save to create it.</em></p>"
    return (
        f"<div class='editable' data-item='{item_id}'>"
        f"<h1>{label}</h1>"
        f"<div class='edit-toolbar'>"
        f"<button class='edit-btn' onclick=\"editDoc('{item_id}')\">Edit</button>"
        f"<span class='edit-filename'>Filename: {filename}</span>"
        f"</div>"
        f"<hr class='edit-divider'>"
        f"<div class='doc-view'>{rendered}</div>"
        f"<div class='doc-edit' style='display:none'>"
        f"<textarea class='doc-source' spellcheck='false'>{html.escape(raw)}</textarea>"
        f"<div class='doc-edit-actions'>"
        f"<button class='save-btn' onclick=\"saveDoc('{item_id}')\">Save</button>"
        f"<button class='cancel-btn' onclick=\"cancelDoc('{item_id}')\">Cancel</button></div>"
        f"</div></div>"
    )


def render_link_item(item: dict[str, Any]) -> str:
    href = item.get("href", "")
    target = href if re.match(r"^https?://", href) else f"/raw/{item['id']}"
    return (
        f"<h1>{html.escape(item.get('label', 'Link'))}</h1>"
        f"<p><a href='{html.escape(target)}' target='_blank' rel='noopener'>{html.escape(href)}</a></p>"
    )


def render_document_item(item: dict[str, Any]) -> str:
    """Render a document with md/html/pdf variants as a tabbed view."""
    label = item.get("label", "Document")
    iid = item["id"]
    tabs: list[tuple[str, str]] = []

    if item.get("path_md"):
        try:
            text = _strip_frontmatter(resolve_path(item["path_md"]).read_text(encoding="utf-8"))
            tabs.append(("Read", _md(text)))
        except HTTPException:
            pass

    if item.get("path_html"):
        try:
            resolve_path(item["path_html"])
            url = f"/raw/{iid}?variant=html"
            tabs.append(
                (
                    "View HTML",
                    f"<iframe class='doc-frame' src='{url}' title='{html.escape(label)}'></iframe>",
                )
            )
        except HTTPException:
            pass

    if item.get("path_pdf"):
        try:
            resolve_path(item["path_pdf"])
            url = f"/raw/{iid}?variant=pdf"
            tabs.append(
                (
                    "PDF",
                    f"<p><a href='{url}' target='_blank' rel='noopener' class='pdf-open-btn'>Open PDF ↗</a></p>",
                )
            )
        except HTTPException:
            pass

    title = f"<h1>{html.escape(label)}</h1>"
    if not tabs:
        return title + "<p class='subtle'>No files found for this document.</p>"
    if len(tabs) == 1:
        return title + tabs[0][1]
    tab_btns = "".join(
        f"<button class='md-tab-btn{' active' if i == 0 else ''}' onclick='mdTab(this,{i})'>"
        f"{html.escape(t)}</button>"
        for i, (t, _) in enumerate(tabs)
    )
    tab_panes = "".join(
        f"<div class='md-tab-pane{' active' if i == 0 else ''}' data-tab='{i}'>{c}</div>"
        for i, (_, c) in enumerate(tabs)
    )
    return (
        title + f"<div class='md-tabs'><div class='md-tab-bar'>{tab_btns}</div>"
        f"<div class='md-tab-body'>{tab_panes}</div></div>"
    )


def render_plan_decision(item: dict[str, Any]) -> str:
    from drydock.build_plan import parse_build_plan

    plan = parse_build_plan(Path(item["plan_path"]))
    return (
        f"<h1>{html.escape(item.get('label', 'Planning Session'))}</h1>"
        f"<p>Plan state: <strong>{html.escape(plan.state)}</strong></p>"
        f"<p>{len(plan.blocks)} proposed work and acceptance objects.</p>"
        "<div class='decision'><div class='decision-bar'>"
        f"<button class='d-btn d-approve' onclick=\"submitPlanDecision('{html.escape(item['id'])}','approve')\">Approve plan</button>"
        "</div></div>"
    )


COMMAND_STATES = ("DONE", "IMPLEMENTED", "STUBBED", "NOT STARTED")


def _split_markdown_row(line: str) -> list[str]:
    """Split a Markdown table row without treating escaped pipes as separators."""
    text = line.strip()
    if text.startswith("|"):
        text = text[1:]
    if text.endswith("|"):
        text = text[:-1]
    return [cell.strip().replace(r"\|", "|") for cell in re.split(r"(?<!\\)\|", text)]


def _markdown_tables(text: str) -> list[tuple[str, list[str], list[list[str]]]]:
    """Return heading, headers, and rows for structurally valid Markdown tables."""
    lines = text.splitlines()
    heading = ""
    tables: list[tuple[str, list[str], list[list[str]]]] = []
    index = 0
    while index < len(lines):
        line = lines[index]
        heading_match = re.match(r"^#{1,6}\s+(.+?)\s*$", line)
        if heading_match:
            heading = heading_match.group(1).strip()
            index += 1
            continue
        if index + 1 >= len(lines) or "|" not in line:
            index += 1
            continue
        headers = _split_markdown_row(line)
        separator = _split_markdown_row(lines[index + 1])
        if len(headers) != len(separator) or not all(
            re.fullmatch(r":?-{3,}:?", cell) for cell in separator
        ):
            index += 1
            continue
        rows: list[list[str]] = []
        index += 2
        while index < len(lines) and "|" in lines[index]:
            row = _split_markdown_row(lines[index])
            if len(row) != len(headers):
                break
            rows.append(row)
            index += 1
        tables.append((heading, headers, rows))
    return tables


def _core_markdown_sources() -> list[tuple[dict[str, Any], str]]:
    """Read only configured Markdown Core Docs through QuarterDeck path resolution."""
    sources = []
    for core_item in items():
        if core_item.get("section") != "core":
            continue
        t = core_item.get("type")
        if t in {"markdown", "editable_markdown"}:
            sources.append((core_item, resolve_path(core_item["path"]).read_text(encoding="utf-8")))
        elif t == "document" and core_item.get("path_md"):
            try:
                sources.append(
                    (core_item, resolve_path(core_item["path_md"]).read_text(encoding="utf-8"))
                )
            except HTTPException:
                pass
    return sources


def _render_acceptance_table(rows: list[dict[str, str]]) -> str:
    rendered = []
    for row in rows:
        rendered.append(
            "<tr>"
            f"<td>{_inline_md(row['ID'])}</td>"
            f"<td>{_inline_md(row['Acceptance Criterion'])}</td>"
            f"<td>{_inline_md(row['Evidence'])}</td>"
            "</tr>"
        )
    return (
        "<table><thead><tr><th>ID</th><th>Acceptance Criterion</th>"
        f"<th>Evidence</th></tr></thead><tbody>{''.join(rendered)}</tbody></table>"
    )


def render_command_status(item: dict[str, Any]) -> str:
    """Derive acceptance readiness and structured consistency from configured Core Docs."""
    sources = _core_markdown_sources()
    candidates = []
    for source_item, text in sources:
        for heading, headers, rows in _markdown_tables(text):
            if heading == "Soundings" and headers == [
                "ID",
                "Acceptance Criterion",
                "State",
                "Evidence",
            ]:
                candidates.append((source_item, text, headers, rows))

    title = f"<h1>{html.escape(item.get('label', 'Acceptance Status'))}</h1>"
    if len(candidates) != 1:
        return (
            title
            + "<div class='item-error'>"
            + html.escape(
                f"Expected exactly one Core Doc Soundings table; found {len(candidates)}."
            )
            + "</div>"
        )

    source_item, _source_text, headers, raw_rows = candidates[0]
    rows = [dict(zip(headers, row, strict=True)) for row in raw_rows]
    findings: list[str] = []
    counts = {state: 0 for state in COMMAND_STATES}
    seen_ids: set[str] = set()
    for row in rows:
        criterion_id = row["ID"]
        state = row["State"]
        if criterion_id in seen_ids:
            findings.append(f"Duplicate acceptance ID: {criterion_id}")
        seen_ids.add(criterion_id)
        if state not in counts:
            findings.append(f"Unknown state {state!r}: {criterion_id}")
        else:
            counts[state] += 1
        if state == "DONE" and not row["Evidence"].strip():
            findings.append(f"DONE row has no evidence: {criterion_id}")

    cards = "".join(
        f"<td><strong>{html.escape(state)}</strong><br>{counts[state]}</td>"
        for state in COMMAND_STATES
    )
    output = (
        title
        + f"<p class='subtle'>Derived from Core Doc: {html.escape(source_item.get('label', source_item.get('id', 'unknown')))}</p>"
        + f"<table><tbody><tr><td><strong>Total criteria</strong><br>{len(rows)}</td>{cards}</tr></tbody></table>"
    )
    if findings:
        output += (
            "<div class='item-error'><strong>Consistency findings</strong><ul>"
            + "".join(f"<li>{html.escape(finding)}</li>" for finding in findings)
            + "</ul></div>"
        )
    else:
        output += "<p><strong>Consistency:</strong> no structured findings.</p>"

    for state in COMMAND_STATES:
        state_rows = [row for row in rows if row["State"] == state]
        output += f"<h2>{html.escape(state)} ({len(state_rows)})</h2>"
        output += (
            _render_acceptance_table(state_rows) if state_rows else "<p class='subtle'>None.</p>"
        )
    return output


def _jsonl_value(record: dict[str, Any], field: str) -> Any:
    value: Any = record
    for part in field.split("."):
        if not isinstance(value, dict):
            return None
        value = value.get(part)
    return value


def render_jsonl_item(item: dict[str, Any]) -> str:
    """Render a JSONL artifact as a read-only, configured table."""
    try:
        path = resolve_path(item["path"])
    except HTTPException as exc:
        if exc.status_code == 404:
            return (
                f"<h1>{html.escape(item.get('label', 'JSONL'))}</h1>"
                "<p class='subtle'>No records yet.</p>"
            )
        raise

    records: list[dict[str, Any]] = []
    errors: list[str] = []
    for line_number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        try:
            value = json.loads(raw)
            if not isinstance(value, dict):
                raise ValueError("record is not an object")
            records.append(value)
        except (json.JSONDecodeError, ValueError) as exc:
            errors.append(f"line {line_number}: {exc}")

    for field, expected in item.get("filters", {}).items():
        records = [record for record in records if _jsonl_value(record, field) == expected]
    sort_field = item.get("sort", "recorded_at")
    records.sort(
        key=lambda record: str(_jsonl_value(record, sort_field) or ""),
        reverse=item.get("sort_direction", "desc") == "desc",
    )
    fields = item.get("fields") or ["recorded_at", "event_type", "title", "summary"]
    date_fields = set(item.get("date_fields", []))
    badge_field = item.get("badge_field")
    badge_colors: dict[str, str] = item.get("badge_colors") or {}

    badge_hdr = "<th></th>" if badge_field else ""
    headings = badge_hdr + "".join(f"<th>{html.escape(str(f))}</th>" for f in fields)
    rows = []
    for record in records:
        cells = []
        if badge_field:
            bval = _jsonl_value(record, badge_field)
            bcolor = badge_colors.get(str(bval) if bval is not None else "", "#94a3b8")
            cells.append(
                f"<td><span class='j-badge' style='background:{html.escape(bcolor)}'>"
                f"{html.escape(str(bval or ''))}</span></td>"
            )
        for field in fields:
            value = _jsonl_value(record, field)
            if isinstance(value, dict | list):
                value = json.dumps(value, sort_keys=True)
            if field in date_fields and value is not None:
                value = str(value)[:10]
            cells.append(f"<td>{html.escape(str(value if value is not None else ''))}</td>")
        rows.append(f"<tr>{''.join(cells)}</tr>")

    output = (
        f"<h1>{html.escape(item.get('label', 'JSONL'))}</h1>"
        f"<p class='subtle'>{len(records)} record(s)</p>"
        f"<table><thead><tr>{headings}</tr></thead><tbody>{''.join(rows)}</tbody></table>"
    )
    if errors:
        output += (
            "<div class='item-error'>"
            + "<br>".join(html.escape(error) for error in errors)
            + "</div>"
        )
    return output


def render_questionnaire(item: dict[str, Any]) -> str:
    data = json.loads(resolve_path(item["path"]).read_text(encoding="utf-8"))
    rows = []
    for question in data.get("questions", []):
        qid = html.escape(question["id"])
        options = question.get("options", [])
        input_type = question.get("input", "text")
        saved = question.get("answer", "")
        saved_vals = saved.split(", ") if isinstance(saved, str) and saved else []

        if input_type in {"select", "multiselect"}:
            multiple = " multiple" if input_type == "multiselect" else ""
            opts = "".join(
                f"<option{' selected' if str(o) in saved_vals else ''}>{html.escape(str(o))}</option>"
                for o in options
            )
            control = f"<select name='{qid}'{multiple}>{opts}</select>"
        elif input_type == "textarea":
            control = f"<textarea name='{qid}' rows='4'>{html.escape(saved)}</textarea>"
        elif input_type == "number":
            val = f" value='{html.escape(saved)}'" if saved else ""
            control = f"<input name='{qid}' type='number'{val}>"
        elif input_type == "slider":
            val = f" value='{html.escape(saved)}'" if saved else ""
            control = (
                f"<input name='{qid}' type='range' "
                f"min='{question.get('min', 0)}' max='{question.get('max', 10)}'{val}>"
            )
        else:
            val = f" value='{html.escape(saved)}'" if saved else ""
            control = f"<input name='{qid}' type='text'{val}>"

        status = " ✓" if saved else ""
        rows.append(
            f"<section class='question'>"
            f"<h3>{html.escape(question.get('label', question['id']))}{status}</h3>"
            f"<p>{html.escape(question.get('prompt', ''))}</p>{control}</section>"
        )

    done = str(data.get("state", "open")) in _DONE_STATES
    prefix = "<span class='q-done-mark'>✓</span> " if done else ""
    return (
        f"<h1>{prefix}{html.escape(data.get('title', data['id']))}</h1>"
        f"<p class='subtle'>{html.escape(data.get('purpose', ''))}</p>"
        f"<form data-questionnaire='{html.escape(data['id'])}'>{''.join(rows)}"
        "<button type='submit'>Save Answers</button></form>"
    )


# ── Kanban (tickets-backed, read-only) ──────────────────────────────────────────


def load_tickets(item: dict[str, Any]) -> list[dict[str, Any]]:
    data = json.loads(resolve_path(item["path"]).read_text(encoding="utf-8"))
    return data.get("tickets", [])


def _ticket_badges(t: dict[str, Any]) -> str:
    out = []
    if t.get("priority"):
        out.append("<span class='badge badge-priority'>PRIORITY</span>")
    if t.get("urgency"):
        out.append("<span class='badge badge-urgent'>URGENT</span>")
    if t.get("blocked"):
        out.append(
            f"<span class='badge badge-blocked' title='{html.escape(t.get('blocked_reason', ''))}'>BLOCKED</span>"
        )
    return "".join(out)


def _ticket_card(item_id: str, t: dict[str, Any]) -> str:
    tid = html.escape(t["id"])
    parent = t.get("parent")
    chip = f"<span class='parent-chip'>↳ {html.escape(parent)}</span>" if parent else ""
    blocked_cls = " blocked" if t.get("blocked") else ""
    badges = _ticket_badges(t)
    ac_chip = _ac_progress(item_id, t)
    return (
        f"<div class='ticket-card{blocked_cls}' onclick=\"loadTicket('{html.escape(item_id)}','{tid}')\">"
        f"<strong>{html.escape(t['title'])}</strong>"
        f"<div class='ticket-meta'><code>{tid}</code>{chip}{ac_chip}</div>"
        f"{f'<div class=ticket-badges>{badges}</div>' if badges else ''}</div>"
    )


def render_kanban(item: dict[str, Any]) -> str:
    tickets = load_tickets(item)
    valid = [t for t in tickets if t.get("id") and t.get("title")]
    skipped = len(tickets) - len(valid)
    item_id = item["id"]

    cols = []
    for key, label in STATUSES:
        cards = "".join(
            _ticket_card(item_id, t) for t in valid if t.get("status", "backlog") == key
        )
        if not cards:
            cards = "<em class='kanban-empty'>empty</em>"
        cols.append(
            f"<section class='kanban-column'><h3>{html.escape(label)}</h3>{cards}</section>"
        )

    board = (
        f"<h1>{html.escape(item.get('label', 'Board'))}</h1>"
        f"<div class='kanban'>{''.join(cols)}</div>"
    )
    if skipped:
        board += f"<div class='item-error'>{skipped} ticket(s) skipped — each needs an id and title.</div>"
    board += "<div id='ticket-detail' class='ticket-detail'></div>"
    return board


def render_ticket_detail(item: dict[str, Any], ticket_id: str) -> str:
    tickets = load_tickets(item)
    t = next((x for x in tickets if x.get("id") == ticket_id), None)
    if t is None:
        return f"<div class='item-error'>No ticket {html.escape(ticket_id)}.</div>"
    item_id = html.escape(item["id"])
    parts = [
        f"<h2>{html.escape(t.get('title', ticket_id))} <code>{html.escape(ticket_id)}</code></h2>",
    ]
    status = t.get("status", "backlog")
    parts.append(
        f"<p class='subtle'>status: <strong>{html.escape(_STATUS_LABEL.get(status, status))}</strong>"
        f"&nbsp;&nbsp;{_ticket_badges(t)}</p>"
    )
    if t.get("blocked") and t.get("blocked_reason"):
        parts.append(
            f"<div class='blocked-note'><strong>Blocked:</strong> {html.escape(t['blocked_reason'])}</div>"
        )

    parent = t.get("parent")
    if parent:
        parts.append(
            f"<p>Parent: <button class='link-btn' onclick=\"loadTicket('{item_id}','{html.escape(parent)}')\">"
            f"{html.escape(parent)}</button></p>"
        )
    children = [x for x in tickets if x.get("parent") == ticket_id]
    if children:
        lis = "".join(
            f"<li><button class='link-btn' onclick=\"loadTicket('{item_id}','{html.escape(c['id'])}')\">"
            f"{html.escape(c['id'])} — {html.escape(c.get('title', ''))}</button></li>"
            for c in children
        )
        parts.append(f"<div><strong>Children</strong><ul class='link-list'>{lis}</ul></div>")

    links = t.get("links") or []
    if links:
        lis = ""
        for lid in links:
            it = next((i for i in items() if i.get("id") == lid), None)
            if it:
                lis += (
                    f"<li><button class='link-btn' onclick=\"loadDoc('{html.escape(lid)}')\">"
                    f"{html.escape(it.get('label', lid))}</button></li>"
                )
            else:
                lis += f"<li class='subtle'>{html.escape(lid)} (missing)</li>"
        parts.append(f"<div><strong>Related</strong><ul class='link-list'>{lis}</ul></div>")

    ac_html = _render_ac(item["id"], t)
    if ac_html:
        parts.append(ac_html)

    if t.get("body"):
        parts.append("<hr>" + _md(t["body"]))
    return f"<div class='ticket-detail-inner'>{''.join(parts)}</div>"


# ── Type registry ───────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class TypeDef:
    required: tuple[str, ...]
    render: Callable[[dict[str, Any]], str]


TYPES: dict[str, TypeDef] = {
    "markdown": TypeDef(("path",), render_markdown_item),
    "document": TypeDef((), render_document_item),
    "editable_markdown": TypeDef(("path",), render_editable_markdown),
    "jsonl": TypeDef(("path",), render_jsonl_item),
    "kanban": TypeDef(("path",), render_kanban),
    "questionnaire": TypeDef(("path",), render_questionnaire),
    "link": TypeDef(("href",), render_link_item),
    "command_status": TypeDef((), render_command_status),
    "plan_decision": TypeDef(("plan_path",), render_plan_decision),
}


def validate_item(item: dict[str, Any]) -> str | None:
    t = item.get("type")
    if t not in TYPES:
        return f"unknown type {t!r}"
    for field in TYPES[t].required:
        if not item.get(field):
            return f"{field!r} is required for type {t!r}"
    return None


def render_item(item: dict[str, Any]) -> str:
    err = validate_item(item)
    if err:
        return f"<div class='item-error'>{html.escape(err)}</div>"
    try:
        out = TYPES[item["type"]].render(item)
    except HTTPException as exc:
        return f"<div class='item-error'>{html.escape(str(exc.detail))}</div>"
    except (OSError, json.JSONDecodeError, KeyError) as exc:
        return f"<div class='item-error'>{html.escape(str(exc))}</div>"
    if item.get("review"):
        out += _decision_bar(item)
    return out


# ── State store (questionnaire answers) ─────────────────────────────────────────


def db_path() -> Path:
    path = (
        BASE_DIR / require_config()["console"].get("state_db", "data/console_state.sqlite")
    ).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def connect_db() -> sqlite3.Connection:
    conn = sqlite3.connect(db_path())
    conn.execute(
        """create table if not exists document_state (
             key text primary key,
             document_id text not null,
             state text not null,
             payload_json text not null,
             updated_at text not null
           )"""
    )
    conn.execute(
        """create table if not exists archived_items (
             item_id text primary key,
             archived_at text not null
           )"""
    )
    return conn


def _archived_item_ids() -> set[str]:
    """Return item IDs that have been moved to the archive via the UI."""
    try:
        with connect_db() as conn:
            rows = conn.execute("select item_id from archived_items").fetchall()
        return {row[0] for row in rows}
    except Exception:
        return set()


def read_state(key: str) -> dict[str, Any]:
    with connect_db() as conn:
        row = conn.execute(
            "select state, payload_json from document_state where key = ?", (key,)
        ).fetchone()
    if not row:
        return {"state": "open", "payload": {}}
    return {"state": row[0], "payload": json.loads(row[1])}


# ── Decision / review (an approve · revise · reject control on any item) ─────────

_DECISION_BANNER = {"approved": "Approved", "revise": "Needs revision", "rejected": "Rejected"}
_DECISION_BANNER_CLASS = {
    "approved": "db-approved",
    "revise": "db-revise",
    "rejected": "db-rejected",
}


def _decision_bar(item: dict[str, Any]) -> str:
    iid = html.escape(item["id"])
    st = read_state(f"decision.{item['id']}")
    cur, fb = st["state"], st["payload"].get("feedback", "")
    banner = ""
    if cur in _DECISION_BANNER:
        tail = f" — {html.escape(fb)}" if fb else ""
        banner = f"<div class='decision-banner {_DECISION_BANNER_CLASS[cur]}'>{_DECISION_BANNER[cur]}{tail}</div>"
    return (
        "<div class='decision'>" + banner + "<div class='decision-bar'>"
        f"<input class='decision-feedback' id='fb-{iid}' placeholder='Optional feedback…' value='{html.escape(fb)}'>"
        f"<button class='d-btn d-approve' onclick=\"submitDecision('{iid}','approved')\">Approve</button>"
        f"<button class='d-btn d-revise'  onclick=\"submitDecision('{iid}','revise')\">Revise</button>"
        f"<button class='d-btn d-reject'  onclick=\"submitDecision('{iid}','rejected')\">Reject</button>"
        "</div></div>"
    )


# ── Acceptance criteria (per-ticket checklist; verification state in SQLite) ─────

_AC_ICON = {"verified": "✓", "failed": "✗"}
_AC_CLASS = {"verified": "ac-verified", "failed": "ac-failed"}


def _ac_state(item_id: str, ticket_id: str) -> dict[str, str]:
    return read_state(f"ac.{item_id}.{ticket_id}")["payload"]


def _ac_progress(item_id: str, t: dict[str, Any]) -> str:
    acs = t.get("ac") or []
    if not acs:
        return ""
    st = _ac_state(item_id, t["id"])
    verified = sum(1 for i in range(len(acs)) if st.get(str(i)) == "verified")
    failed = any(st.get(str(i)) == "failed" for i in range(len(acs)))
    cls = "ac-chip-fail" if failed else ("ac-chip-ok" if verified == len(acs) else "")
    return f"<span class='ac-chip {cls}'>AC {verified}/{len(acs)}</span>"


def _render_ac(item_id: str, t: dict[str, Any]) -> str:
    acs = t.get("ac") or []
    if not acs:
        return ""
    st = _ac_state(item_id, t["id"])
    iid, tid = html.escape(item_id), html.escape(t["id"])
    rows = []
    for i, text in enumerate(acs):
        s = st.get(str(i), "open")
        icon = _AC_ICON.get(s, "○")
        rows.append(
            f"<li class='ac-row {_AC_CLASS.get(s, 'ac-open')}'>"
            f"<span class='ac-icon'>{icon}</span><span class='ac-text'>{html.escape(str(text))}</span>"
            f"<span class='ac-actions'>"
            f"<button onclick=\"setAc('{iid}','{tid}',{i},'verified')\">Verify</button>"
            f"<button onclick=\"setAc('{iid}','{tid}',{i},'failed')\">Fail</button>"
            f"<button onclick=\"setAc('{iid}','{tid}',{i},'open')\">Reset</button>"
            f"</span></li>"
        )
    return (
        f"<div><strong>Acceptance criteria</strong><ul class='ac-list'>{''.join(rows)}</ul></div>"
    )


def _writeback_questionnaire(key: str, state: str, payload: dict[str, Any]) -> None:
    """Write answers back into the questionnaire JSON so questions and answers
    live together as a plain input file the next build step can read."""
    if not key.startswith("questionnaire."):
        return
    q_id = key[len("questionnaire.") :]
    item = next(
        (i for i in items() if i.get("id") == q_id and i.get("type") == "questionnaire"), None
    )
    if not item or "path" not in item:
        return
    q_path = (BASE_DIR / item["path"]).resolve()
    if not q_path.exists():
        return
    try:
        data = json.loads(q_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return
    data["state"] = state
    data["answered_at"] = datetime.now(timezone.utc).isoformat()  # noqa: UP017 - Python 3.10 support
    for question in data.get("questions", []):
        if question["id"] in payload:
            ans = payload[question["id"]]
            question["answer"] = ", ".join(ans) if isinstance(ans, list) else ans
    q_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


class StateUpdate(BaseModel):
    document_id: str
    state: str
    payload: dict[str, Any] = {}


class SourceUpdate(BaseModel):
    content: str


class PlanDecision(BaseModel):
    decision: str


# ── API ─────────────────────────────────────────────────────────────────────────


@app.get("/api/config")
def api_config() -> dict[str, Any]:
    return require_config()


@app.get("/api/items")
def api_items() -> list[dict[str, Any]]:
    return items()


@app.get("/api/document/{item_id}")
def api_document(item_id: str) -> dict[str, Any]:
    item = find_item(item_id)
    return {"item": item, "type": item.get("type"), "html": render_item(item)}


@app.get("/api/ticket/{item_id}/{ticket_id}")
def api_ticket(item_id: str, ticket_id: str) -> dict[str, Any]:
    item = find_item(item_id)
    if item.get("type") != "kanban":
        raise HTTPException(status_code=404, detail=f"Item {item_id!r} is not a kanban")
    try:
        rendered = render_ticket_detail(item, ticket_id)
    except HTTPException as exc:
        rendered = f"<div class='item-error'>{html.escape(str(exc.detail))}</div>"
    return {"item_id": item_id, "ticket_id": ticket_id, "html": rendered}


@app.post("/api/document/{item_id}/source")
def api_set_source(item_id: str, update: SourceUpdate) -> dict[str, Any]:
    item = find_item(item_id)
    if item.get("type") != "editable_markdown":
        raise HTTPException(status_code=400, detail=f"Item {item_id!r} is not editable")
    path = resolve_write_path(item["path"])
    path.write_text(update.content, encoding="utf-8")
    return {"ok": True, "item_id": item_id}


@app.post("/api/plan/{item_id}/decision")
def api_plan_decision(item_id: str, update: PlanDecision) -> dict[str, Any]:
    from drydock.build_plan import set_plan_state

    item = find_item(item_id)
    if item.get("type") != "plan_decision":
        raise HTTPException(status_code=400, detail=f"Item {item_id!r} is not a plan decision")
    if update.decision != "approve":
        raise HTTPException(status_code=400, detail="The Planning Session supports plan approval.")
    plan = set_plan_state(
        Path(item["plan_path"]),
        "approved",
        decision=update.decision,
    )
    return {"ok": True, "decision": update.decision, "state": plan.state}


@app.get("/raw/{item_id}")
def raw_document(item_id: str, variant: str | None = Query(None)):
    item = find_item(item_id)
    t = item.get("type")
    if t == "document":
        if variant == "html":
            path_value = item.get("path_html")
        elif variant == "pdf":
            path_value = item.get("path_pdf")
        else:
            path_value = item.get("path_md")
    elif t == "link":
        path_value = item.get("href")
    else:
        path_value = item.get("path")
    if not path_value:
        raise HTTPException(status_code=404, detail="Item has no file path")
    return FileResponse(resolve_path(path_value))


@app.post("/api/item/{item_id}/archive")
def api_archive_item(item_id: str) -> dict[str, Any]:
    item = find_item(item_id)
    config_sections = CONFIG.get("sections", [])
    pinned_sids = {s["id"] for s in config_sections if s.get("pinned")}
    if item.get("section") in pinned_sids:
        raise HTTPException(status_code=400, detail="Items in pinned sections cannot be archived.")
    with connect_db() as conn:
        conn.execute(
            "insert or ignore into archived_items (item_id, archived_at) values (?, ?)",
            (item_id, datetime.now(timezone.utc).isoformat()),  # noqa: UP017
        )
    return {"ok": True, "item_id": item_id}


@app.post("/api/item/{item_id}/unarchive")
def api_unarchive_item(item_id: str) -> dict[str, Any]:
    find_item(item_id)
    with connect_db() as conn:
        conn.execute("delete from archived_items where item_id = ?", (item_id,))
    return {"ok": True, "item_id": item_id}


@app.get("/api/state/{key}")
def api_get_state(key: str) -> dict[str, Any]:
    with connect_db() as conn:
        row = conn.execute(
            "select key, document_id, state, payload_json, updated_at from document_state where key = ?",
            (key,),
        ).fetchone()
    if not row:
        return {"key": key, "state": "open", "payload": {}, "updated_at": None}
    return {
        "key": row[0],
        "document_id": row[1],
        "state": row[2],
        "payload": json.loads(row[3]),
        "updated_at": row[4],
    }


@app.post("/api/state/{key}")
def api_set_state(key: str, update: StateUpdate) -> dict[str, Any]:
    now = datetime.now(timezone.utc).isoformat()  # noqa: UP017 - Python 3.10 support
    with connect_db() as conn:
        conn.execute(
            """insert into document_state (key, document_id, state, payload_json, updated_at)
               values (?, ?, ?, ?, ?)
               on conflict(key) do update set
                 document_id = excluded.document_id,
                 state = excluded.state,
                 payload_json = excluded.payload_json,
                 updated_at = excluded.updated_at""",
            (
                key,
                update.document_id,
                update.state,
                json.dumps(update.payload, sort_keys=True),
                now,
            ),
        )
    _writeback_questionnaire(key, update.state, update.payload)
    return api_get_state(key)


@app.get("/health")
def health() -> dict[str, str]:
    require_config()
    return {"status": "ok"}


# ── Nav item status ──────────────────────────────────────────────────────────────

_NAV_STATUS_HTML: dict[str, str] = {
    "missing": "<span class='nav-st ns-miss'>✗</span>",
    "pending": "<span class='nav-st ns-pend'>○</span>",
    "done": "<span class='nav-st ns-done'>✓</span>",
}


def item_nav_status(item: dict[str, Any]) -> str:
    """Quick status for nav icon: 'ok', 'missing', 'pending', or 'done'."""
    t = item.get("type")
    if t == "command_status":
        return "ok"
    if t == "document":
        for key in ("path_md", "path_html", "path_pdf"):
            p = item.get(key)
            if p and (BASE_DIR / p).resolve().exists():
                return "ok"
        return "missing"
    path = item.get("path")
    href = item.get("href")
    if path:
        if not (BASE_DIR / path).resolve().exists():
            return "missing"
    elif href and not re.match(r"^https?://", href):
        if not (BASE_DIR / href).resolve().exists():
            return "missing"
    if t == "questionnaire" and path:
        try:
            st = read_state(f"questionnaire.{item['id']}")
            return "done" if st.get("state", "open") in _DONE_STATES else "pending"
        except Exception:
            return "pending"
    return "ok"


# ── UI ───────────────────────────────────────────────────────────────────────────

_STYLE = """
  body { margin:0; font-family:'Segoe UI',Arial,sans-serif; color:#1b2430; background:#f6f7f9; }
  header { padding:12px 22px; background:#111827; color:#fff; display:flex; align-items:baseline; gap:14px; }
  header strong { font-size:15px; } header .sub { font-size:12px; opacity:.65; }
  main { display:grid; grid-template-columns:220px 1fr; min-height:calc(100vh - 46px); }
  nav { padding:14px 8px; border-right:1px solid #d7dde5; background:#fff; }
  .nav-section { margin-bottom:16px; }
  .section-head { display:flex; align-items:center; gap:8px; font-size:11px; font-weight:700;
                  text-transform:uppercase; letter-spacing:.06em; color:#475569; padding:0 8px 5px;
                  border-bottom:1px solid #eef2f7; margin-bottom:5px; cursor:pointer; user-select:none; }
  .section-head .dot { width:8px; height:8px; border-radius:50%; flex:none; }
  .section-head .collapse-arrow { margin-left:auto; font-size:9px; color:#94a3b8; }
  .nav-section.collapsed .collapse-arrow::after { content:"▶"; }
  .nav-section:not(.collapsed) .collapse-arrow::after { content:"▼"; }
  .doc-btn { width:100%; margin:0 0 3px; padding:7px 10px 7px 24px; border:1px solid transparent;
             background:#fff; text-align:left; cursor:pointer; font-size:13px; color:#1b2430; border-radius:3px; }
  .doc-btn:hover { background:#eef2f7; }
  .doc-btn.active { background:#111827; color:#fff; }
  .nav-section[data-sec="archive"] .doc-btn { color:#94a3b8; }
  .nav-section[data-sec="archive"] .doc-btn.active { color:#fff; }
  .nav-section.collapsed .doc-btn, .nav-section.collapsed .section-empty { display:none; }
  .section-empty { padding:4px 24px; font-size:12px; color:#cbd5e1; }
  article { padding:24px 32px; max-width:1100px; overflow-x:auto; }
  article h1 { line-height:1.2; margin-top:0; }
  .subtle { color:#64748b; font-size:13px; }
  .state-done { font-size:12px; color:#166534; }
  .item-error { background:#fef2f2; border:1px solid #fecaca; color:#991b1b; padding:10px 12px;
                border-radius:4px; margin:12px 0; font-size:13px; }
  code { background:#eef2f7; padding:1px 4px; border-radius:3px; font-size:.9em; }
  pre { background:#eef2f7; padding:12px; overflow-x:auto; border-radius:4px; }
  table { border-collapse:collapse; width:100%; } th,td { border-bottom:1px solid #d7dde5; padding:8px; text-align:left; }
  th { background:#f8fafc; font-weight:600; }
  .question { background:#fff; border:1px solid #d7dde5; padding:12px; margin:12px 0; border-radius:4px; }
  input[type=text],input[type=number],select,textarea { width:100%; max-width:620px; padding:8px;
    border:1px solid #cbd5e1; border-radius:3px; box-sizing:border-box; }
  form > button { padding:10px 14px; background:#111827; color:#fff; border:none; cursor:pointer;
    border-radius:3px; margin-top:10px; }
  .kanban { display:grid; grid-template-columns:repeat(auto-fit,minmax(190px,1fr)); gap:10px; margin:14px 0; align-items:start; }
  .kanban-column { background:#fff; border:1px solid #d7dde5; padding:10px; min-height:80px; border-radius:4px; }
  .kanban-column h3 { font-size:12px; text-transform:uppercase; letter-spacing:.05em; color:#64748b; margin:0 0 8px; }
  .kanban-empty { font-size:11px; color:#94a3b8; }
  .ticket-card { border:1px solid #d7dde5; background:#f8fafc; padding:8px; margin:6px 0; border-radius:3px; cursor:pointer; }
  .ticket-card:hover { background:#eef2f7; border-color:#94a3b8; }
  .ticket-card.blocked { border-left:3px solid #dc2626; }
  .ticket-card strong { display:block; font-size:13px; }
  .ticket-meta { font-size:11px; color:#64748b; margin-top:3px; display:flex; gap:6px; align-items:center; }
  .parent-chip { color:#7c3aed; font-weight:600; }
  .ticket-badges { margin-top:6px; display:flex; gap:4px; flex-wrap:wrap; }
  .badge { font-size:9px; font-weight:700; letter-spacing:.04em; padding:1px 6px; border-radius:10px; }
  .badge-priority { background:#fef3c7; color:#92400e; }
  .badge-urgent   { background:#ffedd5; color:#9a3412; }
  .badge-blocked  { background:#fee2e2; color:#991b1b; }
  .ticket-detail:empty { display:none; }
  .ticket-detail-inner { border-top:2px solid #d7dde5; margin-top:18px; padding-top:14px; }
  .ticket-detail-inner h2 { margin:0 0 8px; font-size:17px; }
  .blocked-note { background:#fef2f2; border:1px solid #fecaca; color:#991b1b; padding:8px 10px;
                  border-radius:4px; margin:8px 0; font-size:13px; }
  .link-list { margin:4px 0 0; padding-left:18px; }
  .link-btn { background:none; border:none; color:#2563eb; cursor:pointer; padding:0; font-size:13px; text-decoration:underline; }
  .edit-toolbar { display:flex; align-items:center; gap:16px; margin-bottom:6px; }
  .edit-filename { font-size:13px; color:#64748b; }
  .edit-divider { border:none; border-top:1px solid #d7dde5; margin:0 0 14px; }
  .edit-btn, .save-btn, .cancel-btn { padding:6px 12px; border-radius:3px; cursor:pointer; font-size:13px; border:1px solid #cbd5e1; }
  .edit-btn { background:#fff; color:#111827; }
  .edit-btn:hover { background:#eef2f7; }
  .save-btn { background:#111827; color:#fff; border-color:#111827; }
  .cancel-btn { background:#fff; color:#475569; }
  .doc-source { width:100%; min-height:60vh; padding:12px; border:1px solid #cbd5e1; border-radius:4px;
                box-sizing:border-box; font-family:ui-monospace,'Cascadia Code',Consolas,monospace; font-size:13px; line-height:1.5; }
  .doc-edit-actions { display:flex; gap:8px; margin-top:10px; }
  .decision { margin-top:22px; border-top:2px solid #e2e8f0; padding-top:14px; }
  .decision-bar { display:flex; gap:8px; align-items:center; flex-wrap:wrap; }
  .decision-feedback { flex:1; min-width:180px; padding:8px; border:1px solid #cbd5e1; border-radius:3px; }
  .d-btn { padding:8px 16px; border:none; border-radius:3px; cursor:pointer; font-weight:600; color:#fff; }
  .d-btn:hover { opacity:.9; }
  .d-approve { background:#16a34a; } .d-revise { background:#d97706; } .d-reject { background:#dc2626; }
  .decision-banner { padding:8px 12px; border-radius:4px; margin-bottom:10px; font-weight:600; font-size:13px; }
  .db-approved { background:#dcfce7; color:#166534; }
  .db-revise   { background:#fef3c7; color:#92400e; }
  .db-rejected { background:#fee2e2; color:#991b1b; }
  .ac-list { list-style:none; padding:0; margin:6px 0; }
  .ac-row { display:flex; align-items:center; gap:8px; padding:6px 0; border-bottom:1px solid #f1f5f9; font-size:13px; }
  .ac-icon { font-weight:700; width:16px; text-align:center; }
  .ac-verified .ac-icon { color:#16a34a; } .ac-failed .ac-icon { color:#dc2626; } .ac-open .ac-icon { color:#94a3b8; }
  .ac-text { flex:1; } .ac-failed .ac-text { color:#991b1b; }
  .ac-actions button { font-size:11px; padding:3px 8px; margin-left:4px; border:1px solid #cbd5e1; background:#fff; border-radius:3px; cursor:pointer; }
  .ac-actions button:hover { background:#eef2f7; }
  .ac-chip { font-size:10px; font-weight:700; padding:1px 6px; border-radius:10px; background:#e2e8f0; color:#475569; }
  .ac-chip-ok { background:#dcfce7; color:#166534; } .ac-chip-fail { background:#fee2e2; color:#991b1b; }
  .nav-st { font-size:10px; font-weight:700; margin-right:3px; }
  .ns-miss { color:#dc2626; } .ns-pend { color:#d97706; } .ns-done { color:#16a34a; }
  .ext-arrow { font-size:10px; margin-left:3px; opacity:.55; }
  .q-done-mark { color:#16a34a; font-size:1.15em; font-weight:900; margin-right:2px; }
  .j-badge { display:inline-block; padding:1px 8px; border-radius:10px; font-size:11px; font-weight:600; color:#fff; }
  .md-tabs { margin-top:4px; }
  .md-tab-bar { display:flex; flex-wrap:wrap; gap:3px; border-bottom:2px solid #d7dde5; margin-bottom:14px; }
  .md-tab-btn { padding:5px 14px; border:1px solid #d7dde5; background:#f8fafc; border-radius:4px 4px 0 0;
                cursor:pointer; font-size:12px; color:#475569; border-bottom:none; }
  .md-tab-btn.active { background:#fff; color:#111827; font-weight:600; margin-bottom:-2px; border-bottom:2px solid #fff; }
  .md-tab-btn:hover:not(.active) { background:#eef2f7; }
  .md-tab-pane { display:none; } .md-tab-pane.active { display:block; }
  .doc-frame { width:100%; height:80vh; border:1px solid #d7dde5; border-radius:4px; }
  .pdf-open-btn { display:inline-block; padding:10px 20px; background:#111827; color:#fff;
                  text-decoration:none; border-radius:3px; font-size:14px; margin:12px 0; }
  .pdf-open-btn:hover { opacity:.9; }
  .nav-item-row { display:flex; align-items:center; gap:2px; margin:0 0 3px; }
  .nav-item-row .doc-btn { flex:1; margin:0; }
  .arc-btn { background:none; border:none; cursor:pointer; font-size:11px; color:#94a3b8;
             padding:2px 4px; opacity:.55; flex:none; border-radius:3px; }
  .arc-btn:hover { opacity:1; color:#475569; background:#eef2f7; }
"""


def _config_missing_page() -> str:
    return f"""<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>QuarterDeck</title>
<style>body{{font-family:'Segoe UI',Arial,sans-serif;background:#f6f7f9;color:#1b2430;}}
main{{max-width:760px;margin:48px auto;background:#fff;border:1px solid #d7dde5;padding:28px 32px;border-radius:6px;}}
code{{background:#eef2f7;padding:2px 6px;border-radius:4px;}}</style></head>
<body><main><h1>QuarterDeck Config Missing</h1><p>{html.escape(CONFIG_ERROR or "")}</p>
<p>The QuarterDeck runtime is installed, but this project has no <code>QuarterDeck/console.yaml</code>.
See <code>console.yaml.sample</code> for the contract.</p>
<pre>{html.escape(str(CONFIG_PATH))}</pre></main></body></html>"""


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    if CONFIG_ERROR:
        return _config_missing_page()
    cfg = require_config()
    console = cfg.get("console", {})
    sections = nav_model()

    nav_parts = []
    for s in sections:
        if s["items"]:
            item_htmls = []
            for d in s["items"]:
                lbl = html.escape(d.get("label", d["id"]))
                iid = html.escape(d["id"])
                icon = _NAV_STATUS_HTML.get(item_nav_status(d), "")
                # Archive/unarchive toggle — not shown for pinned sections
                if s["id"] == "archive":
                    arc = f"<button class='arc-btn' onclick=\"archiveToggle('{iid}',false)\" title='Unarchive'>↑</button>"
                elif not s.get("pinned"):
                    arc = f"<button class='arc-btn' onclick=\"archiveToggle('{iid}',true)\" title='Archive'>↓</button>"
                else:
                    arc = ""
                if d.get("type") == "link":
                    href = d.get("href", "")
                    url = href if re.match(r"^https?://", href) else f"/raw/{iid}"
                    btn = (
                        f"<a class='doc-btn' href='{html.escape(url)}' target='_blank' rel='noopener'>"
                        f"{icon}{lbl}<span class='ext-arrow'>↗</span></a>"
                    )
                else:
                    btn = f"<button class='doc-btn' data-item='{iid}'>{icon}{lbl}</button>"
                item_htmls.append(f"<div class='nav-item-row'>{btn}{arc}</div>")
            btns = "".join(item_htmls)
        else:
            btns = "<div class='section-empty'>— empty —</div>"
        collapsed_cls = " collapsed" if s.get("collapsed") else ""
        nav_parts.append(
            f"<div class='nav-section{collapsed_cls}' data-sec='{html.escape(s['id'])}'>"
            f"<div class='section-head' onclick='toggleSection(this.parentElement)'>"
            f"<span class='dot' style='background:{s['dot']}'></span>"
            f"{html.escape(s['label'])}"
            f"<span class='collapse-arrow'></span>"
            f"</div>"
            f"{btns}</div>"
        )
    nav = "".join(nav_parts)

    all_items = items()
    default_id = console.get("default_item") or (all_items[0]["id"] if all_items else "")
    init = next(
        (i for i in all_items if i["id"] == default_id), all_items[0] if all_items else None
    )
    init_js = f'loadDoc("{init["id"]}");' if init else ""

    return f"""<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(console.get("name", "Console"))}</title><style>{_STYLE}</style></head>
<body>
  <header><strong>{html.escape(console.get("name", "Console"))}</strong>
    <span class="sub">{html.escape(cfg.get("project", {}).get("description", ""))}</span></header>
  <main>
    <nav>{nav}</nav>
    <article id="content">Loading…</article>
  </main>
  <script>
    const contentEl = document.getElementById('content');

    function setActive(itemId) {{
      document.querySelectorAll('.doc-btn').forEach(b =>
        b.classList.toggle('active', b.dataset.item === itemId));
    }}
    async function loadDoc(itemId) {{
      setActive(itemId);
      const res = await fetch(`/api/document/${{itemId}}`);
      const data = await res.json();
      if (!res.ok) {{ contentEl.innerHTML = `<p style="color:#991b1b">${{data.detail || 'Error'}}</p>`; return; }}
      contentEl.innerHTML = data.html;
      const form = contentEl.querySelector('form[data-questionnaire]');
      if (form) form.onsubmit = async e => {{
        e.preventDefault();
        const payload = {{}};
        for (const [k, v] of new FormData(form).entries()) {{
          if (payload[k] !== undefined)
            payload[k] = Array.isArray(payload[k]) ? [...payload[k], v] : [payload[k], v];
          else payload[k] = v;
        }}
        const r = await fetch(`/api/state/questionnaire.${{form.dataset.questionnaire}}`, {{
          method: 'POST', headers: {{'Content-Type': 'application/json'}},
          body: JSON.stringify({{document_id: form.dataset.questionnaire, state: 'done', payload}})
        }});
        if (!r.ok) {{
          const d = await r.json().catch(() => ({{}}));
          contentEl.insertAdjacentHTML('afterbegin', `<div class='item-error'>Save failed: ${{d.detail || r.status}}</div>`);
          return;
        }}
        loadDoc(itemId);
      }};
    }}
    async function loadTicket(itemId, ticketId) {{
      const res = await fetch(`/api/ticket/${{itemId}}/${{ticketId}}`);
      const data = await res.json();
      const el = document.getElementById('ticket-detail');
      if (el) {{ el.innerHTML = data.html; el.scrollIntoView({{behavior:'smooth', block:'start'}}); }}
    }}
    function _editable(itemId) {{ return contentEl.querySelector(`.editable[data-item="${{itemId}}"]`); }}
    function editDoc(itemId) {{
      const e = _editable(itemId); if (!e) return;
      e.querySelector('.doc-view').style.display = 'none';
      e.querySelector('.edit-toolbar').style.display = 'none';
      e.querySelector('.doc-edit').style.display = 'block';
    }}
    function cancelDoc(itemId) {{ loadDoc(itemId); }}
    async function submitDecision(itemId, state) {{
      const fb = document.getElementById('fb-' + itemId);
      const r = await fetch(`/api/state/decision.${{itemId}}`, {{
        method: 'POST', headers: {{'Content-Type': 'application/json'}},
        body: JSON.stringify({{document_id: itemId, state, payload: {{feedback: fb ? fb.value : ''}}}})
      }});
      if (r.ok) loadDoc(itemId); else alert('Could not record decision.');
    }}
    async function submitPlanDecision(itemId, decision) {{
      const r = await fetch(`/api/plan/${{itemId}}/decision`, {{
        method: 'POST', headers: {{'Content-Type': 'application/json'}},
        body: JSON.stringify({{decision}})
      }});
      if (r.ok) loadDoc(itemId);
      else {{
        const d = await r.json().catch(() => ({{}}));
        alert('Could not decide plan: ' + (d.detail || r.status));
      }}
    }}
    async function setAc(itemId, ticketId, index, status) {{
      const key = `ac.${{itemId}}.${{ticketId}}`;
      const cur = await (await fetch(`/api/state/${{key}}`)).json();
      const payload = cur.payload || {{}};
      payload[index] = status;
      await fetch(`/api/state/${{key}}`, {{
        method: 'POST', headers: {{'Content-Type': 'application/json'}},
        body: JSON.stringify({{document_id: ticketId, state: 'tracked', payload}})
      }});
      await loadDoc(itemId);        // refresh the board (AC chip on the card)
      loadTicket(itemId, ticketId); // reopen the detail with updated checks
    }}
    async function saveDoc(itemId) {{
      const e = _editable(itemId); if (!e) return;
      const content = e.querySelector('.doc-source').value;
      const r = await fetch(`/api/document/${{itemId}}/source`, {{
        method: 'POST', headers: {{'Content-Type': 'application/json'}},
        body: JSON.stringify({{content}})
      }});
      if (!r.ok) {{ const d = await r.json().catch(() => ({{}})); alert('Save failed: ' + (d.detail || r.status)); return; }}
      loadDoc(itemId);
    }}
    function toggleSection(el) {{
      el.classList.toggle('collapsed');
    }}
    async function archiveToggle(itemId, doArchive) {{
      const url = doArchive ? `/api/item/${{itemId}}/archive` : `/api/item/${{itemId}}/unarchive`;
      const r = await fetch(url, {{method: 'POST'}});
      if (r.ok) window.location.reload();
      else {{ const d = await r.json().catch(() => ({{}})); alert('Archive failed: ' + (d.detail || r.status)); }}
    }}
    function mdTab(btn, index) {{
      const t = btn.closest('.md-tabs');
      t.querySelectorAll('.md-tab-btn').forEach((b, i) => b.classList.toggle('active', i === index));
      t.querySelectorAll('.md-tab-pane').forEach((p, i) => p.classList.toggle('active', i === index));
    }}
    document.querySelectorAll('button.doc-btn[data-item]').forEach(btn => {{
      btn.onclick = () => loadDoc(btn.dataset.item);
    }});
    {init_js}
  </script>
</body></html>"""


@app.exception_handler(HTTPException)
def http_exception_handler(_request, exc: HTTPException):
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})


@app.exception_handler(ConsoleConfigError)
def console_config_error_handler(request, exc: ConsoleConfigError):
    if request.url.path == "/":
        return HTMLResponse(_config_missing_page(), status_code=503)
    return JSONResponse(status_code=503, content=config_error_payload())

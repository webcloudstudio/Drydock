"""QuarterDeck — a YAML-driven viewer for LLM-assisted development.

The QuarterDeck is deliberately dumb. It owns no project state and makes no build
decisions. It reads one `console.yaml` — a sections list and a flat list of **items**
(things) — and renders each item by its `type`. A framework (and the user) append and
update the items; the QuarterDeck only navigates and renders them.

Each item carries navigation properties (`label`, `section`) and type properties
(`type` + type-specific fields). Sections are defined in the `sections:` block of
`console.yaml` (id / label / dot / collapsed / pinned); items reference a section id.

Canonical target sections: Analyze · Plan · Build.

Page types (one Python renderer each, in TYPES):
  - markdown      render a markdown file as HTML
  - document      render md/html/pdf variants as tabs (path_md / path_html / path_pdf)
  - jsonl         render append-only JSON records as a read-only table
  - kanban        render a tickets JSON file as a board (read-only work tracking)
  - questionnaire render a questionnaire JSON as a form; persist answers
  - link          a hyperlink (external URL or a local file served raw)
  - command_status derive acceptance readiness and consistency from configured Core Docs
  - compass       the Build Compass: the live MANIFEST.md work graph — grouped, costed,
                  state-badged, and editable (reorder/regroup/rename/split)

console.yaml also accepts:
  sources:   list of {glob, section, type, ...} rules that auto-discover files as items.
             Items in the explicit `items:` list (matched by ID or by path) take priority.
  overrides: list of {match: <path-relative-to-project-root>, <field overrides>} applied
             to source-generated items before they are added.

Tickets (the kanban's work items) live in a separate JSON file the framework writes;
the QuarterDeck renders them read-only. Contract: QuarterDeck/README.md
"""

from __future__ import annotations

import html
import json
import os
import re
from collections.abc import Callable
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import markdown
import yaml
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from pydantic import BaseModel

try:
    from drydock import __copyright__ as DRYDOCK_COPYRIGHT
except Exception:  # pragma: no cover - QuarterDeck can run outside the package tree.
    DRYDOCK_COPYRIGHT = "Copyright (c) 2026 Web Cloud Studio. All rights reserved."

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
WORKSPACE_ROOT = PROJECT_ROOT.parent.parent  # $DRYDOCK_WORKSPACE/targets/<Target> → workspace root
ACTIVE_TARGET_COOKIE = "quarterdeck_target"
BUILD_FAILURE_FORCE_HINT = "rerun drydock build with --force to override errors"
TARGET_BUTTON_PALETTE = (
    ("#0f766e", "#5eead4"),
    ("#b45309", "#fbbf24"),
    ("#1d4ed8", "#93c5fd"),
    ("#be123c", "#fda4af"),
    ("#4c1d95", "#c4b5fd"),
    ("#166534", "#86efac"),
)

_DONE_STATES = {"done", "answered", "complete", "verified", "promoted"}
_DEFAULT_DOT = "#94a3b8"

# Nautical ICS signal flag SVGs — one per section ID (U/A/P/D/N mapping).
_SECTION_FLAGS: dict[str, str] = {
    "blockers": (
        '<svg class="sec-flag" width="14" height="10" viewBox="0 0 16 12">'
        '<rect x="0" y="0" width="8" height="6" fill="#dc2626"/>'
        '<rect x="8" y="0" width="8" height="6" fill="#eab308"/>'
        '<rect x="0" y="6" width="8" height="6" fill="#eab308"/>'
        '<rect x="8" y="6" width="8" height="6" fill="#dc2626"/>'
        "</svg>"
    ),
    "analyze": (
        '<svg class="sec-flag" width="14" height="10" viewBox="0 0 16 12">'
        '<rect width="16" height="12" fill="#0f766e"/>'
        '<rect x="0" y="0" width="8" height="6" fill="#ffffff"/>'
        '<rect x="8" y="6" width="8" height="6" fill="#ffffff"/>'
        "</svg>"
    ),
    "plan": (
        '<svg class="sec-flag" width="14" height="10" viewBox="0 0 16 12">'
        '<rect width="16" height="12" fill="#1d4ed8"/>'
        '<rect x="4" width="4" height="12" fill="#ffffff"/>'
        '<rect y="4" width="16" height="4" fill="#ffffff"/>'
        "</svg>"
    ),
    "build": (
        '<svg class="sec-flag" width="14" height="10" viewBox="0 0 16 12">'
        '<rect width="16" height="12" fill="#ffffff"/>'
        '<rect x="0" y="0" width="8" height="6" fill="#d97706"/>'
        '<rect x="8" y="6" width="8" height="6" fill="#d97706"/>'
        "</svg>"
    ),
    "core": (
        '<svg class="sec-flag" width="14" height="10" viewBox="0 0 16 12">'
        '<rect width="16" height="12" fill="#1d4ed8"/>'
        '<rect width="8" height="12" fill="#fff"/>'
        "</svg>"
    ),
    "actions": (
        '<svg class="sec-flag" width="14" height="10" viewBox="0 0 16 12">'
        '<rect width="16" height="12" fill="#1d4ed8"/>'
        '<rect x="4" y="3" width="8" height="6" fill="#fff"/>'
        "</svg>"
    ),
    "docs": (
        '<svg class="sec-flag" width="14" height="10" viewBox="0 0 16 12">'
        '<rect y="0" width="16" height="4" fill="#eab308"/>'
        '<rect y="4" width="16" height="4" fill="#1d4ed8"/>'
        '<rect y="8" width="16" height="4" fill="#eab308"/>'
        "</svg>"
    ),
    "project_pages": (
        '<svg class="sec-flag" width="14" height="10" viewBox="0 0 16 12">'
        '<rect y="0" width="16" height="4" fill="#eab308"/>'
        '<rect y="4" width="16" height="4" fill="#1d4ed8"/>'
        '<rect y="8" width="16" height="4" fill="#eab308"/>'
        "</svg>"
    ),
}

_ITEM_FLAGS: dict[str, str] = {
    "build_compass": (
        '<svg class="item-flag" width="14" height="10" viewBox="0 0 16 12" '
        "aria-hidden='true'>"
        '<rect width="16" height="12" fill="#ffffff"/>'
        '<rect x="0" y="0" width="8" height="6" fill="#1d4ed8"/>'
        '<rect x="8" y="6" width="8" height="6" fill="#1d4ed8"/>'
        "</svg>"
    ),
}

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


@dataclass(frozen=True)
class ConsoleTarget:
    target: str
    project_root: Path
    base_dir: Path
    config_path: Path
    accent: str
    accent_soft: str


@dataclass(frozen=True)
class ConsoleContext:
    active_target: str
    base_dir: Path
    project_root: Path
    config_path: Path
    workspace_root: Path
    config: dict[str, Any]
    config_error: str | None
    switchable_targets: tuple[ConsoleTarget, ...]


_REQUEST_CONTEXT: ContextVar[ConsoleContext | None] = ContextVar(
    "quarterdeck_request_context", default=None
)


def _active_context() -> ConsoleContext | None:
    return _REQUEST_CONTEXT.get()


def _current_base_dir() -> Path:
    ctx = _active_context()
    return ctx.base_dir if ctx else BASE_DIR


def _current_project_root() -> Path:
    ctx = _active_context()
    return ctx.project_root if ctx else PROJECT_ROOT


def _current_config_path() -> Path:
    ctx = _active_context()
    return ctx.config_path if ctx else CONFIG_PATH


def _current_workspace_root() -> Path:
    ctx = _active_context()
    return ctx.workspace_root if ctx else WORKSPACE_ROOT


def _current_active_target() -> str:
    ctx = _active_context()
    return ctx.active_target if ctx else PROJECT_ROOT.name


def _current_switchable_targets() -> tuple[ConsoleTarget, ...]:
    ctx = _active_context()
    return ctx.switchable_targets if ctx else ()


def load_config(
    *,
    base_dir: Path | None = None,
    project_root: Path | None = None,
    config_path: Path | None = None,
) -> tuple[dict[str, Any], str | None]:
    base_dir = base_dir or BASE_DIR
    project_root = project_root or PROJECT_ROOT
    config_path = config_path or (base_dir / "console.yaml")
    if not config_path.exists():
        return {}, (
            f"QuarterDeck config not found at {config_path}. "
            "Create QuarterDeck/console.yaml for this project before starting the QuarterDeck."
        )
    try:
        config = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
        _expand_sources(config, base_dir=base_dir, project_root=project_root)
        return config, None
    except yaml.YAMLError as exc:
        return {}, f"QuarterDeck config at {config_path} is invalid YAML: {exc}"


def _expand_sources(
    config: dict[str, Any],
    *,
    base_dir: Path | None = None,
    project_root: Path | None = None,
) -> None:
    """Expand sources: rules into items. Explicit items (by ID or by path) take priority."""
    base_dir = base_dir or BASE_DIR
    project_root = project_root or PROJECT_ROOT
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
                    explicit_paths.add(str((base_dir / val).resolve()))
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

        for path in sorted(project_root.glob(glob_pattern)):
            if not path.is_file():
                continue
            if str(path.resolve()) in explicit_paths:
                continue
            rel_from_root = path.relative_to(project_root)
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


def _target_palette(index: int) -> tuple[str, str]:
    return TARGET_BUTTON_PALETTE[index % len(TARGET_BUTTON_PALETTE)]


def _discover_switchable_targets(workspace_root: Path) -> tuple[ConsoleTarget, ...]:
    targets_root = workspace_root / "targets"
    if not targets_root.is_dir():
        return ()

    discovered: list[ConsoleTarget] = []
    for index, target_dir in enumerate(sorted(p for p in targets_root.iterdir() if p.is_dir())):
        base_dir = target_dir / "QuarterDeck"
        config_path = base_dir / "console.yaml"
        if not config_path.is_file():
            continue
        accent, accent_soft = _target_palette(index)
        discovered.append(
            ConsoleTarget(
                target=target_dir.name,
                project_root=target_dir,
                base_dir=base_dir,
                config_path=config_path,
                accent=accent,
                accent_soft=accent_soft,
            )
        )
    return tuple(discovered)


def _resolve_request_context(request: Request | None = None) -> ConsoleContext:
    switchable_targets = _discover_switchable_targets(WORKSPACE_ROOT)
    target_map = {target.target: target for target in switchable_targets}
    selected_target = request.cookies.get(ACTIVE_TARGET_COOKIE) if request else None
    selected = target_map.get(selected_target or "")
    if selected is None and PROJECT_ROOT.parent.name == "targets":
        selected = target_map.get(PROJECT_ROOT.name)

    if selected is None:
        base_dir = BASE_DIR
        project_root = PROJECT_ROOT
        config_path = CONFIG_PATH
        active_target = PROJECT_ROOT.name
    else:
        base_dir = selected.base_dir
        project_root = selected.project_root
        config_path = selected.config_path
        active_target = selected.target

    config, config_error = load_config(
        base_dir=base_dir, project_root=project_root, config_path=config_path
    )
    return ConsoleContext(
        active_target=active_target,
        base_dir=base_dir,
        project_root=project_root,
        config_path=config_path,
        workspace_root=WORKSPACE_ROOT,
        config=config,
        config_error=config_error,
        switchable_targets=switchable_targets,
    )


@contextmanager
def _request_context(request: Request | None):
    token = _REQUEST_CONTEXT.set(_resolve_request_context(request) if request else None)
    try:
        yield
    finally:
        _REQUEST_CONTEXT.reset(token)


# ── Config access ──────────────────────────────────────────────────────────────


def require_config() -> dict[str, Any]:
    ctx = _active_context()
    if ctx:
        if ctx.config_error:
            raise ConsoleConfigError(ctx.config_error)
        return ctx.config
    if CONFIG_ERROR:
        raise ConsoleConfigError(CONFIG_ERROR)
    return CONFIG


def config_error_payload() -> dict[str, Any]:
    ctx = _active_context()
    detail = ctx.config_error if ctx else CONFIG_ERROR
    config_path = ctx.config_path if ctx else CONFIG_PATH
    return {
        "detail": detail,
        "config_path": str(config_path),
        "next_step": "Add QuarterDeck/console.yaml, then restart the QuarterDeck.",
    }


def items() -> list[dict[str, Any]]:
    return require_config().get("items", [])


def _current_project_name() -> str:
    return _current_active_target() or "Project"


def _current_copyright() -> str:
    project = require_config().get("project", {})
    return str(project.get("copyright") or DRYDOCK_COPYRIGHT)


# Item types that have no backing file — always visible regardless of file existence.
_UNTRACKED_TYPES = frozenset({"link"})


def _item_file_exists(item: dict[str, Any]) -> bool:
    """Return False when the item has a backing file path that does not exist."""
    base_dir = _current_base_dir()
    item_type = item.get("type", "")
    if item_type in _UNTRACKED_TYPES:
        return True
    if item_type == "compass":
        # Always visible: the renderer offers to seed when the file is absent.
        return True
    if item_type == "document":
        for key in ("path_html", "path_md", "path_pdf"):
            path_val = item.get(key)
            if path_val:
                try:
                    if (base_dir / path_val).resolve().exists():
                        return True
                except Exception:
                    pass
        return not any(item.get(k) for k in ("path_html", "path_md", "path_pdf"))
    path_val = item.get("path")
    if not path_val:
        return True
    try:
        return (base_dir / path_val).resolve().exists()
    except Exception:
        return True


def find_item(item_id: str) -> dict[str, Any]:
    for item in items():
        if item.get("id") == item_id:
            return item
    raise HTTPException(status_code=404, detail=f"No item {item_id!r}")


def _item_label(item: dict[str, Any]) -> str:
    """Return the displayed item label, including compatibility overrides."""
    if item.get("id") == "build_compass":
        return "MANIFEST"
    return str(item.get("label", item.get("id", "")))


def nav_model() -> list[dict[str, Any]]:
    """Group items into sidebar sections, config order first.

    Items whose backing file does not exist are hidden from the sidebar; they
    reappear automatically once the file is created — no console.yaml rewrite needed.

    """
    config_sections = require_config().get("sections", [])
    config_map = {s["id"]: s for s in config_sections}

    by_section: dict[str, list[dict[str, Any]]] = {}
    order: list[str] = []
    for item in items():
        if not _item_file_exists(item):
            continue
        sid = item.get("section", "project_pages")
        if sid not in by_section:
            by_section[sid] = []
            order.append(sid)
        by_section[sid].append(item)

    config_ids = [s["id"] for s in config_sections]
    always_visible = {"analyze", "plan", "build"}
    ordered_ids = [sid for sid in config_ids if sid in by_section or sid in always_visible]
    ordered_ids += [sid for sid in order if sid not in config_ids]

    sections = []
    for sid in ordered_ids:
        docs = sorted(by_section.get(sid, []), key=lambda d: d.get("order", 0))
        sec_cfg = config_map.get(sid, {})
        label = sec_cfg.get("label", sid.replace("_", " ").title())
        if sid == "core":
            label = _current_project_name()
        sections.append({
            "id": sid,
            "label": label,
            "dot": sec_cfg.get("dot", _DEFAULT_DOT),
            "collapsed": sec_cfg.get("collapsed", False),
            "pinned": sec_cfg.get("pinned", False),
            "items": docs,
        })
    return sections


# ── File resolution ─────────────────────────────────────────────────────────────


def resolve_path(path_value: str) -> Path:
    """Resolve a config path relative to Console/, confined to the project root
    (the directory containing Console/) so siblings like ../evidence are reachable."""
    base_dir = _current_base_dir()
    project_root = _current_project_root()
    path = (base_dir / path_value).resolve()
    if project_root not in path.parents and path != project_root:
        raise HTTPException(status_code=400, detail=f"Path escapes the project: {path_value}")
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"Missing file: {path_value}")
    return path


def resolve_write_path(path_value: str) -> Path:
    """Resolve for write: confined within the project root; creates parent dirs; file need not exist."""
    base_dir = _current_base_dir()
    project_root = _current_project_root()
    path = (base_dir / path_value).resolve()
    if project_root not in path.parents and path != project_root:
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


def _strip_leading_h1(text: str) -> str:
    """Suppress a file's leading H1 when QuarterDeck already supplies the document title."""
    return re.sub(r"\A[ \t]*# [^\n]*(?:\n+|$)", "", text, count=1)


def _split_h2_sections(text: str) -> list[tuple[str, str]]:
    """Split markdown at ## headings. Returns (tab_label, content) pairs."""
    parts = re.split(r"^## (.+)$", text, flags=re.MULTILINE)
    result: list[tuple[str, str]] = []
    intro = parts[0].strip()
    if intro:
        body = re.sub(r"^# [^\n]*(?:\n|$)", "", intro, count=1).strip()
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
        f"<div class='md-tabs'><div class='md-tab-bar'>{tab_btns}</div>"
        f"<div class='md-tab-body'>{tab_panes}</div></div>"
    )


def _render_help_note(item: dict[str, Any]) -> str:
    help_text = str(item.get("help_text", "")).strip()
    if not help_text:
        return ""
    return f"<div class='page-note'>{html.escape(help_text)}</div>"


# ── Renderers (one per type; each takes the item dict) ──────────────────────────


def render_markdown_item(item: dict[str, Any]) -> str:
    text = _strip_leading_h1(
        _strip_frontmatter(resolve_path(item["path"]).read_text(encoding="utf-8"))
    )
    helper = _render_help_note(item)
    if item.get("tabs"):
        return helper + _render_markdown_tabbed(item, text)
    return helper + _md(text)


def render_editable_markdown(item: dict[str, Any]) -> str:
    """Markdown that the human can edit in place. Renders the doc plus an Edit
    toggle; Save POSTs the raw source back to the file (creates the file if absent)."""
    item_id = html.escape(item["id"])
    try:
        raw = resolve_path(item["path"]).read_text(encoding="utf-8")
        rendered = _md(_strip_leading_h1(_strip_frontmatter(raw)))
    except HTTPException:
        raw = ""
        rendered = "<p><em>File not yet created — edit and save to create it.</em></p>"
    helper = _render_help_note(item)
    return (
        f"<div class='editable' data-item='{item_id}'>"
        f"{helper}"
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
    """Render a document using priority: html > pdf > md (single format, no tabs)."""
    label = item.get("label", "Document")
    iid = item["id"]
    helper = _render_help_note(item)

    if item.get("path_html"):
        try:
            resolve_path(item["path_html"])
            url = f"/raw/{iid}?variant=html"
            # HTML documents own the full pane; do not add QuarterDeck title/help chrome above them.
            return f"<iframe class='doc-frame' src='{url}' title='{html.escape(label)}'></iframe>"
        except HTTPException:
            pass

    if item.get("path_pdf"):
        try:
            resolve_path(item["path_pdf"])
            url = f"/raw/{iid}?variant=pdf"
            return (
                helper
                + f"<p><a href='{url}' target='_blank' rel='noopener' class='pdf-open-btn'>Open PDF ↗</a></p>"
            )
        except HTTPException:
            pass

    if item.get("path_md"):
        try:
            text = _strip_leading_h1(
                _strip_frontmatter(resolve_path(item["path_md"]).read_text(encoding="utf-8"))
            )
            return helper + _md(text)
        except HTTPException:
            pass

    return helper + "<p class='subtle'>No files found for this document.</p>"


# ── Compass (MANIFEST.md step order/grouping + live prompt-stack cost) ────────────

# The compass is a live, read-only view of the Manifest work graph: feature
# groups → executable steps (story/spike) → folded acceptance post-actions. Each
# step's story-point cost is its full assembled build prompt (COMPASS.md +
# implements/context specs + stack + rules + instructions), derived on demand by
# build.assemble_step and never written back.


def _step_roots():
    """Resolve the per-role file roots the assembler reads, for this Target."""
    from drydock.build import StepRoots
    from drydock.paths import get_rigging_root, get_stack_dir

    project_root = _current_project_root()

    return StepRoots(
        target_dir=project_root,
        blueprint_dir=project_root / "blueprint",
        stack_dir=get_stack_dir(),
        rigging_dir=get_rigging_root(),
    )


def _render_compass_empty() -> str:
    return (
        "<p class='subtle'>No build steps yet. Run <code>drydock plan</code> to "
        "generate <code>MANIFEST.md</code>.</p>"
    )


def _render_step_files(step) -> str:
    """Collapsible per-file cost breakdown for one step, grouped by role."""
    rows = []
    for fc in step.files:
        miss = " <span class='cmp-miss'>missing</span>" if fc.missing else ""
        rows.append(
            "<li class='cmp-file'>"
            f"<span class='cmp-role'>{html.escape(fc.role)}</span>"
            f"<span class='cmp-fname'>{html.escape(fc.name)}</span>"
            f"<span class='cmp-fsp'>SP {fc.story_points:,}</span>{miss}"
            "</li>"
        )
    if step.instructions_story_points:
        rows.append(
            "<li class='cmp-file'>"
            "<span class='cmp-role'>instructions</span>"
            "<span class='cmp-fname'>(task text)</span>"
            f"<span class='cmp-fsp'>SP {step.instructions_story_points:,}</span>"
            "</li>"
        )
    return (
        "<details class='cmp-detail'><summary>stack breakdown</summary>"
        f"<ul class='cmp-files'>{''.join(rows)}</ul></details>"
    )


def _feature_options(plan, selected: str | None) -> str:
    """Build the regroup <option> list: every feature plus an Ungrouped choice."""
    opts = ['<option value="">Ungrouped</option>']
    for block in plan.blocks:
        if block.block_type != "feature":
            continue
        sel = " selected" if block.block_id == selected else ""
        opts.append(
            f'<option value="{html.escape(block.block_id)}"{sel}>{html.escape(block.name)}</option>'
        )
    return "".join(opts)


def _fmt_sp(tokens: int) -> str:
    """Render a story-point (token) count compactly: 50000 -> ``50K``."""
    if tokens >= 1000 and tokens % 1000 == 0:
        return f"{tokens // 1000}K"
    if tokens >= 1000:
        return f"{tokens / 1000:.1f}K".replace(".0K", "K")
    return str(tokens)


# Story lifecycle kinds and their shared presentation. ``built`` is the best
# state; ``failed`` the worst. A group takes the color and label of its worst
# story (highest severity).
_KIND_CHIP = {
    "ready": "<span class='cmp-buildable'>Ready To Build</span>",
    "built": "<span class='bp-state bp-done'>Built</span>",
    "failed": "<span class='bp-state bp-failed'>Failed</span>",
    "blocked": "<span class='bp-state bp-blocked'>Blocked</span>",
}
_KIND_STEP_CLS = {
    "built": " bp-step-done",
    "ready": " cmp-step-buildable",
    "blocked": " cmp-step-blocked",
    "failed": " cmp-step-failed",
}
_KIND_GROUP_CLS = {
    "built": " cmp-group-done",
    "ready": " cmp-group-buildable",
    "blocked": " cmp-group-blocked",
    "failed": " cmp-group-failed",
}
_KIND_SEVERITY = {"built": 0, "ready": 1, "blocked": 2, "failed": 3}


def render_compass(item: dict[str, Any]) -> str:
    """Render MANIFEST.md as the build compass: grouped, costed, editable steps.

    Feature groups carry a story-point rollup; each story/spike step shows its
    assembled prompt cost with a collapsible per-file breakdown and its acceptance
    checks folded beneath as post-actions. Steps whose stack exceeds the context
    warn ceiling are flagged. Constrained reorder/regroup controls move steps and
    features; a move that would break the build topology is rejected.
    """
    from drydock.build import assemble_steps, group_steps
    from drydock.build_plan import parse_build_plan
    from drydock.build_status import build_status
    from drydock.errors import SpecificationError

    project_root = _current_project_root()

    try:
        plan = parse_build_plan(project_root / "MANIFEST.md")
    except SpecificationError:
        return _render_compass_empty()

    steps = assemble_steps(plan, _step_roots())
    if not steps:
        return _render_compass_empty()
    groups = group_steps(plan, steps)
    status = build_status(plan)
    buildable = set(status.buildable_ids)

    item_id = html.escape(item.get("id", ""))
    by_id = plan.by_id()
    acs_by_parent: dict[str, list] = {}
    for block in plan.blocks:
        if block.block_type == "ac" and block.parent:
            acs_by_parent.setdefault(block.parent, []).append(block)

    def _story_kind(block_id: str) -> str:
        """Lifecycle kind for one story: ``built`` / ``ready`` / ``failed`` / ``blocked``.

        A story is Built once it has been executed (checksum + commit); the DoD
        outcome then splits Built (passed) from Failed. Every unbuilt story is
        either Ready To Build (all ``depends:`` verified) or Blocked (a
        dependency story is not yet built). There is no idle pending state and no
        separate review stage.
        """
        if block_id in buildable:
            return "ready"
        state = by_id[block_id].state if block_id in by_id else "pending"
        if state in ("closed/verified", "implemented"):
            return "built"
        if state == "closed/failed":
            return "failed"
        return "blocked"

    def _blockers(block_id: str) -> list:
        """The unbuilt ``depends:`` stories keeping this story Blocked."""
        block = by_id.get(block_id)
        if not block:
            return []
        return [
            by_id[dep]
            for dep in block.depends
            if dep in by_id and by_id[dep].state != "closed/verified"
        ]

    def step_controls(step, group_step_count: int) -> str:
        # Story order within a group is irrelevant (the group is built as a unit),
        # so a story exposes change-group controls plus a rename button.
        bid = html.escape(step.block_id)
        name_js = html.escape(step.name, quote=True)
        ungroup_btn = (
            f"<button class='cmp-mbtn cmp-ungroup' title='Ungroup story' "
            f"onclick=\"compassUngroup('{item_id}','{bid}')\">Ungroup</button>"
            if group_step_count > 1 and step.parent
            else ""
        )
        return (
            "<span class='cmp-move'>"
            f"<select class='cmp-regroup' title='Move story to another group' "
            f"onchange=\"compassRegroup('{item_id}','{bid}',this.value)\">"
            f"{_feature_options(plan, step.parent)}</select>"
            f"{ungroup_btn}"
            f"<button class='cmp-mbtn' title='Rename story' "
            f"onclick=\"compassRename('{item_id}','{bid}','{name_js}')\">✎</button>"
            "</span>"
        )

    def feature_controls(feature_id: str | None, step_count: int = 0) -> str:
        if not feature_id:
            return ""
        fid = html.escape(feature_id)
        fname = html.escape(by_id[feature_id].name if feature_id in by_id else "", quote=True)
        split_btn = (
            f"<button class='cmp-mbtn' title='Split into one group per story' "
            f"onclick=\"compassSplit('{item_id}','{fid}')\">⑃ split</button>"
            if step_count > 1
            else ""
        )
        return (
            "<span class='cmp-move'>"
            f"<button class='cmp-mbtn' title='Move group up' "
            f"onclick=\"compassMove('{item_id}','move_feature','{fid}','up')\">▲</button>"
            f"<button class='cmp-mbtn' title='Move group down' "
            f"onclick=\"compassMove('{item_id}','move_feature','{fid}','down')\">▼</button>"
            f"<button class='cmp-mbtn' title='Rename group' "
            f"onclick=\"compassRename('{item_id}','{fid}','{fname}')\">✎</button>"
            f"{split_btn}"
            "</span>"
        )

    def count_label(count: int, singular: str, plural: str) -> str:
        label = singular if count == 1 else plural
        return f"{count} {label}"

    total_sp = sum(s.total_story_points for s in steps)
    total_savings = sum(group.story_point_savings for group in groups)
    story_n = sum(1 for block in plan.blocks if block.block_type == "story")
    spike_n = sum(1 for block in plan.blocks if block.block_type == "spike")
    spike_html = (
        f"<span class='cmp-count'>{count_label(spike_n, 'spike', 'spikes')}</span>"
        if spike_n
        else ""
    )
    warn_n = sum(1 for s in steps if s.over_warn)
    warn_html = (
        f" <span class='cmp-warn'>{warn_n} story block(s) over {_fmt_sp(steps[0].warn_tokens)} SP</span>"
        if warn_n
        else ""
    )

    if status.buildable_ids:
        buildable_txt = ", ".join(status.buildable_ids)
    elif status.steps_failed:
        failed_ids = ", ".join(b.block_id for b in plan.blocks if b.state == "closed/failed")
        buildable_txt = (
            f"(none — blocked by {status.steps_failed} failed story block(s): {failed_ids})"
        )
    else:
        buildable_txt = "(none)"

    ready_n = len(status.buildable_ids)
    pending_n = status.steps_pending - ready_n
    header = (
        "<div class='cmp-hdr'>"
        "<div class='cmp-hdr-counts'>"
        f"<span class='cmp-count'>{count_label(len(plan.blocks), 'block', 'blocks')}</span>"
        f"<span class='cmp-count'>{count_label(story_n, 'story', 'stories')}</span>"
        f"{spike_html}"
        f"<span class='cmp-count cmp-count-built'>"
        f"{status.steps_verified + status.steps_implemented} built</span>"
        f"<span class='cmp-count cmp-count-ready'>{ready_n} ready to build</span>"
        f"<span class='cmp-count cmp-count-blocked'>{pending_n} blocked</span>"
        f"<span class='cmp-count cmp-count-failed'>{status.steps_failed} failed</span>"
        f"<span class='cmp-count cmp-count-sp'>Total SP {total_sp:,}</span>"
        f"<span class='cmp-count cmp-count-sp'>Total Savings {total_savings:,}</span></div>"
        f"<div class='cmp-hdr-buildable'>Buildable now: <strong>{html.escape(buildable_txt)}</strong>"
        f"</div></div>"
    )

    parts = [
        header,
        "<div class='cmp-toolbar'>"
        f"<span class='cmp-total'>{warn_html}</span>"
        f"<button class='cmp-normalize' title='Reorder groups into canonical "
        f"layer-band order' onclick=\"compassNormalize('{item_id}')\">"
        "<span class='cmp-btn-ico'>⇅</span> Normalize order</button>"
        f"<button class='cmp-newgroup' onclick=\"compassAddFeature('{item_id}')\">"
        "<span class='cmp-btn-ico'>+</span> New group</button>"
        "</div>",
    ]

    for group in groups:
        step_cards = []
        group_total = len(group.steps)
        group_verified = sum(
            1
            for s in group.steps
            if by_id.get(s.block_id) and by_id[s.block_id].state == "closed/verified"
        )
        for step in group.steps:
            kind = _story_kind(step.block_id)
            state = by_id[step.block_id].state if step.block_id in by_id else "pending"
            step_cls = _KIND_STEP_CLS.get(kind, "")
            warn = (
                f" <span class='cmp-warn'>over {_fmt_sp(step.warn_tokens)} SP</span>"
                if step.over_warn
                else ""
            )
            dod_rows = "".join(
                "<li class='cmp-ac'>"
                f"<span class='cmp-ackind'>{html.escape(str(ac.fields.get('kind', 'ac')))}</span>"
                f"<span class='cmp-acname'>{html.escape(ac.name)}</span>"
                + (
                    f"<code class='cmp-accheck'>{html.escape(str(ac.fields['check']))}</code>"
                    if ac.fields.get("check")
                    else ""
                )
                + "</li>"
                for ac in acs_by_parent.get(step.block_id, [])
            )
            # A failed story opens its Definition of Done so the failed check is visible.
            dod_open = " open" if kind == "failed" else ""
            dod_html = (
                f"<details class='cmp-detail'{dod_open}>"
                "<summary>definition of done</summary>"
                f"<ul class='cmp-acs'>{dod_rows}</ul></details>"
                if dod_rows
                else ""
            )
            finding = (
                str(by_id[step.block_id].fields.get("finding") or "")
                if step.block_id in by_id
                else ""
            )
            fail_html = (
                f"<div class='cmp-fail-reason' title='{html.escape(finding, quote=True)}'>"
                f"⚠ {html.escape(finding)}</div>"
                f"<div class='cmp-fail-action'>{html.escape(BUILD_FAILURE_FORCE_HINT)}</div>"
                if state == "closed/failed" and finding
                else ""
            )
            blockers = _blockers(step.block_id) if kind == "blocked" else []
            blocked_html = (
                "<div class='cmp-blocked-by'>Blocked by story "
                + ", ".join(f"<strong>{html.escape(b.name)}</strong>" for b in blockers)
                + "</div>"
                if blockers
                else ""
            )
            done_check = (
                "<span class='bp-check' title='Built'>&#10003;</span>" if kind == "built" else ""
            )
            step_cards.append(
                f"<div class='cmp-step{step_cls}'>"
                "<div class='cmp-shead'>"
                f"{done_check}"
                f"{_KIND_CHIP[kind]}"
                f"<span class='cmp-stype cmp-stype-{html.escape(step.block_type)}'>"
                f"{html.escape(step.block_type.upper())}</span>"
                f"<span class='cmp-sname'>{html.escape(step.name)}</span>"
                f"<span class='cmp-gsp'>Story Points = {step.total_story_points:,} "
                f"(overhead {step.overhead_story_points:,})</span>{warn}"
                f"{step_controls(step, group_total)}"
                "</div>"
                f"{fail_html}"
                f"{blocked_html}"
                f"{_render_step_files(step)}"
                f"{dod_html}"
                "</div>"
            )
        gname = group.name
        if group.feature_id and group.feature_id in by_id:
            gname = by_id[group.feature_id].name
        # A group is colored and labeled by its worst (highest-severity) story.
        kinds = [_story_kind(s.block_id) for s in group.steps]
        worst = max(kinds, key=lambda k: _KIND_SEVERITY[k]) if kinds else "built"
        gdone_cls = _KIND_GROUP_CLS.get(worst, "")
        gcheck = (
            "<span class='bp-check' title='Group complete'>&#10003;</span>"
            if worst == "built"
            else _KIND_CHIP[worst]
        )
        if group.feature_id:
            fid = html.escape(group.feature_id)
            fname = html.escape(gname, quote=True)
            title_html = (
                f"<span class='cmp-gname cmp-gname-edit' title='Click to rename group' "
                f"onclick=\"compassRename('{item_id}','{fid}','{fname}')\"># {html.escape(gname)}</span>"
            )
        else:
            title_html = f"<span class='cmp-gname'># {html.escape(gname)}</span>"
        parts.append(
            f"<div class='cmp-group{gdone_cls}'>"
            "<div class='cmp-ghead'>"
            f"{gcheck}{title_html}"
            f"<span class='cmp-gsp'>Combined Story Points = {group.total_story_points:,}</span>"
            f"<span class='cmp-gsp'>Story Point Savings = {group.story_point_savings:,}</span>"
            f"<span class='cmp-gsp'>{group_verified}/{group_total} verified</span>"
            f"{feature_controls(group.feature_id, len(group.steps))}"
            "</div>"
            f"{''.join(step_cards)}"
            "</div>"
        )
    return "".join(parts)


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
                sources.append((
                    core_item,
                    resolve_path(core_item["path_md"]).read_text(encoding="utf-8"),
                ))
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


def _render_question_controls(data: dict[str, Any]) -> list[str]:
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
        elif input_type == "checkbox_grid":
            saved_set = set(saved_vals)
            checkboxes = "".join(
                f"<label class='cb-grid-item'>"
                f"<input type='checkbox' name='{qid}' value='{html.escape(str(o))}'"
                f"{' checked' if str(o) in saved_set else ''}>"
                f" {html.escape(str(o))}</label>"
                for o in options
            )
            control = f"<div class='cb-grid'>{checkboxes}</div>"
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
    return rows


def render_questionnaire(item: dict[str, Any]) -> str:
    data = json.loads(resolve_path(item["path"]).read_text(encoding="utf-8"))
    is_discovery = item.get("template") == "discovery"
    done = str(data.get("state", "open")) in _DONE_STATES
    q_id = html.escape(data["id"])

    prefix = "<span class='q-done-mark'>✓</span> " if done else ""
    title_html = f"<h1>{prefix}{html.escape(data.get('title', data['id']))}</h1>"
    purpose_html = f"<p class='subtle'>{html.escape(data.get('purpose', ''))}</p>"

    rows = _render_question_controls(data)
    template_attr = " data-template='discovery'" if is_discovery else ""
    body = (
        title_html
        + purpose_html
        + "<p class='q-autosave-hint'>Answers save automatically when you leave a field. "
        "Leave a question blank to skip it — only answered questions feed later steps.</p>"
        + f"<form data-questionnaire='{q_id}'{template_attr} autocomplete='off'>"
        + "".join(rows)
        + "<span class='q-save-status' aria-live='polite'></span></form>"
    )
    return body


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


_KIND_LABEL: dict[str, tuple[str, str]] = {
    "feature": ("feature", "tk-kind-feature"),
    "story": ("story", "tk-kind-story"),
    "spike": ("spike", "tk-kind-spike"),
    "task": ("task", "tk-kind-task"),
    "bug": ("bug", "tk-kind-bug"),
}


def _kind_chip(kind: str | None) -> str:
    if not kind:
        return ""
    label, css = _KIND_LABEL.get(kind, (kind, "tk-kind-other"))
    return f"<span class='tk-kind {css}'>{html.escape(label)}</span>"


def _ticket_card(item_id: str, t: dict[str, Any]) -> str:
    tid = html.escape(t["id"])
    parent = t.get("parent")
    chip = f"<span class='parent-chip'>↳ {html.escape(parent)}</span>" if parent else ""
    blocked_cls = " blocked" if t.get("blocked") else ""
    badges = _ticket_badges(t)
    kind_html = _kind_chip(t.get("kind"))
    return (
        f"<div class='ticket-card{blocked_cls}' onclick=\"loadTicket('{html.escape(item_id)}','{tid}')\">"
        f"<strong>{html.escape(t['title'])}</strong>"
        f"<div class='ticket-meta'>{kind_html}<code>{tid}</code>{chip}</div>"
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
    kind = t.get("kind")
    kind_html = f"&nbsp;&nbsp;{_kind_chip(kind)}" if kind else ""
    parts.append(
        f"<p class='subtle'>status: <strong>{html.escape(_STATUS_LABEL.get(status, status))}</strong>"
        f"{kind_html}&nbsp;&nbsp;{_ticket_badges(t)}</p>"
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
    "compass": TypeDef(("path",), render_compass),
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
    return _wrap_page(item, out)


# ── State store (questionnaire answers) ─────────────────────────────────────────


def _q_path_for(item_id: str) -> Path | None:
    """Return the resolved path of a questionnaire JSON file, or None."""
    item = next(
        (i for i in items() if i.get("id") == item_id and i.get("type") == "questionnaire"), None
    )
    if not item or "path" not in item:
        return None
    p = (_current_base_dir() / item["path"]).resolve()
    return p if p.exists() else None


def item_pending(item: dict[str, Any]) -> bool:
    """Return True when this item has an outstanding action requiring user input."""
    t = item.get("type", "")
    if t in _UNTRACKED_TYPES or t in ("command_status", "compass"):
        return False
    if t == "questionnaire":
        path = item.get("path")
        if not path:
            return False
        try:
            p = (_current_base_dir() / path).resolve()
            if not p.exists():
                return True
            data = json.loads(p.read_text(encoding="utf-8"))
            return str(data.get("state", "open")) not in _DONE_STATES
        except Exception:
            return True
    return False


# ── Page header (title row + action buttons + divider) ──────────────────────────

_H1_RE = re.compile(r"^\s*<h1[^>]*>.*?</h1>\s*", re.DOTALL | re.IGNORECASE)


def _wrap_page(item: dict[str, Any], body: str) -> str:
    """Wrap rendered body with the standard page header: title, filename, action buttons."""
    if item.get("id") == "commanders_chair":
        return body

    label = html.escape(_item_label(item))
    iid = html.escape(item["id"])
    t = item.get("type", "")

    fname = ""
    for key in ("path", "path_md", "path_html", "path_pdf", "href"):
        v = item.get(key)
        if v:
            fname = Path(v).name
            break
    fname_html = f"<span class='ph-filename'>{html.escape(fname)}</span>" if fname else ""

    btns: list[str] = []
    if t == "editable_markdown":
        btns.append(f"<button class='ph-btn ph-edit' onclick=\"editDoc('{iid}')\">Edit</button>")

    acts_html = f"<div class='ph-actions'>{''.join(btns)}</div>" if btns else ""
    body = _H1_RE.sub("", body, count=1)
    return (
        f"<div class='page-header'>"
        f"<div class='ph-title-row'><h1 class='ph-title'>{label}</h1>{fname_html}</div>"
        f"{acts_html}"
        f"<hr class='ph-divider'>"
        f"</div>" + body
    )


def _find_q_path_by_id(q_id: str) -> Path | None:
    """Return the resolved path of the questionnaire JSON whose 'id' field matches q_id.

    Config item IDs are auto-generated from filenames (hyphens → underscores), so they
    differ from the questionnaire's own 'id' field. Scan by file content instead.
    """
    for item in items():
        if item.get("type") != "questionnaire" or "path" not in item:
            continue
        p = (_current_base_dir() / item["path"]).resolve()
        if not p.exists():
            continue
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            if data.get("id") == q_id:
                return p
        except (OSError, json.JSONDecodeError):
            continue
    return None


def _writeback_questionnaire(key: str, state: str, payload: dict[str, Any]) -> None:
    """Write answers back into the questionnaire JSON so questions and answers
    live together as a plain input file the next build step can read."""
    if not key.startswith("questionnaire."):
        return
    q_id = key[len("questionnaire.") :]
    q_path = _find_q_path_by_id(q_id)
    if not q_path:
        return
    try:
        data = json.loads(q_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return
    if "resolution" in payload:
        data["resolution"] = payload["resolution"]
    for question in data.get("questions", []):
        if question["id"] in payload:
            ans = payload[question["id"]]
            question["answer"] = ", ".join(ans) if isinstance(ans, list) else ans
    if state in ("answered", "open"):
        questions = data.get("questions", [])
        all_answered = bool(questions) and all(str(q.get("answer", "")).strip() for q in questions)
        data["state"] = "answered" if all_answered else "open"
    else:
        data["state"] = state
    data["answered_at"] = datetime.now(timezone.utc).isoformat()  # noqa: UP017 - Python 3.10 support
    q_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


class StateUpdate(BaseModel):
    document_id: str
    state: str
    payload: dict[str, Any] = {}


class SourceUpdate(BaseModel):
    content: str


class CompassMove(BaseModel):
    kind: str
    block_id: str
    direction: str = ""
    feature: str = ""


class CompassEdit(BaseModel):
    kind: str  # rename | add_feature | split_group
    block_id: str = ""
    name: str = ""


# ── API ─────────────────────────────────────────────────────────────────────────


@app.get("/api/config")
def api_config(request: Request = None) -> dict[str, Any]:
    with _request_context(request):
        return require_config()


@app.get("/api/items")
def api_items(request: Request = None) -> list[dict[str, Any]]:
    with _request_context(request):
        return items()


@app.get("/api/nav")
def api_nav(request: Request = None) -> dict[str, str]:
    with _request_context(request):
        return {"html": render_nav()}


@app.get("/api/document/{item_id}")
def api_document(item_id: str, request: Request = None) -> dict[str, Any]:
    with _request_context(request):
        item = find_item(item_id)
        return {"item": item, "type": item.get("type"), "html": render_item(item)}


@app.get("/api/ticket/{item_id}/{ticket_id}")
def api_ticket(item_id: str, ticket_id: str, request: Request = None) -> dict[str, Any]:
    with _request_context(request):
        item = find_item(item_id)
        if item.get("type") != "kanban":
            raise HTTPException(status_code=404, detail=f"Item {item_id!r} is not a kanban")
        try:
            rendered = render_ticket_detail(item, ticket_id)
        except HTTPException as exc:
            rendered = f"<div class='item-error'>{html.escape(str(exc.detail))}</div>"
        return {"item_id": item_id, "ticket_id": ticket_id, "html": rendered}


@app.post("/api/document/{item_id}/source")
def api_set_source(item_id: str, update: SourceUpdate, request: Request = None) -> dict[str, Any]:
    with _request_context(request):
        item = find_item(item_id)
        if item.get("type") != "editable_markdown":
            raise HTTPException(status_code=400, detail=f"Item {item_id!r} is not editable")
        path = resolve_write_path(item["path"])
        path.write_text(update.content, encoding="utf-8")
        return {"ok": True, "item_id": item_id}


@app.post("/api/compass/{item_id}/move")
def api_compass_move(item_id: str, move: CompassMove, request: Request = None) -> dict[str, Any]:
    from drydock.errors import SpecificationError
    from drydock.manifest_edit import apply_move

    with _request_context(request):
        item = find_item(item_id)
        if item.get("type") != "compass":
            raise HTTPException(status_code=400, detail=f"Item {item_id!r} is not a compass")
        try:
            apply_move(
                _current_project_root() / "MANIFEST.md",
                move.kind,
                move.block_id,
                direction=move.direction,
                feature=move.feature,
            )
        except SpecificationError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"ok": True}


@app.post("/api/compass/{item_id}/edit")
def api_compass_edit(item_id: str, edit: CompassEdit, request: Request = None) -> dict[str, Any]:
    from drydock.errors import SpecificationError
    from drydock.manifest_edit import apply_edit

    with _request_context(request):
        item = find_item(item_id)
        if item.get("type") != "compass":
            raise HTTPException(status_code=400, detail=f"Item {item_id!r} is not a compass")
        try:
            result = apply_edit(
                _current_project_root() / "MANIFEST.md",
                edit.kind,
                block_id=edit.block_id,
                name=edit.name,
            )
        except SpecificationError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"ok": True, **result}


@app.get("/raw/{item_id}")
def raw_document(item_id: str, variant: str | None = Query(None), request: Request = None):
    with _request_context(request):
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


@app.get("/switch-target/{target}")
def switch_target(target: str, request: Request = None):
    with _request_context(request):
        valid_targets = {item.target for item in _current_switchable_targets()}
        if target not in valid_targets:
            raise HTTPException(status_code=404, detail=f"Unknown target: {target}")
        response = RedirectResponse("/?item=commanders_chair", status_code=303)
        response.set_cookie(ACTIVE_TARGET_COOKIE, target, path="/", samesite="lax")
        return response


@app.post("/api/state/{key}")
def api_set_state(key: str, update: StateUpdate, request: Request = None) -> dict[str, Any]:
    with _request_context(request):
        if not key.startswith("questionnaire."):
            raise HTTPException(status_code=400, detail=f"Unsupported state key: {key!r}")
        _writeback_questionnaire(key, update.state, update.payload)
        q_id = key[len("questionnaire.") :]
        q_path = _find_q_path_by_id(q_id)
        state, answered_at = update.state, None
        if q_path:
            try:
                data = json.loads(q_path.read_text(encoding="utf-8"))
                state = data.get("state", update.state)
                answered_at = data.get("answered_at")
            except Exception:
                pass
        return {"key": key, "state": state, "updated_at": answered_at}


@app.get("/health")
def health(request: Request = None) -> dict[str, str]:
    with _request_context(request):
        require_config()
        return {"status": "ok"}


@app.get("/help", response_class=HTMLResponse)
def help_page(request: Request = None) -> HTMLResponse:
    with _request_context(request):
        ctx = _active_context()
        if ctx and ctx.config_error:
            raise HTTPException(status_code=503, detail=ctx.config_error)
        cfg = require_config()
        rel = cfg.get("console", {}).get("app_help_file_location", "")
        if not rel:
            raise HTTPException(
                status_code=404, detail="No app_help_file_location configured in console.yaml."
            )
        path = (_current_workspace_root() / rel).resolve()
        if not path.is_file():
            raise HTTPException(status_code=404, detail=f"Help file not found: {rel}")
        return HTMLResponse(path.read_text(encoding="utf-8"))


# ── Nav item status ──────────────────────────────────────────────────────────────

_NAV_STATUS_HTML: dict[str, str] = {
    "pending": "<span class='nav-status ns-pending'>✗</span>",
    "done": "<span class='nav-status ns-done'>✓</span>",
}


def item_nav_status(item: dict[str, Any]) -> str | None:
    """Return 'pending', 'done', or None (no icon) for the nav status box."""
    t = item.get("type", "")
    if t in _UNTRACKED_TYPES or t in ("command_status", "compass"):
        return None
    if item_pending(item):
        return "pending"
    return "done"


def render_target_switcher() -> str:
    targets = _current_switchable_targets()
    if not targets:
        return ""
    active_target = _current_active_target()

    buttons = []
    for target in targets:
        active_cls = " active" if target.target == active_target else ""
        active_attr = " aria-current='page'" if target.target == active_target else ""
        buttons.append(
            f"<a class='target-btn{active_cls}' href='/switch-target/{html.escape(target.target)}' "
            f"style='--target-accent:{html.escape(target.accent)};--target-accent-soft:{html.escape(target.accent_soft)}'"
            f"{active_attr}>"
            "<span class='target-btn-main'>"
            "<span class='target-btn-flags'>"
            "<span class='target-flag flag-a'></span>"
            "<span class='target-flag flag-b'></span>"
            "</span>"
            f"<span class='target-btn-name'>{html.escape(target.target)}</span>"
            "</span>"
            "</a>"
        )
    buttons_html = "".join(buttons)

    return (
        "<div class='target-dock-break'></div>"
        f"<div class='target-btn-stack'>{buttons_html}</div>"
        "<div class='target-dock-tail'></div>"
    )


def render_nav() -> str:
    """Render the sidebar from the current on-disk item state."""
    nav_parts = []
    for section in nav_model():
        if section["items"]:
            item_htmls = []
            for item in section["items"]:
                lbl = html.escape(_item_label(item))
                iid = html.escape(item["id"])
                icon = _NAV_STATUS_HTML.get(item_nav_status(item) or "", "")
                item_flag = _ITEM_FLAGS.get(item["id"], "")
                if item.get("type") == "link":
                    href = item.get("href", "")
                    url = href if re.match(r"^https?://", href) else f"/raw/{iid}"
                    btn = (
                        f"<a class='doc-btn' href='{html.escape(url)}' "
                        f"target='_blank' rel='noopener'>{icon}{item_flag}{lbl}"
                        "<span class='ext-arrow'>↗</span></a>"
                    )
                else:
                    btn = (
                        f"<button class='doc-btn' data-item='{iid}'>{icon}{item_flag}{lbl}</button>"
                    )
                item_htmls.append(f"<div class='nav-item-row'>{btn}</div>")
            btns = "".join(item_htmls)
        else:
            btns = "<div class='section-empty'>— empty —</div>"
        blockers_cls = " sec-blockers" if section["id"] == "blockers" else ""
        phase_cls = (
            " section-head-target section-head-phase"
            if section["id"] in {"analyze", "plan", "build"}
            else ""
        )
        target_cls = " section-head-target" if section["id"] == "core" else ""
        flag = _SECTION_FLAGS.get(section["id"], "")
        if section["id"] in {"analyze", "plan", "build"}:
            target = html.escape(_current_project_name().upper())
            phase = html.escape(section["label"].upper())
            heading = (
                f"<span class='section-target-name'>{target}</span>"
                f"{flag}"
                f"<span class='section-phase-name'>{phase}</span>"
            )
        else:
            heading = (
                f"{flag}"
                f"<span class='dot' style='background:{section['dot']}'></span>"
                f"<span class='section-label'>{html.escape(section['label'])}</span>"
            )
        nav_parts.append(
            f"<div class='nav-section{blockers_cls}' "
            f"data-sec='{html.escape(section['id'])}'>"
            f"<div class='section-head{target_cls}{phase_cls}'>"
            f"{heading}"
            "</div>"
            f"{btns}</div>"
        )
    return (
        f"<div class='target-dock'>{render_target_switcher()}</div>"
        f"<div class='nav-scroll'>{''.join(nav_parts)}</div>"
    )


# ── UI ───────────────────────────────────────────────────────────────────────────

_STYLE = """
  body { margin:0; font-family:'Segoe UI',Arial,sans-serif; color:#1b2430; background:#f6f7f9; }
  header { padding:12px 22px; background:#111827; color:#fff; display:flex; align-items:center; gap:14px; }
  header strong { font-size:15px; }
  header .header-actions { margin-left:auto; display:flex; align-items:center; gap:10px; }
  header .help-btn { padding:7px 12px; border-radius:999px; border:1px solid rgba(255,255,255,.34);
    background:rgba(255,255,255,.08); color:#fff; font-size:12px; font-weight:800; letter-spacing:.04em; cursor:pointer; display:inline-flex;
    align-items:center; justify-content:center; text-decoration:none; gap:6px; opacity:.9; flex-shrink:0; text-transform:uppercase; }
  header .help-btn:hover { opacity:1; border-color:#fff; background:rgba(255,255,255,.14); }
  header .help-btn .flyout { font-size:11px; opacity:.88; }
  .copyright-bar { padding:8px 22px; background:#e2e8f0; color:#334155; font-size:11px; font-weight:600; border-bottom:1px solid #cbd5e1; }
  main { display:grid; grid-template-columns:240px 1fr; min-height:calc(100vh - 82px); }
  nav { padding:14px 8px 10px; border-right:1px solid #d7dde5; background:#fff; display:flex; flex-direction:column; min-height:0; }
  .nav-scroll { flex:1 1 auto; overflow-y:auto; padding-top:0; }
  .target-dock { padding:0 8px 12px; }
  .target-dock-break { border-top:1px solid #eef2f7; margin:6px 0 10px; }
  .target-dock-tail { border-top:1px solid #eef2f7; margin:10px 0 0; }
  .target-btn-stack { display:flex; gap:8px; flex-wrap:wrap; flex-direction:column; }
  .target-btn { --target-accent:#1d4ed8; --target-accent-soft:#93c5fd; display:flex; align-items:center; justify-content:space-between; gap:10px;
    width:100%; box-sizing:border-box; padding:10px 12px; border-radius:12px; text-decoration:none; border:1px solid color-mix(in srgb, var(--target-accent) 30%, white);
    background:linear-gradient(135deg, color-mix(in srgb, var(--target-accent) 16%, white) 0%, color-mix(in srgb, var(--target-accent-soft) 32%, white) 100%);
    color:#102033; box-shadow:0 10px 20px rgba(15,23,42,.06); transition:transform .12s ease, box-shadow .12s ease, border-color .12s ease; }
  .target-btn:hover { transform:translateY(-1px); box-shadow:0 12px 22px rgba(15,23,42,.12); border-color:var(--target-accent); }
  .target-btn.active { background:linear-gradient(135deg, var(--target-accent) 0%, color-mix(in srgb, var(--target-accent) 78%, black) 100%); color:#fff; border-color:transparent; box-shadow:0 14px 26px rgba(15,23,42,.18); }
  .target-btn-main { display:flex; align-items:center; gap:10px; min-width:0; }
  .target-btn-flags { display:flex; gap:4px; flex:none; }
  .target-flag { display:inline-block; width:14px; height:10px; border-radius:2px; border:1px solid rgba(15,23,42,.16); box-shadow:inset 0 0 0 1px rgba(255,255,255,.18); }
  .target-btn.active .target-flag { border-color:rgba(255,255,255,.35); }
  .flag-a { background:linear-gradient(180deg, #fff 0 33%, var(--target-accent-soft) 33% 66%, var(--target-accent) 66% 100%); }
  .flag-b { background:
    linear-gradient(90deg, transparent 0 50%, rgba(255,255,255,.88) 50% 54%, transparent 54% 100%),
    linear-gradient(180deg, rgba(255,255,255,.9) 0 48%, transparent 48% 52%, rgba(255,255,255,.9) 52% 100%),
    linear-gradient(135deg, color-mix(in srgb, var(--target-accent) 88%, black) 0%, var(--target-accent) 100%); }
  .target-btn-name { font-weight:800; font-size:13px; line-height:1.15; }
  .nav-section { margin-bottom:16px; }
  .section-head { display:flex; align-items:center; gap:8px; font-size:11px; font-weight:700;
                  text-transform:uppercase; letter-spacing:.06em; color:#475569; padding:0 8px 5px;
                  border-bottom:1px solid #eef2f7; margin-bottom:5px; user-select:none; }
  .section-head-target { font-size:13px; font-weight:800; letter-spacing:.03em; color:#0f172a; }
  .section-head-target .section-label { line-height:1.15; }
  .section-head-phase { display:grid; grid-template-columns:minmax(0,1fr) auto minmax(58px,auto); gap:8px; align-items:center; }
  .section-target-name { min-width:0; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; line-height:1.15; }
  .section-phase-name { justify-self:end; text-align:right; line-height:1.15; }
  .section-head .dot { width:8px; height:8px; border-radius:50%; flex:none; }
  .doc-btn { width:100%; margin:0 0 3px; padding:7px 10px 7px 8px; border:1px solid transparent;
             background:#fff; text-align:left; cursor:pointer; font-size:13px; color:#1b2430; border-radius:3px;
             display:flex; align-items:center; }
  .doc-btn:hover { background:#eef2f7; }
  .doc-btn.active { background:#111827; color:#fff; }
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
  .cb-grid { display:grid; grid-template-columns:repeat(auto-fill,minmax(200px,1fr)); gap:4px 16px; margin:8px 0; }
  .cb-grid-item { display:flex; align-items:center; gap:6px; font-size:13px; cursor:pointer; padding:3px 0; }
  .cb-grid-item input[type=checkbox] { width:auto; cursor:pointer; }
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
  .edit-btn, .save-btn, .cancel-btn { padding:6px 12px; border-radius:3px; cursor:pointer; font-size:13px; border:1px solid #cbd5e1; }
  .edit-btn { background:#fff; color:#111827; }
  .edit-btn:hover { background:#eef2f7; }
  .save-btn { background:#111827; color:#fff; border-color:#111827; }
  .cancel-btn { background:#fff; color:#475569; }
  .doc-source { width:100%; min-height:60vh; padding:12px; border:1px solid #cbd5e1; border-radius:4px;
                box-sizing:border-box; font-family:ui-monospace,'Cascadia Code',Consolas,monospace; font-size:13px; line-height:1.5; }
  .doc-edit-actions { display:flex; gap:8px; margin-top:10px; }
  .page-header { margin-bottom:0; }
  .page-note { margin:0 0 14px; padding:10px 12px; background:#eff6ff; border:1px solid #bfdbfe;
               border-radius:6px; color:#1e3a8a; font-size:13px; line-height:1.45; }
  .page-note code { font-family:ui-monospace,'Cascadia Code',Consolas,monospace; font-size:.95em; }
  .ph-title-row { display:flex; align-items:baseline; justify-content:space-between; gap:12px; margin-bottom:6px; }
  .ph-title { margin:0; line-height:1.2; font-size:1.5em; }
  .ph-filename { font-size:12px; color:#94a3b8; font-family:ui-monospace,'Cascadia Code',Consolas,monospace; white-space:nowrap; }
  .ph-actions { display:flex; gap:8px; align-items:center; margin-bottom:10px; }
  .ph-btn { padding:5px 14px; border-radius:3px; cursor:pointer; font-size:13px; font-weight:600; border:1px solid transparent; }
  .ph-edit { background:#f1f5f9; color:#475569; border-color:#cbd5e1; }
  .ph-edit:hover { background:#e2e8f0; }
  .ph-divider { border:none; border-top:1px solid #e2e8f0; margin:0 0 20px; }
  .nav-status { display:inline-flex; width:18px; height:18px; border-radius:3px; align-items:center;
               justify-content:center; font-weight:900; font-size:11px; flex:none; margin-right:6px; }
  .ns-pending { background:#fee2e2; color:#dc2626; border:1.5px solid #fca5a5; }
  .ns-done    { background:#dcfce7; color:#16a34a; border:1.5px solid #86efac; }
  .ext-arrow { font-size:10px; margin-left:3px; opacity:.55; }
  .q-done-mark { color:#16a34a; font-size:1.15em; font-weight:900; margin-right:2px; }
  .j-badge { display:inline-block; padding:1px 8px; border-radius:10px; font-size:11px; font-weight:600; color:#fff; }
  .md-tabs { margin-top:4px; }
  .md-tab-bar { display:flex; flex-wrap:wrap; gap:3px; border-bottom:2px solid #d7dde5; margin-bottom:14px; }
  .md-tab-btn { padding:8px 20px; border:1px solid #d7dde5; background:#f8fafc; border-radius:4px 4px 0 0;
                cursor:pointer; font-size:14px; font-weight:700; color:#475569; border-bottom:none; }
  .md-tab-btn.active { background:#fff; color:#111827; font-weight:700; margin-bottom:-2px; border-bottom:2px solid #fff; }
  .md-tab-btn:hover:not(.active) { background:#eef2f7; }
  .md-tab-pane { display:none; } .md-tab-pane.active { display:block; }
  .doc-frame { width:100%; height:80vh; border:1px solid #d7dde5; border-radius:4px; }
  .pdf-open-btn { display:inline-block; padding:10px 20px; background:#111827; color:#fff;
                  text-decoration:none; border-radius:3px; font-size:14px; margin:12px 0; }
  .pdf-open-btn:hover { opacity:.9; }
  .nav-item-row { display:flex; align-items:center; gap:2px; margin:0 0 3px; }
  .nav-item-row .doc-btn { flex:1; margin:0; }
  .sec-flag { display:inline-flex; align-items:center; flex:none; margin-right:2px;
              border:1px solid rgba(0,0,0,.15); border-radius:1px; }
  .item-flag { display:inline-flex; align-items:center; flex:none; margin-right:6px;
               border:1px solid rgba(0,0,0,.15); border-radius:1px; }
  .sec-blockers > .section-head { color:#dc2626; border-bottom-color:#fecaca; }
  .sec-blockers .doc-btn { color:#dc2626; }
  .sec-blockers .doc-btn:hover { background:#fef2f2; }
  .sec-blockers .doc-btn.active { background:#dc2626; color:#fff; }
  .q-autosave-hint { font-size:12.5px; color:#64748b; margin:6px 0 16px; }
  .q-save-status { display:inline-block; min-height:18px; margin-top:12px; font-size:13px;
                   font-weight:600; color:#16a34a; }
  .q-save-status.q-save-failed { color:#b91c1c; }
  .cmp-total { font-size:14px; font-weight:700; margin:0 0 14px; padding:8px 12px; background:#eef2f7; border-radius:4px; }
  .cmp-group { border:1px solid #d7dde5; border-radius:5px; margin:0 0 12px; overflow:hidden; }
  .cmp-ghead { display:flex; align-items:center; gap:12px; padding:8px 12px; background:#f8fafc; border-bottom:1px solid #e2e8f0; }
  .cmp-gname { font-weight:700; font-family:ui-monospace,Consolas,monospace; }
  .cmp-gsp { font-size:12px; color:#475569; font-weight:600; }
  .cmp-files { list-style:none; margin:0; padding:4px 12px 8px; }
  .cmp-file { display:flex; align-items:center; gap:10px; padding:5px 0; border-bottom:1px solid #f1f5f9; }
  .cmp-file:last-child { border-bottom:none; }
  .cmp-fname { font-family:ui-monospace,Consolas,monospace; font-size:13px; }
  .cmp-fsp { font-size:12px; color:#64748b; margin-left:auto; white-space:nowrap; }
  .cmp-miss { font-size:12px; font-weight:800; letter-spacing:.03em; text-transform:uppercase; color:#b91c1c; background:#fee2e2; border:1px solid #fca5a5; padding:3px 10px; border-radius:6px; white-space:nowrap; }
  .cmp-role { font-size:10px; text-transform:uppercase; letter-spacing:.04em; color:#64748b; background:#eef2f7; padding:1px 6px; border-radius:3px; min-width:74px; text-align:center; }
  .cmp-step { padding:8px 12px; border-bottom:1px solid #eef2f7; }
  .cmp-step:last-child { border-bottom:none; }
  .cmp-shead { display:flex; align-items:center; gap:10px; }
  .cmp-snum { font-size:11px; font-weight:700; color:#1e3a8a; background:#dbeafe; padding:1px 7px; border-radius:3px; }
  .cmp-stype { display:inline-block; font-size:10px; text-transform:uppercase; letter-spacing:.04em; color:#475569; border:1px solid #cbd5e1; padding:1px 6px; border-radius:3px; }
  .cmp-stype-story { font-family:Georgia, 'Times New Roman', serif; font-size:12px; font-style:italic; font-weight:900; letter-spacing:0; color:#7c2d12; background:#fff7ed; border-color:#fdba74; transform:rotate(-2deg); box-shadow:1px 1px 0 #fed7aa; }
  .cmp-sname { font-weight:600; font-size:13px; }
  .cmp-warn { font-size:12px; font-weight:800; letter-spacing:.03em; text-transform:uppercase; color:#92400e; background:#fef3c7; border:1px solid #fcd34d; padding:3px 10px; border-radius:6px; white-space:nowrap; }
  .cmp-detail { margin:6px 0 0; }
  .cmp-detail summary { cursor:pointer; font-size:11px; color:#64748b; }
  .cmp-acs { list-style:none; margin:6px 0 0; padding:0 0 0 18px; }
  .cmp-ac { font-size:12px; color:#475569; padding:2px 0; }
  .cmp-ackind { font-size:10px; color:#64748b; background:#f1f5f9; padding:0 5px; border-radius:3px; }
  .cmp-move { display:inline-flex; align-items:center; gap:4px; margin-left:auto; }
  .cmp-mbtn { font-size:11px; line-height:1; padding:2px 6px; border:1px solid #cbd5e1; background:#fff; border-radius:3px; cursor:pointer; color:#475569; }
  .cmp-mbtn:hover { background:#eef2f7; }
  .cmp-ungroup { font-weight:700; color:#334155; }
  .cmp-toolbar { display:flex; justify-content:space-between; align-items:center; gap:10px; margin:0 0 10px; }
  .cmp-newgroup { display:inline-flex; align-items:center; gap:6px; font-size:13px; font-weight:700; padding:7px 16px; border:1px solid #2563eb; background:#2563eb; color:#fff; border-radius:7px; cursor:pointer; box-shadow:0 1px 2px rgba(37,99,235,.25); transition:background .12s, box-shadow .12s; }
  .cmp-newgroup:hover { background:#1d4ed8; border-color:#1d4ed8; box-shadow:0 2px 5px rgba(37,99,235,.32); }
  .cmp-normalize { display:inline-flex; align-items:center; gap:6px; font-size:13px; font-weight:700; padding:7px 16px; border:1px solid #cbd5e1; background:#fff; color:#334155; border-radius:7px; cursor:pointer; margin-left:auto; box-shadow:0 1px 2px rgba(15,23,42,.06); transition:background .12s, border-color .12s; }
  .cmp-normalize:hover { background:#f1f5f9; border-color:#94a3b8; }
  .cmp-btn-ico { font-size:15px; line-height:1; font-weight:800; }
  .cmp-acname { font-size:12px; color:#334155; }
  .cmp-accheck { font-size:11px; color:#475569; background:#eef2f7; padding:1px 6px; border-radius:3px; font-family:ui-monospace,Consolas,monospace; }
  .cmp-regroup { font-size:11px; padding:1px 4px; border:1px solid #cbd5e1; border-radius:3px; color:#475569; max-width:140px; }
  @media (max-width: 900px) {
    main { grid-template-columns:1fr; }
    nav { border-right:none; border-bottom:1px solid #d7dde5; }
    article { padding:20px 18px; }
    .target-btn-stack { flex-direction:row; }
  }
  .bp-step-done { background:#f0fdf4; border-left:4px solid #22c55e; }
  .cmp-step-buildable { background:#f6efe0; border-left:4px solid #c8a96a; }
  .cmp-step-blocked { background:#f4f5f7; border-left:4px solid #94a3b8; }
  .cmp-step-failed { background:#fef2f2; border-left:4px solid #ef4444; }
  .cmp-group-done { border-color:#86efac; box-shadow:inset 3px 0 0 #22c55e; }
  .cmp-group-done > .cmp-ghead { background:#f0fdf4; }
  .cmp-group-buildable { border-color:#d8c191; box-shadow:inset 3px 0 0 #c8a96a; }
  .cmp-group-buildable > .cmp-ghead { background:#f6efe0; }
  .cmp-group-blocked { border-color:#cbd5e1; box-shadow:inset 3px 0 0 #94a3b8; }
  .cmp-group-blocked > .cmp-ghead { background:#f4f5f7; }
  .cmp-group-failed { border-color:#fca5a5; box-shadow:inset 3px 0 0 #ef4444; }
  .cmp-group-failed > .cmp-ghead { background:#fef2f2; }
  .bp-check { display:inline-flex; align-items:center; justify-content:center; width:22px; height:22px;
              flex:none; font-size:15px; font-weight:900; color:#fff; background:#22c55e;
              border-radius:5px; box-shadow:0 1px 2px rgba(22,101,52,.3); }
  .bp-state { font-size:11px; font-weight:800; letter-spacing:.03em; text-transform:uppercase; padding:1px 8px; border-radius:10px; flex:none; margin-right:4px; }
  .bp-done    { background:#dcfce7; color:#166534; border:1px solid #86efac; }
  .bp-blocked { background:#e2e8f0; color:#475569; border:1px solid #cbd5e1; }
  .bp-failed  { background:#fee2e2; color:#991b1b; border:1px solid #fca5a5; }
  .bp-complete { color:#166534; font-weight:700; }
  .cmp-warn-bar { font-size:13px; font-weight:800; letter-spacing:.02em; text-transform:uppercase; color:#92400e; background:#fef3c7; border:1px solid #fcd34d; padding:6px 14px; border-radius:6px; margin:0 0 12px; display:inline-block; }
  .cmp-hdr { border:1px solid #d7dde5; border-radius:8px; padding:12px 16px; margin:0 0 14px; background:#f8fafc; }
  .cmp-hdr-counts { display:flex; flex-wrap:wrap; gap:6px; font-size:13px; font-weight:600; color:#475569; }
  .cmp-count { padding:2px 10px; border-radius:10px; background:#eef2f7; border:1px solid #dce3ec; white-space:nowrap; }
  .cmp-count-built { color:#166534; background:#dcfce7; border-color:#86efac; }
  .cmp-count-ready { color:#8a6d2f; background:#f6efe0; border-color:#d8c191; }
  .cmp-count-blocked { color:#475569; background:#e2e8f0; border-color:#cbd5e1; }
  .cmp-count-failed { color:#991b1b; background:#fee2e2; border-color:#fca5a5; }
  .cmp-count-sp { font-weight:700; color:#334155; }
  .cmp-hdr-buildable { font-size:13px; color:#475569; margin-top:3px; }
  .cmp-buildable { font-size:11px; font-weight:800; letter-spacing:.03em; text-transform:uppercase; color:#166534; background:#dcfce7; border:1px solid #4ade80; padding:1px 9px; border-radius:10px; flex:none; margin-right:4px; }
  .cmp-fail-reason { font-size:12px; color:#991b1b; background:#fef2f2; border-left:3px solid #f87171; padding:5px 10px; margin:4px 0 6px; border-radius:0 4px 4px 0; }
  .cmp-blocked-by { font-size:12px; color:#475569; background:#f1f5f9; border-left:3px solid #94a3b8; padding:5px 10px; margin:4px 0 6px; border-radius:0 4px 4px 0; }
  .cmp-gname-edit { cursor:pointer; }
  .cmp-gname-edit:hover { text-decoration:underline; text-decoration-style:dotted; }
  .tk-kind { font-size:10px; font-weight:700; letter-spacing:.04em; padding:1px 6px; border-radius:3px; margin-right:4px; text-transform:uppercase; }
  .tk-kind-feature { background:#ede9fe; color:#5b21b6; }
  .tk-kind-story   { background:#dbeafe; color:#1e40af; }
  .tk-kind-spike   { background:#fef9c3; color:#854d0e; }
  .tk-kind-task    { background:#f0fdf4; color:#166534; }
  .tk-kind-bug     { background:#fee2e2; color:#991b1b; }
  .tk-kind-other   { background:#f1f5f9; color:#475569; }
"""


def _config_missing_page() -> str:
    detail = config_error_payload()
    return f"""<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>QuarterDeck</title>
<style>body{{font-family:'Segoe UI',Arial,sans-serif;background:#f6f7f9;color:#1b2430;}}
main{{max-width:760px;margin:48px auto;background:#fff;border:1px solid #d7dde5;padding:28px 32px;border-radius:6px;}}
code{{background:#eef2f7;padding:2px 6px;border-radius:4px;}}</style></head>
<body><main><h1>QuarterDeck Config Missing</h1><p>{html.escape(detail["detail"] or "")}</p>
<p>The QuarterDeck runtime is installed, but this project has no <code>QuarterDeck/console.yaml</code>.
See <code>console.yaml.sample</code> for the contract.</p>
<pre>{html.escape(detail["config_path"])}</pre></main></body></html>"""


@app.get("/", response_class=HTMLResponse)
def index(request: Request = None) -> str:
    with _request_context(request):
        ctx = _active_context()
        if ctx and ctx.config_error:
            return _config_missing_page()
        if not ctx and CONFIG_ERROR:
            return _config_missing_page()
        cfg = require_config()
        console = cfg.get("console", {})
        nav = render_nav()
        project_name = _current_project_name()
        copyright_notice = _current_copyright()

        all_items = items()
        default_id = console.get("default_item") or (all_items[0]["id"] if all_items else "")
        requested_id = request.query_params.get("item") if request else None
        requested = next((i for i in all_items if i["id"] == requested_id), None)
        init = requested or next(
            (i for i in all_items if i["id"] == default_id), all_items[0] if all_items else None
        )
        init_js = f'loadDoc("{init["id"]}");' if init else ""

        help_btn = (
            '<a class="help-btn" href="/help" target="_blank" rel="noopener" title="Open Drydock">'
            'Drydock <span class="flyout">↗</span></a>'
            if console.get("app_help_file_location")
            else ""
        )
        home_btn = (
            '<a class="help-btn" href="https://webcloudstudio.com" target="_blank" rel="noopener" '
            'title="Open Drydock Home">Drydock Home <span class="flyout">↗</span></a>'
        )

        return f"""<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(project_name)}</title><style>{_STYLE}</style></head>
<body>
  <header><strong>The Drydock</strong><div class="header-actions">{home_btn}{help_btn}</div></header>
  <div class="copyright-bar">{html.escape(copyright_notice)}</div>
  <main>
    <nav>{nav}</nav>
    <article id="content">Loading…</article>
  </main>
  <script>
    const contentEl = document.getElementById('content');
    const navEl = document.querySelector('nav');

    function setActive(itemId) {{
      document.querySelectorAll('.doc-btn').forEach(b =>
        b.classList.toggle('active', b.dataset.item === itemId));
    }}
    function bindNavButtons() {{
      document.querySelectorAll('button.doc-btn[data-item]').forEach(btn => {{
        btn.onclick = () => loadDoc(btn.dataset.item);
      }});
    }}
    async function refreshNav(activeItemId) {{
      const res = await fetch('/api/nav');
      const data = await res.json();
      if (!res.ok) return;
      navEl.innerHTML = data.html;
      bindNavButtons();
      if (activeItemId) setActive(activeItemId);
    }}
    async function loadDoc(itemId) {{
      setActive(itemId);
      const res = await fetch(`/api/document/${{itemId}}`);
      const data = await res.json();
      if (!res.ok) {{ contentEl.innerHTML = `<p style="color:#991b1b">${{data.detail || 'Error'}}</p>`; return; }}
      contentEl.innerHTML = data.html;
      const form = contentEl.querySelector('form[data-questionnaire]');
      if (form) wireAutosave(form);
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
      e.querySelector('.doc-edit').style.display = 'block';
    }}
    function cancelDoc(itemId) {{ loadDoc(itemId); }}
    async function compassMove(itemId, kind, blockId, direction) {{
      const r = await fetch(`/api/compass/${{itemId}}/move`, {{
        method: 'POST', headers: {{'Content-Type': 'application/json'}},
        body: JSON.stringify({{kind, block_id: blockId, direction}})
      }});
      if (r.ok) loadDoc(itemId);
      else {{ const d = await r.json().catch(() => ({{}})); alert(d.detail || 'Move failed'); }}
    }}
    async function compassRegroup(itemId, blockId, feature) {{
      const r = await fetch(`/api/compass/${{itemId}}/move`, {{
        method: 'POST', headers: {{'Content-Type': 'application/json'}},
        body: JSON.stringify({{kind: 'regroup_step', block_id: blockId, feature}})
      }});
      if (r.ok) loadDoc(itemId);
      else {{ const d = await r.json().catch(() => ({{}})); alert(d.detail || 'Move failed'); loadDoc(itemId); }}
    }}
    function compassUngroup(itemId, blockId) {{
      compassRegroup(itemId, blockId, '');
    }}
    async function compassEdit(itemId, payload) {{
      const r = await fetch(`/api/compass/${{itemId}}/edit`, {{
        method: 'POST', headers: {{'Content-Type': 'application/json'}},
        body: JSON.stringify(payload)
      }});
      if (r.ok) loadDoc(itemId);
      else {{ const d = await r.json().catch(() => ({{}})); alert(d.detail || 'Edit failed'); }}
    }}
    function compassRename(itemId, blockId, current) {{
      const name = prompt('Rename to:', current);
      if (name === null) return;
      if (!name.trim()) {{ alert('Name must not be empty'); return; }}
      compassEdit(itemId, {{kind: 'rename', block_id: blockId, name: name.trim()}});
    }}
    function compassAddFeature(itemId) {{
      const name = prompt('New group name:');
      if (name === null) return;
      if (!name.trim()) {{ alert('Name must not be empty'); return; }}
      compassEdit(itemId, {{kind: 'add_feature', name: name.trim()}});
    }}
    function compassSplit(itemId, featureId) {{
      if (!confirm('Split this group into one group per story?')) return;
      compassEdit(itemId, {{kind: 'split_group', block_id: featureId}});
    }}
    function compassNormalize(itemId) {{
      if (!confirm('Reorder all groups into canonical layer-band order?')) return;
      compassEdit(itemId, {{kind: 'normalize'}});
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
    function questionnairePayload(form) {{
      const payload = {{}};
      for (const [k, v] of new FormData(form).entries()) {{
        if (payload[k] !== undefined)
          payload[k] = Array.isArray(payload[k]) ? [...payload[k], v] : [payload[k], v];
        else payload[k] = v;
      }}
      return payload;
    }}
    function _qAllAnswered(form) {{
      for (const el of form.querySelectorAll('[name]')) {{
        if (!el.value || !el.value.trim()) return false;
      }}
      return true;
    }}
    function wireAutosave(form) {{
      const status = form.querySelector('.q-save-status');
      let hideTimer = null;
      const save = async () => {{
        if (status) {{ status.textContent = 'Saving…'; status.className = 'q-save-status'; }}
        const r = await fetch(`/api/state/questionnaire.${{form.dataset.questionnaire}}`, {{
          method: 'POST', headers: {{'Content-Type': 'application/json'}},
          body: JSON.stringify({{document_id: form.dataset.questionnaire, state: 'answered',
                                 payload: questionnairePayload(form)}})
        }});
        if (!status) return;
        clearTimeout(hideTimer);
        if (r.ok) {{
          const allDone = _qAllAnswered(form);
          status.textContent = allDone ? 'Complete ✓' : 'Saved ✓';
          hideTimer = setTimeout(() => {{ status.textContent = ''; }}, 1500);
          const active = document.querySelector('.doc-btn.active');
          await refreshNav(active ? active.dataset.item : null);
        }} else {{
          const d = await r.json().catch(() => ({{}}));
          status.textContent = 'Save failed: ' + (d.detail || r.status);
          status.className = 'q-save-status q-save-failed';
        }}
      }};
      form.querySelectorAll('input, select, textarea').forEach(el => {{
        el.addEventListener('blur', save);
        if (el.tagName === 'SELECT' || el.type === 'checkbox' || el.type === 'radio') el.addEventListener('change', save);
      }});
    }}
    function mdTab(btn, index) {{
      const t = btn.closest('.md-tabs');
      t.querySelectorAll('.md-tab-btn').forEach((b, i) => b.classList.toggle('active', i === index));
      t.querySelectorAll('.md-tab-pane').forEach((p, i) => p.classList.toggle('active', i === index));
    }}
    bindNavButtons();
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

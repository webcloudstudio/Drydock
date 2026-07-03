"""Assemble Drydock's authoritative specification into a documentation page."""

from __future__ import annotations

import argparse
import html
import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

DEFAULT_SPECIFICATION = Path("docs/Drydock_Specification.md")
DEFAULT_OUTPUT = Path("docs/index.html")
DEFAULT_THEME = "sail"
SUPPORTED_THEMES = ("sail", "slate", "paper")

PdfRenderer = Callable[[Path, Path], Path]


@dataclass(frozen=True)
class PublishedDocument:
    html_path: Path
    pdf_path: Path | None
    theme: str
    section_paths: tuple[Path, ...] = ()


@dataclass(frozen=True)
class FlattenedSection:
    title: str
    slug: str
    markdown: str


def _unquote_yaml(value: str) -> str:
    """Strip a single layer of YAML double- or single-quote wrapping."""
    s = value.strip()
    if len(s) >= 2 and s[0] == s[-1] and s[0] in ('"', "'"):
        return s[1:-1]
    return s


def parse_source(text: str) -> tuple[dict[str, object], str]:
    """Split conformed Markdown into frontmatter metadata and body."""
    match = re.match(r"^---\s*\n(.*?)\n---\s*\n?(.*)$", text, re.DOTALL)
    if match is None:
        raise ValueError("source is missing a --- frontmatter --- block")
    return parse_frontmatter(match.group(1)), match.group(2).strip("\n")


def parse_frontmatter(frontmatter: str) -> dict[str, object]:
    """Parse the scalar and ideas-list subset used by the Drydock Blueprint."""
    metadata: dict[str, object] = {"ideas": [], "sail_lead": []}
    ideas = metadata["ideas"]
    sail_lead = metadata["sail_lead"]
    assert isinstance(ideas, list)
    assert isinstance(sail_lead, list)

    current_idea: dict[str, object] | None = None
    in_ideas = False
    in_sub_list = False
    in_sail_lead = False

    for line in frontmatter.splitlines():
        if not line.strip():
            continue

        if in_sail_lead:
            lead_item = re.match(r"^\s*-\s+(.+)$", line)
            if lead_item:
                sail_lead.append(lead_item.group(1).strip())
                continue

        if in_ideas and in_sub_list and current_idea is not None:
            sub_item = re.match(r"^\s{4,}-\s+(.+)$", line)
            if sub_item:
                sub_list = current_idea.setdefault("sub_list", [])
                assert isinstance(sub_list, list)
                sub_list.append(sub_item.group(1).strip())
                continue

        idea = re.match(r"^\s*-\s*title:\s*(.*)$", line)
        if in_ideas and idea:
            current_idea = {"title": _unquote_yaml(idea.group(1))}
            ideas.append(current_idea)
            in_sub_list = False
            continue

        sub_list_header = re.match(r"^\s+sub_list:\s*$", line)
        if in_ideas and current_idea is not None and sub_list_header:
            current_idea["sub_list"] = []
            in_sub_list = True
            continue

        key = re.match(r"^([A-Za-z][\w_]*):\s*(.*)$", line)
        if key:
            name, value = key.group(1), key.group(2).strip()
            if name == "sail_lead" and not value:
                in_sail_lead = True
                in_ideas = False
                in_sub_list = False
                continue
            in_ideas = name == "ideas" and not value
            in_sail_lead = False
            in_sub_list = False
            if not in_ideas:
                metadata[name] = _unquote_yaml(value)

    return metadata


def _render_ideas(metadata: dict[str, object]) -> str:
    ideas = metadata.get("ideas", [])
    if not isinstance(ideas, list) or not ideas:
        return ""

    layout = str(metadata.get("ideas_layout", "")).strip().lower()
    if layout == "sail":
        return _render_sail_ideas(metadata, ideas)

    parts = ['<section class="ideas">']
    ideas_title = str(metadata.get("ideas_title", "What Drydock Adds"))
    parts.append(f"<h2>{_render_inline_markup(ideas_title)}</h2>")
    for item in ideas:
        if not isinstance(item, dict):
            continue
        title = _render_inline_markup(str(item.get("title", "")))
        parts.append('<article class="idea">')
        parts.append(f'<div class="idea-title">{title}</div>')
        sub_list = item.get("sub_list", [])
        if isinstance(sub_list, list) and sub_list:
            parts.append("<ul>")
            parts.extend(f"<li>{_render_inline_markup(str(value))}</li>" for value in sub_list)
            parts.append("</ul>")
        parts.append("</article>")
    parts.append("</section>")
    return "\n".join(parts)


def _render_sail_ideas(metadata: dict[str, object], ideas: list[object]) -> str:
    parts = ['<section class="ideas ideas-sail">']
    ideas_title = str(metadata.get("ideas_title", "The SAIL Method"))
    parts.append(f"<h2>{_render_inline_markup(ideas_title)}</h2>")
    sail_lead = metadata.get("sail_lead", [])
    if isinstance(sail_lead, list) and sail_lead:
        parts.append('<div class="sail-lead">')
        parts.extend(f"<p>{_render_inline_markup(str(value))}</p>" for value in sail_lead)
        parts.append("</div>")
    parts.append('<div class="sail-grid">')
    for item in ideas:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title", "")).strip()
        match = re.match(r"^\*\*([SAIL])\*\*\s+[—-]\s+(.+)$", title)
        if match:
            letter, label = match.group(1), match.group(2)
        else:
            letter, label = title[:1].upper(), title[1:].strip(" -—")
        parts.append('<article class="sail-card">')
        parts.append(f'<div class="sail-letter">{html.escape(letter)}</div>')
        parts.append('<div class="sail-copy">')
        parts.append(f'<div class="idea-title">{_render_inline_markup(label)}</div>')
        sub_list = item.get("sub_list", [])
        if isinstance(sub_list, list) and sub_list:
            parts.append("<ul>")
            parts.extend(f"<li>{_render_inline_markup(str(value))}</li>" for value in sub_list)
            parts.append("</ul>")
        parts.append("</div>")
        parts.append("</article>")
    parts.append("</div>")
    parts.append("</section>")
    return "\n".join(parts)


def _json_for_script(value: str) -> str:
    return json.dumps(value).replace("</", r"<\/")


def _logo_data_uri(source: Path, metadata: dict[str, object]) -> str | None:
    import base64

    logo_field = str(metadata.get("logo", "")).strip()
    if not logo_field:
        return None
    logo_path = source.parent / logo_field
    if not logo_path.is_file():
        return None
    b64 = base64.b64encode(logo_path.read_bytes()).decode()
    return f"data:image/png;base64,{b64}"


def _render_inline_markup(text: str) -> str:
    """Render a small inline-markup subset safely for metadata fields."""
    escaped = html.escape(text)
    escaped = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", escaped)
    escaped = re.sub(r"__(.+?)__", r"<strong>\1</strong>", escaped)
    escaped = re.sub(r"(?<!\*)\*(?!\s)(.+?)(?<!\s)\*(?!\*)", r"<em>\1</em>", escaped)
    escaped = re.sub(r"(?<!_)_(?!\s)(.+?)(?<!\s)_(?!_)", r"<em>\1</em>", escaped)
    return escaped


def _resolve_theme(metadata: dict[str, object], override: str | None) -> str:
    selected = (override or str(metadata.get("theme", "")) or DEFAULT_THEME).strip().lower()
    if selected not in SUPPORTED_THEMES:
        available = ", ".join(SUPPORTED_THEMES)
        raise ValueError(f"unknown publish theme: {selected!r}. Available themes: {available}")
    return selected


def render_page(
    metadata: dict[str, object],
    body: str,
    *,
    theme: str | None = None,
    logo_data_uri: str | None = None,
) -> str:
    """Render parsed Blueprint content into a self-contained HTML document."""
    selected_theme = _resolve_theme(metadata, theme)
    title = html.escape(str(metadata.get("title", "Drydock")))
    title_sub = html.escape(str(metadata.get("title_sub", "")))
    eyebrow = html.escape(str(metadata.get("eyebrow", "")))
    subtitle = html.escape(str(metadata.get("subtitle", "")))
    author = html.escape(str(metadata.get("author", "")))
    studio = html.escape(str(metadata.get("studio", "")))
    year = html.escape(str(metadata.get("year", "")))
    copyright_text = html.escape(str(metadata.get("copyright", "")))
    ideas = _render_ideas(metadata)
    body_json = _json_for_script(body)
    title_sub_html = f'<span class="h1-sub">{title_sub}</span>' if title_sub else ""
    logo_html = (
        f'<div class="cover-logo"><img src="{logo_data_uri}" alt="Drydock"></div>'
        if logo_data_uri
        else ""
    )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title} Documentation</title>
<script src="https://cdn.jsdelivr.net/npm/marked/marked.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/mermaid@10/dist/mermaid.min.js"></script>
<style>
:root {{
  --ink: #17212b; --muted: #5b6875; --paper: #f8fafb; --panel: #ffffff;
  --navy: #123047; --green: #0a7650; --line: #d6dee4; --code: #eef3f5; --pre-bg: #f0f1f3;
}}
body.theme-slate {{
  --ink: #26313d; --muted: #647180; --paper: #f4f6f8; --panel: #ffffff;
  --navy: #17212b; --green: #2cb67d; --line: #d7dee5; --code: #e8edf2; --pre-bg: #202a34;
}}
body.theme-paper {{
  --ink: #2e312d; --muted: #6a6f68; --paper: #fbfbf8; --panel: #ffffff;
  --navy: #2f3430; --green: #427a5b; --line: #dfe3dd; --code: #eceee9; --pre-bg: #f0f2ed;
}}
* {{ box-sizing: border-box; }}
body {{ margin: 0; background: var(--paper); color: var(--ink);
  font: 14px/1.5 "Segoe UI", Arial, sans-serif; }}
header {{ background: var(--navy); color: white; padding: 10px 28px;
  display: flex; justify-content: space-between; gap: 24px; }}
header strong {{ letter-spacing: .04em; }}
header span {{ color: #c8d6df; font-size: 12px; }}
main {{ max-width: 980px; margin: 0 auto; padding: 32px 32px 60px; }}
.cover {{ background: var(--panel); border-top: 5px solid var(--green);
  border-bottom: 1px solid var(--line); padding: 24px 30px; margin-bottom: 22px; }}
.cover-grid {{ display: flex; align-items: center; justify-content: space-between; gap: 24px; }}
.cover-text {{ flex: 1; min-width: 0; }}
.cover-logo {{ flex: 0 0 auto; max-width: 260px; }}
.cover-logo img {{ display: block; width: 100%; height: auto; }}
.eyebrow {{ color: var(--green); font-size: 11px; font-weight: 700;
  letter-spacing: .14em; text-transform: uppercase; }}
h1 {{ font-size: 36px; line-height: 1.1; margin: 6px 0 4px; }}
h1 .h1-sub {{ display: block; font-size: 22px; font-weight: 600; color: var(--muted); margin-top: 2px; }}
.subtitle {{ color: var(--muted); font-size: 15px; max-width: 800px; }}
.meta {{ color: var(--muted); display: flex; gap: 18px; margin-top: 14px; font-size: 12px; }}
.ideas {{ margin: 0 0 22px; }}
.ideas h2, #content h2 {{ border-bottom: 2px solid var(--green); padding-bottom: 4px; }}
.ideas h2 {{ font-size: 1.08rem; letter-spacing: .03em; text-transform: uppercase; }}
.idea {{ background: var(--panel); border-left: 5px solid var(--green);
  margin: 8px 0; padding: 10px 14px 10px 16px; }}
.idea-title {{ color: var(--navy); font-size: 1.14rem; font-weight: 800; line-height: 1.2; }}
.idea ul {{ margin: 6px 0 0; color: var(--muted); }}
.ideas-sail {{ background:
  linear-gradient(135deg, rgba(18, 48, 71, 0.06), rgba(10, 118, 80, 0.03)),
  var(--panel);
  border: 1px solid var(--line);
  padding: 20px 22px 10px;
}}
.sail-lead {{
  margin: 2px 0 16px;
  padding: 0 0 12px;
  border-bottom: 1px solid var(--line);
}}
.sail-lead p {{
  margin: 0 0 6px;
  color: var(--navy);
  font-size: 1rem;
  font-weight: 600;
}}
.sail-lead p:last-child {{ margin-bottom: 0; }}
.sail-grid {{ display: grid; gap: 16px; }}
.sail-card {{
  display: grid;
  grid-template-columns: 108px minmax(0, 1fr);
  gap: 16px;
  align-items: start;
  padding: 12px 0 16px;
  border-bottom: 1px solid var(--line);
}}
.sail-card:last-child {{ border-bottom: none; }}
.sail-letter {{
  color: var(--green);
  font-size: 4.8rem;
  line-height: 0.9;
  font-weight: 900;
  letter-spacing: -0.05em;
  text-shadow: 2px 2px 0 rgba(18, 48, 71, 0.08);
}}
.sail-copy .idea-title {{ font-size: 1.22rem; margin-bottom: 4px; }}
.sail-copy ul {{ margin: 0; padding-left: 20px; color: var(--muted); }}
.sail-copy li {{ margin-bottom: 4px; }}
#content {{ background: var(--panel); border: 1px solid var(--line); padding: 26px 30px; }}
#content h2 {{ margin-top: 28px; margin-bottom: 10px; }}
#content h2:first-child {{ margin-top: 0; }}
#content h3 {{ color: var(--green); margin-top: 18px; margin-bottom: 6px; }}
#content p {{ margin: 6px 0 10px; }}
#content table {{ border-collapse: collapse; display: block; overflow-x: auto; width: 100%; margin: 8px 0; }}
#content th, #content td {{ border: 1px solid var(--line); padding: 3px 8px; text-align: left; }}
#content th {{ background: var(--pre-bg); color: var(--ink); font-size: 13px; }}
#content td {{ font-size: 13px; }}
#content code {{ background: var(--code); border-radius: 3px; padding: 1px 4px; font-size: 13px; }}
#content pre {{ background: var(--pre-bg); color: var(--ink); overflow-x: auto;
  padding: 10px 14px; margin: 6px 0 12px; border-left: 3px solid var(--line); font-size: 13px; }}
#content pre code {{ background: transparent; padding: 0; font-size: inherit; }}
#content blockquote {{ border-left: 4px solid var(--green); background: var(--paper);
  color: var(--muted); font-style: italic; margin: 14px 0 14px 18px;
  padding: 10px 18px; border-radius: 0 3px 3px 0; }}
#content blockquote p {{ margin: 4px 0; }}
#content ul, #content ol {{ margin: 6px 0 10px; padding-left: 24px; }}
#content li {{ margin-bottom: 3px; }}
.diagram {{ background: white; border: 1px solid var(--line); overflow-x: auto; padding: 14px; margin: 8px 0; }}
footer {{ color: var(--muted); font-size: 12px; padding: 16px 28px; text-align: center; }}
@media (max-width: 680px) {{
  main {{ padding: 16px 12px 40px; }} .cover, #content {{ padding: 16px; }}
  header, .meta {{ flex-direction: column; gap: 4px; }} h1 {{ font-size: 28px; }}
  .ideas-sail {{ padding: 16px; }}
  .sail-card {{ grid-template-columns: 1fr; gap: 8px; }}
  .sail-letter {{ font-size: 3.8rem; }}
}}
@media print {{
  header, footer {{ display: none; }}
  body {{ background: white; font-size: 12px; line-height: 1.45; }}
  main {{ padding: 0; max-width: 100%; }}
  #content {{ border: none; padding: 0; }}
  .cover {{ border-top: 3px solid var(--green); padding: 16px; }}
  .ideas-sail {{ border: 1px solid var(--line); padding: 14px 16px 8px; }}
  .sail-card {{ break-inside: avoid; grid-template-columns: 70px minmax(0, 1fr); gap: 10px; }}
  .sail-letter {{ font-size: 3rem; }}
  #content pre, #content blockquote {{ break-inside: avoid; }}
  #content h2, #content h3 {{ break-after: avoid; }}
}}
</style>
</head>
<body class="theme-{selected_theme}">
<header><strong>Drydock</strong><span>{copyright_text}</span></header>
<main>
<section class="cover">
  <div class="cover-grid">
    <div class="cover-text">
      <div class="eyebrow">{eyebrow}</div>
      <h1>{title}{title_sub_html}</h1>
      <div class="subtitle">{subtitle}</div>
      <div class="meta"><span>{author}</span><span>{studio}</span><span>{year}</span></div>
    </div>{logo_html}
  </div>
</section>
{ideas}
<article id="content"></article>
</main>
<footer>{author} · {studio} · {year}</footer>
<script>
const BODY = {body_json};
marked.setOptions({{ gfm: true, breaks: false }});
const content = document.getElementById("content");
content.innerHTML = marked.parse(BODY);
content.querySelectorAll("pre > code.language-mermaid").forEach((code) => {{
  const wrapper = document.createElement("div");
  wrapper.className = "diagram";
  const diagram = document.createElement("div");
  diagram.className = "mermaid";
  diagram.textContent = code.textContent;
  wrapper.appendChild(diagram);
  code.parentNode.replaceWith(wrapper);
}});
mermaid.initialize({{ startOnLoad: false, theme: "neutral" }});
mermaid.run({{ nodes: content.querySelectorAll(".mermaid") }});
</script>
</body>
</html>
"""


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or "section"


def split_h1_sections(body: str) -> tuple[FlattenedSection, ...]:
    """Split Markdown into deterministic H1-backed publish sections."""
    sections: list[tuple[str, str]] = []
    preamble: list[str] = []
    current_title: str | None = None
    current_lines: list[str] = []
    in_fence = False

    for line in body.splitlines():
        if re.match(r"^\s*(```|~~~)", line):
            in_fence = not in_fence
        match = None if in_fence else re.match(r"^#\s+(.+?)\s*#*\s*$", line)
        if match:
            if current_title is None:
                preamble_text = "\n".join(preamble).strip()
                if preamble_text:
                    sections.append(("Introduction", preamble_text))
            else:
                sections.append((current_title, "\n".join(current_lines).strip()))
            current_title = match.group(1).strip() or "Introduction"
            current_lines = [line]
            continue

        if current_title is None:
            preamble.append(line)
        else:
            current_lines.append(line)

    if current_title is None:
        sections.append(("Introduction", "\n".join(preamble).strip()))
    else:
        sections.append((current_title, "\n".join(current_lines).strip()))

    used: dict[str, int] = {}
    flattened: list[FlattenedSection] = []
    for title, markdown in sections:
        base = _slugify(title)
        count = used.get(base, 0) + 1
        used[base] = count
        slug = base if count == 1 else f"{base}-{count}"
        flattened.append(FlattenedSection(title=title, slug=slug, markdown=markdown))
    return tuple(flattened)


def _flat_theme_css() -> str:
    return """
:root {
  --ink: #17212b; --muted: #5b6875; --paper: #f8fafb; --panel: #ffffff;
  --navy: #123047; --green: #0a7650; --line: #d6dee4; --code: #eef3f5; --pre-bg: #f0f1f3;
}
body.theme-slate {
  --ink: #26313d; --muted: #647180; --paper: #f4f6f8; --panel: #ffffff;
  --navy: #17212b; --green: #2cb67d; --line: #d7dee5; --code: #e8edf2; --pre-bg: #202a34;
}
body.theme-paper {
  --ink: #2e312d; --muted: #6a6f68; --paper: #fbfbf8; --panel: #ffffff;
  --navy: #2f3430; --green: #427a5b; --line: #dfe3dd; --code: #eceee9; --pre-bg: #f0f2ed;
}
* { box-sizing: border-box; }
body { margin: 0; background: var(--paper); color: var(--ink);
  font: 15px/1.55 "Segoe UI", Arial, sans-serif; }
.shell { min-height: 100vh; display: grid; grid-template-columns: 320px minmax(0, 1fr); }
.side { background: var(--navy); color: white; padding: 28px 24px; border-right: 6px solid var(--green); }
.brand { margin-bottom: 28px; }
.brand img { display: block; max-width: 220px; height: auto; margin-bottom: 14px; }
.brand-title { font-size: 1.35rem; font-weight: 800; line-height: 1.1; }
.brand-subtitle { color: #c8d6df; margin-top: 8px; font-size: .92rem; }
.toc-title { color: #91e1bd; font-size: .76rem; font-weight: 800; letter-spacing: .14em;
  text-transform: uppercase; margin-bottom: 10px; }
.toc { display: grid; gap: 8px; }
.toc a { color: white; text-decoration: none; display: block; border: 1px solid rgba(255,255,255,.18);
  border-left: 4px solid rgba(145,225,189,.7); padding: 9px 10px; line-height: 1.18;
  overflow-wrap: anywhere; background: rgba(255,255,255,.06); }
.toc a:hover, .toc a.active { background: rgba(145,225,189,.16); border-left-color: #91e1bd; }
.toc-index { color: #91e1bd; font-size: .78rem; font-weight: 800; display: block; margin-bottom: 2px; }
.content { padding: 38px min(7vw, 78px) 70px; }
.mast { background: var(--panel); border-top: 5px solid var(--green); border-bottom: 1px solid var(--line);
  padding: 24px 30px; margin-bottom: 22px; }
.eyebrow { color: var(--green); font-size: 11px; font-weight: 800; letter-spacing: .14em; text-transform: uppercase; }
h1 { font-size: clamp(2rem, 4vw, 3.4rem); line-height: 1.05; margin: 7px 0 8px; color: var(--navy); }
.subtitle, .meta { color: var(--muted); }
.meta { display: flex; flex-wrap: wrap; gap: 18px; margin-top: 14px; font-size: .82rem; }
.cards { display: grid; gap: 12px; }
.card { background: var(--panel); border: 1px solid var(--line); border-left: 5px solid var(--green);
  color: var(--ink); display: block; padding: 16px 18px; text-decoration: none; }
.card strong { color: var(--navy); display: block; font-size: 1.1rem; line-height: 1.2; }
#content { background: var(--panel); border: 1px solid var(--line); padding: 28px 32px; }
#content h1 { font-size: clamp(1.9rem, 3.2vw, 2.8rem); border-bottom: 3px solid var(--green); padding-bottom: 8px; }
#content h2 { border-bottom: 2px solid var(--green); padding-bottom: 4px; margin-top: 28px; }
#content h3 { color: var(--green); margin-top: 18px; margin-bottom: 6px; }
#content table { border-collapse: collapse; display: block; overflow-x: auto; width: 100%; margin: 8px 0; }
#content th, #content td { border: 1px solid var(--line); padding: 3px 8px; text-align: left; }
#content th { background: var(--pre-bg); color: var(--ink); font-size: 13px; }
#content code { background: var(--code); border-radius: 3px; padding: 1px 4px; font-size: 13px; }
#content pre { background: var(--pre-bg); color: var(--ink); overflow-x: auto;
  padding: 10px 14px; margin: 6px 0 12px; border-left: 3px solid var(--line); font-size: 13px; }
#content pre code { background: transparent; padding: 0; font-size: inherit; }
#content blockquote { border-left: 4px solid var(--green); background: var(--paper);
  color: var(--muted); font-style: italic; margin: 14px 0 14px 18px; padding: 10px 18px; }
.diagram { background: white; border: 1px solid var(--line); overflow-x: auto; padding: 14px; margin: 8px 0; }
footer { color: var(--muted); font-size: 12px; margin-top: 24px; }
@media (max-width: 780px) {
  .shell { display: block; }
  .side { border-right: 0; border-bottom: 6px solid var(--green); }
  .content { padding: 20px 14px 42px; }
  #content, .mast { padding: 18px; }
}
"""


def _flat_sidebar(
    metadata: dict[str, object],
    sections: tuple[FlattenedSection, ...],
    *,
    logo_data_uri: str | None,
    current_slug: str | None,
    href_prefix: str,
) -> str:
    title = html.escape(str(metadata.get("title", "Drydock")))
    subtitle = html.escape(str(metadata.get("subtitle", "")))
    logo_html = (
        f'<img src="{logo_data_uri}" alt="{title} logo">'
        if logo_data_uri
        else f'<div class="brand-title">{title}</div>'
    )
    links = []
    for index, section in enumerate(sections, start=1):
        active = ' class="active"' if section.slug == current_slug else ""
        href = f"{href_prefix}{section.slug}.html"
        links.append(
            f'<a{active} href="{html.escape(href)}">'
            f'<span class="toc-index">{index:02d}</span>{html.escape(section.title)}</a>'
        )
    return "\n".join([
        '<aside class="side">',
        '<div class="brand">',
        logo_html,
        f'<div class="brand-subtitle">{subtitle}</div>',
        "</div>",
        '<div class="toc-title">Table of Contents</div>',
        f'<nav class="toc">{"".join(links)}</nav>',
        "</aside>",
    ])


def _flat_script(markdown: str) -> str:
    body_json = _json_for_script(markdown)
    return f"""
<script>
const BODY = {body_json};
marked.setOptions({{ gfm: true, breaks: false }});
const content = document.getElementById("content");
content.innerHTML = marked.parse(BODY);
content.querySelectorAll("pre > code.language-mermaid").forEach((code) => {{
  const wrapper = document.createElement("div");
  wrapper.className = "diagram";
  const diagram = document.createElement("div");
  diagram.className = "mermaid";
  diagram.textContent = code.textContent;
  wrapper.appendChild(diagram);
  code.parentNode.replaceWith(wrapper);
}});
mermaid.initialize({{ startOnLoad: false, theme: "neutral" }});
mermaid.run({{ nodes: content.querySelectorAll(".mermaid") }});
</script>
"""


def render_flat_landing_page(
    metadata: dict[str, object],
    sections: tuple[FlattenedSection, ...],
    *,
    theme: str | None = None,
    logo_data_uri: str | None = None,
    section_href_prefix: str,
) -> str:
    selected_theme = _resolve_theme(metadata, theme)
    title = html.escape(str(metadata.get("title", "Drydock")))
    eyebrow = html.escape(str(metadata.get("eyebrow", "")))
    subtitle = html.escape(str(metadata.get("subtitle", "")))
    author = html.escape(str(metadata.get("author", "")))
    studio = html.escape(str(metadata.get("studio", "")))
    year = html.escape(str(metadata.get("year", "")))
    cards = "\n".join(
        f'<a class="card" href="{html.escape(section_href_prefix + section.slug + ".html")}">'
        f"<strong>{html.escape(section.title)}</strong></a>"
        for section in sections
    )
    sidebar = _flat_sidebar(
        metadata,
        sections,
        logo_data_uri=logo_data_uri,
        current_slug=None,
        href_prefix=section_href_prefix,
    )
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>{_flat_theme_css()}</style>
</head>
<body class="theme-{selected_theme}">
<div class="shell">
{sidebar}
<main class="content">
<section class="mast">
  <div class="eyebrow">{eyebrow}</div>
  <h1>{title}</h1>
  <div class="subtitle">{subtitle}</div>
  <div class="meta"><span>{author}</span><span>{studio}</span><span>{year}</span></div>
</section>
<section class="cards">{cards}</section>
<footer>{author} · {studio} · {year}</footer>
</main>
</div>
</body>
</html>
"""


def render_flat_section_page(
    metadata: dict[str, object],
    sections: tuple[FlattenedSection, ...],
    section: FlattenedSection,
    *,
    theme: str | None = None,
    logo_data_uri: str | None = None,
) -> str:
    selected_theme = _resolve_theme(metadata, theme)
    doc_title = html.escape(str(metadata.get("title", "Drydock")))
    section_title = html.escape(section.title)
    author = html.escape(str(metadata.get("author", "")))
    studio = html.escape(str(metadata.get("studio", "")))
    year = html.escape(str(metadata.get("year", "")))
    sidebar = _flat_sidebar(
        metadata,
        sections,
        logo_data_uri=logo_data_uri,
        current_slug=section.slug,
        href_prefix="",
    )
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{section_title} - {doc_title}</title>
<script src="https://cdn.jsdelivr.net/npm/marked/marked.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/mermaid@10/dist/mermaid.min.js"></script>
<style>{_flat_theme_css()}</style>
</head>
<body class="theme-{selected_theme}">
<div class="shell">
{sidebar}
<main class="content">
<article id="content"></article>
<footer>{author} · {studio} · {year}</footer>
</main>
</div>
{_flat_script(section.markdown)}
</body>
</html>
"""


def build_flattened_documentation(
    source: Path,
    output: Path,
    *,
    theme: str | None = None,
) -> tuple[Path, tuple[Path, ...]]:
    """Read Markdown and write a landing page plus one page per H1 section."""
    metadata, body = parse_source(source.read_text(encoding="utf-8"))
    selected_theme = _resolve_theme(metadata, theme)
    sections = split_h1_sections(body)
    logo_data_uri = _logo_data_uri(source, metadata)
    section_dir = output.parent / f"{output.stem}_sections"
    output.parent.mkdir(parents=True, exist_ok=True)
    section_dir.mkdir(parents=True, exist_ok=True)
    output.write_text(
        render_flat_landing_page(
            metadata,
            sections,
            theme=selected_theme,
            logo_data_uri=logo_data_uri,
            section_href_prefix=f"{section_dir.name}/",
        ),
        encoding="utf-8",
    )
    section_paths: list[Path] = []
    for section in sections:
        section_path = section_dir / f"{section.slug}.html"
        section_path.write_text(
            render_flat_section_page(
                metadata,
                sections,
                section,
                theme=selected_theme,
                logo_data_uri=logo_data_uri,
            ),
            encoding="utf-8",
        )
        section_paths.append(section_path)
    return output, tuple(section_paths)


def build_documentation(source: Path, output: Path, *, theme: str | None = None) -> Path:
    """Read a conformed Blueprint and write its assembled documentation page."""
    metadata, body = parse_source(source.read_text(encoding="utf-8"))
    logo_data_uri = _logo_data_uri(source, metadata)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        render_page(metadata, body, theme=theme, logo_data_uri=logo_data_uri),
        encoding="utf-8",
    )
    return output


def default_pdf_path(html_output: Path) -> Path:
    return html_output.with_suffix(".pdf")


def render_pdf_with_playwright(html_path: Path, pdf_path: Path) -> Path:
    """Render HTML to PDF with local Playwright/Chromium if available."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise RuntimeError(
            "PDF publishing requires Playwright with a local Chromium browser. "
            "Install Playwright support and run the browser install step, or omit --pdf."
        ) from exc

    pdf_path.parent.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page()
        page.goto(html_path.resolve().as_uri(), wait_until="networkidle")
        page.pdf(path=str(pdf_path), format="Letter", print_background=True)
        browser.close()
    return pdf_path


def publish_document(
    source: Path,
    output: Path,
    *,
    theme: str | None = None,
    flatten: bool = False,
    pdf: bool = False,
    pdf_output: Path | None = None,
    pdf_renderer: PdfRenderer | None = None,
) -> PublishedDocument:
    metadata, _body = parse_source(source.read_text(encoding="utf-8"))
    selected_theme = _resolve_theme(metadata, theme)
    section_paths: tuple[Path, ...] = ()
    if flatten:
        html_path, section_paths = build_flattened_documentation(
            source,
            output,
            theme=selected_theme,
        )
    else:
        html_path = build_documentation(source, output, theme=selected_theme)
    rendered_pdf: Path | None = None
    if pdf:
        rendered_pdf = pdf_output or default_pdf_path(html_path)
        renderer = pdf_renderer or render_pdf_with_playwright
        rendered_pdf = renderer(html_path, rendered_pdf)
    return PublishedDocument(
        html_path=html_path,
        pdf_path=rendered_pdf,
        theme=selected_theme,
        section_paths=section_paths,
    )


def _repository_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _default_source(root: Path) -> Path:
    return root / DEFAULT_SPECIFICATION


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, help="conformed Markdown source")
    parser.add_argument("--output", type=Path, help="HTML output path")
    parser.add_argument("--theme", choices=SUPPORTED_THEMES, default=None, help="publish theme")
    parser.add_argument(
        "--flatten", action="store_true", help="publish H1 sections as separate pages"
    )
    parser.add_argument("--pdf", action="store_true", help="also render a PDF")
    parser.add_argument("--pdf-output", type=Path, help="PDF output path")
    args = parser.parse_args(argv)

    root = _repository_root()
    source = args.source or _default_source(root)
    output = args.output or root / DEFAULT_OUTPUT
    result = publish_document(
        source,
        output,
        theme=args.theme,
        flatten=args.flatten,
        pdf=args.pdf,
        pdf_output=args.pdf_output,
    )
    print(f"Built documentation: {result.html_path}")
    if result.pdf_path is not None:
        print(f"Built PDF: {result.pdf_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
